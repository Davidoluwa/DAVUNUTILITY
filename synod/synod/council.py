"""The council: a learned router and a learned judge over neural and symbolic experts.

Like a mixture-of-experts layer, nothing about who handles what is written by
hand. Two small models are trained during training, from labeled outcomes:

* the **router** predicts, from the task's features, how likely each solver is
  to be right here. Solvers are consulted most-promising first, and the next
  one only if its expected contribution beats its compute cost:
  P(all consulted so far are wrong) x P(it is right) x (reward + penalty)
  >= cost weight x its typical compute. Reviewers are routed the same way: the
  router learns the value of each reviewer's opinion (by replaying the judge's
  decision with and without it on exploration tasks) and consults it only when
  that value beats its cost. On a fraction of tasks it consults everyone, so it
  keeps learning from full information;

* the **judge** is a gating network over the candidate answers plus a
  "none of these" option. For each candidate it reads who proposed it, that
  member's self-reported evidence and confidence, the task's features, who
  agrees or disagrees with it, and what the reviewers said about it. Its
  softmax weights are pooled across members that agree, giving a probability
  for each answer. It's trained to maximise the probability of the right
  answer (or of "none" when nobody had it).

The council delivers the most probable answer if it clears the bar set by the
objective (+1 right, -1 wrong, 0 abstain, so 0.5), and otherwise abstains.
Answers it believes strongly enough become teaching signal for the members.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .learner import SparseLogLinear, sigmoid, softmax
from .objective import Objective
from .protocol import Decline, Record, Review, Task


@dataclass
class CouncilConfig:
    task_features: bool = True  # judge and router see the task's features (input-dependent gating)
    crosses: bool = True  # judge features crossing member x evidence x task feature
    verifiers: bool = True  # reviewers report signals on candidates
    exchange: bool = True  # confident answers become teaching signal
    healing: bool = True  # members act on their own drift alarms
    learn: bool = True  # train router and judge on labeled outcomes (off = frozen)
    explore: float = 0.1  # chance of consulting everyone, so the router keeps learning
    teach_at: float = 0.9  # judge probability needed to teach from an unlabeled answer
    lr: float = 0.3
    help_budget: int = 0  # how many times the council may ask a teacher for an answer


def _logit(p: float) -> float:
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


class Council:
    def __init__(self, nodes, objective: Objective | None = None, config: CouncilConfig | None = None,
                 seed: int = 0):
        self.nodes = list(nodes)
        self.by_name = {n.name: n for n in self.nodes}
        self.objective = objective or Objective()
        self.config = config or CouncilConfig()
        self.rng = np.random.default_rng(seed + 7)
        self.router = SparseLogLinear(lr=self.config.lr)
        self.judge = SparseLogLinear(lr=self.config.lr)
        self.review_value = SparseLogLinear(lr=0.1)  # learned utility gain of each reviewer's opinion
        for n in self.nodes:
            n.flags = {"healing": self.config.healing}
        self.teacher = None  # callable(task) -> answer, consulted only within help_budget
        self.help_used = 0
        self.asked: list = []
        self.typical_cost: dict = {}  # running average compute per solver

    # -- features --------------------------------------------------------
    def _task_feats(self, view):
        if not self.config.task_features:
            return ()
        return tuple(view.features) or tuple(f"ctx:{c}" for c in view.context)

    def route_features(self, node, view) -> dict:
        f = {f"r|{node.name}": 1.0}
        for t in self._task_feats(view):
            f[f"r|{node.name}|{t}"] = 1.0
        return f

    def route_prob(self, node, view) -> float:
        return sigmoid(self.router.score(self.route_features(node, view)))


    def review_features(self, node, view, props, groups, unsure: float = 0.0) -> dict:
        """What the router knows before asking a reviewer, including how unsure
        the judge already is (the value of a second opinion depends on it)."""
        f = {f"rv|{node.name}": 1.0, f"rv|{node.name}|nc|{min(len(groups), 4)}": 1.0,
             f"rv|{node.name}|unsure|{min(int(unsure * 10), 5)}": 1.0}
        for t in self._task_feats(view):
            f[f"rv|{node.name}|{t}"] = 1.0
        for p in props:
            f[f"rv|{node.name}|has|{p.node}|{'/'.join(str(e) for e in p.evidence[:2])}"] = 1.0
        return f

    @staticmethod
    def clusters(props, tol):
        """Group candidate answers that agree (within tolerance)."""
        order = sorted(range(len(props)), key=lambda i: props[i].value)
        groups, cur = [], []
        for i in order:
            if cur and abs(props[i].value - props[cur[-1]].value) > tol:
                groups.append(cur)
                cur = []
            cur.append(i)
        if cur:
            groups.append(cur)
        return groups

    def candidate_features(self, view, props, groups, verdicts):
        """One feature vector per candidate, plus one for "none of these"."""
        tf = self._task_feats(view)
        where = {i: g for g, members in enumerate(groups) for i in members}
        n_groups = min(len(groups), 4)
        out = []
        for i, p in enumerate(props):
            n = p.node
            f = {f"b|{n}": 1.0, f"cl|{n}": _logit(p.confidence) / 4.0,
                 f"cb|{n}|{int(min(p.confidence, 0.999) * 10)}": 1.0, f"nc|{n}|{n_groups}": 1.0}
            ev = [str(e) for e in p.evidence]
            for k in range(1, len(ev) + 1):
                f[f"e|{n}|{'/'.join(ev[:k])}"] = 1.0
            head = "/".join(ev[:2])
            for t in tf:
                f[f"x|{n}|{t}"] = 1.0
                if self.config.crosses:  # member x its evidence x the task
                    f[f"ex|{n}|{head}|{t}"] = 1.0
            mates = 0
            for j, q in enumerate(props):
                if j == i:
                    continue
                rel = "with" if where[j] == where[i] else "vs"
                mates += rel == "with"
                f[f"{rel}|{n}|{q.node}"] = 1.0
                f[f"{rel}|{n}|{q.node}|{'/'.join(str(e) for e in q.evidence[:2])}"] = 1.0
            f[f"ag|{n}|{mates}"] = 1.0
            for v in verdicts.get(where[i], ()):
                tag = {None: "abstain", True: "endorse", False: "reject"}[v.endorses]
                f[f"v|{n}|{v.node}|{tag}"] = 1.0
                for tok in v.evidence:
                    f[f"v|{n}|{v.node}|{tok}"] = 1.0
            out.append(f)
        none = {"null": 1.0, f"nc|null|{n_groups}": 1.0}
        for t in tf:
            none[f"x|null|{t}"] = 1.0
        for p in props:
            none[f"has|null|{p.node}|{'/'.join(str(e) for e in p.evidence[:2])}"] = 1.0
        return out, none

    # -- one task ----------------------------------------------------------
    def handle(self, task: Task) -> Record:
        cfg, obj = self.config, self.objective
        view = task.view(0.0)
        rec = Record(view)

        # 1. Route: most promising first; the next only if it's worth its compute.
        dense = cfg.learn and self.rng.random() < cfg.explore
        props, routed = [], {}
        ranked = sorted(((self.route_prob(n, view), n) for n in self.nodes if n.solves and n.available()),
                        key=lambda t: (-t[0], t[1].name))
        all_wrong = 1.0
        for pi, node in ranked:
            routed[node.name] = pi
            gain = all_wrong * pi * (obj.reward + obj.penalty)
            price = obj.cost_weight * self.typical_cost.get(node.name, 1.0)
            if dense or gain >= price:
                p = node.solve(view)
                rec.cost += p.cost
                c = self.typical_cost.get(node.name, p.cost)
                self.typical_cost[node.name] = 0.9 * c + 0.1 * p.cost
                rec.proposals.append(p)
                all_wrong *= 1.0 - pi
                if p.value == p.value:  # NaN means "nothing to offer"
                    props.append(p)
            else:
                rec.declined.append(Decline(node.name, f"router: {pi:.0%} chance of being right here; "
                                                       f"a second opinion isn't worth its compute", 0.0))

        # 2. Reviewers whose opinion is worth its cost report signals on each candidate.
        groups = self.clusters(props, view.tolerance)
        verdicts, asked_reviewers = {}, []
        unsure = self._unsure(view, props, groups)
        if cfg.verifiers and groups:
            for node in self.nodes:
                if node.solves or not node.available():
                    continue
                worth = self.review_value.score(self.review_features(node, view, props, groups, unsure))
                price = obj.cost_weight * self.typical_cost.get(node.name, 0.3) * len(groups)
                if not (dense or worth >= price):
                    rec.declined.append(Decline(node.name, f"router: its opinion here is worth {worth:+.3f}, "
                                                           f"less than its compute ({price:.3f})", 0.0))
                    continue
                asked_reviewers.append(node.name)
                spent = 0.0
                for g, members in enumerate(groups):
                    rep = props[members[0]]
                    v = node.critique(view, rep)
                    spent += v.cost
                    verdicts.setdefault(g, []).append(v)
                    rec.reviews.append(Review(node.name, rep, v, v.cost, 0.0, 0.0))
                rec.cost += spent
                c = self.typical_cost.get(node.name, spent / len(groups))
                self.typical_cost[node.name] = 0.9 * c + 0.1 * spent / len(groups)

        # 3. Judge: a gate over candidates and "none of these".
        feats, none = self.candidate_features(view, props, groups, verdicts)
        gates = softmax([self.judge.score(none)] + [self.judge.score(f) for f in feats])
        g0, gp = gates[0], gates[1:]
        mass = [sum(gp[i] for i in members) for members in groups]
        threshold = obj.deliver_threshold(0.0)
        if groups:
            best = int(np.argmax(mass))
            lead = max(groups[best], key=lambda i: gp[i])
            group_of = {id(props[m[0]]): mass[g] for g, m in enumerate(groups)}
            for r in rec.reviews:
                r.belief_before = r.belief_after = group_of.get(id(r.proposal), 0.0)
            if mass[best] >= threshold:
                rec.final, rec.final_belief = props[lead], mass[best]
        rec.notes["council"] = {
            "routed": routed, "none": g0, "threshold": threshold,
            "candidates": [{"node": p.node, "value": p.value, "gate": gp[i],
                            "reasons": self.judge.reasons(feats[i])} for i, p in enumerate(props)],
            "groups": [{"value": props[m[0]].value, "p": mass[g], "nodes": [props[i].node for i in m]}
                       for g, m in enumerate(groups)],
            "none_reasons": self.judge.reasons(none),
        }

        # 4. Outcome: labels train the router and judge; confident answers teach.
        if task.labeled:
            rec.label, rec.label_source = task.target, "passive"
        elif self._wants_help(rec, groups):
            rec.label, rec.label_source = self.teacher(task), "asked"
            self.help_used += 1
            self.asked.append(task.id)
        elif cfg.exchange and rec.final is not None and rec.final_belief >= cfg.teach_at:
            rec.certified = rec.final.value
        # Only labels the council didn't pick train the router and judge (see
        # Record.label_source).
        if rec.label_source == "passive" and cfg.learn:
            if dense:
                self._train_review_value(view, props, groups, verdicts, asked_reviewers, rec.label, unsure)
            self._train(view, props, feats, none, gates, rec.label)
        self._settle(task, rec)
        return rec

    def _train(self, view, props, feats, none, gates, label):
        right = [i for i, p in enumerate(props) if abs(p.value - label) <= view.tolerance]
        target = [i + 1 for i in right] or [0]
        z = sum(gates[k] for k in target)
        for k, f in enumerate([none] + feats):
            # d(-log sum_{k in target} g_k) / d logit_k
            grad = gates[k] - (gates[k] / z if k in target else 0.0)
            self.judge.step(f, grad)
        for i, p in enumerate(props):
            node = self.by_name[p.node]
            pi = self.route_prob(node, view)
            self.router.step(self.route_features(node, view), pi - (1.0 if i in right else 0.0))

    def _decide(self, view, props, groups, verdicts, label):
        """Utility of the judge's decision given these reviewer signals."""
        feats, none = self.candidate_features(view, props, groups, verdicts)
        gates = softmax([self.judge.score(none)] + [self.judge.score(f) for f in feats])
        mass = [sum(gates[1 + i] for i in m) for m in groups]
        best = int(np.argmax(mass))
        if mass[best] < self.objective.deliver_threshold(0.0):
            return 0.0
        value = props[max(groups[best], key=lambda i: gates[1 + i])].value
        right = abs(value - label) <= view.tolerance
        return self.objective.reward if right else -self.objective.penalty

    def _unsure(self, view, props, groups) -> float:
        """How far the judge, without any reviewer, is from certainty (0 = sure)."""
        if not groups:
            return 1.0
        feats, none = self.candidate_features(view, props, groups, {})
        gates = softmax([self.judge.score(none)] + [self.judge.score(f) for f in feats])
        top = max(sum(gates[1 + i] for i in m) for m in groups)
        return min(top, 1.0 - top) * 2.0  # 1 at a coin flip, 0 when sure either way

    def _train_review_value(self, view, props, groups, verdicts, asked, label, unsure=0.0):
        """Counterfactual replay: how much did each reviewer's opinion change
        the outcome? That realised gain is what the router learns to predict."""
        with_all = self._decide(view, props, groups, verdicts, label)
        for name in asked:
            without = {g: [v for v in vs if v.node != name] for g, vs in verdicts.items()}
            gain = with_all - self._decide(view, props, groups, without, label)
            f = self.review_features(self.by_name[name], view, props, groups, unsure)
            self.review_value.step(f, self.review_value.score(f) - gain)

    def _wants_help(self, rec, groups) -> bool:
        """Ask only when we couldn't settle it ourselves: we abstained after
        trying, or the members genuinely disagree."""
        if self.teacher is None or self.help_used >= self.config.help_budget or not rec.proposals:
            return False
        return rec.final is None or len(groups) > 1

    def _settle(self, task: Task, rec: Record) -> None:
        for node in self.nodes:
            note = node.explain(rec)
            if note is not None:
                rec.notes[node.name] = note
        for node in self.nodes:
            node.observe(rec)
        accused = {}
        for node in self.nodes:
            for name in sorted(node.complaints):
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


class FixedPipeline:
    """Baseline orchestration: a hand-written gate picks one node, no deliberation.

    ``route`` maps a TaskView to a node name. Nodes still learn and self-heal,
    but there is no learned routing, no judge and no knowledge exchange.
    """

    def __init__(self, nodes, route, objective: Objective | None = None, healing: bool = True):
        self.nodes = list(nodes)
        self.by_name = {n.name: n for n in self.nodes}
        self.route = route
        self.objective = objective or Objective()
        for n in self.nodes:
            n.flags = {"healing": healing}

    def handle(self, task: Task) -> Record:
        view = task.view(0.0)
        rec = Record(view)
        node = self.by_name[self.route(view)]
        if node.status != "quarantined":
            prop = node.solve(view)
            rec.cost += prop.cost
            rec.proposals.append(prop)
            if prop.value == prop.value and prop.confidence >= self.objective.deliver_threshold(0.0):
                rec.final, rec.final_belief = prop, prop.confidence
        if task.labeled:
            rec.label, rec.label_source = task.target, "passive"
        for n in self.nodes:
            note = n.explain(rec)
            if note is not None:
                rec.notes[n.name] = note
        for n in self.nodes:
            n.observe(rec)
            n.announcement = None
        return rec
