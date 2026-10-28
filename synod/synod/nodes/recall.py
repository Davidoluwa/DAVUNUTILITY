"""Recall: associative episodic memory (non-parametric stand-in for an embedding store).

It remembers shapes it has seen, with their outcomes, and answers by analogy.
Exact on patterns that recur in shape (e.g. every doubling sequence looks the
same once normalised), useless on genuinely new ones - and it knows which is which.
"""
from __future__ import annotations

import numpy as np

from ..node import Node
from ..perception import normalize_window
from ..protocol import NEURAL, Proposal


class RecallNode(Node):
    kind = NEURAL
    width = 6

    def __init__(self, name: str = "recall", seed: int = 0, capacity: int = 3000, k: int = 4,
                 lookup_cost: float = 0.5):
        super().__init__(name, seed)
        self.Z = np.zeros((capacity, self.width))
        self.T = np.zeros(capacity)
        self.valid = np.zeros(capacity, dtype=bool)
        self.author = np.array([""] * capacity, dtype=object)  # provenance: who taught me this
        self.when = np.zeros(capacity, dtype=int)
        self.size = 0
        self._ptr = 0
        self.k = k
        self.lookup_cost = lookup_cost

    def _lookup(self, view):
        sc = self.scratch(view)
        if "pred" in sc:
            return sc
        z, anchor, scale = normalize_window(view.history, self.width)
        if self.size == 0:
            sc.update(pred=anchor, sd=float("inf"), ev=("m", "empty"), dmin=float("inf"))
            return sc
        d = np.sqrt(((self.Z[: self.size] - z) ** 2).sum(1))
        d[~self.valid[: self.size]] = np.inf
        k = min(self.k, int(self.valid[: self.size].sum()))
        if k == 0:
            sc.update(pred=anchor, sd=float("inf"), ev=("m", "empty"), dmin=float("inf"))
            return sc
        idx = np.argpartition(d, k - 1)[:k]
        dmin = float(d[idx].min())
        exact = idx[d[idx] < 1e-6]
        use = exact if len(exact) else idx
        w = 1.0 / (d[use] + 1e-3)
        t = float(np.sum(w * self.T[use]) / np.sum(w))
        spread = float(np.sqrt(np.sum(w * (self.T[use] - t) ** 2) / np.sum(w))) * scale
        dist = "exact" if dmin < 1e-6 else "near" if dmin < 0.05 else "mid" if dmin < 0.3 else "far"
        agree = "agree" if spread <= view.tolerance / 2 else "split"
        sc.update(pred=anchor + t * scale, sd=spread, ev=("m", dist, agree), dmin=dmin)
        return sc

    def solve(self, view) -> Proposal:
        sc = self.scratch(view)
        cost = 0.0 if "pred" in sc else self.lookup_cost
        sc = self._lookup(view)
        sig = view.context
        conf = min(self.competence.mean(("p",) + sc["ev"] + sig), 0.99)
        return Proposal(self.name, self.kind, sc["pred"], conf, cost,
                        f"recalls {sc['ev'][1]} match -> {sc['pred']:.2f}", sc["ev"])

    def learn(self, view, value, source, record) -> None:
        z, anchor, scale = normalize_window(view.history, self.width)
        i = self._ptr
        self.Z[i], self.T[i], self.valid[i] = z, (value - anchor) / scale, True
        self.author[i] = record.final.node if source == "certified" and record.final is not None else ""
        self.when[i] = self._clock
        self._ptr = (self._ptr + 1) % len(self.T)
        self.size = min(self.size + 1, len(self.T))

    def retract(self, author: str, since: int) -> int:
        n = self.size
        bad = self.valid[:n] & (self.author[:n] == author) & (self.when[:n] >= since)
        self.valid[:n][bad] = False
        return int(bad.sum())

    # -- health ----------------------------------------------------------
    def repair(self) -> bool:
        """The index is corrupt: wipe it and rebuild from what arrives next
        (labels, plus answers the council certifies)."""
        self.size = 0
        self._ptr = 0
        self.valid[:] = False
        return True

    def fault(self, kind: str = "memory") -> None:
        """A bad index migration: every stored outcome is shifted. Matches still
        look exact, so the node stays confident while being wrong."""
        self.T[: self.size] += 0.6
