# Brief for worker B

You are joining a project already in progress. Worker A (another Claude, on a different
account) is writing a from-scratch C/C++ inference engine called flintlock. You do the research
and collect the data A needs. Read `coord/README.md` first for how we talk through this repo.

## The project

- Model: Recursive Flint (Hugging Face `RecursiveSI/flint`, released 2026-10-21). It is a
  decoder-only MoE: 39.8B total, ~2.5B active per token, 49 layers, hidden size 2048,
  256 routed experts (top-6, sigmoid router, normalized top-k) plus a shared expert
  (intermediate 1024), expert intermediate 512, first 2 layers dense (intermediate 6144).
  Attention: 32 query heads / 4 KV heads, head dim 128, per-head QK RMSNorm, learned
  per-head attention sinks, 35 sliding-window layers (window 513, with RoPE) and 14 full
  attention layers (no positional encoding). Vocab 150,144.
- Weights in use: `unsloth/flint-GGUF`, file `flint-UD-IQ3_XXS.gguf` (14.54 GB,
  sha256 `7a0a095dde1d931063a5d571e19497d997edbc783eb1ed6b86529bfab9d94804`).
  Attention, shared expert, LM head and dense FFN are q6_K. Expert gate/up are iq2_s, and
  expert down is iq3_xxs. The router is bf16.
- v1 targets: under 4 GB RAM, minimal memory traffic per token, 100+ tok/s.

## What A measured on its machine (4 vCPU Xeon with AVX-512 + AMX, 15 GB RAM, no GPU)

- DRAM read with 4 threads: ~43 GB/s. L3-resident (128 MB set): ~90 GB/s. Disk (O_DIRECT,
  random 1 MB reads): ~2.4-3.6 GB/s.
- Per decoded token Flint streams 1.67 GB. 1.37 GB is always active (attention projections
  0.76 GB, LM head 0.25 GB, shared expert 0.24 GB, router 0.05 GB, dense FFN 0.06 GB). The 6
  routed experts are 0.30 GB.
- So the ceiling is ~26 tok/s fully in RAM, and ~8-21 tok/s with experts on disk under 4 GB
  depending on expert-cache hit rate. 100 tok/s needs fewer bytes per token (requantize the
  always-active set) and more tokens per weight read (speculative decoding), plus a
  high-hit-rate expert cache.

Reproduce: `flintlock/README.md` has build commands for `membw`, `diskbw`, `inspect`.
Run them on your machine too and log your numbers. If they differ a lot, that is useful.

## Task 1: paper notes -> `flintlock/docs/papers.md`

Read full texts (use the `arxiv.org/html/<id>` version) and pull out the numbers that matter
for batch-1 CPU decode of a fine-grained MoE under 4 GB. For each paper: the method in 3-5
lines, the key numbers, and "what flintlock should take from it". A already has notes on these
(no need to redo them, but feel free to correct them):

- Eliseev & Mazur 2023 (2312.17238): LRU expert cache + speculative loading from the next layer's
  gate. Attention 4-bit, experts 2-3 bit. Mixtral 2-4 tok/s on consumer GPUs.
- LLM in a Flash (2312.11514): attention and embeddings stay resident, bundled 32 KiB+ reads,
  flash 1.25 -> 2.25 GB/s with row-column bundling.
- T-MAC (2407.00088): LUT-based low-bit GEMV, speed scales with bit-width. 2-bit Llama-2-7B
  31.8 tok/s vs llama.cpp 9.4 on Surface Laptop 7.
- DraftExpert (2607.24434): drafts with shared + top-1 + a trained draft expert. ~85%
  acceptance, verify cost 1.25-1.35x of one AR step with prefetch, 1.45x average speedup.
- Flint launch blog: 4-bit LM head, NVFP4 within 0.7 points of 16-bit, Metal megakernel,
  125+ tok/s on M4 Pro.

Still to read, highest priority first:

1. Prefetch-Steered Routing (2610.34721): cache-aware expert selection for batch-1 offload.
2. AcceptMoE (2608.02989), EVICT (2605.00342), S2-MoE (2608.15018), EcoSpec (2607.12696),
   expert coactivation (2609.22471), Utility-driven SD for MoE (2506.20675): controlling expert
   union during speculative verification.
3. SpecPrefetch (2607.24787), Pre-gated MoE (2308.12066), MoE-CORE (2610.01950): expert prefetch.
4. KV traffic at long context: Quest (2406.10774), KIVI (2402.02750). Flint's 14 full-attention
   layers read ~29 KB of fp16 KV per token of context per decoded token (~0.94 GB at 32K
   context), so this matters for coding-agent context lengths.
5. Low-bit CPU kernels: bitnet.cpp (2410.16144, 2502.11880), QTIP (2406.11235), and any 2026
   work on AMX for low-bit GEMV.
6. Newer efficient architectures worth knowing for v2 (Gated DeltaNet, DeepSeek sparse
   attention, multi-token prediction heads, Gemma per-layer embeddings): short notes only.

## Task 2: routing traces -> `flintlock/traces/` (A needs this the most)

Flint support exists in Unsloth's llama.cpp fork: `git clone --depth 1 --branch iq1-narrow
https://github.com/unslothai/llama.cpp`. Build it CPU-only. Download the GGUF above and check its sha256.

Run greedy decoding on a few workloads (each at least 1000 generated tokens): a code-editing
task with a file in the prompt, a write-new-code task, and a plain chat/explanation. Capture
the selected expert ids per token per MoE layer (llama.cpp names the top-k tensor
`ffn_moe_topk-<layer>` in its graph callback; see `examples/eval-callback`). Save as compact
arrays: `[tokens, 47 layers, 6]` uint8.

From the traces, report in `coord/log-b.md`:

- LRU hit rate per layer and overall, for a cache of 10%, 20%, 30% and 50% of experts.
  A's RAM budget leaves room for roughly 20% of experts.
- How well layer L+1's router, applied to layer L's router input, predicts layer L+1's experts
  (recall@6, recall@12). This decides whether prefetch can hide disk latency.
- Size of the expert union across windows of 2, 4 and 8 consecutive tokens per layer. This
  decides how expensive speculative verification is.
- Whether a few experts are "hot" (the share of selections covered by the top 10% of experts).

## Task 3: reference outputs -> `flintlock/testdata/`

A needs ground truth to check its engine. Using the llama.cpp build:

- Tokenization of ~20 varied strings (code, unicode, whitespace runs, chat template), as token ids.
- For 3 fixed prompts: greedy output token ids (first 64 tokens), and the top-10 logits at the
  first 4 decode steps.
- Record the exact llama.cpp commit and command lines in `testdata/README.md`.

## Working style

Log early and often in `coord/log-b.md` so A can pick up partial results. If a step is blocked
(for example, building or running outside code needs approval), say so in the log and move on to
the next task.
