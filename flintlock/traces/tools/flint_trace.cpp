// flint_trace: greedy-decode Flint with llama.cpp and record MoE routing per token.
//
// Build against a llama.cpp build tree (see traces/README.md):
//   g++ -O2 -std=c++17 flint_trace.cpp -I$LLAMA/include -I$LLAMA/ggml/include \
//       -L$LLAMA/build/bin -lllama -lggml -lggml-base -Wl,-rpath,$LLAMA/build/bin -o flint_trace
//
// Usage:
//   flint_trace MODEL.gguf PROMPT.txt OUT_PREFIX N_PREDICT [options]
//     --min-gen N         if EOG arrives before N generated tokens, inject --followup and keep going
//     --followup FILE     text (special tokens parsed) injected after an early EOG
//     --hidden            also dump decode-step residual streams (ffn_inp, l_out) as bf16 and
//                         router logits as f32 (large; for local analysis, not for git)
//     --top-logits K      dump top-10 logits for the first K decode steps (default 4)
//     --threads N         (default 4)
//
// PROMPT.txt is raw text; special tokens like <|user|> are parsed. No BOS is added
// (Flint's tokenizer_config has add_bos_token = false).
//
// Outputs (OUT_PREFIX.*):
//   tokens.i32      every token fed to the model, in position order (prompt, decode, follow-ups)
//   phase.u8        per position: 0 = prompt chunk, 1 = single-token decode step, 2 = follow-up chunk
//   topk.u8         [n_pos, n_moe_layers, n_expert_used] expert ids, in llama.cpp's top-k order
//   gen.i32         generated (sampled) tokens, including the final one that is never fed back
//   top_logits.json top-10 (id, logit) for the first K decode steps
//   gen.txt         detokenized generation
//   meta.json       shapes and settings
//   (--hidden) ffn_inp.bf16 / l_out.bf16 [n_dec, n_moe_layers, n_embd], router_logits.f32
//              [n_dec, n_moe_layers, n_expert], dec_pos.i32 [n_dec] position of each decode row

#include "llama.h"
#include "ggml.h"
#include "ggml-backend.h"

#include <algorithm>
#include <chrono>
#include <clocale>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

static const int N_LAYER     = 49;
static const int N_DENSE     = 2;
static const int N_MOE       = N_LAYER - N_DENSE;  // 47
static const int N_EXPERT    = 256;
static const int N_USED      = 6;
static const int N_EMBD      = 2048;

struct trace_state {
    bool active   = false;
    bool decoding = false;  // current batch is a single-token decode step
    bool hidden   = false;
    int  pos0     = 0;
    int  n_tok    = 0;

    std::vector<uint8_t>  topk;      // [n_pos_cap, N_MOE, N_USED]
    std::vector<uint8_t>  topk_seen; // [n_pos_cap, N_MOE]
    // decode-only buffers, one row of [N_MOE, ...] per decode step
    std::vector<uint16_t> ffn_inp, l_out;
    std::vector<float>    router_logits;
    int dec_row = -1;
    std::vector<uint8_t>  dec_seen;  // [N_MOE * 3] for the current decode row
};

static uint16_t f32_to_bf16(float f) {
    uint32_t u;
    memcpy(&u, &f, 4);
    if ((u & 0x7fffffff) > 0x7f800000) return (uint16_t) ((u >> 16) | 0x40);  // NaN
    u += 0x7fff + ((u >> 16) & 1);
    return (uint16_t) (u >> 16);
}

static bool parse_name(const char * name, const char * prefix, int & il) {
    const size_t n = strlen(prefix);
    if (strncmp(name, prefix, n) != 0 || name[n] != '-') return false;
    char * end = nullptr;
    long v = strtol(name + n + 1, &end, 10);
    if (end == name + n + 1 || *end != '\0') return false;
    il = (int) v;
    return true;
}

