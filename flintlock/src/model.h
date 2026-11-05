// Flint forward pass for single-token decode. Weights are used in place from the mmap'd GGUF.
#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "expert_cache.h"
#include "gguf.h"
#include "quants.h"
#include "threadpool.h"

namespace fl {

struct Mat {
    const uint8_t *data = nullptr;
    uint32_t type = 0;
    int64_t n_in = 0;   // row length
    int64_t n_out = 0;  // rows (per expert, for 3D expert tensors)
    size_t row_bytes = 0;
    const uint8_t *row(int64_t r) const { return data + size_t(r) * row_bytes; }
};

struct Layer {
    const float *attn_norm, *ffn_norm, *q_norm, *k_norm, *sinks;
    Mat wq, wk, wv, wo;
    bool dense, swa, rope;
    Mat ffn_gate, ffn_up, ffn_down;            // dense layers
    Mat router;                                // MoE layers
    Mat gate_exps, up_exps, down_exps;         // [n_expert] x [n_out x n_in]
    Mat gate_sh, up_sh, down_sh;               // shared expert
};

// Cache-aware routing: a routed expert that is not in memory may be swapped for one of the
// next `depth` ranked experts that is, if its router score is at least `ratio` times as high.
// depth 0 keeps exact routing.
struct Steer {
    int depth = 0;
    float ratio = 0.9f;
    uint64_t swaps = 0, picks = 0;
};

struct Config {
    int n_layer, n_embd, n_head, n_head_kv, head_dim, n_ff, n_expert, n_expert_used, n_ff_exp, n_ff_shexp, n_swa;
    int64_t n_vocab;
    float rms_eps, rope_base;
};

// Wall-clock split of one decode step, accumulated across steps.
struct Timings {
    double attn_proj = 0, attn = 0, router = 0, expert_io = 0, experts = 0, dense_ffn = 0, head = 0;
    double exp_gu = 0, exp_act = 0, exp_down = 0;  // parts of `experts`
    int tokens = 0;
};

// Anonymous memory backed by 2 MB pages where the kernel allows it.
class HugeArena {
public:
    explicit HugeArena(size_t bytes);
    ~HugeArena();
    HugeArena(const HugeArena &) = delete;
    HugeArena &operator=(const HugeArena &) = delete;
    uint8_t *alloc(size_t bytes);  // 64-byte aligned bump allocation
    size_t used() const { return used_; }

private:
    uint8_t *base_ = nullptr;
    size_t cap_ = 0, used_ = 0;
};

class Flint {
public:
    // resident: copy every always-active weight (everything except routed experts and the
    // embedding table) out of the file mapping into huge-page memory.
    Flint(const GGUF &g, int n_ctx, ThreadPool &pool, bool resident = true);
    size_t resident_bytes() const { return arena_ ? arena_->used() : 0; }

    // Run one token at position pos (positions must arrive in order). Returns n_vocab logits.
    const float *forward(int32_t token, int pos);

    const Config &config() const { return cfg_; }
    // Serve routed experts from a fixed-size cache instead of the file mapping.
    void set_expert_cache(ExpertCache *c) { cache_ = c; }
    std::vector<int> moe_layers() const;
    Steer steer;
    // Experts to prefetch for the next layer, predicted by running the next layer's router on
    // this layer's hidden state. 0 disables prefetching.
    int prefetch_n = 0;
    uint64_t pred_hits = 0, pred_total = 0;  // how many routed experts the prediction got right
    // Experts chosen at the last step: [n_moe_layers][n_expert_used].
    const std::vector<uint8_t> &last_experts() const { return last_experts_; }
    Timings timings;

private:
    void matvec(const Mat &m, const float *x, float *y);  // y = M x, parallel over rows
    void attention(const Layer &L, int il, int pos);
    void moe(const Layer &L, int il);
    void dense_ffn(const Layer &L);

    const GGUF &g_;
    ThreadPool &pool_;
    Config cfg_;
    int n_ctx_;
    std::vector<Layer> layers_;
    Mat tok_embd_, output_;
    const float *output_norm_;
    std::vector<int> kv_slot_layer_;  // per layer: index into kv_ caches
    std::vector<std::vector<float>> k_cache_, v_cache_;
    std::vector<float> inv_freq_, rope_cos_, rope_sin_;
    std::unique_ptr<HugeArena> arena_;
    ExpertCache *cache_ = nullptr;

    // Scratch.
    std::vector<float> x_, h_, q_, k_, v_, att_, ffn_, logits_, router_logits_, moe_out_, gu_;
    std::vector<block_q8_K> hq_, aq_;
    std::vector<uint8_t> last_experts_;
    std::vector<std::vector<int>> predicted_;  // per layer: experts prefetched for it
    std::vector<float> pred_logits_;
};

}  // namespace fl
