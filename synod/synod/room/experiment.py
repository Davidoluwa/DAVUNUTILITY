"""Train the room on the dense curriculum, then test it on six kinds of unseen questions."""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

import numpy as np

from ..council import Council
from ..maths.experiment import make_nodes
from ..objective import Objective
from .experts import NeuralExpert, OperatorExpert
from .room import Room, make_room, verdict
from .workspace import canonical_program, steps_to_program
from .world import RoomScenario, RoomWorld


def _room(**kw):
    def build(seed):
        return make_room(seed=seed, **kw)
    return build


STRATEGIES = {
    "room": _room(),
    "room, without inventing procedures": _room(invent=False),
    "room, one neural expert": _room(n_neural=1),
    "operators alone (no neural, memory or analogy)": _room(n_neural=0, memory=False, analogy=False),
    "search alone, no learning": _room(),
    "room, cross-fitted (two sparring benches)": _room(crossfit=True),
    "council v2 (question -> answer)": lambda seed: Council(make_nodes(seed)),
}
UNTRAINED = {"search alone, no learning"}  # skips practice: the same deliberation with nothing learned


@dataclass
class RoomRun:
    name: str
    rows: list = field(default_factory=list)
    orchestrator: object = None
    transcripts: dict = field(default_factory=dict)
    seconds: float = 0.0

    def summary(self, split=None):
        rows = [r for r in self.rows if split is None or r["split"] == split]
        n = max(len(rows), 1)
        right = [r for r in rows if r["correct"]]
        return {
            "n": len(rows),
            "accuracy": len(right) / n,
            "wrong": sum(r["delivered"] and not r["correct"] for r in rows) / n,
            "abstain": sum(not r["delivered"] for r in rows) / n,
            "said_missing": sum(r.get("said_missing", False) for r in rows) / n,
            "method": sum(r["method"] for r in right) / max(len(right), 1),
            "cost": sum(r["cost"] for r in rows) / n,
            "utility": sum(r["utility"] for r in rows) / n,
        }

    def curve(self, width=1000):
        train = [r for r in self.rows if r["split"] == "train"]
        return [float(np.mean([r["correct"] for r in train[i:i + width]])) for i in range(0, len(train), width)]


def backers(res) -> list:
    """For each step of the delivered solution: the experts who proposed it."""
    if res.route is None:
        return []
    return [[p.expert for p in m.cands[k].props] for m, k in res.route.trail]


def run_room(name: str = "room", seed: int = 0, scenario: RoomScenario | None = None, keep=None,
             freeze_at_test: bool = True) -> RoomRun:
    scenario = scenario or RoomScenario(seed=seed)
    world = RoomWorld(scenario)
    orch = STRATEGIES[name](seed)
    obj = Objective()
    out = RoomRun(name, orchestrator=orch)
    started = time.time()
    tasks = [] if name in UNTRAINED else list(world.train_stream())
    n_train = len(tasks)
    if name in UNTRAINED:
        orch.config.learn = False
    tasks += world.test_tasks(n_train)
    for k, task in enumerate(tasks):
        if freeze_at_test and k == n_train:
            if isinstance(orch, Room):
                orch.config.learn = False
            else:
                orch.config.learn = False
                orch.config.exchange = False
        if isinstance(orch, Room):
            res = orch.handle(task)
            given = res.answer
            method = res.route is not None and (canonical_program(steps_to_program(res.steps)) == task.solution
                                                if task.answerable else res.insufficient)
            row = {"steps": len(res.steps) - 1 if res.route else 0, "backers": backers(res) if given is not None else [],
                   "said_missing": res.insufficient, "ops": tuple(s.op for s in res.steps)}
            cost = res.cost
        else:
            # the old council can only answer with a number; an incomplete
            # question can't teach it anything, so it never sees one as labeled
            rec = orch.handle(task if task.answerable else replace(task, labeled=False))
            given = rec.final.value if rec.final is not None else None
            method, row, cost = False, {"steps": 0, "backers": []}, rec.cost
        ok = verdict(task, given) == "right"
        row.update({"split": task.split, "family": task.family, "delivered": given is not None, "correct": bool(ok),
                    "method": bool(method and ok), "cost": cost, "utility": obj.score(given is not None, bool(ok), cost),
                    "depth": len(task.solution and _ops(task.solution))})
        out.rows.append(row)
        if keep is not None and keep(task):
            out.transcripts[task.id] = (task, res if isinstance(orch, Room) else rec)
    out.seconds = time.time() - started
    return out


def _ops(prog) -> list:
    if not isinstance(prog, tuple) or prog[0] in ("N", "K", "L", "Q", "F", "C", "X"):
        return []
    out = [prog[0]]
    for a in prog[1:]:
        out += _ops(a)
    return out


def division_of_labour(run: RoomRun) -> dict:
    """Who backed the steps of right solutions on the test sets, by kind of expert."""
    room = run.orchestrator
    kind = {e.name: ("operator" if isinstance(e, OperatorExpert) else "neural" if isinstance(e, NeuralExpert)
                     else e.name) for e in room.full.experts}
    by_split = defaultdict(Counter)
    for r in run.rows:
        if r["split"] == "train" or not r["correct"]:
            continue
        for names in r["backers"]:
            for k in set(kind.get(n, n) for n in names):
                by_split[r["split"]][k] += 1
            by_split[r["split"]]["steps"] += 1
    return by_split


def specialisation(run: RoomRun) -> dict:
    """For each neural expert: the share of its correct backing that falls on
    its favourite kind of question (1/number of families = no specialisation)."""
    room = run.orchestrator
    names = [e.name for e in room.full.neural]
    per = {n: Counter() for n in names}
    for r in run.rows:
        if not r["correct"]:
            continue
        for step in r["backers"]:
            for n in step:
                if n in per:
                    per[n][r["family"]] += 1
    out = {}
    for n, c in per.items():
        tot = sum(c.values())
        if tot:
            fam, top = c.most_common(1)[0]
            p = np.array(list(c.values())) / tot
            out[n] = {"top": fam, "share": top / tot, "entropy": float(-(p * np.log2(p)).sum()), "n": tot}
    return out
