#!/usr/bin/env python3
"""Routing-trace analysis for flintlock (Task 2).

Usage:
  python analyze.py TRACE_DIR [--hidden-dir DIR --model MODEL.gguf] [--json OUT.json]

TRACE_DIR holds <workload>.npz files written by pack.py (topk uint8 [n_pos, 47, 6], phase uint8,
tokens int32). Prefetch-prediction metrics need the decode-step residual streams that
flint_trace --hidden writes (not committed: ~430 KB per token) plus the router weights from the GGUF.

All metrics use decode steps only (phase == 1). Caches are warmed with the prompt's routing first,
in position order, as a real engine would after prefill.
"""
import argparse
import glob
import heapq
import json
import os
import sys
from collections import OrderedDict

import numpy as np

N_MOE, N_USED, N_EXP, N_EMBD = 47, 6, 256, 2048
EXPERT_BYTES = 335872 + 335872 + 401408  # gate (iq2_s) + up (iq2_s) + down (iq3_xxs), one expert, one layer
CACHE_FRACS = [0.10, 0.20, 0.30, 0.50]


def lru_layer(seq_warm, seq_eval, cap):
    """Per-layer LRU. seq_* are [T, 6] arrays of expert ids. Returns (hits, lookups) over seq_eval."""
    c = OrderedDict()

    def touch(row, count):
        h = 0
        for e in row:
            e = int(e)
            if e in c:
                c.move_to_end(e)
                h += 1
            else:
                c[e] = None
                if len(c) > cap:
                    c.popitem(last=False)
        return h

    for row in seq_warm:
        touch(row, False)
    hits = 0
    for row in seq_eval:
        hits += touch(row, True)
    return hits, seq_eval.size


def ema_layer(seq_warm, seq_eval, cap, decay):
    """Per-layer cache that evicts the resident expert with the lowest decayed selection count
    (score = sum over past tokens of decay^age * [selected]), never one the current token needs.
    Same interface as lru_layer. A cheap stand-in for frequency-aware policies (LFU with aging, RHAC)."""
    score = np.zeros(N_EXP)
    cached = np.zeros(N_EXP, bool)
    hits = 0
    t0 = seq_warm.shape[0]
    for t, row in enumerate(np.concatenate([seq_warm, seq_eval], 0)):
        score *= decay
        score[row] += 1.0
        need = np.zeros(N_EXP, bool)
        need[row] = True
        for e in row:
            if cached[e]:
                if t >= t0:
                    hits += 1
                continue
            if cached.sum() >= cap:
                cand = np.where(cached & ~need, score, np.inf)
                cached[int(np.argmin(cand))] = False
            cached[e] = True
    return hits, seq_eval.size


def lru_prefetch_layer(seq_warm, seq_eval, pred, cap):
    """Per-layer LRU where, before each decode step, the predicted experts `pred[t]` (from the
    previous layer's state) are loaded into the cache if absent (inserted as most recent).
    Returns (demand hits, demand misses = stalls, prefetch loads) over seq_eval."""
    c = OrderedDict()

    def insert(e):
        c[e] = None
        if len(c) > cap:
            c.popitem(last=False)

    for row in seq_warm:
        for e in row:
            e = int(e)
            if e in c:
                c.move_to_end(e)
            else:
                insert(e)
    hits = stalls = pre = 0
    for t, row in enumerate(seq_eval):
        if pred is not None:
            for e in pred[t]:
                e = int(e)
                if e not in c:
                    insert(e)
                    pre += 1
        for e in row:
            e = int(e)
            if e in c:
                c.move_to_end(e)
                hits += 1
            else:
                insert(e)
                stalls += 1
    return hits, stalls, pre


def lru_global(warm, ev, cap):
    """One LRU pool shared by all layers, accessed in layer order within each token.
    warm/ev are [T, 47, 6]. Returns per-layer hits and total lookups per layer."""
    c = OrderedDict()
    hits = np.zeros(N_MOE, np.int64)
    for phase_arr, count in ((warm, False), (ev, True)):
        for t in range(phase_arr.shape[0]):
            for l in range(N_MOE):
                for e in phase_arr[t, l]:
                    k = l * N_EXP + int(e)
                    if k in c:
                        c.move_to_end(k)
                        if count:
                            hits[l] += 1
                    else:
                        c[k] = None
                        if len(c) > cap:
                            c.popitem(last=False)
    return hits, ev.shape[0] * N_USED


