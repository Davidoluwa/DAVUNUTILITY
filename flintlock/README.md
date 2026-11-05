# flintlock

A from-scratch C/C++ inference engine for small-active MoE models, starting with
[Recursive Flint](https://huggingface.co/RecursiveSI/flint) (40B total, ~2.5B active).

v1 targets: under 4 GB RAM, as little memory traffic per token as possible, 100+ tok/s.

## Status

Flint runs end to end and produces correct output. On the 4 vCPU box: **9.8 tok/s decode in
3.7 GB of RAM** (`--ram-gb 4 --prefetch 10`), with output identical to running fully in memory.
See `docs/DESIGN.md` for measurements and the feasibility analysis of the v1 targets.

- Kernels for q6_K, iq2_s, iq3_xxs and bf16 match a scalar reference to 1e-8.
- Tokenizer matches the original Hugging Face tokenizer on 95k tokens of code, JSON, Markdown,
  CJK and emoji. llama.cpp does not split camelCase the way the original does; we do.

## Build and run

```bash
make
./build/run -m flint-UD-IQ3_XXS.gguf --chat -p "Write a prime check in Python" -n 200
```

Flags: `-n` tokens, `--temp` (0 = greedy), `--top-k`, `--top-p`, `-t` threads, `--ctx`,
`--trace FILE` (routed expert ids per token, uint8 `[47 layers x 6]` per token),
`--ram-gb N` (total memory budget; enables the expert cache), `--prefetch N` (experts to prefetch
for the next layer), `--steer depth,ratio` (cache-aware routing; changes outputs).

Low-memory run: `./build/run -m MODEL --chat -p "..." --ram-gb 4 --prefetch 10`

## Tools

- `build/run`: generation, with a per-token time breakdown.
- `build/eval -m MODEL --text FILE [--save ref.bin | --ref ref.bin]`: perplexity, and top-1/KL
  agreement with a saved reference run. Prices any approximation.
- `build/test_quants MODEL`: kernel correctness against the scalar reference, and throughput.
- `build/bench_moe MODEL [threads]`: the MoE gate/up step in isolation.
- `tools/trace_stats.py TRACE`: expert cache hit rates and reuse from `run --trace`.
- `build/tokenize MODEL STRINGS.txt`: token ids per line. Compare with `tools/hf_tokenize.py`.
- `build/membw`: read bandwidth by working-set size and thread count (the decode roofline).
- `build/diskbw FILE`: direct (uncached) disk reads at several chunk sizes and queue depths.
- `build/inspect MODEL.gguf [dram_GBps] [disk_GBps]`: GGUF metadata, tensor types, and the
  bytes each decoded token must stream, with bandwidth-only speed ceilings.

## First measurements (4 vCPU Xeon, AVX-512 + AMX, 15 GB RAM, no GPU)

| What | Measured |
| --- | --- |
| DRAM read, 4 threads, 2 GB set | ~43 GB/s |
| L3-resident read, 4 threads, 128 MB set | ~90 GB/s |
| Disk, random 1 MB reads (O_DIRECT) | ~2.4-3.6 GB/s |

Flint `UD-IQ3_XXS` (14.5 GB) streams 1.67 GB per token: 1.37 GB is always active
(attention, shared expert, router, LM head, all q6_K) and 0.30 GB is the 6 routed experts.
That caps decode at ~26 tok/s fully in RAM and ~8-21 tok/s with experts read from disk,
so 100 tok/s needs fewer bytes per token and more tokens per weight read.
