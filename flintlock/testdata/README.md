# Flint reference outputs

Ground truth for checking flintlock against llama.cpp running the same weights
(`flint-UD-IQ3_XXS.gguf`, sha256 `7a0a095dde1d931063a5d571e19497d997edbc783eb1ed6b86529bfab9d94804`),
plus reference tokenizations from the original Hugging Face tokenizer.

## Files

| File | What |
| --- | --- |
| `tokenization.json` | 37 strings, token ids from HF `tokenizers` (`hf_ids`) and from llama.cpp (`llama_cpp_ids`), with `agree` per string |
| `decode_<prompt>.json` | Prompt ids, 64 greedy output ids + text, top-10 logits at decode steps 0-3 |
| `act_<prompt>.npz` | Activations at decode step 1 (the first single-token step), for layer-by-layer debugging |
| `prompts/` | The three prompt texts |
| `tools/` | `flint_tokenize.cpp`, `tokenize_compare.py`, `tokenize_fuzz.py`, `make_refs.py` (the decode runs use `traces/tools/flint_trace.cpp`) |

## Tokenization

Match **`hf_ids`**: that is the tokenizer Flint was trained with. Token ids are without BOS
(`add_bos_token` is false for Flint) and with special tokens such as `<|user|>` parsed.

llama.cpp agrees on 36 of 37 strings, including every ASCII camelCase, PascalCase and ALLCAPS case.
The one disagreement is Cyrillic camelCase (`cyrillic_camel`): `ПоИД` is `По|И|Д` in HF but
`П|о\xD0|\x98|Д` in llama.cpp (the second llama.cpp token is `о` plus the first UTF-8 byte of `И`).

Why: Flint's split regex keeps a lowercase run apart from a following uppercase letter
(`[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+|...`). llama.cpp has no hand-written
splitter for this regex and its generic path maps `\p{Lu}`, `\p{Ll}`, `\p{Lt}`, `\p{Lm}`, `\p{Lo}` all to
one LETTER class (`src/unicode.cpp:1496-1500`), so `camelCase` reaches BPE as one pre-token. For ASCII
that changes nothing: no vocab token contains a lowercase->uppercase transition, so BPE never merges
across the boundary. It changes ids only when a byte-level token can span the boundary, which needs
the lowercase letter and the uppercase one to share UTF-8 lead bytes (Cyrillic `о`/`И` are both
`0xD0 ..`). Fuzzing (`tools/tokenize_fuzz.py`) over the llama.cpp source tree plus 20,000 synthetic
mixed-case identifiers (79M characters, 31.8M tokens): 2 of 49,301 strings differ, both Cyrillic
camelCase in minified JavaScript.

For flintlock: implement the split with real Unicode general categories (Lu, Ll, Lt, Lm, Lo, M);
then all 37 `hf_ids` should match.

```bash
python tools/tokenize_compare.py ./flint_tokenize flint-UD-IQ3_XXS.gguf tokenizer.json tokenization.json
python tools/tokenize_fuzz.py ./flint_tokenize flint-UD-IQ3_XXS.gguf tokenizer.json path/to/llama.cpp
```

`tokenizer.json` is from `RecursiveSI/flint` (main, downloaded 2026-11-05); `tokenizers` 0.23.3.

## Decode references

| Prompt | Prompt tokens | Why |
| --- | --- | --- |
| `p1_raw_completion` | 5 | No chat template, shortest path ("The capital of France is" -> " Paris") |
| `p2_chat_short` | 26 | Chat template with special tokens; output opens with `<think>` |
| `p3_chat_long_swa` | 1097 | Longer than the 513-token sliding window, so SWA masking, RoPE and NoPE layers all matter |

`decode_<prompt>.json`:
- `prompt_ids`: llama.cpp's tokenization. HF `tokenizers` gives identical ids for all three
  prompts, and for the three trace prompts.