def belady_layer(seq_warm, seq_eval, cap):
    """Belady/MIN per layer (offline optimum; upper bound for any policy). Same interface as lru_layer."""
    seq = np.concatenate([seq_warm, seq_eval], 0)
    T = seq.shape[0]
    t0 = seq_warm.shape[0]
    INF = 1 << 30
    # next use time of each (t, e) after token t
    nxt = np.full((T, N_USED), INF, np.int64)
    last = {}
    for t in range(T - 1, -1, -1):
        for j, e in enumerate(seq[t]):
            nxt[t, j] = last.get(int(e), INF)
        for e in seq[t]:
            last[int(e)] = t
    # Experts of the current token not yet accessed carry next-use == t (the minimum), so the
    # max-heap never evicts them while cap >= 6. Stale heap entries are skipped lazily.
    cache = {}  # e -> next use
    heap = []   # (-next_use, e)
    hits = 0
    for t in range(T):
        for j, e in enumerate(seq[t]):
            e = int(e)
            if e in cache:
                if t >= t0:
                    hits += 1
            elif len(cache) >= cap:
                while True:
                    nu, v = heapq.heappop(heap)
                    if cache.get(v) == -nu:
                        del cache[v]
                        break
            cache[e] = int(nxt[t, j])
            heapq.heappush(heap, (-cache[e], e))
    return hits, seq_eval.size


def union_sizes(ev, w):
    """Mean / p50 / p90 / max size of the expert union over windows of w consecutive decode steps, per layer."""
    T = ev.shape[0]
    out = np.zeros((N_MOE, T - w + 1), np.int32)
    for l in range(N_MOE):
        for s in range(T - w + 1):
            out[l, s] = len(set(ev[s:s + w, l].ravel().tolist()))
    return out


def hotness(ev, frac=0.10):
    """Share of selections covered by the most-selected frac of experts, per layer."""
    k = int(round(frac * N_EXP))
    shares = []
    for l in range(N_MOE):
        cnt = np.bincount(ev[:, l].ravel(), minlength=N_EXP)
        shares.append(np.sort(cnt)[::-1][:k].sum() / cnt.sum())
    return np.array(shares)


def bf16_to_f32(a):
    return (a.astype(np.uint32) << 16).view(np.float32)


def rmsnorm(x, w, eps):
    return x / np.sqrt((x * x).mean(-1, keepdims=True) + eps) * w


def load_router(model):
    import gguf
    r = gguf.GGUFReader(model)
    t = {x.name: x for x in r.tensors}
    eps = float(r.fields['flint.attention.layer_norm_rms_epsilon'].contents())
    W = np.zeros((N_MOE, N_EXP, N_EMBD), np.float32)
    nw = np.zeros((N_MOE, N_EMBD), np.float32)
    for li in range(N_MOE):
        W[li] = bf16_to_f32(np.array(t[f'blk.{li + 2}.ffn_gate_inp.weight'].data).view(np.uint16)).reshape(N_EXP, N_EMBD)
        nw[li] = np.array(t[f'blk.{li + 2}.ffn_norm.weight'].data, dtype=np.float32)
    return W, nw, eps


def recall_at(pred_logits, actual, k):
    """pred_logits [T, 256], actual [T, 6] -> mean |topk(pred) ∩ actual| / 6."""
    top = np.argpartition(-pred_logits, k - 1, axis=-1)[:, :k]
    hit = (top[:, :, None] == actual[:, None, :]).any(1).sum(1)
    return float(hit.mean() / N_USED)


