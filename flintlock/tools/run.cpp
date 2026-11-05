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
    int n_gen = 128, threads = 4, ctx = 4096, top_k = 20, seed = 1;
    float temp = 0, top_p = 0.95f;
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
        else { std::fprintf(stderr, "unknown arg %s\n", a.c_str()); return 1; }
    }
    if (model.empty()) { std::fprintf(stderr, "need -m MODEL.gguf\n"); return 1; }

    GGUF g(model);
    Tokenizer tok(g);
    ThreadPool pool(threads);
    Flint m(g, ctx, pool);
    std::mt19937 rng(seed);

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
    if (tf) std::fclose(tf);

    const Timings &T = m.timings;
    const double n = std::max(1, T.tokens);
    std::fprintf(stderr, "\n\nprefill: %zu tok in %.2f s (%.2f tok/s)\n", ids.size(), t1 - t0, ids.size() / (t1 - t0));
    std::fprintf(stderr, "decode:  %d tok in %.2f s (%.2f tok/s)\n", generated, t2 - t1, generated / (t2 - t1));
    std::fprintf(stderr, "per token (ms): attn-proj %.1f  attention %.1f  router %.1f  experts %.1f  dense-ffn %.1f  head %.1f\n",
                 1e3 * T.attn_proj / n, 1e3 * T.attn / n, 1e3 * T.router / n, 1e3 * T.experts / n, 1e3 * T.dense_ffn / n,
                 1e3 * T.head / n);
    std::fprintf(stderr, "RSS: %ld MB\n", rss_mb());
    return 0;
}
