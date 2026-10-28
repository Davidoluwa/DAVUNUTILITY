"""Run the scenario under different orchestration strategies and compare."""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from .council import Council, CouncilConfig, FixedPipeline
from .nodes import CriticNode, InducerNode, IntuitionNode, RecallNode
from .objective import Objective
from .perception import signature
from .world import Scenario, World


def make_nodes(seed: int = 0):
    return [
        IntuitionNode("intuition", seed + 11),
        RecallNode("recall", seed + 12),
        InducerNode("inducer", seed + 13),
        CriticNode("critic", seed + 14),
    ]


def hand_written_gate(view) -> str:
    """The 'programmatic gate' a human would write: exact-looking -> symbolic."""
    precision, integral, _, _ = signature(view.history, view.tolerance)
    return "inducer" if integral == "int" else "intuition"


STRATEGIES = {
    "synod": lambda nodes: Council(nodes),
    "neural-only": lambda nodes: FixedPipeline(nodes, lambda v: "intuition"),
    "symbolic-only": lambda nodes: FixedPipeline(nodes, lambda v: "inducer"),
    "hand-written gate": lambda nodes: FixedPipeline(nodes, hand_written_gate),
    "synod w/o task features": lambda nodes: Council(nodes, config=CouncilConfig(task_features=False)),
    "synod w/o reviewers": lambda nodes: Council(nodes, config=CouncilConfig(verifiers=False)),
    "synod w/o exchange": lambda nodes: Council(nodes, config=CouncilConfig(exchange=False)),
    "synod w/o self-healing": lambda nodes: Council(nodes, config=CouncilConfig(healing=False)),
}


@dataclass
class Run:
    name: str
    rows: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    events: list = field(default_factory=list)
    transcripts: dict = field(default_factory=dict)
    seconds: float = 0.0
    maintenance: float = 0.0

    def frame(self, key):
        return np.array([r[key] for r in self.rows], dtype=float)

    def summary(self, lo: int = 0, hi: int | None = None) -> dict:
        rows = self.rows[lo:hi]
        n = max(len(rows), 1)
        delivered = [r for r in rows if r["delivered"]]
        return {
            "utility": sum(r["utility"] for r in rows) / n,
            "accuracy": sum(r["correct"] for r in rows) / n,
            "wrong": sum(r["delivered"] and not r["correct"] for r in rows) / n,
            "abstain": 1 - len(delivered) / n,
            "cost": sum(r["cost"] for r in rows) / n,
            "precision": (sum(r["correct"] for r in delivered) / len(delivered)) if delivered else 0.0,
        }


def run(name: str, seed: int = 0, scenario: Scenario | None = None, keep_transcripts=(), objective=None) -> Run:
    scenario = scenario or Scenario()
    objective = objective or Objective()
    world = World(seed, scenario)
    nodes = make_nodes(seed)
    orch = STRATEGIES[name](nodes)
    orch.objective = objective
    by_name = {n.name: n for n in nodes}
    out = Run(name, nodes=nodes)
    started = time.time()
    for t, task in world.stream():
        for e in scenario.events:
            if e.at != t:
                continue
            out.events.append((t, e.note))
            if e.action == "fault":
                by_name[e.node].fault(e.node)
            elif e.action == "clear_fault":
                by_name[e.node].clear_fault()
        rec = orch.handle(task)
        delivered = rec.final is not None
        correct = delivered and task.is_correct(rec.final.value)
        catches = sum(
            1 for r in rec.reviews
            if r.verdict.endorses is False and not task.is_correct(r.proposal.value)
        )
        false_alarms = sum(
            1 for r in rec.reviews
            if r.verdict.endorses is False and task.is_correct(r.proposal.value)
        )
        out.rows.append({
            "t": t, "family": task.family, "phase": scenario.phase(t),
            "delivered": delivered, "correct": bool(correct), "cost": rec.cost,
            "utility": objective.score(delivered, bool(correct), rec.cost),
            "lead": rec.proposals[0].node if rec.proposals else "-",
            "final": rec.final.node if delivered else "abstain",
            "belief": rec.final_belief, "reviews": len(rec.reviews), "catches": catches,
            "false_alarms": false_alarms, "proposals": len(rec.proposals),
            "certified": rec.certified is not None,
            "reviewers": tuple(r.reviewer for r in rec.reviews),
        })
        if t in keep_transcripts:
            out.transcripts[t] = (task, rec)
    out.seconds = time.time() - started
    out.maintenance = sum(n.maintenance_cost for n in nodes)
    return out


def routing_table(run: Run, lo: int, hi: int):
    table = defaultdict(Counter)
    for r in run.rows[lo:hi]:
        table[r["family"]][r["final"]] += 1
    return table
