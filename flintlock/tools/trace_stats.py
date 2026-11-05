"""Expert-routing statistics from a `run --trace` file.

The trace is uint8 [tokens, moe_layers, top_k]. This answers the questions that size the
expert cache: hit rate per cache size and policy, how many distinct experts a window of
consecutive tokens touches (cost of speculative verification), and how skewed usage is.

  python3 -I tools/trace_stats.py TRACE.bin [--layers 47] [--topk 6] [--skip N] [--expert-mb 1.07]
"""
import argparse
from collections import Counter, OrderedDict

ap = argparse.ArgumentParser()
ap.add_argument("trace")
ap.add_argument("--layers", type=int, default=47)
ap.add_argument("--topk", type=int, default=6)
ap.add_argument("--experts", type=int, default=256)
ap.add_argument("--skip", type=int, default=0, help="ignore the first N tokens (e.g. the prompt)")
ap.add_argument("--expert-mb", type=float, default=1.07, help="bytes of one expert (gate+up+down)")
a = ap.parse_args()

raw = open(a.trace, "rb").read()
step = a.layers * a.topk
T = len(raw) // step
toks = [[tuple(raw[t * step + l * a.topk: t * step + (l + 1) * a.topk]) for l in range(a.layers)] for t in range(T)]
toks = toks[a.skip:]
T = len(toks)
print(f"{T} tokens x {a.layers} layers x top-{a.topk}  ({a.experts} experts/layer)")


def lru(cap):
    hits = total = 0
    for l in range(a.layers):
        c = OrderedDict()
        for t in range(T):
            for e in toks[t][l]:
                total += 1
                if e in c:
                    hits += 1
                    c.move_to_end(e)
                else:
                    c[e] = 1
                    if len(c) > cap:
                        c.popitem(last=False)
    return hits / total


def lfu(cap):
    """Keep the cap experts with the highest running use count (ties: most recent)."""
    hits = total = 0
    for l in range(a.layers):
        cnt = Counter()
        res = set()
        for t in range(T):
            for e in toks[t][l]:
                total += 1
                hits += e in res
                cnt[e] += 1
                if e not in res:
                    res.add(e)
                    if len(res) > cap:
                        res.remove(min(res, key=lambda x: cnt[x]))
    return hits / total


def belady(cap):
    """Optimal offline policy: evict the expert whose next use is furthest away."""
    hits = total = 0
    for l in range(a.layers):
        seq = [e for t in range(T) for e in toks[t][l]]
        nxt = [0] * len(seq)
        last = {}
        for i in range(len(seq) - 1, -1, -1):
            nxt[i] = last.get(seq[i], 1 << 30)
            last[seq[i]] = i
        res = {}
        for i, e in enumerate(seq):
            total += 1
            if e in res:
                hits += 1
            elif len(res) >= cap:
                del res[max(res, key=lambda x: res[x])]
            res[e] = nxt[i]
    return hits / total


print("\n== cache hit rate (per-layer caches, fraction of all 256 experts kept per layer)")
print(f"  {'kept':>6} {'experts':>8} {'GB':>6}   {'LRU':>6} {'LFU':>6} {'optimal':>8}")
for frac in (0.10, 0.17, 0.20, 0.30, 0.50):
    cap = max(1, round(frac * a.experts))
    gb = cap * a.layers * a.expert_mb / 1024
    print(f"  {frac:6.0%} {cap * a.layers:8d} {gb:6.2f}   {lru(cap):6.1%} {lfu(cap):6.1%} {belady(cap):8.1%}")

print("\n== distinct experts per layer across a window of consecutive tokens (verification cost)")
for w in (1, 2, 4, 8):
    s = n = 0
    for l in range(a.layers):
        for t in range(0, T - w + 1, w):
            s += len({e for k in range(w) for e in toks[t + k][l]})
            n += 1
    u = s / n
    print(f"  window {w}: {u:5.1f} distinct (x{u / a.topk:.2f} of one token, {u / (w * a.topk):.0%} of no-overlap worst case)")

print("\n== reuse and skew")
same = sum(len(set(toks[t][l]) & set(toks[t - 1][l])) for t in range(1, T) for l in range(a.layers))
print(f"  experts shared with the previous token: {same / ((T - 1) * a.layers):.2f} of {a.topk}")
cover = []
for l in range(a.layers):
    c = Counter(e for t in range(T) for e in toks[t][l])
    top = sum(v for _, v in c.most_common(round(0.1 * a.experts)))
    cover.append(top / (T * a.topk))
    used = len(c)
print(f"  selections covered by each layer's top 10% experts: {sum(cover) / len(cover):.1%}"
      f" (min {min(cover):.1%}, max {max(cover):.1%})")
used = sum(len({e for t in range(T) for e in toks[t][l]}) for l in range(a.layers)) / a.layers
print(f"  experts touched at least once per layer: {used:.0f} of {a.experts}")