def prefetch_metrics(hd, W, nw, eps, actual):
    """hd: dict with ffn_inp, l_out [T, 47, 2048] (bf16 as uint16). actual: [T, 47, 6] decode-step routing.
    Predict layer L+1's experts from layer L's state with layer L+1's router."""
    T = actual.shape[0]
    res = {k: np.zeros((N_MOE - 1, 2)) for k in ('a_router_input_L', 'b_ffn_inp_L_renorm', 'c_l_out_L', 'skip2_ffn_inp_L')}
    res['skip2_ffn_inp_L'] = np.zeros((N_MOE - 2, 2))
    res['self_check'] = np.zeros((N_MOE, 2))
    pred_sets = {6: [None] * N_MOE, 12: [None] * N_MOE}  # predictor b, for layer li from layer li-1
    for li in range(N_MOE):
        x_inp = bf16_to_f32(np.asarray(hd['ffn_inp'][:, li]))
        x_out = bf16_to_f32(np.asarray(hd['l_out'][:, li]))
        own = rmsnorm(x_inp, nw[li], eps)                     # layer L's actual router input
        res['self_check'][li] = [recall_at(own @ W[li].T, actual[:, li], 6), recall_at(own @ W[li].T, actual[:, li], 12)]
        if li + 1 < N_MOE:
            nxt = li + 1
            preds = {
                'a_router_input_L': own @ W[nxt].T,
                'b_ffn_inp_L_renorm': rmsnorm(x_inp, nw[nxt], eps) @ W[nxt].T,
                'c_l_out_L': rmsnorm(x_out, nw[nxt], eps) @ W[nxt].T,
            }
            for name, p in preds.items():
                res[name][li] = [recall_at(p, actual[:, nxt], 6), recall_at(p, actual[:, nxt], 12)]
            order = np.argsort(-preds['b_ffn_inp_L_renorm'], axis=-1)
            pred_sets[6][nxt] = order[:, :6]
            pred_sets[12][nxt] = order[:, :12]
        if li + 2 < N_MOE:
            p = rmsnorm(x_inp, nw[li + 2], eps) @ W[li + 2].T
            res['skip2_ffn_inp_L'][li] = [recall_at(p, actual[:, li + 2], 6), recall_at(p, actual[:, li + 2], 12)]
    # temporal baseline: previous token's experts at layer L+1
    prev = np.zeros((N_MOE, 2))
    for li in range(N_MOE):
        a = actual[1:, li]
        p1 = actual[:-1, li]
        p2 = np.concatenate([actual[:-1, li], np.vstack([actual[:1, li], actual[:-2, li]])], 1) if T > 2 else p1
        prev[li, 0] = (a[:, :, None] == p1[:, None, :]).any(2).sum(1).mean() / N_USED
        prev[li, 1] = (a[:, :, None] == p2[:, None, :]).any(2).sum(1).mean() / N_USED
    res['prev_token_same_layer'] = prev
    return res, pred_sets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('trace_dir')
    ap.add_argument('--hidden-dir')
    ap.add_argument('--model')
    ap.add_argument('--json')
    ap.add_argument('--no-belady', action='store_true')
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.trace_dir, '*.npz')))
    router = load_router(args.model) if args.hidden_dir else None
    report = {}
    pooled = {'union': {2: [], 4: [], 8: []}, 'ev': []}
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        z = np.load(f)
        topk, phase = z['topk'], z['phase']
        dec = np.where(phase == 1)[0]
        first = dec[0]
        warm, ev = topk[:first], topk[dec]
        r = {'n_prompt_positions': int(first), 'n_decode_steps': int(len(dec)), 'n_positions': int(len(phase))}
        pooled['ev'].append(ev)

        lru = {}
        for frac in CACHE_FRACS:
            cap = int(round(frac * N_EXP))
            per = np.array([lru_layer(warm[:, l], ev[:, l], cap)[0] for l in range(N_MOE)]) / (len(dec) * N_USED)
            g_hits, g_n = lru_global(warm, ev, int(round(frac * N_EXP * N_MOE)))
            ent = {'per_layer_cap': cap, 'per_layer_hit': per.round(4).tolist(), 'overall_hit_partitioned': float(per.mean()),
                   'overall_hit_global_pool': float(g_hits.sum() / (g_n * N_MOE)),
                   'global_pool_per_layer_hit': (g_hits / g_n).round(4).tolist()}
            if not args.no_belady:
                b = np.array([belady_layer(warm[:, l], ev[:, l], cap)[0] for l in range(N_MOE)]) / (len(dec) * N_USED)
                ent['overall_hit_belady_partitioned'] = float(b.mean())
            for d in (0.9, 0.98, 0.995):
                h = np.array([ema_layer(warm[:, l], ev[:, l], cap, d)[0] for l in range(N_MOE)]) / (len(dec) * N_USED)
                ent[f'overall_hit_ema{d}_partitioned'] = float(h.mean())
            miss = (1 - ent['overall_hit_global_pool']) * N_USED * N_MOE
            ent['misses_per_token_global'] = float(miss)
            ent['disk_MB_per_token_global'] = float(miss * EXPERT_BYTES / 1e6)
            lru[f'{int(frac * 100)}%'] = ent
        r['lru'] = lru

        r['union'] = {}
        for w in (2, 4, 8):
            u = union_sizes(ev, w)
            pooled['union'][w].append(u)
            r['union'][str(w)] = {'mean': float(u.mean()), 'p50': float(np.median(u)), 'p90': float(np.percentile(u, 90)),
                                   'max': int(u.max()), 'max_possible': 6 * w,
                                   'uniform_iid_expected': float(N_EXP * (1 - (1 - N_USED / N_EXP) ** w)),
                                   'per_layer_mean': u.mean(1).round(2).tolist()}
        hot10 = hotness(ev, 0.10)
        hot20 = hotness(ev, 0.20)
        r['hot'] = {'top10pct_share_mean': float(hot10.mean()), 'top10pct_share_per_layer': hot10.round(3).tolist(),
                    'top20pct_share_mean': float(hot20.mean()),
                    'note': 'uniform routing would give 0.10 / 0.20; finite-sample noise raises this somewhat'}

        if args.hidden_dir:
            meta = json.load(open(os.path.join(args.hidden_dir, f'trace_{name}.meta.json')))
            nd = meta['n_decode_steps']
            hd = {k: np.memmap(os.path.join(args.hidden_dir, f'trace_{name}.{k}.bf16'), dtype=np.uint16, mode='r').reshape(nd, N_MOE, N_EMBD)
                  for k in ('ffn_inp', 'l_out')}
            dec_pos = np.fromfile(os.path.join(args.hidden_dir, f'trace_{name}.dec_pos.i32'), dtype=np.int32)
            assert (dec_pos == dec).all()
            W, nw, eps = router
            pm, pred_sets = prefetch_metrics(hd, W, nw, eps, topk[dec].astype(np.int64))
            r['prefetch'] = {k: {'recall@6_mean': float(v[:, 0].mean()), 'recall@12_mean': float(v[:, 1].mean()),
                                 'recall@6_per_layer': v[:, 0].round(3).tolist(), 'recall@12_per_layer': v[:, 1].round(3).tolist()}
                             for k, v in pm.items()}
            # LRU + next-layer prefetch (predictor b). Layer 2 (index 0) has no MoE layer before it: no prefetch.
            comb = {}
            for frac in (0.20, 0.30):
                cap = int(round(frac * N_EXP))
                for kp in (0, 6, 12):
                    s = np.array([lru_prefetch_layer(warm[:, l], ev[:, l], pred_sets[kp][l] if kp else None, cap)
                                  for l in range(N_MOE)])  # [47, 3]
                    hits, stalls, pre = s.sum(0) / len(dec)
                    comb[f'{int(frac * 100)}%_prefetch{kp}'] = {
                        'demand_hit_rate': float(hits / (hits + stalls)), 'stalls_per_token': float(stalls),
                        'prefetch_loads_per_token': float(pre), 'disk_MB_per_token': float((stalls + pre) * EXPERT_BYTES / 1e6),
                        'stall_MB_per_token': float(stalls * EXPERT_BYTES / 1e6)}
            r['lru_plus_prefetch'] = comb
        report[name] = r
        print(f'{name}: done', file=sys.stderr)

    # pooled hotness across workloads + stability of the hot set across workloads
    names = list(report)
    if len(names) > 1:
        k = int(round(0.10 * N_EXP))
        hot_sets = []
        for ev in pooled['ev']:
            hs = []
            for l in range(N_MOE):
                cnt = np.bincount(ev[:, l].ravel(), minlength=N_EXP)
                hs.append(set(np.argsort(-cnt)[:k].tolist()))
            hot_sets.append(hs)
        ov = {}
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                ov[f'{names[i]}~{names[j]}'] = float(np.mean([len(hot_sets[i][l] & hot_sets[j][l]) / k for l in range(N_MOE)]))
        # how much of workload j's selections a hot set learned on the other workloads covers
        transfer = {}
        for j, ev in enumerate(pooled['ev']):
            share = []
            for l in range(N_MOE):
                cnt_other = sum(np.bincount(pooled['ev'][i][:, l].ravel(), minlength=N_EXP) for i in range(len(names)) if i != j)
                hs = np.argsort(-cnt_other)[:k]
                cnt = np.bincount(ev[:, l].ravel(), minlength=N_EXP)
                share.append(cnt[hs].sum() / cnt.sum())
            transfer[names[j]] = float(np.mean(share))
        report['_cross_workload'] = {'top10pct_hot_set_overlap': ov, 'top10pct_hot_set_from_other_workloads_share': transfer}

    out = json.dumps(report, indent=1)
    if args.json:
        open(args.json, 'w').write(out)
    else:
        print(out)


if __name__ == '__main__':
    main()
