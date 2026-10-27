"""Train the maths council, then test it on five kinds of unseen questions."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..council import Council, FixedPipeline
from ..objective import Objective
from .mathlang import read
from .nodes import CheckerNode, EstimatorNode, ParserNode, ReaderNode
from .world import MathScenario, MathWorld

SPLITS = ("seen", "paraphrase", "big", "story", "compose")


def make_nodes(seed: int = 0):
    return [ParserNode("parser", seed + 1), ReaderNode("reader", seed + 2),
            EstimatorNode("estimator", seed + 3), CheckerNode("checker", seed + 4)]


def _gate(nodes):
    parser = next(n for n in nodes if n.name == "parser")

    def route(view):
        r = read(view.question)
        return "parser" if parser.ranked(r.skeleton, r) else "reader"

    return route


STRATEGIES = {
    "synod": lambda nodes: Council(nodes),
    "parser alone (symbolic)": lambda nodes: FixedPipeline(nodes, lambda v: "parser"),
    "reader alone (neural)": lambda nodes: FixedPipeline(nodes, lambda v: "reader"),
    "hand-written gate": lambda nodes: FixedPipeline(nodes, _gate(nodes)),
}


@dataclass
class MathRun:
    name: str
    rows: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    orchestrator: object = None
    transcripts: dict = field(default_factory=dict)
    seconds: float = 0.0

    def summary(self, split=None):
        rows = [r for r in self.rows if split is None or r["split"] == split]
        n = max(len(rows), 1)
        return {
            "n": len(rows),
            "accuracy": sum(r["correct"] for r in rows) / n,
            "wrong": sum(r["delivered"] and not r["correct"] for r in rows) / n,
            "abstain": sum(not r["delivered"] for r in rows) / n,
            "cost": sum(r["cost"] for r in rows) / n,
            "utility": sum(r["utility"] for r in rows) / n,
        }

    def curve(self, width=500):
        train = [r for r in self.rows if r["split"] == "train"]
        return [float(np.mean([r["correct"] for r in train[i:i + width]])) for i in range(0, len(train), width)]


def run_maths(name: str = "synod", seed: int = 0, scenario: MathScenario | None = None, keep=None,
              help_budget: int = 0) -> MathRun:
    scenario = scenario or MathScenario(seed=seed)
    world = MathWorld(scenario)
    nodes = make_nodes(seed)
    orch = STRATEGIES[name](nodes)
    if help_budget and isinstance(orch, Council):
        orch.config.help_budget = help_budget
        orch.teacher = lambda task: task.target
    obj = Objective()
    out = MathRun(name, nodes=nodes, orchestrator=orch)
    started = time.time()
    tasks = list(world.train_stream())
    tasks += world.test_tasks(len(tasks))
    for task in tasks:
        rec = orch.handle(task)
        ok = rec.final is not None and task.is_correct(rec.final.value)
        parser_mode = next((p.evidence[0] for p in rec.all_proposals() if p.node == "parser" and p.evidence), "-")
        out.rows.append({
            "split": task.split, "family": task.family, "delivered": rec.final is not None, "correct": bool(ok),
            "cost": rec.cost, "utility": obj.score(rec.final is not None, bool(ok), rec.cost),
            "final": rec.final.node if rec.final is not None else "abstain", "parser_mode": parser_mode,
            "certified": rec.certified is not None,
            "asked": rec.label is not None and not task.labeled,
        })
        if keep is not None and keep(task):
            out.transcripts[task.id] = (task, rec)
    out.seconds = time.time() - started
    return out
