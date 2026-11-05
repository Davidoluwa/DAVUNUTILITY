#include "model.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>

namespace fl {

namespace {

double now() { return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count(); }

Mat get_mat(const GGUF &g, const std::string &name) {
    const Tensor *t = g.tensor(name);
    if (!t) throw std::runtime_error("model: missing tensor " + name);
    if (!type_supported(t->type)) throw std::runtime_error("model: unsupported type for " + name);
    Mat m;
    m.data = t->data;
    m.type = t->type;
    m.n_in = t->dims[0];
    m.n_out = t->dims.size() > 1 ? t->dims[1] : 1;
    m.row_bytes = row_size(t->type, m.n_in);
    return m;
}

const float *get_f32(const GGUF &g, const std::string &name) {
    const Tensor *t = g.tensor(name);
    if (!t || t->type != T_F32) throw std::runtime_error("model: missing f32 tensor " + name);
    return reinterpret_cast<const float *>(t->data);
}

void rmsnorm(float *out, const float *x, const float *w, int n, float eps) {
    double ss = 0;
    for (int i = 0; i < n; i++) ss += double(x[i]) * x[i];
    const float s = 1.0f / std::sqrt(float(ss / n) + eps);
    for (int i = 0; i < n; i++) out[i] = x[i] * s * w[i];
}

inline float silu(float x) { return x / (1.0f + std::exp(-x)); }

std::vector<uint8_t> get_u8_arr(const GGUF &g, const std::string &key, int n) {
    const KV *kv = g.get(key);
    std::vector<uint8_t> out(n, 0);
    if (!kv || kv->type != GVal::ARR) throw std::runtime_error("model: missing array " + key);
    for (int i = 0; i < n && uint64_t(i) < kv->arr_n; i++) {
        switch (kv->arr_type) {
            case GVal::BOOL: case GVal::U8: case GVal::I8: out[i] = kv->arr_data[i] != 0; break;
            case GVal::U32: case GVal::I32: { int32_t v; std::memcpy(&v, kv->arr_data + 4 * i, 4); out[i] = v != 0; } break;
            default: throw std::runtime_error("model: unexpected array type for " + key);
        }
    }
    return out;
}

}  // namespace

Flint::Flint(const GGUF &g, int n_ctx, ThreadPool &pool) : g_(g), pool_(pool), n_ctx_(n_ctx) {
    if (g.get_str("general.architecture") != "flint") throw std::runtime_error("model: not a flint GGUF");
    auto I = [&](const char *k) { return int(g.get_int(std::string("flint.") + k, -1)); };
    cfg_.n_layer = I("block_count");
    cfg_.n_embd = I("embedding_length");
    cfg_.n_head = I("attention.head_count");
    cfg_.n_head_kv = I("attention.head_count_kv");
    cfg_.head_dim = I("attention.key_length");
    cfg_.n_ff = I("feed_forward_length");
    cfg_.n_expert = I("expert_count");
    cfg_.n_expert_used = I("expert_used_count");
    cfg_.n_ff_exp = I("expert_feed_forward_length");
    cfg_.n_ff_shexp = I("expert_shared_feed_forward_length");
    cfg_.n_swa = I("attention.sliding_window");
    cfg_.rms_eps = float(g.get_float("flint.attention.layer_norm_rms_epsilon", 1e-6));
    cfg_.rope_base = float(g.get_float("flint.rope.freq_base", 10000));
    const int n_dense = I("leading_dense_block_count");
    if (g.get_int("flint.expert_gating_func", 0) != 2 || g.get_int("flint.expert_weights_norm", 0) != 1)
        throw std::runtime_error("model: expected sigmoid gating with normalized weights");

    auto swa = get_u8_arr(g, "flint.attention.sliding_window_pattern", cfg_.n_layer);
    auto rope = get_u8_arr(g, "flint.attention.rope_pattern", cfg_.n_layer);

    tok_embd_ = get_mat(g, "token_embd.weight");
    output_ = get_mat(g, "output.weight");
    output_norm_ = get_f32(g, "output_norm.weight");
    cfg_.n_vocab = output_.n_out;

    const int hd = cfg_.head_dim, kvd = cfg_.n_head_kv * hd;
    for (int il = 0; il < cfg_.n_layer; il++) {
        auto P = [&](const char *s) { return "blk." + std::to_string(il) + "." + s; };
        Layer L{};
        L.attn_norm = get_f32(g, P("attn_norm.weight"));
        L.ffn_norm = get_f32(g, P("ffn_norm.weight"));
        L.q_norm = get_f32(g, P("attn_q_norm.weight"));
        L.k_norm = get_f32(g, P("attn_k_norm.weight"));
        L.sinks = get_f32(g, P("attn_sinks.weight"));
        L.wq = get_mat(g, P("attn_q.weight"));
        L.wk = get_mat(g, P("attn_k.weight"));
        L.wv = get_mat(g, P("attn_v.weight"));
        L.wo = get_mat(g, P("attn_output.weight"));
        L.swa = swa[il];
        L.rope = rope[il];
        L.dense = il < n_dense;
        if (L.dense) {
            L.ffn_gate = get_mat(g, P("ffn_gate.weight"));
            L.ffn_up = get_mat(g, P("ffn_up.weight"));
            L.ffn_down = get_mat(g, P("ffn_down.weight"));
        } else {
            L.router = get_mat(g, P("ffn_gate_inp.weight"));
            L.gate_exps = get_mat(g, P("ffn_gate_exps.weight"));
            L.up_exps = get_mat(g, P("ffn_up_exps.weight"));
            L.down_exps = get_mat(g, P("ffn_down_exps.weight"));
            L.gate_sh = get_mat(g, P("ffn_gate_shexp.weight"));
            L.up_sh = get_mat(g, P("ffn_up_shexp.weight"));
            L.down_sh = get_mat(g, P("ffn_down_shexp.weight"));
        }
        layers_.push_back(L);

        // Sliding-window layers only ever need the last n_swa positions: keep a ring buffer.
        const int64_t slots = L.swa ? std::min(cfg_.n_swa, n_ctx) : n_ctx;
        kv_slot_layer_.push_back(int(k_cache_.size()));
        k_cache_.emplace_back(size_t(slots) * kvd);
        v_cache_.emplace_back(size_t(slots) * kvd);
    }

    inv_freq_.resize(hd / 2);
    for (int i = 0; i < hd / 2; i++) inv_freq_[i] = std::pow(cfg_.rope_base, -2.0f * i / hd);

    const int E = cfg_.n_embd;
    x_.resize(E);
    h_.resize(E);
    q_.resize(cfg_.n_head * hd);
    k_.resize(kvd);
    v_.resize(kvd);
    att_.resize(cfg_.n_head * hd);
    ffn_.resize(std::max<int64_t>({int64_t(cfg_.n_ff) * 2, int64_t(cfg_.n_ff_shexp) * 2 + int64_t(cfg_.n_expert_used) * cfg_.n_ff_exp * 2}));
    gu_.resize(ffn_.size());
    logits_.resize(cfg_.n_vocab);
    router_logits_.resize(cfg_.n_expert);
    moe_out_.resize(E);
    hq_.resize(std::max({cfg_.n_embd, cfg_.n_head * hd, cfg_.n_ff}) / QK_K + 1);
    aq_.resize(std::max<int64_t>(cfg_.n_ff, cfg_.n_ff_shexp + int64_t(cfg_.n_expert_used) * cfg_.n_ff_exp) / QK_K + 8);
    last_experts_.resize(size_t(cfg_.n_layer - n_dense) * cfg_.n_expert_used);
}

void Flint::matvec(const Mat &m, const float *x, float *y) {
    if (type_uses_q8(m.type)) quantize_row_q8_K(x, hq_.data(), m.n_in);
    pool_.parallel_for(m.n_out, [&](int64_t b, int64_t e, int) {
        for (int64_t r = b; r < e; r++) y[r] = vec_dot(m.type, m.row(r), hq_.data(), x, m.n_in);
    });
}

void Flint::attention(const Layer &L, int il, int pos) {
    const int hd = cfg_.head_dim, nh = cfg_.n_head, nkv = cfg_.n_head_kv, kvd = nkv * hd;
    double t0 = now();

    // Q, K, V in one parallel pass over all their rows.
    rmsnorm(h_.data(), x_.data(), L.attn_norm, cfg_.n_embd, cfg_.rms_eps);
    quantize_row_q8_K(h_.data(), hq_.data(), cfg_.n_embd);
    const int64_t nq = L.wq.n_out, nk = L.wk.n_out, nv = L.wv.n_out;
    pool_.parallel_for(nq + nk + nv, [&](int64_t b, int64_t e, int) {
        for (int64_t r = b; r < e; r++) {
            if (r < nq) q_[r] = vec_dot(L.wq.type, L.wq.row(r), hq_.data(), h_.data(), L.wq.n_in);
            else if (r < nq + nk) k_[r - nq] = vec_dot(L.wk.type, L.wk.row(r - nq), hq_.data(), h_.data(), L.wk.n_in);
            else v_[r - nq - nk] = vec_dot(L.wv.type, L.wv.row(r - nq - nk), hq_.data(), h_.data(), L.wv.n_in);
        }
    });

    // Per-head QK RMSNorm, then NEOX RoPE (pairs i and i + hd/2) on layers that use it.
    for (int h = 0; h < nh; h++) rmsnorm(&q_[h * hd], &q_[h * hd], L.q_norm, hd, cfg_.rms_eps);
    for (int h = 0; h < nkv; h++) rmsnorm(&k_[h * hd], &k_[h * hd], L.k_norm, hd, cfg_.rms_eps);
    if (L.rope) {
        auto rot = [&](float *v) {
            for (int i = 0; i < hd / 2; i++) {
                const float th = pos * inv_freq_[i], c = std::cos(th), s = std::sin(th);
                const float a = v[i], b = v[i + hd / 2];
                v[i] = a * c - b * s;
                v[i + hd / 2] = a * s + b * c;
            }
        };
        for (int h = 0; h < nh; h++) rot(&q_[h * hd]);
        for (int h = 0; h < nkv; h++) rot(&k_[h * hd]);
    }

    const int ci = kv_slot_layer_[il];
    const int slots = int(k_cache_[ci].size() / kvd);
    const int slot = pos % slots;
    std::copy(k_.begin(), k_.end(), k_cache_[ci].begin() + size_t(slot) * kvd);
    std::copy(v_.begin(), v_.end(), v_cache_[ci].begin() + size_t(slot) * kvd);
    double t1 = now();

    // Attend over [first, pos]. A sliding layer sees itself plus the previous n_swa - 1 tokens.
    const int first = L.swa ? std::max(0, pos - cfg_.n_swa + 1) : 0;
    const int n_pos = pos - first + 1;
    const float scale = 1.0f / std::sqrt(float(hd));
    const int group = nh / nkv;
    pool_.parallel_for(nh, [&](int64_t hb, int64_t he, int) {
        std::vector<float> sc(n_pos);
        for (int64_t h = hb; h < he; h++) {
            const float *qh = &q_[h * hd];
            const int kvh = int(h) / group;
            float mx = L.sinks[h];
            for (int j = 0; j < n_pos; j++) {
                const float *kp = &k_cache_[ci][size_t((first + j) % slots) * kvd + kvh * hd];
                float s = 0;
                for (int d = 0; d < hd; d++) s += qh[d] * kp[d];
                sc[j] = s * scale;
                mx = std::max(mx, sc[j]);
            }
            // The learned sink only adds to the denominator: attention mass that goes nowhere.
            float den = std::exp(L.sinks[h] - mx);
            for (int j = 0; j < n_pos; j++) den += (sc[j] = std::exp(sc[j] - mx));
            float *o = &att_[h * hd];
            std::fill(o, o + hd, 0.f);
            for (int j = 0; j < n_pos; j++) {
                const float p = sc[j] / den;
                const float *vp = &v_cache_[ci][size_t((first + j) % slots) * kvd + kvh * hd];
                for (int d = 0; d < hd; d++) o[d] += p * vp[d];
            }
        }
    });
    double t2 = now();

    matvec(L.wo, att_.data(), h_.data());
    for (int i = 0; i < cfg_.n_embd; i++) x_[i] += h_[i];
    timings.attn_proj += (t1 - t0) + (now() - t2);
    timings.attn += t2 - t1;
}

void Flint::dense_ffn(const Layer &L) {
    double t0 = now();
    rmsnorm(h_.data(), x_.data(), L.ffn_norm, cfg_.n_embd, cfg_.rms_eps);
    quantize_row_q8_K(h_.data(), hq_.data(), cfg_.n_embd);
    const int64_t nf = L.ffn_gate.n_out;
    pool_.parallel_for(2 * nf, [&](int64_t b, int64_t e, int) {
        for (int64_t r = b; r < e; r++) {
            const Mat &m = r < nf ? L.ffn_gate : L.ffn_up;
            gu_[r] = vec_dot(m.type, m.row(r % nf), hq_.data(), h_.data(), m.n_in);
        }
    });
    for (int64_t i = 0; i < nf; i++) ffn_[i] = silu(gu_[i]) * gu_[nf + i];
    matvec(L.ffn_down, ffn_.data(), h_.data());
    for (int i = 0; i < cfg_.n_embd; i++) x_[i] += h_[i];
    timings.dense_ffn += now() - t0;
}

void Flint::moe(const Layer &L, int il) {
    const int E = cfg_.n_embd, K = cfg_.n_expert_used, F = cfg_.n_ff_exp, FS = cfg_.n_ff_shexp;
    double t0 = now();
    rmsnorm(h_.data(), x_.data(), L.ffn_norm, E, cfg_.rms_eps);

    // Router: sigmoid scores, top-K, weights renormalized to sum to 1.
    for (int e = 0; e < cfg_.n_expert; e++)
        router_logits_[e] = 1.0f / (1.0f + std::exp(-vec_dot(L.router.type, L.router.row(e), nullptr, h_.data(), E)));
    int sel[16];
    float w[16];
    {
        std::vector<int> idx(cfg_.n_expert);
        for (int e = 0; e < cfg_.n_expert; e++) idx[e] = e;
        std::partial_sort(idx.begin(), idx.begin() + K, idx.end(),
                          [&](int a, int b) { return router_logits_[a] > router_logits_[b]; });
        float sum = 0;
        for (int k = 0; k < K; k++) sel[k] = idx[k], w[k] = router_logits_[idx[k]], sum += w[k];
        sum = std::max(sum, 6.103515625e-5f);
        for (int k = 0; k < K; k++) w[k] /= sum;
    }
    const int moe_index = il - (cfg_.n_layer - int(last_experts_.size()) / K);  // il minus dense layer count
    uint8_t *rec = &last_experts_[size_t(moe_index) * K];
    for (int k = 0; k < K; k++) rec[k] = uint8_t(sel[k]);
    double t1 = now();

    // Gate and up rows for the shared expert and the K routed experts, in one parallel pass.
    // Layout of gu_: [shared gate FS][shared up FS][expert k gate F][expert k up F]...
    quantize_row_q8_K(h_.data(), hq_.data(), E);
    const int64_t n_rows = 2 * FS + int64_t(K) * 2 * F;
    pool_.parallel_for(n_rows, [&](int64_t b, int64_t e, int) {
        for (int64_t r = b; r < e; r++) {
            const uint8_t *row;
            uint32_t type;
            if (r < 2 * FS) {
                const Mat &m = r < FS ? L.gate_sh : L.up_sh;
                row = m.row(r % FS);
                type = m.type;
            } else {
                const int64_t rr = r - 2 * FS, k = rr / (2 * F), j = rr % (2 * F);
                const Mat &m = j < F ? L.gate_exps : L.up_exps;
                row = m.row(int64_t(sel[k]) * F + (j % F));
                type = m.type;
            }
            gu_[r] = vec_dot(type, row, hq_.data(), nullptr, E);
        }
    });
    // Activations: shared expert into aq_[0..FS/256), expert k into the following blocks.
    for (int i = 0; i < FS; i++) ffn_[i] = silu(gu_[i]) * gu_[FS + i];
    for (int k = 0; k < K; k++) {
        const float *g = &gu_[2 * FS + int64_t(k) * 2 * F];
        for (int i = 0; i < F; i++) ffn_[FS + k * F + i] = silu(g[i]) * g[F + i];
    }
    quantize_row_q8_K(ffn_.data(), aq_.data(), FS + int64_t(K) * F);

    // Down projections: each output row sums the shared expert and the weighted routed experts.
    const block_q8_K *aq_sh = aq_.data();
    pool_.parallel_for(E, [&](int64_t b, int64_t e, int) {
        for (int64_t r = b; r < e; r++) {
            float acc = vec_dot(L.down_sh.type, L.down_sh.row(r), aq_sh, nullptr, FS);
            for (int k = 0; k < K; k++)
                acc += w[k] * vec_dot(L.down_exps.type, L.down_exps.row(int64_t(sel[k]) * E + r), aq_sh + (FS + k * F) / QK_K,
                                      nullptr, F);
            moe_out_[r] = acc;
        }
    });
    for (int i = 0; i < E; i++) x_[i] += moe_out_[i];
    timings.router += t1 - t0;
    timings.experts += now() - t1;
}

const float *Flint::forward(int32_t token, int pos) {
    if (pos >= n_ctx_) throw std::runtime_error("model: context full");
    dequant_row(tok_embd_.type, tok_embd_.row(token), x_.data(), cfg_.n_embd);
    for (int il = 0; il < cfg_.n_layer; il++) {
        const Layer &L = layers_[il];
        attention(L, il, pos);
        if (L.dense) dense_ffn(L);
        else moe(L, il);
    }
    double t0 = now();
    rmsnorm(h_.data(), x_.data(), output_norm_, cfg_.n_embd, cfg_.rms_eps);
    matvec(output_, h_.data(), logits_.data());
    timings.head += now() - t0;
    timings.tokens++;
    return logits_.data();
}

}  // namespace fl
