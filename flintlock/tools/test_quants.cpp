// Checks every dot kernel against the scalar reference on real Flint rows, then measures
// how close each kernel gets to memory bandwidth.
//   test_quants MODEL.gguf [threads]
#include <chrono>
#include <cmath>
#include <cstdio>
#include <random>
#include <vector>

#include "../src/gguf.h"
#include "../src/quants.h"
#include "../src/threadpool.h"

using namespace fl;

static double now() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char **argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s MODEL.gguf [threads]\n", argv[0]);
        return 1;
    }
    GGUF g(argv[1]);
    int nth = argc > 2 ? std::atoi(argv[2]) : 4;
    std::mt19937 rng(42);
    std::normal_distribution<float> nd(0.f, 1.f);
    int fails = 0;

    const char *names[] = {"blk.10.attn_q.weight", "blk.10.ffn_gate_exps.weight", "blk.10.ffn_down_exps.weight",
                           "blk.10.ffn_gate_inp.weight", "output.weight"};
    std::printf("== correctness (kernel vs scalar reference, 64 random rows each)\n");
    for (const char *name : names) {
        const Tensor *t = g.tensor(name);
        if (!t) { std::printf("  missing %s\n", name); fails++; continue; }
        const int64_t n = t->dims[0];
        int64_t rows = 1;
        for (size_t d = 1; d < t->dims.size(); d++) rows *= t->dims[d];
        const size_t rs = row_size(t->type, n);
        std::vector<float> x(n);
        std::vector<block_q8_K> q8(n / QK_K + 1);
        double worst = 0, worst_q8 = 0;
        for (int r = 0; r < 64; r++) {
            for (auto &v : x) v = nd(rng);
            if (type_uses_q8(t->type)) quantize_row_q8_K(x.data(), q8.data(), n);
            const int64_t row = std::uniform_int_distribution<int64_t>(0, rows - 1)(rng);
            const void *w = t->data + row * rs;
            float a = vec_dot(t->type, w, q8.data(), x.data(), n);
            float b = vec_dot_ref(t->type, w, q8.data(), x.data(), n);
            // Scale errors by sum|w*x| so near-zero dot products do not blow up the ratio.
            std::vector<float> wf(n);
            dequant_row(t->type, w, wf.data(), n);
            double mag = 0, exact = 0;
            for (int64_t i = 0; i < n; i++) mag += std::fabs(wf[i] * x[i]), exact += double(wf[i]) * x[i];
            worst = std::fmax(worst, std::fabs(a - b) / (mag + 1e-30));
            worst_q8 = std::fmax(worst_q8, std::fabs(a - exact) / (mag + 1e-30));
        }
        bool ok = worst < 1e-5;
        fails += !ok;
        std::printf("  %-30s %-8s n=%-5lld kernel-vs-ref %.2e  with-q8-error %.2e  %s\n", name, ggml_type_name(t->type),
                    (long long)n, worst, worst_q8, ok ? "OK" : "FAIL");
    }

    std::printf("\n== throughput (%d threads), each pass reads the whole tensor\n", nth);
    ThreadPool pool(nth);
    for (const char *name : names) {
        const Tensor *t = g.tensor(name);
        if (!t) continue;
        const int64_t n = t->dims[0];
        int64_t rows = 1;
        for (size_t d = 1; d < t->dims.size(); d++) rows *= t->dims[d];
        const size_t rs = row_size(t->type, n);
        std::vector<float> x(n), y(rows);
        for (auto &v : x) v = nd(rng);
        std::vector<block_q8_K> q8(n / QK_K + 1);
        if (type_uses_q8(t->type)) quantize_row_q8_K(x.data(), q8.data(), n);
        auto pass = [&] {
            pool.parallel_for(rows, [&](int64_t b, int64_t e, int) {
                for (int64_t r = b; r < e; r++) y[r] = vec_dot(t->type, t->data + r * rs, q8.data(), x.data(), n);
            });
        };
        pass();  // fault pages in
        int reps = std::max(1, int(2e9 / double(t->nbytes)));
        double t0 = now();
        for (int k = 0; k < reps; k++) pass();
        double dt = (now() - t0) / reps;
        std::printf("  %-30s %-8s %8.1f MB  %7.2f ms/pass  %6.1f GB/s  %7.1f Gweights/s\n", name, ggml_type_name(t->type),
                    t->nbytes / 1e6, dt * 1e3, t->nbytes / dt / 1e9, double(rows) * n / dt / 1e9);
    }
    return fails ? 1 : 0;
}
