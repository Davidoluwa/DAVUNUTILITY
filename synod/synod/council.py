"""The council: a thin protocol, not a router.

The council never decides *who is good at what*. It only runs the meeting:

1. announce the task and collect bids, cheapest lookers first, so later nodes
   can see the table and skip work that is already covered;
2. rank bids by their expected contribution to the shared objective, using the
   peers' trust-adjusted reading of each bid;
3. let the lead solve, and let the lead buy reviews it judges worth their cost;
4. weigh candidates (including reviewers' counter-proposals), deliver or abstain;
5. broadcast the full transcript so every node can update itself and its peers,
   then relay any audit requests and "I was broken" announcements.

Every judgement in that loop comes from a node's learned beliefs.

Two answers that cannot both be right are treated as evidence against each
other (at most one can be correct), which is how a confident node can still be
overruled by a peer with a better track record - or send the council looking
for a tie-breaker.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from .node import Decline
from .objective import Objective
from .protocol import Record, Review, Task


@dataclass
class CouncilConfig:
    reviews: bool = True  # leads may buy peer review
    trust: bool = True  # peers discount each other's claims by track record
    exchange: bool = True  # certified answers become teaching signal
    healing: bool = True  # nodes act on their own drift alarms
    max_proposals: int = 3
    max_reviews: int = 2
    certify_at: float = 0.8  # learners apply their own, stricter bars on top
    pressure_window: int = 40
    max_belief: float = 0.99  # nobody gets to be certain
    help_budget: int = 0  # how many times the council may ask a teacher for an answer


class Council:
    def __init__(self, nodes, objective: Objective | None = None, config: CouncilConfig | None = None):
        self.nodes = list(nodes)
        self.by_name = {n.name: n for n in self.nodes}
        self.objective = objective or Objective()
        self.config = config or CouncilConfig()
        for n in self.nodes:
            n.flags = {"healing": self.config.healing, "review": self.config.reviews}
        self._recent_errors: deque = deque(maxlen=self.config.pressure_window)
        self._normal_error = None  # long-run error rate: what "normal" looks like
        self.teacher = None  # callable(task) -> answer, consulted only within help_budget
        self.help_used = 0
        self.asked: list = []

    # -- shared signals -------------------------------------------------
    def pressure(self) -> float:
        """System stress: how much worse than *normal* have we been lately?"""
        if len(self._recent_errors) < 20 or self._normal_error is None:
            return 0.0
        err = float(np.mean(self._recent_errors))
        return float(np.clip((err - self._normal_error - 0.05) / 0.2, 0.0, 1.0))

    def belief_in(self, author: str, claim: float) -> float:
        """The council's reading of a claim: the median of every *other* node's
        calibration map of the author."""
        claim = min(claim, self.config.max_belief)
        if not self.config.trust:
            return claim
        readings = [n.claims.adjust(author, claim) for n in self.nodes if n.name != author]
        return min(float(np.median(readings)), self.config.max_belief) if readings else claim

    @staticmethod
    def reconcile(cands, tolerance):
        """Beliefs after accounting for conflicts.

        Candidates within 2x tolerance of each other could both be right, so they
        count as one answer (the most trusted speaks for it). Answers further
        apart are mutually exclusive, and each belief is already conditioned on
        the clash (a rejected lead was updated by Bayes; a counter-proposal is
        believed per its author's record as a dissenter). So they're kept as they
        are unless they add up to more than certainty, in which case they're
        rescaled: exclusive answers can't jointly be more than 100% likely."""
        clusters = []
        for c in cands:
            for cl in clusters:
                if abs(cl["value"] - c["prop"].value) <= 2 * tolerance:
                    cl["members"].append(c)
                    cl["p"] = max(cl["p"], c["belief"])
                    break
            else:
                clusters.append({"value": c["prop"].value, "p": c["belief"], "members": [c]})
        total = sum(cl["p"] for cl in clusters)
        scale = 1.0 / total if total > 1.0 else 1.0
        return {id(c): cl["p"] * scale for cl in clusters for c in cl["members"]}

    # -- one deliberation ------------------------------------------------
    def handle(self, task: Task) -> Record:
        obj = self.objective
        view = task.view(self.pressure())
        sig = view.context
        rec = Record(view)

        # Open outcry: cheapest lookers speak first, later ones see the table.
        standing = None
        for node in sorted(self.nodes, key=lambda n: n.estimate_glance_cost()):
            out = node.bid(view, obj, standing) if node.solves else None
            if out is None:
                continue
            rec.cost += out.spent
            if isinstance(out, Decline):
                rec.declined.append(out)
                continue
            rec.bids.append(out)
            reading = self.belief_in(out.node, out.p_mean)
            # Only offers that are (nearly) ready count as covering the table.
            if out.cost <= 1.0 and (standing is None or reading > standing[1]):
                standing = (out.node, reading)

        def merit(bid):
            # Read the bidder's calibrated estimate through the peers' trust, but
            # keep its own exploration margin (sample - mean) on top.
            p = float(np.clip(self.belief_in(bid.node, bid.p_mean) + bid.p_success - bid.p_mean, 0.0, 1.0))
            return obj.decision_value(p, view.pressure) - obj.cost_weight * bid.cost

        ranked = sorted(rec.bids, key=merit, reverse=True)
        threshold = obj.deliver_threshold(view.pressure)
        cands: list = []  # {"prop", "belief"}; beliefs before conflict reconciliation

        def best():
            if not cands:
                return None, 0.0
            post = self.reconcile(cands, view.tolerance)
            c = max(cands, key=lambda c: post[id(c)])
            return c, post[id(c)]

        for bid in ranked:
            if len(rec.proposals) >= self.config.max_proposals or merit(bid) <= 0:
                break
            if best()[1] >= threshold:
                break
            lead = self.by_name[bid.node]
            prop = lead.solve(view)
            rec.cost += prop.cost
            rec.proposals.append(prop)
            entry = {"prop": prop, "belief": self.belief_in(prop.node, prop.confidence)}
            cands.append(entry)
            self._review(lead, view, sig, entry, rec, cands)

        top, belief = best()
        if top is not None and belief >= threshold:
            rec.final, rec.final_belief = top["prop"], belief

        if task.labeled:
            rec.label = task.target
        elif self._wants_help(rec):
            # The answer (or abstention) above already stands; asking afterwards
            # is for learning, so the next question of this shape goes better.
            rec.label = self.teacher(task)
            self.help_used += 1
            self.asked.append(task.id)
        elif self.config.exchange and rec.final is not None and rec.final_belief >= self.config.certify_at:
            # Only teach from consensus: no rejection of the answer, and no rival
            # answer anywhere in the deliberation.
            rejected = any(r.proposal is rec.final and r.verdict.endorses is False for r in rec.reviews)
            contested = any(abs(p.value - rec.final.value) > 2 * view.tolerance for p in rec.all_proposals()
                            if p.value == p.value)
            if not rejected and not contested:
                rec.certified = rec.final.value

        self._settle(task, rec)
        return rec

    def _wants_help(self, rec) -> bool:
        """Ask only when we couldn't settle it ourselves: we abstained after
        trying, or our members genuinely disagree."""
        if self.teacher is None or self.help_used >= self.config.help_budget or not rec.proposals:
            return False
        tol = rec.view.tolerance
        values = [p.value for p in rec.all_proposals() if p.value == p.value]
        contested = any(abs(a - b) > 2 * tol for a in values for b in values)
        return rec.final is None or contested

    def _review(self, lead, view, sig, entry, rec, cands) -> None:
        prop = entry["prop"]
        used = {prop.node}
        for _ in range(self.config.max_reviews):
            options = [
                (n.name, n.review_cost(view))
                for n in self.nodes
                if n.reviews and n.available() and n.name not in used
            ]
            if not options:
                break
            before = self.reconcile(cands, view.tolerance)[id(entry)]
            choice = lead.wants_review(view, sig, before, options, self.objective)
            if choice is None:
                break
            used.add(choice)
            verdict = self.by_name[choice].critique(view, prop)
            rec.cost += verdict.cost
            if verdict.endorses is not None:
                entry["belief"] = lead.update_belief(entry["belief"], choice, verdict.endorses, sig, verdict.evidence)
            if verdict.counter is not None:
                # A rival answer, believed according to this reviewer's record as a dissenter.
                cands.append({"prop": verdict.counter, "belief": lead.dissent_belief(verdict.counter, sig)})
            after = self.reconcile(cands, view.tolerance)[id(entry)]
            rec.reviews.append(Review(choice, prop, verdict, verdict.cost, before, after))

    def _settle(self, task: Task, rec: Record) -> None:
        for node in self.nodes:
            note = node.explain(rec)
            if note is not None:
                rec.notes[node.name] = note
        for node in self.nodes:
            node.observe(rec)
        accused = {}
        for node in self.nodes:
            for name in node.complaints:
                accused.setdefault(name, node.name)
            node.complaints.clear()
        for name, by in accused.items():
            if name in self.by_name:
                self.by_name[name].audit(requested_by=by)
        for node in self.nodes:
            if node.announcement == "degraded":
                for peer in self.nodes:
                    if peer is not node:
                        peer.peer_degraded(node.name)
            node.announcement = None
        if task.labeled and rec.final is not None:
            err = 0.0 if task.is_correct(rec.final.value) else 1.0
            self._recent_errors.append(err)
            self._normal_error = err if self._normal_error is None else 0.99 * self._normal_error + 0.01 * err


class FixedPipeline:
    """Baseline orchestration: a hand-written gate picks one node, no deliberation.

    ``route`` maps a TaskView to a node name. Nodes still learn and self-heal,
    but there is no bidding, review, trust or knowledge exchange.
    """

    def __init__(self, nodes, route, objective: Objective | None = None, healing: bool = True):
        self.nodes = list(nodes)
        self.by_name = {n.name: n for n in self.nodes}
        self.route = route
        self.objective = objective or Objective()
        for n in self.nodes:
            n.flags = {"healing": healing, "review": False}

    def handle(self, task: Task) -> Record:
        view = task.view(0.0)
        rec = Record(view)
        node = self.by_name[self.route(view)]
        if node.status != "quarantined":
            prop = node.solve(view)
            rec.cost += prop.cost
            rec.proposals.append(prop)
            if prop.confidence >= self.objective.deliver_threshold(0.0):
                rec.final, rec.final_belief = prop, prop.confidence
        if task.labeled:
            rec.label = task.target
        for n in self.nodes:
            note = n.explain(rec)
            if note is not None:
                rec.notes[n.name] = note
        for n in self.nodes:
            n.observe(rec)
            n.announcement = None
        return rec
