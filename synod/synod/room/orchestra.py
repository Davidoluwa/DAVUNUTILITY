"""One room for every modality: the orchestra.

A single population (every domain's operators, one neural pool, one memory,
one analogy, one goal expert, every reviewer) and one judge meet problems of
every kind, mixed in one stream, with nothing saying which kind each is.
Each domain's reader recognises its own problems; everything else, from who
to trust on which kind of problem, to which experts to listen to, to what
procedures to invent, is learned in the same room. Operators are shared:
a problem read as algebra can still use an arithmetic operation (``is x
prime?`` after solving for x), because every operator binds whatever facts
on the table it can apply to.

  python -m synod.room orchestra [--seeds N]   -> results/ORCHESTRA_REPORT.md
"""
from __future__ import annotations

import numpy as np

from .workspace import ARITH, Domain


class Orchestra(Domain):
    name = "orchestra"

    def __init__(self, parts):
        self.parts = list(parts)
        self.ops = list(dict.fromkeys(op for d in self.parts for op in d.ops))
        self.missing_info = any(d.missing_info for d in self.parts)
        super().__init__()

    def pick(self, text) -> Domain:
        """The domain whose reader recognises this problem (the last one reads anything)."""
        for d in self.parts:
            if d.recognises(text):
                return d
        return self.parts[-1]

    def reviewers(self, seed: int) -> list:
        out = []
        for d in self.parts:
            out += d.reviewers(seed)
        return out

    def verdict(self, task, res) -> str:
        return self.pick(task.question).verdict(task, res)

    def truth(self, task) -> str:
        return self.pick(task.question).truth(task)


def orchestra() -> Orchestra:
    from ..algebra.lang import ALGEBRA
    from ..code.lang import CODE
    from .workspace import _DOMAINS
    return _DOMAINS.get("orchestra") or Orchestra([CODE, ALGEBRA, ARITH])


class OrchestraWorld:
    """Every curriculum in one shuffled stream; every test set, named by domain."""

    def __init__(self, seed: int = 0, n: dict | None = None, per: int = 100):
        from ..algebra.world import AlgebraScenario, AlgebraWorld
        from ..code.world import CodeScenario, CodeWorld
        from .world import RoomScenario, RoomWorld
        n = n or {"arith": 8000, "code": 3000, "algebra": 2000}
        self.worlds = {
            "arith": RoomWorld(RoomScenario(n_train=n["arith"], n_per_test_split=per, seed=seed)),
            "code": CodeWorld(CodeScenario(n_train=n["code"], n_per_test_split=per, seed=seed)),
            "algebra": AlgebraWorld(AlgebraScenario(n_train=n["algebra"], n_per_test_split=per, seed=seed)),
        }
        self.n = n
        self.rng = np.random.default_rng(seed + 77)

    def train_stream(self):
        streams = {k: iter(w.train_stream()) for k, w in self.worlds.items()}
        left = dict(self.n)
        tid = 0
        while any(left.values()):
            keys = [k for k, v in left.items() if v > 0]
            k = keys[int(self.rng.choice(len(keys), p=np.array([left[x] for x in keys]) / sum(left[x] for x in keys)))]
            task = next(streams[k])
            left[k] -= 1
            yield _renamed(task, tid, "train", k)
            tid += 1

    def test_tasks(self, start_id: int):
        out = []
        tid = start_id
        for k, w in self.worlds.items():
            for task in w.test_tasks(0):
                out.append(_renamed(task, tid, f"{k}:{task.split}", k))
                tid += 1
        order = self.rng.permutation(len(out))
        return [out[i] for i in order]


def _renamed(task, tid, split, domain):
    from dataclasses import replace
    return replace(task, id=tid, split=split, family=f"{domain}:{task.family}")


