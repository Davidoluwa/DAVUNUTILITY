// Teacher-forced quality check on a text file: perplexity, plus agreement with a saved reference
// run (top-1 match and KL over the reference's top-32 tokens). Used to price approximations such
// as cache-aware routing against exact routing.
//   eval -m MODEL --text FILE [--n 512] [--save ref.bin | --ref ref.bin] [--ram-gb 4] [--steer 4,0.9]
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "../src/expert_cache.h"
#include "../src/gguf.h"
#include "../src/model.h"
#include "../src/tokenizer.h"

using namespace fl;

constexpr int kTop = 32;
struct Rec {
    int32_t id[kTop];
    float lp[kTop];
};

static long rss_mb() {
    std::ifstream f("/proc/self/status");
    std::string line;
    while (std::getline(f, line))
        if (line.rfind("VmRSS:", 0) == 0) return std::atol(line.c_str() + 6) / 1024;
    return 0;
}

int main(int argc, char **argv) {
    std::string model, text_path, save, ref;
    int n = 512, threads = 4, prefetch = 0;
    float ram_gb = 0;
    Steer steer;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&] { return i + 1 < argc ? std::string(argv[++i]) : std::string(); };
        if (a == "-m") model = next();
        else if (a == "--text") text_path = next();
        else if (a == "--n") n = std::atoi(next().c_str());
        else if (a == "--save") save = next();
        else if (a == "--ref") ref = next();
        else if (a == "-t") threads = std::atoi(next().c_str());
        else if (a == "--ram-gb") ram_gb = std::atof(next().c_str());
        else if (a == "--prefetch") prefetch = std::atoi(next().c_str());
        else if (a == "--steer") {
            std::string v = next();
            steer.depth = std::atoi(v.c_str());
            if (v.find(',') != std::string::npos) steer.ratio = std::atof(v.substr(v.find(',') + 1).c_str());
        } else { std::fprintf(stderr, "unknown arg %s\n", a.c_str()); return 1; }
    }
    std::ifstream tf(text_path);
    std::stringstream ss;
    ss << tf.rdbuf();

    GGUF g(model);
    Tokenizer tok(g);
    std::vector<int32_t> ids = tok.encode(ss.str(), false);
    if (int(ids.size()) > n + 1) ids.resize(n + 1);
    const int T = int(ids.size()) - 1;

    ThreadPool pool(threads);
    Flint m(g, T + 8, pool);
    m.steer = steer;
    m.prefetch_n = prefetch;
    std::unique_ptr<ExpertCache> cache;
    if (ram_gb > 0) {
        g.drop_page_cache();
        const double budget = ram_gb * 1e9 - (rss_mb() + 150.0) * 1048576.0;
        cache = std::make_unique<ExpertCache>(model, g, m.moe_layers(), size_t(std::max(0.0, budget)));
        m.set_expert_cache(cache.get());
    }

    std::vector<Rec> refs;
    if (!ref.empty()) {
        refs.resize(T);
        FILE *f = std::fopen(ref.c_str(), "rb");
        if (!f || std::fread(refs.data(), sizeof(Rec), T, f) != size_t(T)) { std::fprintf(stderr, "bad ref\n"); return 1; }
        std::fclose(f);
    }
    FILE *out = save.empty() ? nullptr : std::fopen(save.c_str(), "wb");

    const int64_t V = m.config().n_vocab;
    std::vector<float> lp(V);
    std::vector<int> idx(V);
    double nll = 0, kl = 0;
    int agree = 0;
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < T; i++) {
        const float *lg = m.forward(ids[i], i);
        const float mx = *std::max_element(lg, lg + V);
        double z = 0;
        for (int64_t v = 0; v < V; v++) z += std::exp(double(lg[v] - mx));
        const float lz = float(std::log(z)) + mx;
        for (int64_t v = 0; v < V; v++) lp[v] = lg[v] - lz;
        nll -= lp[ids[i + 1]];

        for (int64_t v = 0; v < V; v++) idx[v] = int(v);
        std::partial_sort(idx.begin(), idx.begin() + kTop, idx.end(), [&](int a, int b) { return lp[a] > lp[b]; });
        Rec r;
        for (int k = 0; k < kTop; k++) r.id[k] = idx[k], r.lp[k] = lp[idx[k]];
        if (out) std::fwrite(&r, sizeof r, 1, out);
        if (!refs.empty()) {
            agree += refs[i].id[0] == r.id[0];
            for (int k = 0; k < kTop; k++) kl += std::exp(refs[i].lp[k]) * (refs[i].lp[k] - lp[refs[i].id[k]]);
        }
    }
    const double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    if (out) std::fclose(out);

    std::printf("tokens %d  ppl %.4f  (%.1f tok/s, RSS %ld MB)\n", T, std::exp(nll / T), T / secs, rss_mb());
    if (!refs.empty()) std::printf("vs reference: top-1 agreement %.2f%%  KL %.5f nats/token\n", 100.0 * agree / T, kl / T);
    if (cache) {
        const CacheStats &c = cache->stats;
        std::printf("expert cache: %.1f%% hits (incl. prefetched), steering swapped %.1f%% of picks\n",
                    100.0 * (c.hits + c.prefetch_hits) / std::max<uint64_t>(1, c.hits + c.prefetch_hits + c.misses),
                    100.0 * m.steer.swaps / std::max<uint64_t>(1, m.steer.picks));
    }
    return 0;
}
