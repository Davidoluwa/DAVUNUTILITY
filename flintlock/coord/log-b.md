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

## 2026-11-05 12:32 UTC: routing traces v1 pushed (Task 2)
Done: `traces/{code_edit,code_new,chat}.npz` with `topk` uint8 `[n_pos, 47, 6]` (1299 greedy decode
steps each, plus prompt rows; `phase == 1` marks decode rows), `traces/results.json` (all numbers,
per layer), `traces/README.md` (format, exact commands, metric definitions). Tools in `traces/tools/`.
Command: `python traces/tools/analyze.py traces --hidden-dir RAW --model flint-UD-IQ3_XXS.gguf`.
Caveat: all three generations stayed inside `<think>` for all 1299 tokens (Flint reasons at length),
so this is reasoning-phase routing. An answer-phase trace (empty `<think></think>` prefilled) is next.

Findings (decode steps only; caches warmed with the prompt's routing; columns code_edit / code_new / chat):

| Expert hit rate | 10% (26/layer) | 20% (51/layer) | 30% (77/layer) | 50% (128/layer) |
| --- | --- | --- | --- | --- |
| LRU per layer | .38 / .33 / .41 | .57 / .49 / .62 | .71 / .63 / .74 | .86 / .83 / .88 |
| LRU one global pool | .37 / .32 / .41 | .57 / .50 / .62 | .71 / .63 / .74 | .87 / .84 / .88 |
| Decayed-frequency (EMA 0.98) | .46 / .41 / .51 | .63 / .58 / .68 | .74 / .70 / .78 | .87 / .85 / .89 |
| Belady (offline optimum) | .64 / .59 / .67 | .78 / .74 / .81 | .86 / .84 / .88 | .94 / .94 / .95 |
| Disk MB/token, global LRU | 191 / 205 / 180 | 129 / 153 / 114 | 87 / 111 / 79 | 41 / 48 / 35 |

- Per layer (20%, mean of 3): worst layers 2-7 (0.35-0.44), best 13-21 (0.60-0.69), the rest
  0.53-0.63. Per-layer hit rate tracks per-layer hotness almost exactly (r = 0.96), so per-layer
  cache sizes should come from measured hit-rate curves (as MoE-CORE does).
- Global pool vs per-layer partition: no difference. EMA scoring is +3 to +8 points over LRU at
  10-30%. Belady is +20 at 20%, so a better policy has headroom (MoE-CORE's RHAC; see docs/papers.md).
- Prefetch, recall@6 / recall@12 of layer L+1's experts (mean over predicted layers 3..48):

  | Predictor (all use layer L+1's router) | code_edit | code_new | chat |
  | --- | --- | --- | --- |
  | layer L's router input as is | .77 / .92 | .78 / .93 | .79 / .93 |
  | layer L's `ffn_inp`, renormed with L+1's `ffn_norm` | .77 / .92 | .78 / .93 | .79 / .94 |
  | layer L's output (after its MoE; less lead time) | .85 / .97 | .87 / .98 | .87 / .98 |
  | two layers ahead (L+2 from L) | .69 / .85 | .71 / .87 | .71 / .87 |
  | baseline: previous token's experts, same layer | .15 / .21 | .17 / .22 | .19 / .26 |

  Per layer, recall@6 is lowest for layer 3 (0.61) and 47 (0.65), 0.70-0.85 elsewhere, best
  around layers 34-40. Layer 2 has no earlier MoE layer to predict from.
- LRU (per layer) plus prefetching layer L+1's predicted top-k before it runs:

  | 20% cache | demand hit | stalled loads/token | prefetch loads/token | total disk MB/token |
  | --- | --- | --- | --- | --- |
  | no prefetch | .57 / .49 / .62 | 121 / 143 / 108 | 0 | 130 / 153 / 115 |
  | prefetch top-6 | .86 / .86 / .88 | 38 / 41 / 35 | 123 / 141 / 108 | 173 / 196 / 153 |
  | prefetch top-12 | .91 / .92 / .92 | 24 / 24 / 22 | 286 / 307 / 277 | 333 / 355 / 321 |

  30% cache + top-6 prefetch: demand hit .90 / .89 / .91, total disk 122 / 146 / 108 MB/token.
  Estimate, bandwidth only, using A's 43 GB/s DRAM and 3 GB/s disk: at 20% with no prefetch,
  ~130 MB of exposed reads (~43 ms) plus ~32 ms for the 1.37 GB always-active set is ~13 tok/s.
  Top-6 prefetch leaves ~40 MB exposed but reads ~175 MB in total (~58 ms), so it is disk-bandwidth
  bound at ~17 tok/s. Top-12 reads ~335 MB (~9 tok/s). So prefetch hides latency but adds traffic.
  At 20% cache, prefetch only high-confidence experts (top-6 or fewer). Raising the hit rate
  (better policy, more cache, smaller experts) is what moves the ceiling.
- Expert union per layer over w consecutive decode steps (mean, p90; uniform-random would be
  11.9 / 23.2 / 44.2): w=2: 11.1 / 11.0 / 10.9 (p90 12); w=4: 20.2 / 20.1 / 19.4 (p90 23);
  w=8: 34.8 / 35.9 / 33.4 (p90 40-42). Consecutive tokens share only ~0.9 of 6 experts per layer.
  Verifying 8 drafted tokens therefore touches ~5.7x the expert bytes of one token. Speculative
  decoding pays off only if acceptance beats that, or if verification is restricted to resident
  experts (AcceptMoE, see papers.md).
- Hot experts: within a workload the top 10% (26) of each layer's experts take 0.41 / 0.39 / 0.47
  of selections, and the top 20% take 0.59 / 0.58 / 0.64. But hot sets do not transfer between
  workloads: top-10% sets overlap 21-37%, and a hot set learned on the other two workloads covers
  only 0.20-0.23 of a workload's selections (uniform = 0.10). Static pinning from a profile is worth
  ~2x over random, not the 4x seen in-workload. The cache needs to adapt online.
- Tracing cost: decode ran at ~5.3-6.1 tok/s with all hooks (4 threads, model mmapped, 15 GB RAM),
  not a benchmark. (code_edit dropped to 2.7 tok/s for a stretch while I ran a RAM-heavy job.)
Asks for the other worker: none. Tell me if you want other cache fractions, a specific policy
simulated, or different workloads (agentic tool use?).
Next: Task 3 reference outputs, answer-phase trace, then Task 1 paper notes.
