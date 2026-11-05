#!/usr/bin/env python3
"""Pack flint_trace output into the committed format.

Usage: python pack.py RAW_PREFIX OUT.npz

OUT.npz (np.savez_compressed):
  topk    uint8 [n_pos, 47, 6]  expert ids for MoE layers 2..48, in llama.cpp's top-k order (highest score first)
  phase   uint8 [n_pos]         0 = prompt (batched prefill), 1 = single-token decode step, 2 = injected follow-up turn
  tokens  int32 [n_pos]         token fed at each position
  gen     int32 [n_gen]         tokens sampled by greedy decoding (the last one is never fed back)
"""
import json
import sys

import numpy as np

raw, out = sys.argv[1], sys.argv[2]
m = json.load(open(raw + '.meta.json'))
n = m['n_pos']
topk = np.fromfile(raw + '.topk.u8', dtype=np.uint8).reshape(n, 47, 6)
phase = np.fromfile(raw + '.phase.u8', dtype=np.uint8)
tokens = np.fromfile(raw + '.tokens.i32', dtype=np.int32)
gen = np.fromfile(raw + '.gen.i32', dtype=np.int32)
assert phase.shape == (n,) and tokens.shape == (n,)
assert m['missing_routing_entries'] == 0 and (topk != 255).all()
np.savez_compressed(out, topk=topk, phase=phase, tokens=tokens, gen=gen)
print(f'{out}: {n} positions ({int((phase == 1).sum())} decode steps)')
