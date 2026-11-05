# Paper notes for flintlock

Scope: what matters for batch-1 CPU decode of a fine-grained MoE (Flint: 256 routed experts, top-6,
47 MoE layers, ~1.07 MB per expert at iq2_s/iq3_xxs) with most experts on disk and < 4 GB RAM.

How to read these notes:
- Papers were read from the arXiv HTML full text (worker B, 2026-11-05). Numbers are quoted from the
  paper's text or tables. **[unverified]** marks numbers that came from a summary of a part of
  the page I could not read verbatim; check them before relying on them.
- **[ours]** marks our own arithmetic or measurements (traces: `traces/README.md`,
  `coord/log-b.md`). It is not the paper's claim.
- A's earlier notes (Eliseev & Mazur, LLM in a Flash, T-MAC, DraftExpert, Flint blog) are in A's
  log/brief and are not repeated here.

## What flintlock should take, in one place

1. **Use layer L+1's router on layer L's input to prefetch, without training a predictor.** Our
   traces give recall@6 ≈ 0.77-0.78 and recall@12 ≈ 0.92-0.93 for it [ours]. Every expert-offload
   system here that targets batch-1 decode uses this signal: MoE-CORE (eq. 16), PSR's
   "pre-gate ranking", FATE in SpecPrefetch's comparison (R@6 84.66 on 64 experts), and
   Pre-gated MoE (trained). MoE-CORE measured depth-1 prefetch TPOT at 36.0 ms vs 42.6 ms with no
   prefetch, and depth 2 gained almost nothing (35.9 ms).
2. **Replace plain LRU with a frequency-aware policy.** Belady's offline optimum beats LRU by ~21
   points at a 20% cache on our traces, and even a plain decayed-frequency score gains ~6 [ours]. MoE-CORE (DeepSeek-V4-Flash, 256 experts, top-6,
   our exact shape) loses ~30% TPOT and drops from >90% to 60-82% hit rate when its
   frequency/EMA policy (RHAC) is replaced. Also give layers unequal cache sizes, sized from
   measured hit-rate curves (MoE-CORE).
3. **Keep routing exact in v1.** Cache-steered routing (PSR, Cache-Prior, S2-MoE gating, AcceptMoE
   masking) buys up to ~2x latency but changes outputs. PSR's quality cost is small (-0.03 to -0.36
   points) but not zero. If we add it later, use PSR's "logical cache" trick so outputs do not
   depend on disk timing.
4. **Do not expect speculative decoding to be cheap on a 256-expert model.** The union of experts
   over k drafted tokens grows almost linearly: ~11/20/35 experts for 2/4/8 tokens vs 6 for one
   token [ours]. EcoSpec's gains were smallest on the 256-expert DeepSeek (union 31.4 -> 31.2
   [unverified]). AcceptMoE's offload measurements put standard SD at ~2.7x the expert bytes per
   output token of plain AR decoding [ours, from their Table 2]. If we do SD, gate it with a measured utility rule
   (Cascade, EVICT): verify only while (expected accepted tokens) / (measured verify cost) > 1.
   Use short drafts, and prefer drafts whose experts are already resident (AcceptMoE).
