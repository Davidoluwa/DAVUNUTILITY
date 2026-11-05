"""Convert worker B's decode_<prompt>.json references to the plain text check_ref reads.
  python3 -I tools/ref_to_txt.py testdata/decode_p1_raw_completion.json > p1.txt"""
import json
import sys

d = json.load(open(sys.argv[1]))
print(" ".join(map(str, d["prompt_ids"])))
print(" ".join(map(str, d["greedy_ids"])))
for s in d["top10_logits"]:
    print(s["step"], " ".join(f"{i}:{v}" for i, v in zip(s["ids"], s["logits"])))
