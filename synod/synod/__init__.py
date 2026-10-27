"""Synod: a council of neural and symbolic nodes that run themselves.

No router decides who handles what. Each node keeps a learned model of its own
competence, a calibration map of every peer, and a stake in one shared
objective (reliable answers at low compute), and acts on those beliefs.
"""
from .council import Council, CouncilConfig, FixedPipeline
from .objective import Objective
from .protocol import NEURAL, SYMBOLIC, Bid, Proposal, Record, Task, TaskView, Verdict

__all__ = [
    "Council", "CouncilConfig", "FixedPipeline", "Objective",
    "NEURAL", "SYMBOLIC", "Bid", "Proposal", "Record", "Task", "TaskView", "Verdict",
]
