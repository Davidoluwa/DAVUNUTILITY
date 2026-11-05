#!/usr/bin/env python3
"""Fuzz llama.cpp's Flint tokenizer against Hugging Face `tokenizers` on a corpus of files plus
synthetic mixed-case identifiers.

Usage: python tokenize_fuzz.py FLINT_TOKENIZE_BIN MODEL.gguf TOKENIZER_JSON CORPUS_DIR [...]

Each file is split into chunks of ~2000 characters at line boundaries. Prints a summary and the
first mismatches (if any).
"""
import os
import random
import struct
import subprocess
import sys
import tempfile

from tokenizers import Tokenizer

EXTS = {'.c', '.cpp', '.h', '.hpp', '.py', '.js', '.ts', '.tsx', '.svelte', '.java', '.kt', '.swift', '.go',
        '.rs', '.md', '.json', '.yaml', '.yml', '.sh', '.txt', '.cmake', '.m', '.mm', '.cu', '.metal'}


def chunks_of(path, limit=2000):
    try:
        text = open(path, encoding='utf-8').read()
    except (UnicodeDecodeError, OSError):
        return []
    out, cur = [], ''
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > limit and cur:
            out.append(cur)
            cur = ''
        cur += line
    if cur:
        out.append(cur)
    return out


def synthetic(n, seed=0):
    rng = random.Random(seed)
    words = ['get', 'set', 'http', 'json', 'xml', 'url', 'id', 'user', 'account', 'parse', 'response', 'request',
             'max', 'buffer', 'size', 'to', 'string', 'is', 'valid', 'école', 'straße', 'αθήνα', 'привет', 'i',
             'a', 'io', 'api', 'db', 'ok', 'gpu', 'cpu', 'kv', 'moe', 'déjà', 'ñu', 'œuvre']
    styles = [str.lower, str.upper, str.capitalize, lambda w: w[:1].lower() + w[1:].upper()]
    out = []
    for _ in range(n):
        parts = []
        for _ in range(rng.randint(1, 8)):
            k = rng.randint(1, 5)
            ident = ''.join(rng.choice(styles)(rng.choice(words)) for _ in range(k))
            if rng.random() < 0.2:
                ident += rng.choice(["'s", "'S", "'t", "'LL", "_", "2", "()", "."])
            parts.append(ident)
        out.append(rng.choice([' ', '\n', '.', '_', ', ', '\t']).join(parts))
    return out


def main():
    tok_bin, model, tok_json = sys.argv[1:4]
    texts = []
    for root in sys.argv[4:]:
        for d, _, files in os.walk(root):
            if '/.git' in d:
                continue
            for fn in files:
                if os.path.splitext(fn)[1] in EXTS:
                    texts.extend(chunks_of(os.path.join(d, fn)))
    n_corpus = len(texts)
    texts.extend(synthetic(20000))
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        for s in texts:
            b = s.encode('utf-8')
            f.write(struct.pack('<I', len(b)))
            f.write(b)
        path = f.name
    res = subprocess.run([tok_bin, model, path], capture_output=True, text=True, check=True)
    os.unlink(path)
    lines = res.stdout.split('\n')
    hf = Tokenizer.from_file(tok_json)
    encs = hf.encode_batch(texts, add_special_tokens=False)
    bad, n_tok, n_chars = [], 0, 0
    for i, (s, e) in enumerate(zip(texts, encs)):
        lc = [int(x) for x in lines[i].split()]
        n_tok += len(e.ids)
        n_chars += len(s)
        if lc != e.ids:
            bad.append((i, s, e.ids, lc))
    print(f'corpus chunks: {n_corpus}, synthetic strings: {len(texts) - n_corpus}, '
          f'characters: {n_chars}, HF tokens: {n_tok}, mismatching strings: {len(bad)}')
    for i, s, h, l in bad[:10]:
        j = next(k for k in range(min(len(h), len(l)) + 1) if k == min(len(h), len(l)) or h[k] != l[k])
        print(f'--- #{i} first difference at token {j}')
        print('text :', repr(s[:200]))
        print('hf   :', [hf.decode([t]) for t in h[max(0, j - 3):j + 5]])
        print('llama:', [hf.decode([t]) for t in l[max(0, j - 3):j + 5]])


if __name__ == '__main__':
    main()
