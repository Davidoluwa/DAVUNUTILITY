# Flint routing traces

Expert selections recorded from llama.cpp running `flint-UD-IQ3_XXS.gguf` with greedy decoding, for
designing flintlock's expert cache, prefetcher and speculative decoding. Results and their reading
are in `coord/log-b.md` (entry "routing traces v1") and in `results.json`.

## Files

| File | What |
| --- | --- |
| `code_edit.npz` | Code-editing task: a 120-line Python file in the prompt (find bugs, add a method, emit the whole file) |
| `code_new.npz` | Write-new-code task: a single-file C11 LRU cache with tests and a benchmark |
| `chat.npz` | Plain explanation: memory hierarchy for a non-programmer |
| `code_edit_answer.npz` | Same prompt as `code_edit`, with a short closed `<think>...</think>` and `Here are the bugs I found:\n\n1. **` prefilled, so all 1299 decoded tokens are the answer: 4 bullet points, then the full corrected Python file. Answer-phase routing. |
| `code_edit_emptythink.npz` | Same prompt with an empty `<think></think>` prefilled. Flint ignores it and reasons untagged for all 1299 tokens, so this is a second reasoning-phase sample of the same task. |
| `results.json` | Output of `tools/analyze.py` on the first three traces (per-layer numbers included) |
| `results_extra.json` | The same analysis for the two `code_edit_*` traces |
| `prompts/` | The exact prompt texts (chat template applied by hand; special tokens parsed) |
| `tools/flint_trace.cpp` | Tracer: links libllama, greedy decode, hooks `ffn_moe_topk-L` via `cb_eval` |
| `tools/pack.py` | Raw tracer output -> `.npz` |
| `tools/analyze.py` | LRU / Belady hit rates, prefetch recall, expert-union sizes, hot-expert share |

Each `.npz` (`np.load`) holds:

- `topk` uint8 `[n_pos, 47, 6]`: expert ids for MoE layers 2..48 (index 0 = layer 2), for every
  position fed to the model, highest router score first.
- `phase` uint8 `[n_pos]`: 0 = prompt (prefilled in 256-token batches), 1 = single-token decode step,
  2 = injected follow-up turn (unused: no workload hit end-of-turn before 1100 tokens).

The first three workloads never left `<think>` within 1299 tokens, so they are reasoning-phase
routing. `code_edit_answer` is the answer-phase counterpart (mostly code emission).
- `tokens` int32 `[n_pos]`: the token fed at each position. `gen` int32: every greedy-sampled token.

Use `phase == 1` rows for decode statistics. Prompt rows come from batched prefill; their routing
is the same function of the hidden state, but llama.cpp computed them in batches of 256.

## How they were made

```bash
# llama.cpp: Unsloth fork, branch iq1-narrow, commit 722adcdff6341cd4befa07ca49486db17d8f6f39
git clone --depth 1 --branch iq1-narrow https://github.com/unslothai/llama.cpp
cmake -B build -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF && cmake --build build -j4
L=$PWD
g++ -O2 -std=c++17 tools/flint_trace.cpp -I$L/include -I$L/ggml/include -L$L/build/bin \
    -lllama -lggml -lggml-base -Wl,-rpath,$L/build/bin -o flint_trace
for w in code_edit code_new chat; do
  ./flint_trace flint-UD-IQ3_XXS.gguf prompts/$w.txt raw_$w 1300 --min-gen 1100 \
      --followup prompts/followup.txt --hidden --top-logits 4
  python tools/pack.py raw_$w $w.npz
done
python tools/analyze.py . --hidden-dir . --model flint-UD-IQ3_XXS.gguf --json results.json
```

`--hidden` also writes the decode-step residual streams (`ffn_inp`, `l_out`, bf16) and router
logits for the prefetch analysis. They are ~430 KB per token, so they are not committed; rerun to
get them. Machine: 4 vCPU Xeon @ 2.1 GHz (AVX-512, AMX), 15 GB RAM, model mmapped, 4 threads.

## Definitions used in the analysis

- **Decode steps only**, and caches are warmed by replaying the prompt's routing in position order
  first (what an engine's cache would hold after prefill).
- **LRU, partitioned**: one LRU per layer holding `frac x 256` experts.
  **LRU, global pool**: one LRU over all 47x256 (layer, expert) pairs holding `frac x 12032`
  entries, touched in layer order. **Belady**: offline optimal eviction (an upper bound on any
  policy), per layer.
- **Disk MB/token** = misses per token x 1,073,152 bytes (gate iq2_s + up iq2_s + down iq3_xxs).
- **Prefetch recall@k**: |top-k of the predicted scores ∩ the 6 experts llama.cpp actually chose| / 6.
  Predictors for layer L+1, all using layer L+1's bf16 router:
  - `a_router_input_L`: layer L's router input as is (`rmsnorm(ffn_inp_L) * ffn_norm_L`). Available
    before layer L's MoE runs, so a prefetch can overlap layer L's experts and layer L+1's attention.
  - `b_ffn_inp_L_renorm`: the same residual normed with layer L+1's `ffn_norm` weight. Same timing.
  - `c_l_out_L`: layer L's output (input of layer L+1). Available only after layer L's MoE, so it can
    hide only layer L+1's attention.
  - `skip2_ffn_inp_L`: predict layer L+2 from layer L (two layers of lead time).
  - `prev_token_same_layer`: baseline, the previous token's experts at that layer (@12: previous two tokens).
  - `self_check`: layer L's router on its own input, rebuilt in numpy from the bf16 dump. It
    measures the error from my reconstruction (bf16 storage), not a prediction.
- **Union over w tokens**: distinct experts selected at one layer by w consecutive decode steps
  (max 6w). This is the expert set a w-token speculative verification pass must load.
- **Hot share**: fraction of a layer's selections that go to its 10% (26) most-selected experts.
  Uniform routing would give 0.10 plus a little finite-sample noise.
