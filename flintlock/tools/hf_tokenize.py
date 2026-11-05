"""Reference token ids from the original Hugging Face tokenizer, in the same format as
build/tokenize (one line of ids per input line, same escapes).
  python hf_tokenize.py tokenizer.json STRINGS.txt"""
import sys

from tokenizers import Tokenizer


def unescape(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            c = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(c, c))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


tok = Tokenizer.from_file(sys.argv[1])
with open(sys.argv[2], encoding="utf-8") as f:
    for line in f.read().split("\n"):
        if line == "" and f.tell():
            continue
        ids = tok.encode(unescape(line), add_special_tokens=False).ids
        print(" ".join(map(str, ids)))
