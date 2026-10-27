"""Synod does maths.

  python -m synod.maths train [--teacher N] [--seed S]   train, test, save the council
  python -m synod.maths ask "What is the gcd of 84 and 126?"
  python -m synod.maths chat                              ask questions interactively
  python -m synod.maths report [--seeds N]                compare strategies, write results/MATHS_REPORT.md
  python -m synod.maths exam [--seed S]                   40 hand-written questions -> results/EXAM_REPORT.md
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time

from ..protocol import Task
from ..transcript import render
from .experiment import SPLITS, run_maths
from .mathlang import context, read

MODEL = os.path.join("results", "maths_council.pkl")


def train(seed=0, teacher=40, verbose=True):
    t0 = time.time()
    r = run_maths("synod", seed=seed, help_budget=teacher)
    council = r.orchestrator
    council.teacher = None  # not picklable, and nobody is on call during `ask`
    os.makedirs(os.path.dirname(MODEL), exist_ok=True)
    with open(MODEL, "wb") as fh:
        pickle.dump(council, fh)
    if verbose:
        print(f"trained and tested in {time.time() - t0:.0f}s"
              + (f"; asked the teacher {sum(x['asked'] for x in r.rows)} times" if teacher else ""))
        for s in SPLITS:
            m = r.summary(s)
            print(f"  {s:11s} {m['accuracy']:6.1%} right  {m['wrong']:6.1%} wrong  {m['abstain']:6.1%} abstained")
        print(f"saved to {MODEL}")
    return council


def load():
    if not os.path.exists(MODEL):
        print("no trained council yet; training one (about a minute)...", file=sys.stderr)
        council = train(verbose=False)
    else:
        with open(MODEL, "rb") as fh:
            council = pickle.load(fh)
    for node in council.nodes:
        node.explore = False  # answering, not experimenting: bid what you believe
    return council


_ids = [10 ** 6]


def ask(council, question: str):
    _ids[0] += 1
    task = Task(_ids[0], (), 1e-6, None, "", False, question=question, context=context(read(question)))
    rec = council.handle(task)
    return rec, render(task, rec)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m synod.maths")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--teacher", type=int, default=40, help="how many questions it may ask (0 = none)")
    t.add_argument("--seed", type=int, default=0)
    a = sub.add_parser("ask")
    a.add_argument("question", nargs="+")
    sub.add_parser("chat")
    rp = sub.add_parser("report")
    rp.add_argument("--seeds", type=int, default=3)
    ex = sub.add_parser("exam")
    ex.add_argument("--seed", type=int, default=0)
    ex.add_argument("--no-compare", action="store_true", help="skip the single-node and gate baselines")
    args = ap.parse_args(argv)

    if args.cmd == "train":
        train(args.seed, args.teacher)
    elif args.cmd == "ask":
        council = load()
        print(ask(council, " ".join(args.question))[1])
    elif args.cmd == "exam":
        from .exam import main as exam_main
        exam_main(args.seed, compare=not args.no_compare)
    elif args.cmd == "chat":
        council = load()
        print("ask me a maths question (empty line to quit)")
        while True:
            try:
                q = input("> ").strip()
            except EOFError:
                break
            if not q:
                break
            print(ask(council, q)[1])
    else:
        from .report import compare, detail, write
        seeds = list(range(args.seeds))
        table = compare(seeds)
        det = detail(0)
        path = os.path.join("results", "MATHS_REPORT.md")
        write(table, det, seeds, path)
        for name, tbl in table.items():
            print(f"{name:34s} " + "  ".join(f"{s} {tbl[s]['accuracy']:.0%}" for s in SPLITS))
        print(f"report written to {path}")


if __name__ == "__main__":
    main()
