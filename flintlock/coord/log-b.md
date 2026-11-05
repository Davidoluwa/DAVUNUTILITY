# Worker B log

## 2026-11-05 12:02 UTC: worker B online
Done: read `coord/README.md` and `coord/worker-b-brief.md` from `ccr-11fa8e16-o7vrpz`. Branch is
`ccr-bc7d2125-a6hw18`. Started downloading `flint-UD-IQ3_XXS.gguf` and building Unsloth's llama.cpp
(`iq1-narrow`, commit `722adcdff6341cd4befa07ca49486db17d8f6f39`) CPU-only.
Findings: my machine is also 4 vCPU Xeon @ 2.10 GHz, 15 GB RAM, no GPU, ~31 GB free disk.
Asks for the other worker: none yet.
Next: open doorbell PR, then Task 2 (routing traces), Task 3 (reference outputs), Task 1 (papers).
Task 3 addition from my user: reference token ids also from the HF `tokenizers` library with
`RecursiveSI/flint`'s `tokenizer.json`, including camelCase and ALLCAPS strings, because
llama.cpp's version of Flint's split pattern may merge upper/lowercase letters differently.

## 2026-11-05 12:22 UTC: setup done, GGUF verified, tokenizer finding, traces running
Done: doorbell is draft PR #4 (https://github.com/Davidoluwa/DAVUNUTILITY/pull/4), subscribed; pinged
PR #3. GGUF downloaded, `sha256sum` = `7a0a095d...b9d94804` (matches the brief). llama.cpp built
CPU-only (`cmake -B build -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF`).
Wrote `traces/tools/flint_trace.cpp` (links libllama; greedy decode, hooks `ffn_moe_topk-L` plus,
optionally, `ffn_inp-L`, `l_out-L`, `ffn_moe_logits-L` via `cb_eval`). Routing trace 1 of 3 done.
Findings:
- GGUF facts relevant to A: no `exp_probs_b` selection bias tensor, so selection is plain top-6 of
  the bf16 router logits (sigmoid is monotonic). `expert_gating_func = 2` (sigmoid),
  `expert_weights_norm = true`, `expert_weights_scale = 1.0`, `rms_norm_eps = 1e-6`.
  `flint.expert_shared_count = 2` in the GGUF, but the shared tensors are one 1024-wide FFN.
  One routed expert (gate iq2_s + up iq2_s + down iq3_xxs) = 1,073,152 bytes; all 47x256 = 12.9 GB.
- Router rebuild check: `rmsnorm(ffn_inp_L) * ffn_norm_L` times the bf16 router in numpy reproduces
  llama.cpp's top-6 set exactly on 98.9% of (token, layer) pairs (99.8% of individual experts); the
  rest is bf16 rounding of my stored residual. llama.cpp's top-k comes out sorted by score, descending.
- Tokenizer: llama.cpp does collapse `\p{Lu}`/`\p{Ll}`/`\p{Lt}`/`\p{Lm}`/`\p{Lo}` to one LETTER class
  (`src/unicode.cpp:1496-1500`, and there is no hand-written splitter for Flint's regex), so `camelCase`
  stays one pre-token where HF splits `camel|Case`. But the token ids almost never change: no vocab
  token contains a lowercase->uppercase transition, so BPE cannot merge across that boundary in
  ASCII. Fuzz over the llama.cpp tree plus 20k synthetic mixed-case identifiers (79M chars, 31.8M
  tokens): 2 of 49,301 strings differ, both Cyrillic camelCase (`ПоИД`: HF `По|И|Д`, llama.cpp
  `П|о\xD0|\x98|Д`). A byte-level token can cross the boundary when upper and lowercase letters share
  a UTF-8 lead byte. ASCII camelCase/ALLCAPS: identical in every test. So A's tokenizer should implement
  HF's regex (with real Lu/Ll classes), and llama.cpp ids are not ground truth for non-ASCII mixed case.
Asks for the other worker: none.
Next: traces 2-3 (code_new, chat), then analysis; Task 3 decode references.
