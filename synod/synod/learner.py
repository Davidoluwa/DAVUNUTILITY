"""A sparse log-linear learner over string features.

Both learned parts of the council (the router and the judge) are built on this.
Features are names like "e|parser|analogy" or "x|reader|w:times"; weights are
learned online. The per-feature step size shrinks as a feature accumulates
gradient (Adagrad), but the accumulator decays, so the model never stops
adapting when the world changes.
"""
from __future__ import annotations

import math
from itertools import repeat
from operator import mul


class SparseLogLinear:
    def __init__(self, lr: float = 0.3, decay: float = 0.999, l2: float = 1e-4):
        self.lr, self.decay, self.l2 = lr, decay, l2
        self.w: dict = {}
        self.g2: dict = {}

    def score(self, feats: dict) -> float:
        return sum(map(mul, map(self.w.get, feats, repeat(0.0)), feats.values()))

    def step(self, feats: dict, grad: float) -> None:
        """One gradient step, where grad = dLoss/dScore for this feature vector."""
        W, G2 = self.w, self.g2
        wget, gget = W.get, G2.get
        l2, decay, lr, sqrt = self.l2, self.decay, self.lr, math.sqrt
        for f, v in feats.items():
            w = wget(f, 0.0)
            g = grad * v + l2 * w
            acc = decay * gget(f, 0.0) + g * g
            G2[f] = acc
            W[f] = w - lr * g / sqrt(1.0 + acc)

    def reasons(self, feats: dict, top: int = 4):
        """The features pushing this score hardest, as (feature, contribution)."""
        parts = [(f, self.w.get(f, 0.0) * v) for f, v in feats.items()]
        parts = [p for p in parts if abs(p[1]) > 1e-3]
        return sorted(parts, key=lambda p: -abs(p[1]))[:top]


class EvidenceLogLinear(SparseLogLinear):
    """A log-linear model whose features can only be evidence *for* the
    outcome: their weights never go below zero. Only the features named in
    ``signed`` (a prior, say) can count against it.

    An operator that learns from a signed bag of words learns vetoes as well
    as cues ("squares never comes when the question says *even*"), because in
    training each word only ever appeared alongside certain others. Put two
    familiar clauses together and each one's words veto the other's
    operation. Non-negative evidence cannot learn a veto, so what a familiar
    clause asks for is still asked for in a new combination."""

    def __init__(self, lr: float = 0.3, decay: float = 0.999, l2: float = 1e-4, signed=("bias",)):
        super().__init__(lr, decay, l2)
        self.signed = frozenset(signed)

    def step(self, feats: dict, grad: float) -> None:
        super().step(feats, grad)
        W, signed = self.w, self.signed
        for f in feats:
            if W[f] < 0.0 and f not in signed:
                W[f] = 0.0


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def softmax(zs):
    m = max(zs)
    es = [math.exp(z - m) for z in zs]
    s = sum(es)
    return [e / s for e in es]
