"""A sparse log-linear learner over string features.

Both learned parts of the council (the router and the judge) are built on this.
Features are names like "e|parser|analogy" or "x|reader|w:times"; weights are
learned online. The per-feature step size shrinks as a feature accumulates
gradient (Adagrad), but the accumulator decays, so the model never stops
adapting when the world changes.
"""
from __future__ import annotations

import math


class SparseLogLinear:
    def __init__(self, lr: float = 0.3, decay: float = 0.999, l2: float = 1e-4):
        self.lr, self.decay, self.l2 = lr, decay, l2
        self.w: dict = {}
        self.g2: dict = {}

    def score(self, feats: dict) -> float:
        w = self.w
        return sum(w.get(f, 0.0) * v for f, v in feats.items())

    def step(self, feats: dict, grad: float) -> None:
        """One gradient step, where grad = dLoss/dScore for this feature vector."""
        for f, v in feats.items():
            w = self.w.get(f, 0.0)
            g = grad * v + self.l2 * w
            acc = self.decay * self.g2.get(f, 0.0) + g * g
            self.g2[f] = acc
            self.w[f] = w - self.lr * g / math.sqrt(1.0 + acc)

    def reasons(self, feats: dict, top: int = 4):
        """The features pushing this score hardest, as (feature, contribution)."""
        parts = [(f, self.w.get(f, 0.0) * v) for f, v in feats.items()]
        parts = [p for p in parts if abs(p[1]) > 1e-3]
        return sorted(parts, key=lambda p: -abs(p[1]))[:top]


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
