"""Base class for every council member, neural or symbolic.

A node is not a function the orchestrator calls. It carries its own beliefs and
makes its own decisions on behalf of the whole system:

* **self-restraint**  - it skips work it rarely helps with, and work the table
  already has covered;
* **honest bidding**  - it bids its calibrated (Thompson-sampled) chance of success;
* **seeking review**  - as lead, it buys peer review only when the value of the
  information beats its compute cost;
* **judging peers**   - it keeps its own calibration map of every peer's claims,
  tracks each reviewer's record, and asks a peer to audit itself when that
  peer keeps failing confidently;
* **self-diagnosis**  - it watches itself for drift and surprises, runs a
  regression self-test, repairs or quarantines itself, and earns its way back
  on probation;
* **clean-up**        - when a peer admits it was broken, it retracts what it
  recently learned from that peer.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .beliefs import ClaimCalibrator, Competence, DriftMonitor
from .perception import signature
from .protocol import NEURAL, Bid, Proposal, Record, TaskView, Verdict


@dataclass
class Decline:
    node: str
    reason: str
    spent: float = 0.0


class Node:
    kind = NEURAL
    solves = True
    reviews = True

    shadow_rate = 0.25  # how often to quietly re-check myself on labeled tasks I lost
    probation_trials = 12
    retest_every = 30  # while quarantined
    regression_limit = 0.25  # self-test accuracy drop that confirms a fault
    surprise_at = 0.98  # a miss at this confidence is a 1-in-50 event: check yourself
    glance_value = 0.5  # rough value of producing one bid-worthy option
    curiosity = 0.05  # chance of looking anyway, so a node can find out it got better
    retract_window = 120  # how far back to retract lessons from a peer that broke
    # A learner decides for itself how sure the council must be before it will
    # learn from an unlabeled answer.
    learn_from_certified_at = 0.95

    def __init__(self, name: str, seed: int = 0):
        self.name = name
        self.rng = np.random.default_rng(seed)
        self.competence = Competence(prior_mean=0.5, strength=4.0, decay=0.995)
        self.usefulness = Competence(prior_mean=0.6, strength=4.0, decay=0.99)
        self.claims = ClaimCalibrator()
        # How informative is each peer as a reviewer, in each kind of situation?
        self.review_tnr = Competence(prior_mean=0.85, strength=6.0, decay=0.99)  # endorse | right
        self.review_tpr = Competence(prior_mean=0.6, strength=6.0, decay=0.99)  # reject | wrong
        self.review_answers = Competence(prior_mean=0.7, strength=4.0, decay=0.99)
        self.dissent = Competence(prior_mean=0.5, strength=4.0, decay=0.98)  # counter-proposal right?
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
        self.flags = {"healing": True, "review": True}
        self._scratch: dict = {}
        self._probation_left = 0
        self._since_retest = 0
        self._clock = 0

    # ------------------------------------------------------------------
    # Capabilities: subclasses implement what they are actually good at.
    # ------------------------------------------------------------------
    def glance(self, view: TaskView):
        """Cheap first look. Returns (evidence tuple, compute spent, expected cost to finish)."""
        raise NotImplementedError

    def solve(self, view: TaskView) -> Proposal:
        raise NotImplementedError

    def critique(self, view: TaskView, proposal: Proposal) -> Verdict:
        return Verdict(self.name, self.kind, None, 0.0, "cannot review")

    def review_cost(self, view: TaskView) -> float:
        return 1.0

    def learn(self, view: TaskView, value: float, source: str, record: Record) -> None:
        """Absorb a labeled or council-certified example."""

    def repair(self) -> bool:
        """Try to fix yourself after confirmed degradation. True if repaired."""
        return False

    def fault(self, kind: str) -> None:  # simulation hook
        raise NotImplementedError

    def clear_fault(self) -> None:  # simulation hook
        pass

    # ------------------------------------------------------------------
    # Shared autonomous behaviour.
    # ------------------------------------------------------------------
    def available(self) -> bool:
        return self.status == "healthy"

    def scratch(self, view: TaskView) -> dict:
        return self._scratch.setdefault(view.id, {})

    def bid(self, view: TaskView, objective, standing: Optional[tuple] = None):
        """standing = (node, belief) of the best bid already on the table."""
        if not self.solves or not self.available():
            return None
        sig = signature(view.history, view.tolerance)
        pressure = view.pressure

        # 0. Don't duplicate work: if the table is already covered well enough
        #    that even a perfect answer from me couldn't pay for my look, pass.
        if standing is not None:
            ceiling = objective.decision_value(1.0, pressure) - objective.decision_value(standing[1], pressure)
            if ceiling < objective.cost_weight * self.estimate_glance_cost():
                self.stats["declined_covered"] += 1
                return Decline(self.name, f"already covered by {standing[0]} (belief {standing[1]:.2f})", 0.0)

        # 1. Self-restraint: is it even worth looking? (learned per situation)
        # "usefulness" = how often looking here ends with something worth bidding.
        worth = self.usefulness.sample(sig, self.rng)
        est = self.estimate_glance_cost()
        # Under system stress, everyone pays more attention.
        curious = self.rng.random() < self.curiosity + 0.3 * pressure
        if not curious and worth * self.glance_value < objective.cost_weight * est:
            self.stats["declined_unseen"] += 1
            return Decline(self.name, f"rarely useful here (p_useful~{worth:.2f})", 0.0)

        # 2. Look, then bid honestly from the self-model for what was seen.
        evidence, spent, expected = self.glance(view)
        self.scratch(view)["glance_ev"] = evidence
        key = ("g",) + tuple(evidence) + sig
        p_sample = self.competence.sample(key, self.rng)
        p_mean = self.competence.mean(key)
        useful = objective.decision_value(p_sample, pressure) > objective.cost_weight * expected
        self.usefulness.update(sig, 1.0 if useful else 0.0)
        if not useful:
            self.stats["declined_seen"] += 1
            return Decline(self.name, f"looked, unlikely to help (p~{p_mean:.2f}, sampled {p_sample:.2f})", spent)
        self.stats["bids"] += 1
        return Bid(self.name, p_sample, expected, spent, tuple(evidence), p_mean)

    def estimate_glance_cost(self) -> float:
        return 1.0

    def wants_review(self, view: TaskView, sig, belief: float, options, objective) -> Optional[str]:
        """Pick the reviewer whose verdict is worth more than it costs, if any."""
        if not self.flags["review"]:
            return None
        pr_ = view.pressure
        base = objective.decision_value(belief, pr_)
        best, best_gain = None, 0.0
        for name, cost in options:
            key = (name,) + sig
            tnr = self.review_tnr.mean(key)
            tpr = self.review_tpr.mean(key)
            p_answer = self.review_answers.mean(key)
            p_endorse = belief * tnr + (1 - belief) * (1 - tpr)
            value = 0.0
            if p_endorse > 1e-9:
                value += p_endorse * objective.decision_value(belief * tnr / p_endorse, pr_)
            if 1 - p_endorse > 1e-9:
                value += (1 - p_endorse) * objective.decision_value(belief * (1 - tnr) / (1 - p_endorse), pr_)
            value = p_answer * value + (1 - p_answer) * base
            gain = value - base - objective.cost_weight * cost
            if gain > best_gain:
                best, best_gain = name, gain
        if best is None and options and self.rng.random() < 0.03:
            # Occasional curiosity keeps our model of reviewers from going stale.
            best = options[self.rng.integers(len(options))][0]
            self.stats["curious_reviews"] += 1
        return best

    def update_belief(self, belief: float, reviewer: str, endorses: bool, sig) -> float:
        key = (reviewer,) + sig
        tnr = self.review_tnr.mean(key)
        tpr = self.review_tpr.mean(key)
        if endorses:
            num, den = belief * tnr, belief * tnr + (1 - belief) * (1 - tpr)
        else:
            num, den = belief * (1 - tnr), belief * (1 - tnr) + (1 - belief) * tpr
        return num / den if den > 1e-12 else belief

    def dissent_belief(self, counter: Proposal, sig) -> float:
        """How often has this reviewer's counter-proposal (with this kind of
        evidence) turned out right when it overruled someone?"""
        return min(self.dissent.mean((counter.node,) + tuple(counter.evidence) + sig), 0.99)

    def peer_degraded(self, peer: str) -> None:
        """A peer admitted it was broken: stop trusting its old track record and
        retract anything recently learned from its certified answers."""
        self.claims.forget(peer)
        retracted = self.retract(peer, since=self._clock - self.retract_window)
        if retracted:
            self.journal.append((self._clock, f"retracted {retracted} lessons learned from {peer}"))

    def retract(self, author: str, since: int) -> int:
        """Forget lessons taught by ``author`` since ``since``. Returns how many."""
        return 0

    # ------------------------------------------------------------------
    # Settlement: everything a node learns comes through here.
    # ------------------------------------------------------------------
    def observe(self, record: Record) -> None:
        view = record.view
        self._clock += 1
        sig = signature(view.history, view.tolerance)
        if record.label is not None:
            label, tol = record.label, view.tolerance
            participants = record.participants()
            proposed = False
            for prop in record.all_proposals():
                ok = abs(prop.value - label) <= tol
                if prop.node == self.name:
                    proposed = True
                    self._settle_own(view, sig, prop, ok, label)
                else:
                    weight = 1.0 if self.name in participants else 0.5
                    self.claims.update(prop.node, prop.confidence, ok, weight)
                    self._watch_peer(prop, ok, record)
            for rv in record.reviews:
                ok = abs(rv.proposal.value - label) <= tol
                key = (rv.reviewer,) + sig
                answered = rv.verdict.endorses is not None
                self.review_answers.update(key, 1.0 if answered else 0.0)
                if rv.verdict.counter is not None:
                    c = rv.verdict.counter
                    hit = abs(c.value - label) <= tol
                    self.dissent.update((c.node,) + tuple(c.evidence) + sig, 1.0 if hit else 0.0)
                if answered:
                    if ok:
                        self.review_tnr.update(key, 1.0 if rv.verdict.endorses else 0.0)
                    else:
                        self.review_tpr.update(key, 0.0 if rv.verdict.endorses else 1.0)
            if self.solves and not proposed and self.status != "quarantined":
                glanced = "glance_ev" in self._scratch.get(view.id, {})
                rate = self.shadow_rate if glanced else self.curiosity
                if self.status == "probation" or self.rng.random() < rate:
                    self._shadow(view, sig, label)
            self.learn(view, label, "label", record)
        elif record.certified is not None and record.final_belief >= self.learn_from_certified_at:
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
        and being proven right against a peer raises it faster."""
        if ok or prop.confidence < 0.9:
            return
        told_you = any(r.reviewer == self.name and r.proposal is prop and r.verdict.endorses is False
                       for r in record.reviews)
        shocking = prop.confidence >= self.surprise_at
        level = self._concern.get(prop.node, 0.0) * 0.8 + (2.0 if told_you or shocking else 1.0)
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
        g_ev = self._scratch.get(view.id, {}).get("glance_ev")
        if g_ev is not None:
            self.competence.update(("g",) + tuple(g_ev) + sig, y)
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
        """Quietly re-check yourself on a labeled task you did not answer."""
        sc = self.scratch(view)
        if "glance_ev" not in sc:
            ev, spent, _ = self.glance(view)
            sc["glance_ev"] = ev
            self.maintenance_cost += spent
        prop = self.solve(view)
        self.maintenance_cost += prop.cost
        self.stats["shadow"] += 1
        ok = abs(prop.value - label) <= view.tolerance
        self._settle_own(view, sig, prop, ok, label)
        # Would bidding have been worth it? Lets a sidelined node earn its way back.
        self.usefulness.update(sig, 1.0 if prop.confidence > 0.5 else 0.0)

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
            ev, spent, _ = self.glance(view)
            self.scratch(view)["glance_ev"] = ev
            prop = self.solve(view)
            self.maintenance_cost += spent + prop.cost
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
