# Worker A log

## 2026-11-05 12:05 UTC: engine repo started, roofline measured
Done: benchmarks (`bench/membw.c`, `bench/diskbw.c`), zero-copy GGUF reader (`src/gguf.*`),
per-token traffic inspector (`tools/inspect.cpp`). Brief for B in `coord/worker-b-brief.md`.
Findings: DRAM ~43 GB/s (4 threads), L3 ~90 GB/s up to 128 MB, disk ~3 GB/s random. Flint IQ3_XXS
streams 1.67 GB/token (1.37 GB always active at q6_K, 0.30 GB routed). Ceiling ~26 tok/s in RAM.
Asks for B: routing traces (Task 2) first, then reference outputs (Task 3), then paper notes (Task 1).
Next: CPU kernels for the q6_K / iq2_s / iq3_xxs formats and a Flint forward pass.

## 2026-11-05 11:53 UTC: doorbell is live
Done: opened draft PR #3 (https://github.com/Davidoluwa/DAVUNUTILITY/pull/3) and subscribed to it.
Asks for B: comment on PR #3 with your branch name and doorbell PR number once you are set up.
Next: CPU kernels for q6_K, iq2_s and iq3_xxs, then the Flint forward pass.

## 2026-11-05 12:10 UTC: Flint runs end to end in flintlock
Done: q6_K/iq2_s/iq3_xxs/bf16 dot kernels (match scalar reference to 1e-8), tokenizer, Flint forward
pass, `build/run` CLI. Greedy output is coherent and correct (prime check, sky-is-blue answers).
Findings:
- Decode 6.5 tok/s warm (153 ms/token): experts 70 ms, attention projections 58 ms, head 11 ms,
  router 6 ms. File barely fits in page cache, so experts partly come from disk. Unoptimized.
- Tokenizer matches HF `tokenizers` 0.23.3 on 95,180 tokens (`testdata/tokenizer_strings.txt` plus
  big code/JSON/Markdown files). llama.cpp collapses \p{Lu}/\p{Ll} into one letter class for this
  regex, so its camelCase/ALLCAPS tokenization differs from training. Treat llama.cpp token ids as
  non-reference for those strings.
- `run --trace FILE` dumps routed experts per token, so A can also produce routing traces.
Asks for B: Task 2 traces from llama.cpp are still useful as an independent check. Task 3 reference
logits matter most now (to quantify our numeric drift).
Next: resident set in huge pages + AVX-512 VNNI kernels, then expert cache under 4 GB.

## 2026-11-05 12:45 UTC: under 4 GB at 9.8 tok/s; v1 targets need a decision
Done: AVX-512 kernels, huge-page resident set, O_DIRECT expert cache with fixed budget, next-layer
prefetch, cache-aware routing option, teacher-forced eval tool. Details: docs/DESIGN.md.
Findings:
- `--ram-gb 4 --prefetch 10`: 9.8 tok/s, RSS 3.68 GB, output identical to full-RAM run.
- Next-layer router prediction recall: 80% (top-6), 92% (top-10).
- Steering (swap missing experts for resident runners-up) shifts outputs a lot: 4.7% swaps -> 86.5%
  top-1 agreement, KL 0.22. Off by default.
- Expert math is compute-bound on codebook decode (~9 Gweights/s per core).
- 100 tok/s for a 2.5B-active model on 4 cores / 43 GB/s is out of reach by 2-3x on each of
  bandwidth, disk and compute. Asking the user about hardware vs model.
Asks for B: Task 3 reference logits still useful. Paper notes on expert-aware speculative decoding
(DraftExpert, EVICT, AcceptMoE) and on cheap decode of codebook quants are now the most relevant.

## 2026-11-05 13:05 UTC: read B's traces and references; pings did not wake A; A's disk allowance spent
Done: copied B's `traces/`, `testdata/`, `docs/papers.md`, `coord/log-b.md` into this branch.
Tokenizer matches all 37 `hf_ids` in `testdata/tokenization.json` (including Cyrillic camelCase).
Wrote `tools/check_ref.cpp` + `tools/ref_to_txt.py` to compare greedy ids and top-10 logits with B's
`decode_*.json`.
Findings:
- B's three pings on PR #3 (12:01, 12:31, 12:32) did not wake A; A saw them at a 12:46 check-in.
  Same GitHub user on both sides, so no wake-up events. See coord/README.md.
- Correction to A's earlier claim: llama.cpp's merged letter classes change pre-tokens for camelCase,
  but token ids only for rare non-ASCII cases (B's fuzzing).
- A's sandbox disk fell to 1-2 MB/s after a few hundred GB of reads, so A cannot run the model now.
  The 3 GB/s figure was a burst rate.
Asks for B (B's machine has the model):
1. Run the reference check on this branch: `make build/check_ref`, then for each prompt
   `python3 -I tools/ref_to_txt.py testdata/decode_<p>.json > <p>.txt && ./build/check_ref -m MODEL <p>.txt`
   (no --ram-gb, so it reads the model through the page cache). Report the output lines.
2. If any prompt diverges, compare per-layer activations against your `act_*.npz` to find the layer.
Next: waiting on the user's hardware/model decision; meanwhile code-only work.
