#!/usr/bin/env python3
"""Turn flint_trace output (run with --hidden --top-logits 4, N_PREDICT 64) into reference files.

Usage: python make_refs.py RAW_PREFIX PROMPT_FILE OUT_DIR NAME

Writes OUT_DIR/decode_NAME.json and OUT_DIR/act_NAME.npz.

act_NAME.npz holds decode step 1, i.e. the first single-token forward pass: the model is fed the
first greedy token at position n_prompt. Arrays (float32 unless noted; MoE layers 2..48, index 0 = layer 2):
  ffn_inp [47, 2048]        residual stream after attention (input of ffn_norm), stored by llama.cpp's
                            callback as f32 and rounded to bf16 by the tracer
  l_out [47, 2048]          residual stream after the layer (attention + MoE + shared expert), bf16-rounded
  router_logits [47, 256]   router logits before sigmoid (exact f32 from llama.cpp)
  topk uint8 [47, 6]        selected experts, highest score first
  token int32, pos int32    the token fed and its position
"""
import json
import sys

import numpy as np

raw, prompt_file, out_dir, name = sys.argv[1:5]
m = json.load(open(raw + '.meta.json'))
tokens = np.fromfile(raw + '.tokens.i32', dtype=np.int32)
gen = np.fromfile(raw + '.gen.i32', dtype=np.int32)
phase = np.fromfile(raw + '.phase.u8', dtype=np.uint8)
topk = np.fromfile(raw + '.topk.u8', dtype=np.uint8).reshape(-1, 47, 6)
n_prompt = m['n_prompt']
assert (phase[:n_prompt] == 0).all() and m['missing_routing_entries'] == 0
top = json.load(open(raw + '.top_logits.json'))
text = open(raw + '.gen.txt', encoding='utf-8', errors='replace').read()

ref = {
    'prompt_file': 'prompts/' + prompt_file.split('/')[-1],
    'prompt_text': open(prompt_file, encoding='utf-8').read(),
    'n_prompt': n_prompt,
    'prompt_ids': tokens[:n_prompt].tolist(),
    'greedy_ids': gen[:64].tolist(),
    'greedy_text': text,
    'top10_logits': [
        {'step': s['step'], 'position': s['pos'],
         'note': 'logits after feeding position-1; step 0 = after the prompt',
         'ids': [t[0] for t in s['top10']], 'logits': [t[1] for t in s['top10']], 'pieces': [t[2] for t in s['top10']]}
        for s in top
    ],
}
json.dump(ref, open(f'{out_dir}/decode_{name}.json', 'w'), ensure_ascii=False, indent=1)

nd = m['n_decode_steps']
bf = lambda a: (a.astype(np.uint32) << 16).view(np.float32)
ffn_inp = bf(np.fromfile(raw + '.ffn_inp.bf16', dtype=np.uint16).reshape(nd, 47, 2048)[0])
l_out = bf(np.fromfile(raw + '.l_out.bf16', dtype=np.uint16).reshape(nd, 47, 2048)[0])
rl = np.fromfile(raw + '.router_logits.f32', dtype=np.float32).reshape(nd, 47, 256)[0]
dec_pos = np.fromfile(raw + '.dec_pos.i32', dtype=np.int32)
p = int(dec_pos[0])
np.savez_compressed(f'{out_dir}/act_{name}.npz', ffn_inp=ffn_inp, l_out=l_out, router_logits=rl,
                    topk=topk[p], token=np.int32(tokens[p]), pos=np.int32(p))
print(f'{name}: n_prompt {n_prompt}, greedy {len(ref["greedy_ids"])} ids, act at pos {p} token {tokens[p]}')
