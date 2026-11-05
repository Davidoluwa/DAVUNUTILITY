// Replays the MoE gate/up step on real Flint weights, outside the model, to find where time goes.
//   bench_moe MODEL.gguf [threads]
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <sys/mman.h>
#include <vector>

#include "../src/gguf.h"
#include "../src/quants.h"
#include "../src/threadpool.h"

using namespace fl;

static double now() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char **argv) {
    GGUF g(argv[1]);
    const int nth = argc > 2 ? std::atoi(argv[2]) : 4;
    ThreadPool pool(nth);
    const int E = 2048, F = 512, FS = 1024, K = 6, NL = 47;
    std::mt19937 rng(1);

    // Copy 6 random experts per layer (gate+up) and the shared expert into anonymous huge pages.
    struct LayerData { std::vector<const uint8_t *> gate, up; const uint8_t *sg, *su; size_t rb_exp, rb_sh; };
    std::vector<LayerData> L(NL);
    const size_t rb_exp = row_size(T_IQ2_S, E), rb_sh = row_size(T_Q6_K, E);
    const size_t per_layer = 2 * K * F * rb_exp + 2 * FS * rb_sh;
    uint8_t *mem = (uint8_t *)mmap(nullptr, per_layer * NL + (4 << 20), PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    madvise(mem, per_layer * NL + (4 << 20), MADV_HUGEPAGE);
    uint8_t *p = mem;
    for (int l = 0; l < NL; l++) {
        const int il = l + 2;
        auto T = [&](const char *n) { return g.tensor("blk." + std::to_string(il) + "." + n + ".weight"); };
        const Tensor *tg = T("ffn_gate_exps"), *tu = T("ffn_up_exps"), *sg = T("ffn_gate_shexp"), *su = T("ffn_up_shexp");
        for (int k = 0; k < K; k++) {
            int e = int(rng() % 256);
            std::memcpy(p, tg->data + size_t(e) * F * rb_exp, F * rb_exp); L[l].gate.push_back(p); p += F * rb_exp;
            std::memcpy(p, tu->data + size_t(e) * F * rb_exp, F * rb_exp); L[l].up.push_back(p); p += F * rb_exp;
        }
        std::memcpy(p, sg->data, FS * rb_sh); L[l].sg = p; p += FS * rb_sh;
        std::memcpy(p, su->data, FS * rb_sh); L[l].su = p; p += FS * rb_sh;
    }
    std::printf("copied %.1f MB of expert + shared gate/up weights for %d layers\n", (p - mem) / 1e6, NL);

    std::vector<float> h(E), gu(2 * FS + 2 * K * F);
    std::normal_distribution<float> nd;
    for (auto &v : h) v = nd(rng);
    std::vector<block_q8_K> hq(E / QK_K);
    quantize_row_q8_K(h.data(), hq.data(), E);

    auto bench = [&](const char *name, int64_t rows_sh, int64_t rows_exp) {
        const int64_t n_rows = rows_sh + rows_exp;
        auto step = [&](const LayerData &d) {
            pool.parallel_for(n_rows, [&](int64_t b, int64_t e, int) {
                for (int64_t r = b; r < e; r++) {
                    if (r < rows_sh) {
                        const uint8_t *row = (r < FS ? d.sg : d.su) + size_t(r % FS) * rb_sh;
                        gu[r] = vec_dot(T_Q6_K, row, hq.data(), nullptr, E);
                    } else {
                        const int64_t rr = r - rows_sh, k = rr / (2 * F), j = rr % (2 * F);
                        const uint8_t *row = (j < F ? d.gate[k] : d.up[k]) + size_t(j % F) * rb_exp;
                        gu[r] = vec_dot(T_IQ2_S, row, hq.data(), nullptr, E);
                    }
                }
            });
        };
        for (auto &d : L) step(d);  // warm
        const int reps = 10;
        double t0 = now();
        for (int i = 0; i < reps; i++)
            for (auto &d : L) step(d);
        const double ms = (now() - t0) / reps * 1e3;
        const double mb = (rows_sh * rb_sh + rows_exp * rb_exp) * NL / 1e6;
        std::printf("  %-34s %6.2f ms per 47 layers  (%.0f MB, %.1f GB/s)\n", name, ms, mb, mb / ms);
    };
    std::printf("threads=%d\n", nth);
    bench("shared + 6 experts (model layout)", 2 * FS, 2 * K * F);
    bench("6 experts only (iq2_s)", 0, 2 * K * F);
    bench("shared only (q6_K)", 2 * FS, 0);
    return 0;
}
