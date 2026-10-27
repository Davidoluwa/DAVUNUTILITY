"""python -m synod [--seeds N] [--out DIR]"""
from __future__ import annotations

import argparse
import os
import time

from .report import compare, detail_run, export_json, write_report


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Synod demo scenario and compare strategies.")
    ap.add_argument("--seeds", type=int, default=3, help="seeds per strategy (default 3)")
    ap.add_argument("--out", default="results", help="output directory (default results/)")
    ap.add_argument("--processes", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()
    started = time.time()
    seeds = list(range(args.seeds))
    print(f"running {args.seeds} seed(s) x 8 strategies ...", flush=True)
    table = compare(seeds, args.processes)
    detail = detail_run(0)
    report = os.path.join(args.out, "REPORT.md")
    write_report(table, detail, seeds, report)
    export_json(table, detail, os.path.join(args.out, "results.json"))
    print(f"\n{'strategy':24s} {'utility':>9s} {'accuracy':>9s} {'wrong':>7s} {'compute':>8s}")
    for name, a in table.items():
        print(f"{name:24s} {a['utility']:+9.3f} {a['accuracy']:9.1%} {a['wrong']:7.1%} {a['cost']:8.2f}")
    print("\nautonomous events (seed 0):")
    for t, who, msg in detail["timeline"]:
        print(f"  t={t:4d} {who:9s} {msg}")
    if detail["showcase"]:
        title, text = detail["showcase"][0]
        print(f"\nexample deliberation - {title}:\n{text}")
    print(f"\nreport written to {report} ({time.time() - started:.0f}s)")


if __name__ == "__main__":
    main()
