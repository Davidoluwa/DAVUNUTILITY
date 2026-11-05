# flintlock

A from-scratch C/C++ inference engine for small-active MoE models, starting with
[Recursive Flint](https://huggingface.co/RecursiveSI/flint) (40B total, ~2.5B active).

v1 targets: under 4 GB RAM, as little memory traffic per token as possible, 100+ tok/s.

## Build

```bash
mkdir -p build
gcc -O3 -march=native -pthread bench/membw.c -o build/membw
gcc -O2 -pthread bench/diskbw.c -o build/diskbw
g++ -O2 -std=c++17 tools/inspect.cpp src/gguf.cpp -o build/inspect
```

## Tools

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