- `greedy_ids`: 64 greedy tokens. Greedy = argmax over the raw logits; ties go to the lowest id
  (none occurred).
- `top10_logits`: steps 0-3. Step 0 is the logits after the full prompt (predicts `greedy_ids[0]`).
  Step s is after feeding `greedy_ids[s-1]` at position `n_prompt + s - 1`. Raw logits, no softmax.
  `pieces` are the HF-decoded token strings.

Top-1 minus top-2 logit margin at steps 0-3: p1 2.26 / 1.77 / 3.36 / 5.96, p2 16.07 / 3.97 / 6.18 /
14.40, p3 16.66 / 5.40 / 8.42 / 6.96. An engine within a few tenths of a logit of these values
should reproduce at least the first 4 greedy tokens. Later tokens can legitimately diverge once
two candidates come close.

`act_<prompt>.npz`: the first single-token decode step (`token` = `greedy_ids[0]` fed at `pos` =
`n_prompt`), MoE layers 2..48 (index 0 = layer 2):
- `ffn_inp` `[47, 2048]`: residual after attention, before `ffn_norm`.
- `l_out` `[47, 2048]`: layer output.
- `router_logits` `[47, 256]`: before sigmoid.
- `topk` uint8 `[47, 6]`: chosen experts, highest first.

`ffn_inp` and `l_out` were rounded to bf16 when captured (relative error up to 2^-9). Compare with a
relative tolerance of ~1e-2 rather than bitwise. `router_logits` are exact f32. Layers 0-1 (dense)
are not captured. If layer 2's `ffn_inp` matches, layers 0-1 are right.

Reproducibility: two separate runs on the same prompt (p3 here and the `code_edit` routing trace,
which used a different context size) gave identical greedy ids and bit-identical top-10 logits.

### How they were made

```bash
# llama.cpp: Unsloth fork, branch iq1-narrow, commit 722adcdff6341cd4befa07ca49486db17d8f6f39
git clone --depth 1 --branch iq1-narrow https://github.com/unslothai/llama.cpp && cd llama.cpp
cmake -B build -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF && cmake --build build -j4
L=$PWD
g++ -O2 -std=c++17 traces/tools/flint_trace.cpp -I$L/include -I$L/ggml/include -L$L/build/bin \
    -lllama -lggml -lggml-base -Wl,-rpath,$L/build/bin -o flint_trace
g++ -O2 -std=c++17 testdata/tools/flint_tokenize.cpp -I$L/include -I$L/ggml/include -L$L/build/bin \
    -lllama -Wl,-rpath,$L/build/bin -o flint_tokenize
for p in p1_raw_completion p2_chat_short p3_chat_long_swa; do
  ./flint_trace flint-UD-IQ3_XXS.gguf testdata/prompts/$p.txt ref_$p 64 --hidden --top-logits 4
  python testdata/tools/make_refs.py ref_$p testdata/prompts/$p.txt testdata $p
done
```

llama.cpp settings, all defaults unless listed:
- CPU only, 4 threads, model mmapped.
- `n_ctx` = prompt + 64 rounded up to 256; `n_batch` = `n_ubatch` = 256. The prompt is prefilled in
  256-token chunks with logits requested for every prompt token, so the last layer computes all
  rows. Decode is one token per call.
- `flash_attn` = auto. KV cache f16, full-size SWA cache.
- llama.cpp repacks all q6_K tensors into its AMX buffer on this CPU (Xeon @ 2.1 GHz, AVX-512 +
  AMX). iq2_s, iq3_xxs and bf16 tensors use the generic CPU path.
- Model facts from the load log:
  - rope type 2 (NEOX, rotate halves), freq_base 10000.
  - n_swa 513. Layers 0, 1, 5, 9, ..., 45, 48 are full attention without RoPE; the rest are SWA
    with RoPE.
  - rms_norm_eps 1e-6.
  - Sigmoid gating, top-k weights normalized, scale 1.0, no selection-bias tensor.
