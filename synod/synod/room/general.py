"""The same room on other modalities: code and algebra, against baselines.

  python -m synod.room general --seeds 3   -> results/GENERAL_REPORT.md

Each domain supplies only its reader, its operations and its check; the
experts, the judge, deliberation, search and learning are the room's. The
baselines show what the learning adds: the same room with only its operator
experts, and the same search with nothing learned.
"""
from __future__ import annotations

import os
import time

import numpy as np

from .experiment import run_room
from .room import RoomConfig, make_room


def _domains():
    from ..algebra.lang import ALGEBRA
    from ..algebra.world import SPLITS as ALG_SPLITS, AlgebraScenario, AlgebraWorld
    from ..code.lang import CODE
    from ..code.world import SPLITS as CODE_SPLITS, CodeScenario, CodeWorld
    return {
        "code": dict(domain=CODE, splits=CODE_SPLITS, config=lambda: RoomConfig(),
                     world=lambda seed, n, per: CodeWorld(CodeScenario(n_train=n, n_per_test_split=per, seed=seed)),
                     n_train=3000,
                     names={"seen": "familiar kinds of task", "paraphrase": "descriptions worded in new ways",
                            "compose": "combinations of steps never seen together",
                            "longer": "four-step programs (training had at most three)"}),
        "algebra": dict(domain=ALGEBRA, splits=ALG_SPLITS,
                        config=lambda: RoomConfig(max_steps=10, think_harder=((12, 3),)),
                        world=lambda seed, n, per: AlgebraWorld(AlgebraScenario(n_train=n, n_per_test_split=per, seed=seed)),
                        n_train=2000,
                        names={"seen": "familiar kinds of question", "paraphrase": "questions worded in new ways",
                               "forms": "equation shapes and variable letters never seen",
                               "compose": "systems needing moves never combined in training",
                               "longer": "three equations in three unknowns (training had at most two)"}),
    }


VARIANTS = {
    "the room": {},
    "operators alone (no neural, memory or analogy)": dict(n_neural=0, memory=False, analogy=False),
    "search alone, nothing learned": None,
}


def job(args):
    domain_name, variant, seed, per = args
    d = _domains()[domain_name]
    kw = VARIANTS[variant]
    untrained = kw is None
    build = lambda s: make_room(seed=s, domain=d["domain"], config=d["config"](), **(kw or {}))  # noqa: E731
    world = d["world"](seed, 0 if untrained else d["n_train"], per)
    started = time.time()
    run = run_room("search alone, no learning" if untrained else variant, seed=seed, world=world, build=build)
    out = {s: run.summary(s) for s in d["splits"]}
    inv = getattr(run.orchestrator, "inventor", None)
    extra = {"seconds": time.time() - started,
             "kept": [p.describe() for p in getattr(run.orchestrator, "procedures", [])],
             "tried": [e.get("body") for e in (inv.log if inv else []) if e.get("procedure")]}
    return domain_name, variant, seed, out, extra


def compare(seeds, per: int = 100, processes: int = 4, domains=None):
    domains = domains or list(_domains())
    jobs = [(dn, v, s, per) for dn in domains for v in VARIANTS for s in seeds]
    jobs.sort(key=lambda j: j[1] == "search alone, nothing learned")
    try:
        from multiprocessing import Pool
        with Pool(processes) as pool:
            results = pool.map(job, jobs)
    except (OSError, ImportError):
        results = [job(j) for j in jobs]
    table = {}
    for dn, v, s, out, extra in results:
        table.setdefault(dn, {}).setdefault(v, []).append((s, out, extra))
    return table


def _p(x):
    return f"{100 * x:.0f}%"


def write(table, seeds, path=os.path.join("results", "GENERAL_REPORT.md")):
    ds = _domains()
    L = ["# The room on other modalities\n",
         "One engine. Each domain supplies only a reader, its operations and its check; the experts, the judge, "
         "deliberation, search, learning, sleep and invention are the same code that does arithmetic word problems "
         f"(`results/ROOM_REPORT.md`). Averaged over {len(seeds)} seeds; range across seeds in brackets.\n"]
    for dn, rows in table.items():
        d = ds[dn]
        splits = d["splits"]
        L.append(f"## {dn}\n")
        if dn == "code":
            L.append("Write a list program from a description and three examples. No answers are ever revealed: the "
                     "examples are the only check, and the room delivers only a program that passes them. Graded on "
                     "four hidden inputs of other lengths and ranges. When nothing passes, the room searches, then "
                     "searches twice as wide, and again (6, 12, 24 routes), and as a last resort once more trusting its own "
                     "judge less (doubt after failure).\n")
        else:
            L.append("Solve equations and systems of equations by general moves (expand, gather terms, divide both "
                     "sides, isolate, substitute, eliminate, read off a value); no solve move. Half the practice "
                     "questions reveal their answer, never the derivation. When unsure, the room deliberates again "
                     "with a wider beam and more options per operator.\n")
        L.append("| strategy | " + " | ".join(splits) + " |")
        L.append("|---|" + "---|" * len(splits))
        for v, res in rows.items():
            cells = []
            for s in splits:
                acc = [r[1][s]["accuracy"] for r in res]
                cells.append(f"{_p(np.mean(acc))} ({_p(min(acc))}-{_p(max(acc))})")
            L.append(f"| {v} | " + " | ".join(cells) + " |")
        L.append("\nWrong answers (the rest of the misses are abstentions):\n")
        L.append("| strategy | " + " | ".join(splits) + " |")
        L.append("|---|" + "---|" * len(splits))
        for v, res in rows.items():
            L.append(f"| {v} | " + " | ".join(_p(np.mean([r[1][s]["wrong"] for r in res])) for s in splits) + " |")
        L.append("\nCompute per question (units of expert work, including any search):\n")
        L.append("| strategy | " + " | ".join(splits) + " |")
        L.append("|---|" + "---|" * len(splits))
        for v, res in rows.items():
            L.append(f"| {v} | " + " | ".join(f"{np.mean([r[1][s]['cost'] for r in res]):.0f}" for s in splits) + " |")
        L.append("\n" + "\n".join(f"- **{s}**: {d['names'][s]}" for s in splits))
        room = rows.get("the room", [])
        if room:
            kept = sorted({k for _, _, e in room for k in e["kept"]})
            tried = sorted({k for _, _, e in room for k in e["tried"] if k})
            L.append(f"\nProcedures the room tried: {', '.join(f'`{t}`' for t in tried) or 'none'}. "
                     f"Kept: {', '.join(f'`{k}`' for k in kept) or 'none'}.")
            L.append(f"\nWall-clock per run (practice and tests, one core): "
                     f"{np.mean([e['seconds'] for _, _, e in room]):.0f}s.\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    return path
