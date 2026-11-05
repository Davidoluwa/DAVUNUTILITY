// Generate text with Flint.
//   run -m MODEL.gguf -p "prompt" [-n 128] [--chat] [--temp 0] [--top-k 20] [--top-p 0.95]
//       [-t 4] [--ctx 4096] [--seed 1] [--trace experts.bin]
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>
#include <vector>

#include <sys/resource.h>

#include <memory>

#include "../src/expert_cache.h"
#include "../src/gguf.h"
#include "../src/model.h"
#include "../src/tokenizer.h"

using namespace fl;

static double now() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

static int sample(const float *logits, int64_t n, float temp, int top_k, float top_p, std::mt19937 &rng) {
    if (temp <= 0) return int(std::max_element(logits, logits + n) - logits);
    std::vector<int> idx(n);
    for (int64_t i = 0; i < n; i++) idx[i] = int(i);
    const int k = std::min<int64_t>(top_k > 0 ? top_k : n, n);
    std::partial_sort(idx.begin(), idx.begin() + k, idx.end(), [&](int a, int b) { return logits[a] > logits[b]; });
    std::vector<double> p(k);
    double sum = 0;
    for (int i = 0; i < k; i++) sum += (p[i] = std::exp((logits[idx[i]] - logits[idx[0]]) / temp));
    double cum = 0;
    int cut = k;
    for (int i = 0; i < k; i++) {
        cum += p[i] / sum;
        if (cum >= top_p) { cut = i + 1; break; }
    }
    std::discrete_distribution<int> d(p.begin(), p.begin() + cut);
    return idx[d(rng)];
}

static long rss_mb() {
    FILE *f = std::fopen("/proc/self/status", "r");
    char line[256];
    long kb = 0;
    while (f && std::fgets(line, sizeof line, f))
        if (std::strncmp(line, "VmRSS:", 6) == 0) kb = std::atol(line + 6);
    if (f) std::fclose(f);
    return kb / 1024;
}