static bool cb_eval(struct ggml_tensor * t, bool ask, void * ud) {
    auto * st = (trace_state *) ud;
    if (!st->active) return false;
    int il = -1;
    int kind = -1;  // 0 topk, 1 ffn_inp, 2 l_out, 3 router logits
    if      (parse_name(t->name, "ffn_moe_topk",   il)) kind = 0;
    else if (parse_name(t->name, "ffn_inp",        il)) kind = 1;
    else if (parse_name(t->name, "l_out",          il)) kind = 2;
    else if (parse_name(t->name, "ffn_moe_logits", il)) kind = 3;
    if (kind < 0 || il < N_DENSE || il >= N_LAYER) return ask ? false : true;
    if (kind > 0 && !(st->hidden && st->decoding)) return ask ? false : true;
    if (ask) return true;

    const int li = il - N_DENSE;
    std::vector<uint8_t> raw(ggml_nbytes(t));
    ggml_backend_tensor_get(t, raw.data(), 0, raw.size());
    const size_t nb0 = t->nb[0], nb1 = t->nb[1];
    const int ne0 = (int) t->ne[0], ne1 = (int) t->ne[1];

    if (kind == 0) {
        if (t->type != GGML_TYPE_I32 || ne0 != N_USED) {
            fprintf(stderr, "unexpected topk tensor %s type %d ne0 %d\n", t->name, t->type, ne0);
            exit(1);
        }
        if (ne1 != st->n_tok) {
            fprintf(stderr, "warning: %s has %d rows, batch has %d tokens\n", t->name, ne1, st->n_tok);
        }
        for (int r = 0; r < ne1 && r < st->n_tok; ++r) {
            const size_t pos = (size_t) st->pos0 + r;
            for (int k = 0; k < N_USED; ++k) {
                int32_t e;
                memcpy(&e, raw.data() + r * nb1 + k * nb0, 4);
                st->topk[(pos * N_MOE + li) * N_USED + k] = (uint8_t) e;
            }
            st->topk_seen[pos * N_MOE + li] = 1;
        }
        return true;
    }

    // hidden-state capture, decode steps only (ne1 == 1)
    if (t->type != GGML_TYPE_F32 || ne1 != 1) {
        fprintf(stderr, "unexpected hidden tensor %s type %d ne1 %d\n", t->name, t->type, ne1);
        exit(1);
    }
    const size_t row = (size_t) st->dec_row;
    if (kind == 3) {
        if (ne0 != N_EXPERT) { fprintf(stderr, "bad logits ne0 %d\n", ne0); exit(1); }
        float * dst = st->router_logits.data() + (row * N_MOE + li) * N_EXPERT;
        for (int i = 0; i < ne0; ++i) memcpy(&dst[i], raw.data() + i * nb0, 4);
    } else {
        if (ne0 != N_EMBD) { fprintf(stderr, "bad embd ne0 %d\n", ne0); exit(1); }
        uint16_t * dst = (kind == 1 ? st->ffn_inp.data() : st->l_out.data()) + (row * N_MOE + li) * N_EMBD;
        for (int i = 0; i < ne0; ++i) {
            float f;
            memcpy(&f, raw.data() + i * nb0, 4);
            dst[i] = f32_to_bf16(f);
        }
    }
    st->dec_seen[li * 3 + (kind - 1)] = 1;
    return true;
}

static std::string read_file(const std::string & path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) { fprintf(stderr, "cannot read %s\n", path.c_str()); exit(1); }
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

template <typename T>
static void write_bin(const std::string & path, const T * data, size_t n) {
    FILE * f = fopen(path.c_str(), "wb");
    if (!f) { fprintf(stderr, "cannot write %s\n", path.c_str()); exit(1); }
    fwrite(data, sizeof(T), n, f);
    fclose(f);
}

static std::vector<llama_token> tokenize(const llama_vocab * vocab, const std::string & text) {
    int n = -llama_tokenize(vocab, text.c_str(), (int) text.size(), nullptr, 0, false, true);
    std::vector<llama_token> toks(n);
    if (llama_tokenize(vocab, text.c_str(), (int) text.size(), toks.data(), n, false, true) < 0) {
        fprintf(stderr, "tokenize failed\n");
        exit(1);
    }
    return toks;
}

static std::string piece(const llama_vocab * vocab, llama_token id) {
    char buf[512];
    int n = llama_token_to_piece(vocab, id, buf, sizeof(buf), 0, true);
    return n < 0 ? std::string() : std::string(buf, n);
}