5. **For long context, Quest-style page selection on the 14 full-attention layers is the big
   lever.** At 32K context, those layers read ~0.94 GB per token; Quest at budget 2048 reads
   ~12.5% of it [ours, from the paper's formula]. KIVI-style 2-bit KV is orthogonal and cuts the
   rest ~5x. Both papers are untested with 4 KV heads, QK-norm, sinks and NoPE layers.
6. **Kernels: none of the papers read covers iq2_s/iq3_xxs on AVX-512/AMX.** bitnet.cpp and QTIP are
   ternary-only and GPU-only, respectively. llama.cpp on our Xeon already repacks every q6_K
   tensor into its AMX backend (1254 MiB buffer) and leaves iq2_s/iq3_xxs experts on the generic
   CPU path [ours]. That makes it the baseline to beat for the always-active set.

## 1. Expert caching and prefetch

### Prefetch-Steered Routing (PSR), arXiv 2610.34721
Siming Huang (HKUST Guangzhou), 26 Oct 2026. "Prefetch-Steered Routing: Deterministic Cache-Aware
Expert Selection for Offloaded Mixture-of-Experts Decoding."

Method:
- Adds a bonus λ·Δ̄ to the router logits of resident experts (Cache-Prior style), so routing
  prefers experts already in the cache.
- The bonus is computed from a deterministic *logical* cache, so outputs do not depend on PCIe
  timing. Physical copies only affect latency.
- At layer l-1 it applies layer l's router to the MoE input ("pre-gate ranking"). Of the top 8
  candidates, at most n = 1-2 non-resident experts are inserted per layer per token.
- Eviction uses EMAs of top-K membership (decays 0.5 and 0.98) plus a token prior, with at most 2
  copies in flight. Routing is not exact.

Key numbers (OLMoE-1B-7B: 64 experts, top-8, 12.6 MB bf16 experts, RTX 4090, batch 1,
teacher-forced ~9.8k tokens; Table 2):

| 50% of experts resident | ms/token | copies/token |
| --- | --- | --- |
| All resident | 6.8 | 0 |
| Exact routing, LRU | 24.7 | 30.5 |
| Exact routing, best cache + prefetch | 20.5 | 30.7 |
| PSR λ=0.3, n=1 | 10.7 | 13.8 |

- PSR is 2.31x faster than exact LRU. At 25% resident: LRU 42.5 ms vs PSR 16.9-19.2 ms.
- Quality, mean change over 8 tasks vs exact routing (Table 3): -0.03 points at 50%, -0.36 at 25%.
  Plain Cache-Prior at λ=0.3: -1.69.
- Moonlight-16B-A3B (64 experts, top-6, sigmoid router), 37.5% resident: LRU 43.6 ms vs PSR
  22.6 ms (KL 0.021). The candidate window had to shrink from 8 to 4 because 8 saturated the link.
- Qwen3.6-35B-A3B (256 experts): compute-bound, no PSR speed win [unverified].
- [ours] The demand copies imply OLMoE LRU hit rates of ~52% at 25% and ~76% at 50%, the same
  range as our 50-57% at 20% for Flint.

Take: the closest published design to ours. The pre-gate signal is the one we measured. Steering
routing is the larger win, but it costs quality, so it is a v2 option with a logical cache.

### MoE-CORE, arXiv 2610.01950
Ke Yang et al. (Huawei, UCAS, SJTU), 1 Oct 2026. "MoE-CORE: Coordinated Expert Offloading and
Residency for Memory-Constrained MoE Inference."

Method (decode):
- Per-layer cache sizes come from measured hit-rate curves (nonuniform).
- The cache is initialized from offline mean router scores for the domain.
- RHAC residency priority mixes recent frequency, EMA of selection, current router score and age.
- Cross-layer prefetch applies the next layer's router to the current hidden state, bounded by
  the compute/transfer overlap window.
- Optional AES substitutes a miss with a resident expert just below the top-k boundary
  (approximate).

Key numbers (DeepSeek-V4-Flash-W4A8: 256 experts, top-6; Ascend 950PR NPU, experts in host memory,
batch 1):
- TPOT: layer-on-demand 62-71 ms vs MoE-CORE 38-45 ms, 1.39-1.75x across 5 datasets (Table 1).
- Hit rate vs slots per layer (exact hits): 47.47% at 12 slots, 96.43% at 120 slots. 12->24 slots
  adds 21.01 points; 84->120 adds 5.13. [ours] That puts 84 slots (~33% of experts) at ~91%.
- Without RHAC: TPOT 36.0 -> 46.8 ms; hit rate falls to ~60-82%.
- Prefetch depth: none 42.6 ms (89.05% hits), depth 1 36.0 ms (92.43%), depth 2 35.9 (93.81%),
  depth 3 36.5.
- AES: +4.7% TPOT, effective availability 92.43% -> 99.972%.
- MTP (batch 2): acceptance 95.21% / 78.33% / 60.78% at depth 1/2/3.

Take: same expert shape as Flint, exact routing. Copy RHAC-style scoring, per-layer cache sizes
and depth-1 prefetch. Their hit rates are higher than our LRU at a similar fraction. The policy
matters more than the cache size.

### SpecPrefetch, arXiv 2607.24787
Jinwei Kong et al., v2 30 Jul 2026. "SpecPrefetch: Parameter-Efficient Expert Prefetching for Sparse
MoE Foundation Models."

Method:
- A low-rank adapter per layer pair maps layer l's router input to layer l+1's expert logits. It
  is KL-trained against the frozen router: 0.82M parameters for DeepSeek-VL2-Tiny.
- Each step it asynchronously loads the top M_max non-resident experts, with M_max set from the
  compute/transfer overlap window.
- The native router still decides, so outputs are exact.

Key numbers (DeepSeek-VL2-Tiny: 64 experts, top-6, 4-bit, 1.94 MB/expert):
- Recall@6 on GSM8K: SpecPrefetch 84.35, FATE (training-free cross-layer reuse) 84.66, ProMoE
  77.80, draft model 78.57 (Table 1). A single MLP instead of the low-rank adapter: 64.30.
- On device (Snapdragon 8 Elite, cold NVMe): 3.753 -> 4.055 tok/s (+8.12%, Table 4).
- Ready recall: naive prefetch 23.4% vs 91.7%.
- Exposed expert loading is 67% of per-layer latency on GPU and 52% on mobile with a cold cache.

Take: the only disk-backed (NVMe) result in this set. Training-free cross-layer prediction (FATE)
is as good as a trained adapter on 64 experts. Our 0.77 recall@6 on 256 experts is lower, but
chance is 2.3% vs 9.4%. A small trained adapter is a cheap upgrade if recall limits us.

### Pre-gated MoE, arXiv 2308.12066
Ranggi Hwang et al. (KAIST, USTC, Microsoft), ISCA 2024.

Method:
- A fine-tuned "pre-gate" in block N selects experts for block N+1, so their CPU->GPU copy overlaps
  block N's compute.
- Only the selected experts are copied. Switch Transformer, top-1.

Key numbers:
- A100 + CPU DRAM, batch 1: MoE-block latency 1.7x lower than on-demand loading, 42x lower than
  prefetching all experts. Throughput 1.5x vs on-demand, 81% of GPU-only. Peak GPU memory 23%.
- Accuracy is mixed: SQuAD EM 77.4 vs 78.2 for Base-8, but 82.4 vs 81.9 for Large-128.
- One block of lookahead is best; accuracy falls at 2-3.

Take: historical anchor for the cross-layer idea. Top-1 Switch models are far from our regime.

## 2. Speculative decoding on MoE: the expert-union problem

[ours] Flint baseline: expected union of k independent uniform top-6 picks is
256·(1-(250/256)^k) = 11.9 / 23.2 / 44.2 for k = 2 / 4 / 8. Measured on our traces it is ~11 / 20 /
35, so locality saves ~7-20%, not the ~k-fold that would make verification nearly free.

### AcceptMoE, arXiv 2608.02989
Shuang Liang et al. (Imperial College London, Tile-AI), 4 Aug 2026. "AcceptMoE:
Commitment-Weighted Self-Sizing Verifier Expert Sets for Efficient MoE Speculative Decoding."

Method:
- The verifier's eligible expert set is the root token's own top-k plus the top n_er experts by
  "commitment-weighted demand" u_e = Σ_t α_t r_{t,e} 1[e∈K_t]. Drafts likely to be accepted
  weigh more.
- n_er = ⌈exp(entropy)⌉ sizes the set per block.
- Router logits are masked to the set (approximate).
- Under offload, it prunes non-resident members first.

Key numbers (Qwen3-30B-A3B, Qwen3-Coder-30B-A3B, GPT-OSS-120B with EAGLE-3; batch 1):
- Set sizes are 23-34 experts per layer. Average accuracy 90.63 vs 90.90 for standard SD and 91.01
  for AR. Mean accepted length is the same (4.39).
- Full residency: 1.290x over standard SD.
- Offload (RTX 5090, H2D MiB per output token, Qwen-Inst / Coder / OSS): standard SD 2394 / 2025 /
  1243; AR 888 / 721 / 439; AcceptMoE 633 / 464 / 298. Cache hit rate rises from 73-74% to 84-88%,
  for 2.06x over standard SD.
- Fetch stalls fall from 65-78% to 27-35% of wall time.

Take: [ours] standard SD moved 2.7-2.8x the expert bytes per output token of AR under offload.
That is the core risk for us. Restricting verification to resident or high-demand experts recovers
it at ~0.3 points of accuracy.

### EVICT, arXiv 2605.00342
Lehan Pan et al. (USTC), v2 Sep 2026. "Making Every Verified Token Count: Adaptive Verification for
MoE Speculative Decoding."

Method:
- Training-free. Estimate expected accepted length from draft probabilities.
- Verify only the ancestor-closed top-k* draft nodes, where k* maximizes E[accepted] / C(k).
- C(k) is a per-k latency table profiled offline.

Key numbers (Qwen3-30B-A3B, A100, batch 1, Table 1, temperature 0):
- Throughput: vanilla 144.46 tok/s, EAGLE-3 176.34 (1.22x), EVICT 202.82 (1.40x).
- EVICT verifies 74.7% fewer tokens, activates 32.5% fewer experts, and has 26.6% lower
  verification latency. Accepted length drops 3.65 -> 3.09.
- Ling-flash-2.0 (256 experts, top-8): 1.22x [unverified].

Take: cheap and exact. Profile C(k) on our CPU and truncate drafts by expected value per unit
cost.

### S2-MoE, arXiv 2608.15018
Haochen Huang, Shengxuan Qiu, Meng Li (PKU), v2 Aug 2026. "S2-MoE: Enabling Efficient
Self-Speculative Decoding for Mixture-of-Experts on Edge Devices."

Method:
- Self-speculation with a routing-aware draft tree. A node is admitted only if
  p_i·T_AR / (ΔC_verify + C_draft) ≥ 1, where ΔC_verify counts only new experts.
- Reuse-aware gating biases token logits toward a shared expert set (approximate).
- Draft and target share one KV cache.

Key numbers:
- Speedup 1.3-5.3x on Jetson Orin and 1.2-2.9x on RTX 4090 over AR.
- Reuse ratio (unique experts / AR activations), DeepSeek (64 experts, top-6), HumanEval: 0.6017 -> 0.4453.
- Quality: KL 0.065, top-1 agreement 89.13%, perplexity ratio 1.013 (DeepSeek).

Take: edge + SSD offload setting like ours. The new-experts-only cost term is the right accounting
for any SD we build.

### EcoSpec, arXiv 2607.12696
Jincheng Xie et al., 14 Jul 2026. "Less Experts, Faster Decoding: Cost-Aware Speculative Decoding for
Mixture-of-Experts."

Method:
- A small expert predictor estimates each draft token's experts.
- Draft candidates are scored by P(accept) / (new experts not yet in the verify set).
- Verification is unchanged (exact).

Key numbers (8x H200, batch 1):
- Verified text: on DeepSeek-V3.1, cutting 0.2 experts per layer per step saves ~0.5 GB of expert
  traffic per step (44.04 MB per FP8 expert).
- [unverified, from a summary of the tables] Speedup over the drafter baseline: Qwen3-235B
  1.22x -> 1.36x; GPT-OSS-120B 1.14x -> 1.31x; DeepSeek-V3.1 (256 experts) 1.10x -> 1.15x.
- [unverified] Union per layer per verify step: DeepSeek 31.4 -> 31.2.
- [unverified] At batch 8 it is slower than AR.

Take: on a 256-expert model, choosing cheaper drafts barely shrinks the union. Do not count on it.

### Expert coactivation, arXiv 2609.22471
Kumari Nishu et al. (Apple), 18 Sep 2026. "Efficient Mixture-of-Experts with Speculative Decoding via
Expert Coactivation."

Method (training time):
- Global load-balancing loss and shared experts.
- A KL consistency loss between neighbouring tokens' router outputs.
- "Autoregressive" expert selection that keeps ≥ k-l of the previous token's experts, so γ+1
  tokens use ≤ k+γl experts.

Key numbers:
- Verifying 4 tokens needs 9 unique experts for a standard MoE vs 5 for the coactivation-trained
  one (Fig. 1).
- 21% higher SD throughput than the standard MoE at on-par accuracy (~1B scale, 16 experts,
  top-4, NPU).

Take: the only approach that shrinks the union itself, but it needs router retraining. Not for v1.

### Cascade (utility-driven SD for MoE), arXiv 2506.20675
Anish Saxena, Po-An Tsai, Hritvik Taneja, Aamer Jaleel, Moinuddin Qureshi (Georgia Tech, NVIDIA),
MICRO 2025.

Method:
- Speculation utility = (gain in effective token rate) / (iteration-time overhead), measured at
  runtime.
- Disable SD below 1; otherwise test-and-set the draft length K with hill-climbing and back-off.

Key numbers (RTX 6000 Ada, batch 1):
- Mixtral K=7 verification costs ~3x on math, ~2.3x on code.
- Static K=3: +39% on code but a 54% slowdown on math.
- Cascade limits the worst slowdown to 5% (vs 26/38/54% for static K=1/2/3) and gains 7-14% in
  throughput over static K (abstract).

Take: any SD in flintlock needs this kind of runtime gate. On a memory-bound CPU, a wrong K is a
straight loss.

## 3. KV traffic at long context

[ours] Flint full-attention layers: 14 x 4 KV heads x 128 x 2 (K, V) x 2 B = 28,672 B per context
token per decoded token. That is 0.94 GB at 32K, ~22 ms at 43 GB/s. Sliding layers add a constant
35 x 513 x 2048 B = 36.8 MB.

### Quest, arXiv 2406.10774
Jiaming Tang, Yilong Zhao, Kan Zhu, Guangxuan Xiao, Baris Kasikci, Song Han; v2 Aug 2024.

Method:
- KV in pages (16 tokens in the paper's examples). Each page stores channel-wise min and max of K.
- Page score = Σ_i max(q_i·m_i, q_i·M_i), an upper bound on q·k in the page.
- Each step attends only to the top pages within a token budget. The first two layers stay dense.

Key numbers:
- Passkey, LongChat-7B at 10K: 99% at budget 64. Yarn-Llama-2-7B at 100K: 100% at budget 2048.
- LongBench: budget ~11K matches the full cache.
- At 32K with budget 2048: self-attention 7.03x faster than FlashInfer; end-to-end decode 1.74x
  (FP16 weights) / 2.23x (4-bit weights).
- Fraction of KV read = 1/S + K·S/L. Top-k overhead 5-10 µs below 128K.

Take: [ours] with S = 16 and budget 2048 at 32K, the full-attention layers read 12.5% of the KV
(~117 MB, ~2.7 ms). It needs no training. The min/max bound uses only q·k, so it fits the NoPE
full-attention layers. Untested: 4 KV heads (choose pages per KV head, shared by its 8 query
heads), QK-norm, attention sinks.

### KIVI, arXiv 2402.02750
Zirui Liu et al.; v2 Jul 2024.

Method:
- 2-bit asymmetric KV quantization: K per-channel, V per-token.
- Groups of 32. The newest R = 128 tokens stay full precision.

Key numbers:
- Llama-2-13B CoQA / TruthfulQA: 16-bit 66.37 / 29.53; KIVI-2 (K per-channel) 63.53 / 28.60; K
  per-token instead 52.93 / 24.98 (Table 1).
- LongBench averages, 16-bit / KIVI-4 / KIVI-2: Llama-2-7B 44.52 / 44.59 / 44.27. Mistral-7B 32K
  (GQA, 8 KV heads) 43.54 / 43.53 / 42.43.
- Falcon-7B (1 KV head) needs 4-bit. Group size 128 hurts (GSM8K 17.29 vs 20.77).
- 2.6x less peak memory, 2.35-3.47x throughput (A100).

Take: [ours] ~0.19 of fp16 bytes with fp16 scales, so ~180 MB at 32K. It composes with Quest.
Flint's 4 KV heads sit between the tested GQA-8 and MQA cases, so start with 4-bit K.

## 4. Low-bit CPU kernels

### bitnet.cpp, arXiv 2410.16144 and 2502.11880
Jinheng Wang et al. (Microsoft), Oct 2024 and Feb 2025.

Method:
- Ternary-only kernels. I2_S is 2-bit multiply-add. TL1 and TL2 are lookup-table kernels with 2 or
  3 weights per index (2 / 1.67 bits per weight).
- Signs are applied with XOR+ADD. Tiles bm = 16/32. AVX2 and NEON only.

Key numbers:
- i7-13700H (AVX2, < 100 GB/s), 7B, tok/s (2502.11880 Table 7): fp16 3.30, Q4_0 9.09, T-MAC
  12.29, TQ2_0 19.92, TL2_0 20.72, I2_S 20.62. 100B: TL2_0 1.69.
- On an i5-13400F, throughput peaks at 4 threads "due to the saturation of the bandwidth."
- Output quality: the bitnet.cpp kernels matched fp32 output exactly on 1,000 prompts (700M model,
  2410.16144 Table 7), vs 1.4% exact match for llama.cpp's TQ1_0/TQ2_0. TL*_1 and I2_S are
  lossless; TL*_0 requantize to int8.

Take: confirms a 4-thread client CPU is bandwidth-bound for decode, the same regime as our
43 GB/s. The LUT-vs-MAD trade-off (TBL path ~68% slower than one MAD [unverified]) suggests MAD
kernels with AVX-512 VNNI for iq2/iq3. These formats are not ternary, so the code does not apply
directly.

### QTIP, arXiv 2406.11235
Albert Tseng, Qingyao Sun, David Hou, Christopher De Sa (Cornell); v4 Jun 2025.

Method:
- Random Hadamard transform, then a bitshift trellis (L = 16, k = 2, V = 1).
- Computed codebooks (1MAD, 3INST) decode in ≤ 4 (often ~2) instructions per weight. The HYB
  codebook is a 2 KiB LUT and can be fine-tuned.

Key numbers:
- Llama-2-7B 2-bit perplexity without fine-tuning: 6.82 (3INST) vs QuIP# 8.22 (fp16 5.12).
  Fine-tuned 2-bit: 5.86 vs AQLM 6.14. Llama-2-70B 2-bit: 3.70.
- Batch-1 on an RTX 6000 Ada (960 GB/s): 7B at 188 / 161 / 140 tok/s for 2 / 3 / 4 bit, >80% of
  peak bandwidth.
- GPU only; no CPU numbers.

Take: the quality ceiling for 2-bit weights is much better than iq2-class formats on paper. A v2
option for re-quantizing the always-active set if AVX-512 decode of a trellis code is cheap enough.
Unproven on CPU.

### AMX for low-bit decode
From a web search (2026-11-05) and the abstracts and secondary write-ups it found, **not full-text
reads**; treat as leads:
- **KTransformers** (SOSP '25, Tsinghua MADSys;
  [paper](https://madsys.cs.tsinghua.edu.cn/publication/ktransformers-unleashing-the-full-potential-of-cpu/gpu-hybrid-inference-for-moe-models/SOSP25-chen.pdf)).
  CPU/GPU hybrid MoE with experts on the CPU. Uses an AMX kernel for high-arithmetic-intensity work
  (prefill) and a lightweight AVX-512 kernel for low-intensity work (decode), because AMX is
  inefficient there. 4.62-19.74x prefill speedup. An LMSYS post describes an AMX-INT4 path.
- **SGLang on Xeon 6** ([LMSYS blog, 2025-07-14](https://www.lmsys.org/blog/2025-07-14-intel-xeon-optimization/)).
  AMX and AVX-512 MoE kernels in BF16 / INT8 / FP8, chosen by input shape. Reports 85% of memory
  bandwidth for the MoE kernels.
- **CoX-MoE** ([arXiv 2605.17889](https://arxiv.org/pdf/2605.17889)). AMX CPU-GPU co-execution;
  quotes ~144 TFLOPs AMX vs ~18 TFLOPs AVX-512 BF16 per Sapphire Rapids socket.
- **Ultra-low-bit x86 kernels** ([arXiv 2508.06753](https://arxiv.org/pdf/2508.06753)). 2-bit GEMM
  kernels near roofline on several x86 CPUs, up to 2.2x over bitnet.cpp end to end. AMX use not
  confirmed.
- No result found for a 2-4-bit weight-only MoE *decode* kernel on AMX. AMX takes INT8 / BF16
  tiles, so low-bit weights must be unpacked to int8 first.

[ours] On our Xeon, the llama.cpp fork repacks all q6_K tensors (attention, shared expert, dense
FFN) into its AMX buffer type (`AMX model buffer size = 1254.46 MiB`). iq2_s / iq3_xxs and the LM
head / embeddings stay on the plain CPU path. Consistent with KTransformers: at batch 1, use
AVX-512 (VNNI) GEMV kernels and save AMX for prefill and multi-token verification, where several
tokens share each weight read.

## 5. Architectures worth knowing for v2 (short)

- **Gated DeltaNet** (Yang, Kautz, Hatamizadeh; arXiv 2412.06464).
  - Linear attention with a gated delta rule, S_t = S_{t-1}(α_t(I - β_t k_t k_tᵀ)) + β_t v_t k_tᵀ.
  - The state is fixed at d_v x d_k per head, ~32 KB in bf16 at 128x128 [ours], so decode cost
    does not grow with context.
  - S-NIAH-1 at 8K (1.3B): 91.8 vs Mamba2 30.4 vs DeltaNet 98.8.
  - Hybrids with sliding-window attention score best [unverified: avg 56.40 vs 55.32].
  - Relevance: if a future Flint-like model swaps the 14 NoPE full-attention layers for this, KV
    traffic at 32K drops from ~0.94 GB to a constant.
- **DeepSeek Sparse Attention** (DeepSeek-V3.2-Exp tech report, 2025).
  - A "lightning indexer" scores each past token with I_{t,s} = Σ_j w_{t,j}·ReLU(q_{t,j}·k_s), using
    a few FP8 heads. The model then attends only to the top 2048 tokens.
  - Core attention goes from O(L²) to O(Lk). The indexer is still O(L²) but cheap.
  - Benchmarks match V3.1-Terminus, e.g. MMLU-Pro 85.0 vs 85.0, SWE-Verified 67.8 vs 68.4.
  - Relevance: a learned, trained-in version of Quest. Same CPU benefit, but the model must be
    trained with it.
- **Multi-token prediction** (DeepSeek-V3, arXiv 2412.19437).
  - One extra MTP module predicts token t+2. Used as a drafter, the second token is accepted
    85-90% of the time, for 1.8x TPS.
  - MoE-CORE reports MTP acceptance 95.21% / 78.33% / 60.78% at depth 1/2/3 on DeepSeek-V4-Flash.
  - Relevance: Flint ships no MTP head. A trained 1-layer drafter sharing Flint's embeddings is
    the analogue, with the expert-union caveat from section 2.
- **Gemma 3n per-layer embeddings** (HF blog, 26 Jun 2025).
  - Per-layer embedding tables live in CPU memory and are looked up by token id, so the
    accelerator holds less. E2B: 5B real parameters, 2B "in VRAM", 2 GB. E4B: 8B and 4B, 3 GB.
  - Relevance: same principle as keeping only the touched rows of Flint's 252 MB embedding table
    resident. For decode, only one 2048-wide row per token is needed.