int main(int argc, char **argv) {
    std::string model, prompt = "Hello", trace;
    int n_gen = 128, threads = 4, ctx = 4096, top_k = 20, seed = 1, io_threads = 8;
    float temp = 0, top_p = 0.95f, ram_gb = 0;
    int prefetch = 0;
    Steer steer;
    bool chat = false;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&] { return i + 1 < argc ? std::string(argv[++i]) : std::string(); };
        if (a == "-m") model = next();
        else if (a == "-p") prompt = next();
        else if (a == "-n") n_gen = std::atoi(next().c_str());
        else if (a == "-t") threads = std::atoi(next().c_str());
        else if (a == "--ctx") ctx = std::atoi(next().c_str());
        else if (a == "--temp") temp = std::atof(next().c_str());
        else if (a == "--top-k") top_k = std::atoi(next().c_str());
        else if (a == "--top-p") top_p = std::atof(next().c_str());
        else if (a == "--seed") seed = std::atoi(next().c_str());
        else if (a == "--chat") chat = true;
        else if (a == "--trace") trace = next();
        else if (a == "--ram-gb") ram_gb = std::atof(next().c_str());
        else if (a == "--io-threads") io_threads = std::atoi(next().c_str());
        else if (a == "--prefetch") prefetch = std::atoi(next().c_str());
        else if (a == "--steer") {
            std::string v = next();
            steer.depth = std::atoi(v.c_str());
            if (v.find(',') != std::string::npos) steer.ratio = std::atof(v.substr(v.find(',') + 1).c_str());
        }
        else { std::fprintf(stderr, "unknown arg %s\n", a.c_str()); return 1; }
    }
    if (model.empty()) { std::fprintf(stderr, "need -m MODEL.gguf\n"); return 1; }

    GGUF g(model);
    Tokenizer tok(g);
    ThreadPool pool(threads);
    Flint m(g, ctx, pool);
    m.steer = steer;
    m.prefetch_n = prefetch;
    std::mt19937 rng(seed);

    // Memory budget: whatever the process holds now, plus the expert cache, stays under ram_gb.
    std::unique_ptr<ExpertCache> cache;
    if (ram_gb > 0) {
        g.drop_page_cache();
        const double margin_mb = 150;  // scratch, tokenizer cache, attention buffers
        const double budget = ram_gb * 1e9 - (rss_mb() + margin_mb) * 1048576.0;
        cache = std::make_unique<ExpertCache>(model, g, m.moe_layers(), size_t(std::max(0.0, budget)), io_threads);
        m.set_expert_cache(cache.get());
        std::fprintf(stderr, "expert cache: %zu slots of %.2f MB (%.1f%% of %d experts), %.2f GB\n", cache->slots(),
                     cache->slot_bytes() / 1e6, 100.0 * cache->slots() / (m.moe_layers().size() * m.config().n_expert),
                     int(m.moe_layers().size()) * m.config().n_expert, cache->slots() * cache->slot_bytes() / 1e9);
    }

    // Flint's chat template: <|user|>{message}<|assistant|>, no BOS.
    std::string text = chat ? "<|user|>" + prompt + "<|assistant|>" : prompt;
    std::vector<int32_t> ids = tok.encode(text, true);
    std::fprintf(stderr, "prompt: %zu tokens, %d threads\n", ids.size(), threads);

    FILE *tf = trace.empty() ? nullptr : std::fopen(trace.c_str(), "wb");
    auto record = [&] {
        if (tf) std::fwrite(m.last_experts().data(), 1, m.last_experts().size(), tf);
    };

    double t0 = now();
    const float *logits = nullptr;
    int pos = 0;
    for (int32_t id : ids) {
        logits = m.forward(id, pos++);
        record();
    }
    double t1 = now();
    m.timings = Timings{};
    struct rusage ru0, ru1;
    getrusage(RUSAGE_SELF, &ru0);
    std::printf("%s", text.c_str());
    std::fflush(stdout);

    int generated = 0;
    for (; generated < n_gen; generated++) {
        int next = sample(logits, m.config().n_vocab, temp, top_k, top_p, rng);
        if (tok.is_eog(next)) break;
        std::printf("%s", tok.decode(next).c_str());
        std::fflush(stdout);
        logits = m.forward(next, pos++);
        record();
    }
    double t2 = now();
    getrusage(RUSAGE_SELF, &ru1);
    if (tf) std::fclose(tf);

    const Timings &T = m.timings;
    const double n = std::max(1, T.tokens);
    std::fprintf(stderr, "\n\nprefill: %zu tok in %.2f s (%.2f tok/s)\n", ids.size(), t1 - t0, ids.size() / (t1 - t0));
    std::fprintf(stderr, "decode:  %d tok in %.2f s (%.2f tok/s)\n", generated, t2 - t1, generated / (t2 - t1));
    std::fprintf(stderr,
                 "per token (ms): attn-proj %.1f  attention %.1f  router %.1f  expert-io %.1f  experts %.1f  dense-ffn %.1f  "
                 "head %.1f\n",
                 1e3 * T.attn_proj / n, 1e3 * T.attn / n, 1e3 * T.router / n, 1e3 * T.expert_io / n, 1e3 * T.experts / n,
                 1e3 * T.dense_ffn / n, 1e3 * T.head / n);
    std::fprintf(stderr, "experts split (ms): gate/up %.1f  activation %.1f  down %.1f\n", 1e3 * T.exp_gu / n,
                 1e3 * T.exp_act / n, 1e3 * T.exp_down / n);
    if (cache) {
        const CacheStats &c = cache->stats;
        const double all = double(std::max<uint64_t>(1, c.hits + c.prefetch_hits + c.misses));
        std::fprintf(stderr,
                     "expert cache (whole run): %.1f%% already cached, %.1f%% from prefetch, %.1f%% loaded on demand; "
                     "%.2f GB read, %.1f s waiting on disk\n",
                     100 * c.hits / all, 100 * c.prefetch_hits / all, 100 * c.misses / all, c.bytes_read / 1e9,
                     c.wait_seconds);
        if (c.prefetched)
            std::fprintf(stderr, "prefetch: %llu issued, %.1f%% evicted unused; next-layer prediction recall %.1f%%\n",
                         (unsigned long long)c.prefetched, 100.0 * c.prefetch_unused / c.prefetched,
                         100.0 * m.pred_hits / std::max<uint64_t>(1, m.pred_total));
        if (m.steer.depth) std::fprintf(stderr, "steering swapped %.1f%% of picks\n", 100.0 * m.steer.swaps / std::max<uint64_t>(1, m.steer.picks));
    }
    std::fprintf(stderr, "RSS: %ld MB, resident weights %.2f GB, page faults during decode: %ld major, %ld minor\n",
                 rss_mb(), m.resident_bytes() / 1e9, ru1.ru_majflt - ru0.ru_majflt, ru1.ru_minflt - ru0.ru_minflt);
    return 0;
}
