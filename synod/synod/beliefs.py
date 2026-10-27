"""The small Bayesian building blocks every node is made of.

* ``Competence``   - "how often am I (or a peer) right in situations like this?"
* ``ClaimCalibrator`` - "when that peer says 90%, how often is it actually right?"
* ``DriftMonitor`` - "am I suddenly worse than I think I am?"
"""
from __future__ import annotations

import math


class Competence:
    """Hierarchical Beta-Bernoulli belief P(success | key).

    Keys are tuples. Each prefix of a key is its own cell, and a cell's prior is
    its parent's posterior mean, so sparse situations borrow strength from
    broader ones and specialise as evidence arrives. Counts decay on update so
    beliefs track a changing world.
    """

    def __init__(self, prior_mean: float = 0.5, strength: float = 4.0, decay: float = 0.995):
        self.prior_mean = prior_mean
        self.strength = strength
        self.decay = decay
        self._c: dict = {}

    @staticmethod
    def _prefixes(key):
        return [key[:i] for i in range(len(key) + 1)]

    def posterior(self, key):
        m = self.prior_mean
        a_eff = b_eff = 1.0
        for k in self._prefixes(key):
            a, b = self._c.get(k, (0.0, 0.0))
            a_eff = a + self.strength * m
            b_eff = b + self.strength * (1.0 - m)
            m = a_eff / (a_eff + b_eff)
        return a_eff, b_eff

    def mean(self, key) -> float:
        a, b = self.posterior(key)
        return a / (a + b)

    def sample(self, key, rng) -> float:
        a, b = self.posterior(key)
        return float(rng.beta(a, b))

    def count(self, key) -> float:
        a, b = self._c.get(key, (0.0, 0.0))
        return a + b

    def update(self, key, y: float, weight: float = 1.0) -> None:
        for k in self._prefixes(key):
            a, b = self._c.get(k, (0.0, 0.0))
            self._c[k] = (a * self.decay + weight * y, b * self.decay + weight * (1.0 - y))

    def humble(self, factor: float) -> None:
        """Shrink all evidence: keep the shape of beliefs, drop the certainty."""
        self._c = {k: (a * factor, b * factor) for k, (a, b) in self._c.items()}


CLAIM_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99, 1.0 + 1e-9)


def claim_bin(p: float) -> int:
    for i in range(len(CLAIM_EDGES) - 1):
        if p < CLAIM_EDGES[i + 1]:
            return i
    return len(CLAIM_EDGES) - 2


class ClaimCalibrator:
    """One node's model of how much to believe each peer's stated confidence.

    With no evidence a claim is taken at face value. As outcomes arrive, the
    observed hit-rate for that peer at that confidence level takes over. A
    well-calibrated peer is believed exactly; an overconfident or broken peer is
    discounted quickly. This is what "trust" means in Synod.
    """

    def __init__(self, strength: float = 4.0, decay: float = 0.9):
        self.strength = strength
        self.decay = decay
        self._c: dict = {}

    def adjust(self, peer: str, claim: float) -> float:
        a, b = self._c.get((peer, claim_bin(claim)), (0.0, 0.0))
        return (a + self.strength * claim) / (a + b + self.strength)

    def update(self, peer: str, claim: float, correct: bool, weight: float = 1.0) -> None:
        k = (peer, claim_bin(claim))
        a, b = self._c.get(k, (0.0, 0.0))
        y = 1.0 if correct else 0.0
        self._c[k] = (a * self.decay + weight * y, b * self.decay + weight * (1.0 - y))

    def forget(self, peer: str) -> None:
        self._c = {k: v for k, v in self._c.items() if k[0] != peer}

    def trust(self, peer: str) -> float:
        """Summary score in [0, 1]: 1 - usage-weighted calibration gap."""
        num = den = 0.0
        for (p, i), (a, b) in self._c.items():
            if p != peer or a + b < 1e-9:
                continue
            centre = 0.5 * (CLAIM_EDGES[i] + min(CLAIM_EDGES[i + 1], 1.0))
            num += (a + b) * abs(a / (a + b) - centre)
            den += a + b
        return 1.0 if den == 0 else max(0.0, 1.0 - num / den)


class DriftMonitor:
    """One-sided CUSUM on (claimed confidence - outcome).

    Fires when a node keeps doing worse than it believes it should. A calibrated
    node drifts towards zero; a silently broken one crosses the threshold fast.
    """

    def __init__(self, slack: float = 0.05, threshold: float = 3.0):
        self.slack = slack
        self.threshold = threshold
        self.s = 0.0

    def update(self, predicted: float, correct: bool) -> bool:
        self.s = max(0.0, self.s + (predicted - (1.0 if correct else 0.0)) - self.slack)
        return self.s > self.threshold

    def reset(self) -> None:
        self.s = 0.0


def erf_conf(tolerance: float, sd: float) -> float:
    """P(|N(0, sd^2)| <= tolerance)."""
    if sd <= 1e-12:
        return 1.0
    return math.erf(tolerance / (math.sqrt(2.0) * sd))


def conf_bucket(p: float) -> str:
    for edge, name in ((0.2, "c0"), (0.4, "c1"), (0.6, "c2"), (0.8, "c3"), (0.95, "c4")):
        if p < edge:
            return name
    return "c5"
