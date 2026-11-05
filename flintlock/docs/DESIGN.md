# flintlock design notes

Decode speed for a batch-1 LLM is set by how many bytes each token has to move, and from where.
Every design choice here follows from three measured numbers on the dev box and one number
from the model.

## The dev box (4 vCPU Xeon 6, AVX-512 + VNNI + AMX, 15 GB RAM, no GPU)

| Resource | Measured | Tool |
| --- | --- | --- |
| DRAM read, 4 threads | ~43 GB/s | `build/membw` |
| L3-resident read (<=128 MB set) | ~90 GB/s | `build/membw` |
| Disk, random 1 MB direct reads | ~2.4-3.6 GB/s burst | `build/diskbw` |

The disk figure is a burst rate. After a few hundred GB of reads in one session, this sandbox's
disk dropped to 1-2 MB/s. Any design that streams experts must be sized against the sustained rate
of the real target device, not a burst benchmark.

## The model: per-token traffic for Flint (`UD-IQ3_XXS`, 14.5 GB)

From `build/inspect`. Every decoded token streams:

| Part | Format | MB/token | Notes |
| --- | --- | --- | --- |
| Attention projections | q6_K | 759 | 49 layers; 32 query heads x 128 = 2x hidden size |
| LM head | q6_K | 252 | |
| Shared expert | q6_K | 243 | |
| Dense FFN (layers 0-1) | q6_K | 62 | |
| Router | bf16 | 49 | |
| **Always active, total** | | **1,366** | 1.36 GB resident |
| Routed experts (6 of 256) | iq2_s / iq3_xxs | 303 | 12.9 GB on disk, 1.07 MB per expert |

Ceiling from DRAM bandwidth alone: 1.67 GB / 43 GB/s = **~26 tok/s**, before anything else.

## What exists (all measured on the dev box)

| Version | Decode | RAM | Notes |
| --- | --- | --- | --- |
| First working build | 6.5 tok/s | 11 GB | mmap, AVX2 kernels |
| AVX-512 kernels, huge-page resident set | 9.0 tok/s | 12 GB | experts fault in from disk |
| Expert cache, 4 GB budget, exact routing | 7.4 tok/s | **3.7 GB** | identical output to full-RAM run |
| + next-layer prefetch (10 experts) | 9.0 tok/s | 3.7 GB | 92% of experts predicted one layer ahead |
| + balanced gate/up scheduling | **9.8 tok/s** | 3.7 GB | current |

Correctness checks:
- Kernels match a scalar reference to 1e-8 (`build/test_quants`).
- Tokenizer matches Hugging Face `tokenizers` on 95k tokens (`tools/hf_tokenize.py`).
- 4 GB run vs full-RAM run: 100% top-1 agreement, KL 0 (`build/eval`).

## Expert routing (from `run --trace`, 600 decoded tokens of a code edit)

| Cache size (share of experts) | LRU hit | LFU hit | Optimal (Belady) |
| --- | --- | --- | --- |
| 10% | 35% | 38% | 61% |
| 17% (what fits in 4 GB) | 49% | 51% | 71% |
| 30% | 65% | 66% | 82% |
| 50% | 81% | 81% | 90% |

- Consecutive tokens share only 0.96 of their 6 experts per layer: little short-range reuse.
- A window of 4 tokens touches 20 distinct experts per layer (3.35x one token), so speculative
  verification saves only ~16% of expert reads.
- The top 10% of experts cover 40% of picks; 236 of 256 experts per layer get used in 600 tokens.

So with exact routing, a 4 GB budget cannot get past ~71% hits even with perfect knowledge of the
future. Disk then caps decode near 20 tok/s.

## Prefetch and cache-aware routing, measured (4 GB budget)

Next-layer prefetch (run layer L+1's router on layer L's hidden state, start reads early). Output
is unchanged; only timing moves.

| Prefetch | Decode | Expert I/O per token | Loaded on demand | Prediction recall |
| --- | --- | --- | --- | --- |
| off | 7.4 tok/s | 40 ms | 57% | n/a |
| 6 experts | 8.9 tok/s | 17 ms | 14% | 80% |
| 10 experts | 9.0 tok/s | 14 ms | 7% | 92% |

Cache-aware routing (`--steer depth,ratio`), teacher-forced on 400 tokens of mixed prose and code
against the exact full-RAM run (`build/eval`):

| Steering | Cache hits | Picks swapped | Top-1 agreement | KL nats/token | Perplexity |
| --- | --- | --- | --- | --- | --- |
| off | 52% | 0% | 100% | 0 | 12.07 |
| 4, 0.9 | 57% | 4.7% | 86.5% | 0.22 | 11.01 |
| 8, 0.8 | 62% | 10% | 87.5% | 0.27 | 10.81 |
| 16, 0.6 | 74% | 21% | 83.3% | 0.35 | 11.85 |

Swapping even 5% of expert picks changes about 1 in 7 top predictions: Flint's 256 fine-grained
experts are not interchangeable. Perplexity on this small sample did not get worse (biasing toward
recently used experts may act as a topical prior), but the behavior shift is large, so steering
stays off by default until it is checked on real coding tasks.

