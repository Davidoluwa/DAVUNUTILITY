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