# ----------------------------------------------------------------------------
# The experiment: one room for everything, against a specialist room per domain
# ----------------------------------------------------------------------------
def run(seed: int = 0, per: int = 100, n: dict | None = None):
    from collections import Counter, defaultdict
    from .experiment import run_room
    from .experts import NeuralExpert, OperatorExpert
    from .room import make_room
    world = OrchestraWorld(seed=seed, n=n, per=per)
    r = run_room("orchestra", seed=seed, world=world, build=lambda s: make_room(seed=s, domain=orchestra()))
    room = r.orchestrator
    splits = sorted({row["split"] for row in r.rows if row["split"] != "train"})
    summary = {s: r.summary(s) for s in splits}
    # who backed the steps of right answers, per domain
    kind = {e.name: ("operator" if isinstance(e, OperatorExpert) else "neural" if isinstance(e, NeuralExpert) else e.name)
            for e in room.full.experts}
    by_domain = defaultdict(Counter)
    neural = defaultdict(Counter)
    for row in r.rows:
        if row["split"] == "train" or not row["correct"]:
            continue
        d = row["split"].split(":")[0]
        for names in row["backers"]:
            by_domain[d]["steps"] += 1
            for k in set(kind.get(x, x) for x in names):
                by_domain[d][k] += 1
            for x in names:
                if kind.get(x) == "neural":
                    neural[x][d] += 1
    special = {}
    for x, c in neural.items():
        tot = sum(c.values())
        p = np.array([c[d] for d in ("arith", "code", "algebra")], dtype=float) / max(tot, 1)
        p = p[p > 0]
        special[x] = {"share": {d: c[d] / tot for d in ("arith", "code", "algebra")}, "entropy": float(-(p * np.log2(p)).sum())}
    return {"summary": summary, "labour": {d: dict(c) for d, c in by_domain.items()}, "neural": special,
            "experts": len(room.experts), "seconds": r.seconds,
            "kept": [p.describe() for p in room.procedures]}


def _job(args):
    seed, per, n = args
    return seed, run(seed, per, n)


def compare(seeds, per: int = 100, n: dict | None = None, processes: int = 4):
    try:
        from multiprocessing import Pool
        with Pool(min(processes, len(seeds))) as pool:
            out = pool.map(_job, [(s, per, n) for s in seeds])
    except (OSError, ImportError):
        out = [_job((s, per, n)) for s in seeds]
    return dict(out)


def write(results, path="results/ORCHESTRA_REPORT.md", specialists: dict | None = None):
    import os
    seeds = sorted(results)
    first = results[seeds[0]]
    splits = list(first["summary"])
    L = ["# The orchestra: one room for every modality\n",
         f"One room of {first['experts']} experts (every domain's operators, one neural pool, one memory, one analogy, "
         "one goal expert, every reviewer) and one judge. Arithmetic word problems, code from examples and algebra "
         "arrive mixed in one stream of practice, with nothing saying which is which; each domain's reader recognises "
         "its own problems, and everything else is learned together. Same practice per domain as the specialist rooms "
         f"(8000 arithmetic, 3000 code, 2000 algebra). Averaged over {len(seeds)} seeds.\n",
         "## Right answers on every test set\n",
         "| test set | the orchestra | " + ("specialist room | " if specialists else "") + "range (orchestra) |",
         "|---|---|" + ("---|" if specialists else "") + "---|"]
    for s in splits:
        acc = [results[k]["summary"][s]["accuracy"] for k in seeds]
        spec = f" {specialists[s]} |" if specialists and s in specialists else (" |" if specialists else "")
        L.append(f"| {s} | {100 * np.mean(acc):.0f}% |{spec} {100 * min(acc):.0f}-{100 * max(acc):.0f}% |")
    L.append("\n## Division of labour across modalities (seed 0)\n")
    L.append("Share of the steps in right test answers each kind of expert backed, per domain.\n")
    kinds = ["operator", "neural", "memory", "analogy", "goal"]
    L.append("| domain | " + " | ".join(kinds) + " |")
    L.append("|---|" + "---|" * len(kinds))
    for d, c in sorted(first["labour"].items()):
        n = max(c.get("steps", 0), 1)
        L.append(f"| {d} | " + " | ".join(f"{100 * c.get(k, 0) / n:.0f}%" for k in kinds) + " |")
    L.append("\nWhere each neural expert's correct backing went (seed 0; entropy of 1.58 bits = spread evenly over the "
             "three, 0 = one modality only):\n")
    L.append("| expert | arithmetic | code | algebra | entropy (bits) |")
    L.append("|---|---|---|---|---|")
    for x, v in sorted(first["neural"].items()):
        sh = v["share"]
        L.append(f"| {x} | {100 * sh['arith']:.0f}% | {100 * sh['code']:.0f}% | {100 * sh['algebra']:.0f}% | {v['entropy']:.2f} |")
    kept = sorted({k for r in results.values() for k in r["kept"]})
    L.append(f"\nProcedures kept: {', '.join(f'`{k}`' for k in kept) or 'none'}.")
    L.append(f"\nWall-clock per run: {np.mean([r['seconds'] for r in results.values()]):.0f}s.\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    return path
