"""Message types exchanged on the council bus.

Nodes only ever see a ``TaskView``: the hidden family and target of a task stay
with the world/council so no node can cheat its way to a good self-image.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

NEURAL = "neural"
SYMBOLIC = "symbolic"


@dataclass(frozen=True)
class TaskView:
    """The public part of a task."""

    id: int
    history: Tuple[float, ...]
    tolerance: float
    # Shared "system stress" signal in [0, 1]. Rises when the whole system has
    # been making mistakes lately; every node folds it into its own decisions.
    pressure: float = 0.0


@dataclass(frozen=True)
class Task:
    id: int
    history: Tuple[float, ...]
    tolerance: float
    target: float
    family: str
    labeled: bool

    def view(self, pressure: float = 0.0) -> TaskView:
        return TaskView(self.id, self.history, self.tolerance, pressure)

    def is_correct(self, value: float) -> bool:
        return abs(value - self.target) <= self.tolerance


@dataclass
class Bid:
    node: str
    p_success: float  # node's (Thompson-sampled) belief it will be right
    cost: float  # expected extra compute to produce the answer
    spent: float  # compute already burnt forming the bid
    evidence: tuple = ()
    p_mean: float = 0.5  # the calibrated estimate behind the sample


@dataclass
class Proposal:
    node: str
    kind: str
    value: float
    confidence: float  # node's calibrated P(within tolerance)
    cost: float
    rationale: str
    evidence: tuple = ()


@dataclass
class Verdict:
    node: str
    kind: str
    endorses: Optional[bool]  # None = abstained ("I can't judge this")
    cost: float
    rationale: str
    counter: Optional[Proposal] = None


@dataclass
class Review:
    """A review request and what came back (verdict is None if the reviewer abstained)."""

    reviewer: str
    proposal: Proposal
    verdict: Optional[Verdict]
    cost: float
    belief_before: float
    belief_after: float


@dataclass
class Record:
    """Full transcript of one deliberation, broadcast to every node at settlement."""

    view: TaskView
    bids: list = field(default_factory=list)
    declined: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    final: Optional[Proposal] = None
    final_belief: float = 0.0
    cost: float = 0.0
    label: Optional[float] = None  # ground truth, only for labeled tasks
    certified: Optional[float] = None  # pseudo-label the council vouches for

    @property
    def delivered(self) -> bool:
        return self.final is not None

    def all_proposals(self):
        seen = list(self.proposals)
        for r in self.reviews:
            if r.verdict is not None and r.verdict.counter is not None:
                seen.append(r.verdict.counter)
        return seen

    def participants(self):
        names = {p.node for p in self.proposals}
        names.update(r.reviewer for r in self.reviews)
        return names
