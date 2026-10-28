"""Base class for every council member, neural or symbolic.

A member is an expert with self-knowledge. It does not decide who answers; the
council's learned router and judge do that. What a member owns:

* **its craft**       - ``solve`` (for solvers) or ``critique`` (for reviewers);
* **self-knowledge**  - a calibrated model of how often it is right in situations
  like this one, reported as the confidence and evidence on every proposal;
* **its own learning** - ``learn`` from ground truth and from answers the
  council is confident enough to teach from;
* **its own health**  - it watches itself for drift and surprises, runs a
  regression self-test, repairs or quarantines itself, and earns its way back
  on probation; it can ask a peer to check itself, and it retracts lessons
  learned from a peer that admits it was broken.
"""
from __future__ import annotations

from collections import Counter, deque
from typing import Optional

import numpy as np

from .beliefs import Competence, DriftMonitor
from .protocol import NEURAL, Proposal, Record, TaskView, Verdict


class Node:
    kind = NEURAL
    solves = True  # False for pure reviewers

    probation_trials = 12
    retest_every = 30  # while quarantined
    regression_limit = 0.25  # self-test accuracy drop that confirms a fault
    surprise_at = 0.98  # a miss at this confidence is a 1-in-50 event: check yourself
    retract_window = 120  # how far back to retract lessons from a peer that broke

    def __init__(self, name: str, seed: int = 0):
        self.name = name
        self.rng = np.random.default_rng(seed)
        self.competence = Competence(prior_mean=0.5, strength=4.0, decay=0.995)
        self.drift = DriftMonitor()
        self.status = "healthy"  # healthy | probation | quarantined
        self.archive: deque = deque(maxlen=80)
        self.stats: Counter = Counter()
        self.maintenance_cost = 0.0
        self.journal: list = []  # notable autonomous decisions
        self.announcement: Optional[str] = None
        self.complaints: set = set()  # peers I want audited
        self._concern: dict = {}
        self._last_audit = -10**9
        self.flags = {"healing": True}
        self._scratch: dict = {}
        self._probation_left = 0
        self._since_retest = 0
        self._clock = 0

    # ------------------------------------------------------------------
    # Capabilities: subclasses implement what they are actually good at.
    # ------------------------------------------------------------------
    def solve(self, view: TaskView) -> Proposal:
        raise NotImplementedError

    def critique(self, view: TaskView, proposal: Proposal) -> Verdict:
        """Reviewers report signals about a candidate answer."""
        return Verdict(self.name, self.kind, None, 0.0, "cannot review")

    def learn(self, view: TaskView, value: float, source: str, record: Record) -> None:
        """Absorb an example. source is "label" (ground truth that arrived on its
        own), "asked" (ground truth the council asked for: use it as knowledge,
        not to calibrate anything) or "certified" (an answer the council was
        confident enough to teach from)."""

    def explain(self, record: Record):
        """Optionally share an explanation of a settled task with the others
        (e.g. the program that produces the label). Posted to record.notes."""
        return None

    def repair(self) -> bool:
        """Try to fix yourself after confirmed degradation. True if repaired."""
        return False

    def retract(self, author: str, since: int) -> int:
        """Forget lessons taught by ``author`` since ``since``. Returns how many."""
        return 0

    def fault(self, kind: str) -> None:  # simulation hook
        raise NotImplementedError

    def clear_fault(self) -> None:  # simulation hook
        pass

    # ------------------------------------------------------------------
    def available(self) -> bool:
        return self.status == "healthy"

    def scratch(self, view: TaskView) -> dict:
        return self._scratch.setdefault(view.id, {})

    def peer_degraded(self, peer: str) -> None:
        """A peer admitted it was broken: retract anything recently learned
        from its answers."""
        retracted = self.retract(peer, since=self._clock - self.retract_window)
        if retracted:
            self.journal.append((self._clock, f"retracted {retracted} lessons learned from {peer}"))

    # ------------------------------------------------------------------
    # Settlement: everything a node learns comes through here.
    # ------------------------------------------------------------------
    def observe(self, record: Record) -> None:
        view = record.view
        self._clock += 1
        sig = view.context
        if record.label is not None and record.label_source == "asked":
            # A label we asked for: knowledge, but never calibration evidence.
            self.learn(view, record.label, "asked", record)
        elif record.label is not None:
            label, tol = record.label, view.tolerance
            proposed = False
            for prop in record.all_proposals():
                ok = abs(prop.value - label) <= tol
                if prop.node == self.name:
                    proposed = True
                    self._settle_own(view, sig, prop, ok, label)
                else:
                    self._watch_peer(prop, ok, record)
            if self.solves and self.status == "probation" and not proposed:
                self._shadow(view, sig, label)
            self.learn(view, label, "label", record)
        elif record.certified is not None:
            self.learn(view, record.certified, "certified", record)

        if self.status == "quarantined":
            self._since_retest += 1
            if self._since_retest >= self.retest_every:
                self._since_retest = 0
                regression = self.self_test()
                if regression is not None and regression < 0.05:
                    self.status = "probation"
                    self._probation_left = self.probation_trials
                    self.journal.append((self._clock, f"self-test passed (accuracy drop {regression:.0%}): leaving quarantine on probation"))
        self._scratch.pop(view.id, None)

    def _watch_peer(self, prop: Proposal, ok: bool, record: Record) -> None:
        """Peers are responsible for each other: confident failures raise concern,
        and having flagged the answer in review raises it faster."""
        if ok or prop.confidence < 0.9:
            return
        flagged = any(r.reviewer == self.name and r.proposal is prop and r.verdict.endorses is False
                      for r in record.reviews)
        shocking = prop.confidence >= self.surprise_at
        level = self._concern.get(prop.node, 0.0) * 0.8 + (2.0 if flagged or shocking else 1.0)
        self._concern[prop.node] = level
        if level >= 1.8:
            self.complaints.add(prop.node)
            self._concern[prop.node] = 0.0

    def audit(self, requested_by: str) -> None:
        """A peer asked me to check myself."""
        if self.status != "healthy" or not self.flags["healing"] or self._clock - self._last_audit < 15:
            return
        self.stats["audits"] += 1
        self._diagnose(trigger=f"audit requested by {requested_by}")

    def _settle_own(self, view, sig, prop: Proposal, ok: bool, label: float) -> None:
        y = 1.0 if ok else 0.0
        self.competence.update(("ctx",) + sig, y)
        self.competence.update(("p",) + tuple(prop.evidence) + sig, y)
        self.archive.append((view, label, ok))
        self.stats["settled"] += 1
        self.stats["settled_ok"] += int(ok)
        if self.status == "probation":
            self._probation_left -= 1
            if self._probation_left <= 0:
                self.status = "healthy"
                self.drift.reset()
                self.journal.append((self._clock, "probation complete: back in service"))
        elif self.flags["healing"]:
            drifting = self.drift.update(prop.confidence, ok)
            surprised = not ok and prop.confidence >= self.surprise_at
            if surprised and self._clock - self._last_audit >= 15:
                self._diagnose(trigger=f"surprised by a miss at {prop.confidence:.0%} confidence")
            elif drifting:
                self._diagnose()

    def _shadow(self, view, sig, label) -> None:
        """On probation: quietly re-check yourself on labeled tasks."""
        prop = self.solve(view)
        self.maintenance_cost += prop.cost
        self.stats["shadow"] += 1
        self._settle_own(view, sig, prop, abs(prop.value - label) <= view.tolerance, label)

    def self_test(self, n: int = 40) -> Optional[float]:
        """Regression test: re-solve recent archived cases and compare with how
        well I did on them at the time. Returns the accuracy drop (0 = fine)."""
        cases = list(self.archive)[-n:]
        if len(cases) < 10:
            return None
        then = sum(ok for _, _, ok in cases) / len(cases)
        hits = 0
        for view, label, _ in cases:
            self._scratch.pop(view.id, None)
            prop = self.solve(view)
            self.maintenance_cost += prop.cost
            hits += int(abs(prop.value - label) <= view.tolerance)
            self._scratch.pop(view.id, None)
        return max(0.0, then - hits / len(cases))

    def _diagnose(self, trigger: str = "drift alarm") -> None:
        self.stats["alarms"] += 1
        self._last_audit = self._clock
        self.drift.reset()
        regression = self.self_test()
        if regression is None or regression < self.regression_limit:
            self.journal.append((self._clock, f"{trigger}, but self-test passed: false alarm"))
            return
        self.stats["confirmed_faults"] += 1
        self.competence.humble(0.15)
        self.announcement = "degraded"
        if self.repair():
            self.status = "probation"
            self._probation_left = self.probation_trials
            self.journal.append((self._clock, f"{trigger} -> self-test failed (accuracy down {regression:.0%}): repaired itself, now on probation"))
        else:
            self.status = "quarantined"
            self._since_retest = 0
            self.journal.append((self._clock, f"{trigger} -> self-test failed (accuracy down {regression:.0%}): cannot self-repair, quarantined itself"))