static std::string json_escape(const std::string & s) {
    std::string o;
    for (unsigned char c : s) {
        switch (c) {
            case '"':  o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n";  break;
            case '\r': o += "\\r";  break;
            case '\t': o += "\\t";  break;
            default:
                if (c < 0x20) { char b[8]; snprintf(b, sizeof(b), "\\u%04x", c); o += b; }
                else o += (char) c;
        }
    }
    return o;
}

int main(int argc, char ** argv) {
    std::setlocale(LC_NUMERIC, "C");
    if (argc < 5) {
        fprintf(stderr, "usage: %s MODEL PROMPT.txt OUT_PREFIX N_PREDICT [--min-gen N] [--followup FILE] "
                        "[--hidden] [--top-logits K] [--threads N]\n", argv[0]);
        return 1;
    }
    const std::string model_path = argv[1], prompt_path = argv[2], out = argv[3];
    const int n_predict = atoi(argv[4]);
    int min_gen = 0, top_logit_steps = 4, n_threads = 4;
    bool hidden = false;
    std::string followup_path;
    for (int i = 5; i < argc; ++i) {
        std::string a = argv[i];
        if      (a == "--min-gen"    && i + 1 < argc) min_gen = atoi(argv[++i]);
        else if (a == "--followup"   && i + 1 < argc) followup_path = argv[++i];
        else if (a == "--hidden")                      hidden = true;
        else if (a == "--top-logits" && i + 1 < argc) top_logit_steps = atoi(argv[++i]);
        else if (a == "--threads"    && i + 1 < argc) n_threads = atoi(argv[++i]);
        else { fprintf(stderr, "unknown arg %s\n", a.c_str()); return 1; }
    }

    llama_backend_init();
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 0;
    llama_model * model = llama_model_load_from_file(model_path.c_str(), mp);
    if (!model) { fprintf(stderr, "load failed\n"); return 1; }
    const llama_vocab * vocab = llama_model_get_vocab(model);
    const int n_vocab = llama_vocab_n_tokens(vocab);

    const std::string prompt_text = read_file(prompt_path);
    const std::vector<llama_token> prompt = tokenize(vocab, prompt_text);
    std::vector<llama_token> followup;
    if (!followup_path.empty()) followup = tokenize(vocab, read_file(followup_path));
    const int n_prompt = (int) prompt.size();

    const int max_followups = 4;
    const int n_pos_cap = n_prompt + n_predict + max_followups * ((int) followup.size()) + 8;

    trace_state st;
    st.hidden = hidden;
    st.topk.assign((size_t) n_pos_cap * N_MOE * N_USED, 255);
    st.topk_seen.assign((size_t) n_pos_cap * N_MOE, 0);
    st.dec_seen.assign(N_MOE * 3, 0);
    if (hidden) {
        st.ffn_inp.assign((size_t) n_predict * N_MOE * N_EMBD, 0);
        st.l_out.assign((size_t) n_predict * N_MOE * N_EMBD, 0);
        st.router_logits.assign((size_t) n_predict * N_MOE * N_EXPERT, 0.0f);
    }

    const int chunk = 256;
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx           = (uint32_t) (((n_pos_cap + 255) / 256) * 256);
    cp.n_batch         = chunk;
    cp.n_ubatch        = chunk;
    cp.n_threads       = n_threads;
    cp.n_threads_batch = n_threads;
    cp.cb_eval         = cb_eval;
    cp.cb_eval_user_data = &st;
    cp.no_perf         = false;
    llama_context * ctx = llama_init_from_model(model, cp);
    if (!ctx) { fprintf(stderr, "context failed\n"); return 1; }

    llama_batch_ext * batch = llama_batch_ext_init(ctx);
    std::vector<llama_token> fed;    // every token fed, by position
    std::vector<uint8_t>     phase;  // per position
    std::vector<llama_token> gen;
    std::vector<int32_t>     dec_pos;
    std::string top_json = "[";
    int n_pos = 0, n_followups = 0;

    // feed a multi-token chunk with logits for every token (keeps all rows in the last layer)
    auto feed_chunk = [&](const std::vector<llama_token> & toks, uint8_t ph) {
        for (size_t off = 0; off < toks.size(); off += chunk) {
            const int n = (int) std::min<size_t>(chunk, toks.size() - off);
            llama_batch_ext_clear(batch);
            for (int i = 0; i < n; ++i) {
                const int idx = llama_batch_ext_add_token(batch, 0, toks[off + i]);
                const llama_pos pos = n_pos + i;
                llama_batch_ext_set_pos(batch, idx, &pos);
                llama_batch_ext_set_output_logits(batch, idx, true);
            }
            st.active = true; st.decoding = false; st.pos0 = n_pos; st.n_tok = n;
            if (llama_process(ctx, LLAMA_PROCESS_TYPE_DECODE, batch)) { fprintf(stderr, "decode failed\n"); exit(1); }
            st.active = false;
            for (int i = 0; i < n; ++i) { fed.push_back(toks[off + i]); phase.push_back(ph); }
            n_pos += n;
        }
    };

    auto argmax_and_log = [&](int step) -> llama_token {
        const float * logits = llama_get_logits_ith(ctx, -1);
        llama_token best = 0;
        for (int i = 1; i < n_vocab; ++i) if (logits[i] > logits[best]) best = i;
        if (step < top_logit_steps) {
            std::vector<int> idx(n_vocab);
            for (int i = 0; i < n_vocab; ++i) idx[i] = i;
            std::partial_sort(idx.begin(), idx.begin() + 10, idx.end(), [&](int a, int b) {
                return logits[a] > logits[b] || (logits[a] == logits[b] && a < b);
            });
            if (step > 0) top_json += ",";
            top_json += "\n  {\"step\": " + std::to_string(step) + ", \"pos\": " + std::to_string(n_pos) + ", \"top10\": [";
            for (int k = 0; k < 10; ++k) {
                char b[160];
                snprintf(b, sizeof(b), "%s[%d, %.6f, \"%s\"]", k ? ", " : "", idx[k], logits[idx[k]],
                         json_escape(piece(vocab, idx[k])).c_str());
                top_json += b;
            }
            top_json += "]}";
        }
        return best;
    };

    const auto t0 = std::chrono::steady_clock::now();
    feed_chunk(prompt, 0);
    const auto t1 = std::chrono::steady_clock::now();
    fprintf(stderr, "prompt: %d tokens in %.1f s\n", n_prompt, std::chrono::duration<double>(t1 - t0).count());

    int step = 0;
    llama_token tok = argmax_and_log(step++);
    gen.push_back(tok);
    std::string text = piece(vocab, tok);
    double t_dec = 0.0;
    int n_dec_steps = 0;
    while ((int) gen.size() < n_predict) {
        if (llama_vocab_is_eog(vocab, tok)) {
            if ((int) gen.size() < min_gen && !followup.empty() && n_followups < max_followups) {
                fprintf(stderr, "EOG after %zu generated tokens; injecting follow-up\n", gen.size());
                // the EOG token itself is part of the conversation: feed it, then the follow-up
                // (Flint's EOG set includes <|user|>; do not repeat it if the follow-up starts with it)
                std::vector<llama_token> fu = { tok };
                fu.insert(fu.end(), followup.begin() + (followup[0] == tok ? 1 : 0), followup.end());
                feed_chunk(fu, 2);
                n_followups++;
                text += "\n[[FOLLOW-UP INJECTED]]\n";
                tok = argmax_and_log(step++);
                gen.push_back(tok);
                text += piece(vocab, tok);
                continue;
            }
            break;
        }
        llama_batch_ext_clear(batch);
        const int idx = llama_batch_ext_add_token(batch, 0, tok);
        const llama_pos pos = n_pos;
        llama_batch_ext_set_pos(batch, idx, &pos);
        llama_batch_ext_set_output_logits(batch, idx, true);
        st.active = true; st.decoding = true; st.pos0 = n_pos; st.n_tok = 1;
        st.dec_row = (int) dec_pos.size();
        std::fill(st.dec_seen.begin(), st.dec_seen.end(), 0);
        const auto ta = std::chrono::steady_clock::now();
        if (llama_process(ctx, LLAMA_PROCESS_TYPE_DECODE, batch)) { fprintf(stderr, "decode failed\n"); return 1; }
        t_dec += std::chrono::duration<double>(std::chrono::steady_clock::now() - ta).count();
        st.active = false;
        if (hidden) {
            for (int i = 0; i < N_MOE * 3; ++i) {
                if (!st.dec_seen[i]) { fprintf(stderr, "missing hidden capture %d at pos %d\n", i, n_pos); return 1; }
            }
        }
        dec_pos.push_back(n_pos);
        fed.push_back(tok); phase.push_back(1);
        n_pos++;
        n_dec_steps++;
        tok = argmax_and_log(step++);
        gen.push_back(tok);
        text += piece(vocab, tok);
        if (n_dec_steps % 100 == 0) {
            fprintf(stderr, "decoded %d steps, %.2f tok/s\n", n_dec_steps, n_dec_steps / t_dec);
        }
    }
    top_json += "\n]\n";

    // check every fed position got routing for every MoE layer
    int missing = 0;
    for (int p = 0; p < n_pos; ++p) for (int l = 0; l < N_MOE; ++l) missing += !st.topk_seen[(size_t) p * N_MOE + l];
    if (missing) fprintf(stderr, "WARNING: %d (position, layer) routing entries missing\n", missing);

    write_bin(out + ".tokens.i32", fed.data(), fed.size());
    write_bin(out + ".phase.u8", phase.data(), phase.size());
    write_bin(out + ".topk.u8", st.topk.data(), (size_t) n_pos * N_MOE * N_USED);
    write_bin(out + ".gen.i32", gen.data(), gen.size());
    if (hidden) {
        const size_t nd = dec_pos.size();
        write_bin(out + ".ffn_inp.bf16", st.ffn_inp.data(), nd * N_MOE * N_EMBD);
        write_bin(out + ".l_out.bf16", st.l_out.data(), nd * N_MOE * N_EMBD);
        write_bin(out + ".router_logits.f32", st.router_logits.data(), nd * N_MOE * N_EXPERT);
        write_bin(out + ".dec_pos.i32", dec_pos.data(), nd);
    }
    { std::ofstream f(out + ".top_logits.json"); f << top_json; }
    { std::ofstream f(out + ".gen.txt", std::ios::binary); f << text; }
    {
        std::ofstream f(out + ".meta.json");
        f << "{\n"
          << "  \"model\": \"" << json_escape(model_path) << "\",\n"
          << "  \"prompt_file\": \"" << json_escape(prompt_path) << "\",\n"
          << "  \"n_prompt\": " << n_prompt << ",\n"
          << "  \"n_pos\": " << n_pos << ",\n"
          << "  \"n_decode_steps\": " << n_dec_steps << ",\n"
          << "  \"n_generated\": " << gen.size() << ",\n"
          << "  \"n_followups\": " << n_followups << ",\n"
          << "  \"moe_layers\": [" << N_DENSE << ", " << (N_LAYER - 1) << "],\n"
          << "  \"n_expert\": " << N_EXPERT << ",\n"
          << "  \"n_expert_used\": " << N_USED << ",\n"
          << "  \"missing_routing_entries\": " << missing << ",\n"
          << "  \"decode_seconds\": " << t_dec << ",\n"
          << "  \"decode_tok_per_s\": " << (t_dec > 0 ? n_dec_steps / t_dec : 0.0) << ",\n"
          << "  \"threads\": " << n_threads << ",\n"
          << "  \"hidden\": " << (hidden ? "true" : "false") << "\n"
          << "}\n";
    }
    fprintf(stderr, "done: %d positions, %d decode steps, %.2f tok/s decode (with capture)\n",
            n_pos, n_dec_steps, t_dec > 0 ? n_dec_steps / t_dec : 0.0);
    llama_perf_context_print(ctx);
    llama_batch_ext_free(batch);
    llama_free(ctx);
    llama_model_free(model);
    llama_backend_free();
    return 0;
}