Worker B's trace analysis (llama.cpp, 3 workloads x 1,299 decode steps, `traces/README.md`) adds
two things: prefetch adds total disk traffic (at a 20% cache, top-6 prefetch raises reads from
~130 to ~175 MB/token; top-12 to ~335 MB/token), so prefetch depth should shrink once compute stops
being the bottleneck. And a decayed-frequency (EMA 0.98) policy beats LRU by 3-8 points at 10-30%
cache, with ~20 points of headroom to the offline optimum.

B's answer-phase trace (Flint writing the code after reasoning) is harder than the reasoning
phase on the same task: LRU at 20% cache 0.47 vs 0.57, next-layer recall@6 0.70 vs 0.77, and a hot set
learned while reasoning covers only 18% of answer-phase picks. Expect a miss burst after `</think>`
and size the cache for the answer phase. B's disk on an identical VM measured 1.0-2.4 GB/s with
2-3x swings between runs, so plan for well under 3 GB/s. B also suggests repacking each expert's
three slices (gate, up, down) into one contiguous 4 KB-aligned 1.07 MB blob: one large read per
miss instead of three ~330-400 KB reads, which were the slowest read size measured.

## Where the time goes now (4 GB, prefetch 10, 9.8 tok/s = 102 ms/token)

| Part | ms/token | Bound by |
| --- | --- | --- |
| Expert gate/up (iq2_s + shared q6_K) | 25.5 | codebook decode compute (~9 Gweights/s per core) |
| Expert down (iq3_xxs + shared q6_K) | 15.1 | codebook decode compute |
| Attention projections (q6_K) | 31.2 | DRAM bandwidth + q6_K decode |
| Expert I/O incl. prefetch router | 14.0 | disk + 4 cores shared by compute and I/O |
| LM head | 6.9 | DRAM bandwidth |
| Other | ~9 | |

## Levers, and what the papers say

- **Cache-aware routing** (Prefetch-Steered Routing, arXiv 2610.34721): prefer resident experts
  when the router is nearly indifferent. Reported 2.2-2.3x faster than exact routing + LRU on
  OLMoE at 25-50% residency, with small accuracy changes. Implemented as `--steer depth,ratio`;
  priced with `build/eval`.
- **Next-layer prefetch** (Eliseev & Mazur 2023; Pre-gated MoE): run layer L+1's router on
  layer L's hidden state and start loading early. Implemented as `--prefetch N`.
- **Keep attention and embeddings resident, stream FFN weights** (LLM in a Flash): matches our split.
- **LUT / low-bit CPU kernels** (T-MAC): speed scales with bits once kernels are not decode-bound.
  Ours are still decode-bound on the codebook formats (iq2_s ~50, iq3_xxs ~44 Gweights/s).
- **Speculative decoding on MoE** (DraftExpert 2607.24434, EVICT 2605.00342, AcceptMoE 2608.02989,
  Utility-driven SD 2506.20675): verification pulls in the union of experts, so gains are modest
  (1.3-1.6x on end devices) unless drafting is made expert-aware.

## Feasibility of the v1 targets (100 tok/s, under 4 GB) for Flint on this box

| Constraint | Budget at 100 tok/s | Flint needs | Gap |
| --- | --- | --- | --- |
| DRAM bandwidth (43 GB/s) | 430 MB/token | 1,060 MB/token even with the always-active set requantized to ~4.5 bits | 2.5x |
| Disk (3 GB/s), under 4 GB | 30 MB/token of misses | 303 MB/token routed, >=29% miss even with optimal caching | ~3x |
| Expert compute (4 cores) | 10 ms/token total | ~18 ms/token for expert math alone at current kernel speed | 2x |

Each row alone rules out 100 tok/s for a 2.5B-active model on 4 cores and 43 GB/s. Realistic for
Flint here: ~20-30 tok/s with everything in RAM, ~15-20 tok/s under 4 GB after the remaining work.

What would reach 100 tok/s:
1. **More memory bandwidth.** An M4 Pro-class machine (~270 GB/s) has 6x the bandwidth; Recursive
   reports 125 tok/s there with a fused Metal kernel.
2. **A model with ~0.4-0.6B active parameters** at ~3-4 bits, which fits the 430 MB/token budget.
3. **Both bandwidth and RAM relaxed** on this box gets ~30 tok/s, not 100.

## Next steps

1. Faster expert decode: iq2_s codes are 3-level signed values, which fit a 4-bit code plus a
   16-entry shuffle table; that trades ~1.5x cache capacity for much cheaper decode.
2. Requantize the always-active set to ~4.5 bits (source: BF16 originals fetched by HTTP range
   requests, so the 80 GB checkpoint never touches disk), with a perplexity/KL gate.
3. Fuse more of the layer into single parallel regions; cut per-row kernel overhead.
4. Decide on the hardware or model question above before chasing 100 tok/s.
