"""Critic: a symbolic reviewer built from soft, learned constraints.

Each constraint is a piece of common-sense structure ("a steadily rising
sequence keeps rising", "constant growth ratios persist"). None is treated as
law: the critic learns, per situation, how often reality actually respects each
one, and only vetoes an answer on constraints that have earned it. Constraints
that turn out to be folklore in some situation quietly stop being used there.
"""
from __future__ import annotations

import numpy as np

from ..beliefs import Competence
from ..node import Node
from ..protocol import SYMBOLIC, Verdict


def _d(h):
    return np.diff(np.asarray(h, dtype=float))


class Constraint:
    name = "constraint"

    def applies(self, h) -> bool:
        raise NotImplementedError

    def holds(self, h, v, tol) -> bool:
        raise NotImplementedError


class Monotone(Constraint):
    name = "keeps-direction"

    def applies(self, h):
        d = _d(h)[-5:]
        return bool(np.all(d > 0) or np.all(d < 0))

    def holds(self, h, v, tol):
        return (v - h[-1]) * np.sign(h[-1] - h[-2]) >= -tol


class Convexity(Constraint):
    name = "keeps-curvature"

    def applies(self, h):
        d2 = np.diff(_d(h))[-4:]
        return bool(np.all(d2 > 0) or np.all(d2 < 0))

    def holds(self, h, v, tol):
        d2 = np.diff(_d(h))
        return (v - 2 * h[-1] + h[-2]) * np.sign(d2[-1]) >= -tol


class StepBound(Constraint):
    name = "bounded-step"

    def applies(self, h):
        return True

    def holds(self, h, v, tol):
        return abs(v - h[-1]) <= 3.0 * float(np.max(np.abs(_d(h)))) + tol


class ConstantRatio(Constraint):
    name = "constant-growth-ratio"

    def applies(self, h):
        d = _d(h)[-5:]
        if np.any(np.abs(d) < 1e-9):
            return False
        r = d[1:] / d[:-1]
        return bool(np.std(r) <= 0.02 * max(1.0, abs(np.mean(r))))

    def holds(self, h, v, tol):
        d = _d(h)[-5:]
        r = float(np.mean(d[1:] / d[:-1]))
        guess = h[-1] + r * d[-1]
        return abs(v - guess) <= tol + 1e-6 * abs(r * d[-1])


class Envelope(Constraint):
    name = "stays-in-envelope"

    def applies(self, h):
        d = _d(h)
        return int(np.sum(np.sign(d[1:]) != np.sign(d[:-1]))) >= 3

    def holds(self, h, v, tol):
        lo, hi = float(np.min(h)), float(np.max(h))
        pad = 0.25 * (hi - lo) + tol
        return lo - pad <= v <= hi + pad


class CriticNode(Node):
    kind = SYMBOLIC
    solves = False
    trusted_at = 0.9

    def __init__(self, name: str = "critic", seed: int = 0, check_cost: float = 0.06):
        super().__init__(name, seed)
        self.constraints = [Monotone(), Convexity(), StepBound(), ConstantRatio(), Envelope()]
        # P(reality satisfies constraint | it applies, situation): learned, not assumed.
        self.reliability = Competence(prior_mean=0.8, strength=4.0, decay=0.995)
        self.check_cost = check_cost

    def critique(self, view, proposal) -> Verdict:
        """Report every applicable constraint: kept or broken, and whether its
        track record here makes it one I'd stand behind."""
        h, v, tol = view.history, proposal.value, view.tolerance
        sig = view.context
        signals, broken_trusted, any_trusted = [], [], False
        for c in self.constraints:
            if not c.applies(h):
                continue
            rel = self.reliability.mean((c.name,) + sig)
            ok = c.holds(h, v, tol)
            trust = "trusted" if rel >= self.trusted_at else "weak"
            any_trusted |= trust == "trusted"
            signals.append(f"{c.name}:{'kept' if ok else 'broken'}:{trust}")
            if trust == "trusted" and not ok:
                broken_trusted.append(c.name)
        cost = 0.1 + self.check_cost * len(self.constraints)
        endorses = None if not any_trusted else not broken_trusted
        why = ", ".join(x.replace(":", " ", 1) for x in signals) or "no constraint applies"
        return Verdict(self.name, self.kind, endorses, cost, why, evidence=tuple(signals))

    def learn(self, view, value, source, record) -> None:
        if source != "label":
            return
        h, tol = view.history, view.tolerance
        sig = view.context
        for c in self.constraints:
            if c.applies(h):
                self.reliability.update((c.name,) + sig, 1.0 if c.holds(h, value, tol) else 0.0)

    def describe_knowledge(self):
        rows = []
        for c in self.constraints:
            a, b = self.reliability._c.get((c.name,), (0.0, 0.0))
            if a + b > 0:
                rows.append((c.name, a / (a + b), a + b))
        return rows
