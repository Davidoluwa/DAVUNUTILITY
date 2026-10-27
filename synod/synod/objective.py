"""The one objective every node serves: reliable answers at low compute cost."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Objective:
    reward: float = 1.0  # a correct delivered answer
    penalty: float = 1.0  # a wrong delivered answer (abstaining scores 0)
    cost_weight: float = 0.02  # utility lost per unit of compute

    def wrong_cost(self, pressure: float = 0.0) -> float:
        # Under system stress every node becomes more risk-averse.
        return self.penalty * (1.0 + pressure)

    def deliver_threshold(self, pressure: float = 0.0) -> float:
        w = self.wrong_cost(pressure)
        return w / (self.reward + w)

    def decision_value(self, p: float, pressure: float = 0.0) -> float:
        """Value of holding an answer believed correct with prob p (abstain if negative)."""
        return max(p * self.reward - (1.0 - p) * self.wrong_cost(pressure), 0.0)

    def score(self, delivered: bool, correct: bool, cost: float) -> float:
        gain = 0.0
        if delivered:
            gain = self.reward if correct else -self.penalty
        return gain - self.cost_weight * cost
