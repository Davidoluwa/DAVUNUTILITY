"""The room: a council of many experts that solves maths step by step.

A question is solved as a sequence of steps on a shared workspace. At every
step:

1. **Everyone volunteers.** Every expert reads the scene and the workspace and
   proposes the next step it believes in (or that the solution is finished),
   with a calibrated confidence and its reasons.
2. **Proposals pool.** Experts proposing the same step back the same
   candidate. Reviewers report signals on each candidate's result.
3. **The judge weighs them.** A learned gate over the candidates plus "none of
   these", reading who backs each candidate, how sure they are, what the
   reviewers said and where the solution stands.
4. **Several routes stay open.** The room keeps the most probable partial
   solutions alive (beam search). Routes that reach the same answer pool their
   probability, so two different methods agreeing makes the room surer.

The answer is delivered if its probability clears the objective's bar
(0.5), with the whole worked solution and the deliberation behind each step.

Some questions can't be answered: a number they need isn't given. "There
isn't enough information" is always on the table as an outcome of its own (a
claim about the question, unlike abstaining, which is "I'm not sure"), and
the judge learns when to back it like anything else.

Learning happens in the same room, from the same signals. When an answer is
revealed, the room looks for a worked solution that reaches it: its own, if
it was right; otherwise the route its own experts and judge find most likely
among those that reach it (so a short, plausible chain beats a long one that
happens to use every number). That solution is broadcast. Every expert learns its part from it, the judge learns
whom to trust at each step, and each expert's self-model learns how often its
proposals were the step the solution needed. Unlabeled questions the room is
sure of (>= 0.9) become worked examples too (members only).

**Cross-fitting.** The judge is a stacked combiner of its experts, and a
combiner trained on its members' in-sample predictions learns to over-trust
whichever members overfit (Wolpert's stacked generalisation). So, as stacking
prescribes, the room trains the combiner out of fold: two sparring benches each
learn half the wordings (split by wording), and a training question is
deliberated by the bench that has never seen its wording. The judge and every
expert's self-model learn from that, so they learn what each kind of expert is
worth on unfamiliar ground. A full bench learns everything, and answers.
"""
from __future__ import annotations

import copy
import math
import zlib
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

import numpy as np

from ..learner import SparseLogLinear, softmax
from ..objective import Objective
from ..protocol import NEURAL
from .experts import NeuralExpert, OperatorExpert, Scene
from .procedures import Library, replay_path, retell, rewrite, tree, uses
from .workspace import (ANSWER, ARITH, CANT, INSUFFICIENT, STOP, TERMINAL, UNKNOWABLE, Step, Workspace, canon,
                        program_to_steps, register, verdict_value)


@dataclass
class RoomConfig:
    beam: int = 3  # routes kept open while answering
    train_beam: int = 1  # while training (cheaper)
    max_steps: int = 5
    teach_at: float = 0.9  # probability needed to teach from an unlabeled answer
    specialize: bool = True  # neural pool trained as a mixture of experts
    learn: bool = True
    search_width: int = 6
    search_alternatives: int = 3  # bindings per operator considered while searching
    speak_at: float = 0.01  # an operator with less than this share of the operators' readiness stays quiet
    escalate: tuple = ((6, 3), (12, 3), (24, 4))  # verifiable problems: search wider while nothing passes the check
    think_harder: tuple = ()  # (beam, bindings per operator) to retry with, wider each time, while the room would abstain
    stop_habits: bool = False  # the judge reading the step number and previous operation on "answer" (habits that break on longer problems)
    judge_lr: float = 0.3
    dropout: float = 0.3  # judge trains with random experts left out, so it learns what each is worth alone
    sleep: bool = True  # every so often, replay a sample of past worked solutions
    invent: bool = True  # ... and try recurring sub-chains of them as new operations
    invent_from: int = 1500  # practice questions before the first sleep
    invent_every: int = 1000  # practice questions between sleeps
    trial_length: int = 500  # questions the room and its copy both meet before deciding
    warmup: int = 300  # past solutions replayed in each sleep


class Candidate:
    __slots__ = ("step", "value", "props", "reviews", "feats", "fam")

    def __init__(self, step, value):
        self.step, self.value, self.props, self.reviews, self.feats, self.fam = step, value, [], (), None, 0

    @property
    def token(self):
        return self.step.token


@dataclass
class Moment:
    """One step of deliberation: what was on the table and how it was weighed."""
    ws: Workspace
    cands: list
    gates: list  # [none, cand0, cand1, ...]


@dataclass
class Route:
    logp: float
    ws: Workspace
    trail: list = field(default_factory=list)  # [(Moment, chosen index)]

    @property
    def outcome(self):
        """What this route concludes: the last result, or that it can't be known."""
        if self.trail:
            m, k = self.trail[-1]
            if m.cands[k].step.op == INSUFFICIENT:
                return UNKNOWABLE
        return self.ws.answer


@dataclass
class Result:
    question: str
    answer: Optional[Fraction] = None
    probability: float = 0.0
    route: Optional[Route] = None  # the best route to the delivered (or best) answer
    answers: list = field(default_factory=list)  # [(value, probability, routes reaching it)]
    cost: float = 0.0
    label: Optional[float] = None
    reference: Optional[list] = None  # the worked solution the room learned from
    certified: bool = False
    threshold: float = 0.5
    surprise: float = 0.0  # -log P(worked solution) under the room before it learned it (nats)
    verified: bool = False  # the answer passed the problem's own check (verifiable domains)
    searched: bool = False  # it took a search, not just deliberation, to find it
    effort: int = 0  # the widest search it needed (0: deliberation was enough)

    @property
    def steps(self) -> list:
        return [] if self.route is None else [m.cands[k].step for m, k in self.route.trail]

    @property
    def insufficient(self) -> bool:
        return self.answer is UNKNOWABLE


verdict = verdict_value  # right / wrong / abstain for a numeric answer (each domain has its own, see Room.grade)


def _key(step) -> str:
    return step.token if step.op in TERMINAL else canon(step).token


def _logit(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


class Bench:
    """One full set of experts (a room has one, or two when cross-fitting)."""

    def __init__(self, experts, name: str = ""):
        self.name = name
        self.experts = list(experts)
        self.by_name = {e.name: e for e in self.experts}
        self.steppers = [e for e in self.experts if e.role == "step"]
        self.reviewers = [e for e in self.experts if e.role == "review"]
        self.neural = [e for e in self.steppers if isinstance(e, NeuralExpert)]
        self.operators = [e for e in self.steppers if isinstance(e, OperatorExpert)]

    def add(self, expert) -> None:
        """A new member (an operator for an invented procedure) joins the bench,
        just after the other operators."""
        k = max(self.experts.index(e) for e in self.operators) + 1 if self.operators else 0
        self.experts.insert(k, expert)
        self.by_name[expert.name] = expert
        self.steppers = [e for e in self.experts if e.role == "step"]
        self.reviewers = [e for e in self.experts if e.role == "review"]
        self.operators = [e for e in self.steppers if isinstance(e, OperatorExpert)]
        for n in self.neural:
            n.add_token(expert.op)
            n.binders[expert.op] = expert


class Room:
    def __init__(self, benches, objective: Objective | None = None, config: RoomConfig | None = None, seed=0,
                 domain=None):
        self.domain = domain or ARITH
        self.benches = list(benches)
        self.experts = [e for b in self.benches for e in b.experts]
        self.objective = objective or Objective()
        self.config = config or RoomConfig()
        self.judge = SparseLogLinear(lr=self.config.judge_lr)
        self.rng = np.random.default_rng(seed + 13)
        self.stats: dict = {"searched": 0, "found": 0, "own_solution": 0, "certified": 0, "told_insufficient": 0}
        # with cross-fitting: [sparring a, sparring b, full]; otherwise one bench does everything
        self.full = self.benches[-1]
        self.folds = self.benches[:-1] or [self.full]
        self.procedures: list = []  # operations this room invented and kept
        self.inventor = Inventor() if self.config.sleep else None
        self.seen = 0  # practice questions so far

    def __setstate__(self, state):
        self.__dict__.update(state)
        for proc in state.get("procedures", ()):
            register(proc)

    def fold(self, scene: Scene) -> int:
        """Which sparring bench learns this wording (split by wording, so the
        other one meets it as genuinely new)."""
        return zlib.crc32(" ".join(scene.skeleton).encode()) % len(self.folds)

    def outsider(self, scene: Scene) -> Bench:
        """The bench that has never learned this wording."""
        return self.folds[(self.fold(scene) + 1) % len(self.folds)]

    def learners(self, scene: Scene) -> list:
        return list(dict.fromkeys([self.folds[self.fold(scene)], self.full]))

    # -- one step of deliberation ----------------------------------------
    @staticmethod
    def familiar(scene: Scene, bench: Bench) -> int:
        """Has this bench seen this exact wording before? (Self-knowledge the
        judge reads, so it can trust experts differently on new ground.)"""
        m = bench.by_name.get("memory")
        return int(m is not None and scene.skeleton in m.book)

    def candidates(self, scene: Scene, ws: Workspace, bench: Bench, search: bool = False, allow_steps: bool = True):
        pool: dict = {}
        kinds = self.domain.answer_kinds
        fam = self.familiar(scene, bench)
        cost = 0.0
        spoken = []
        # Operators' readiness is read relative to each other (a softmax over
        # experts rather than independent votes): on unfamiliar ground the right
        # operator is often only mildly ready, but far more ready than the rest.
        # One with a negligible share stays quiet (the neural experts can still
        # call on it to bind); while searching for a worked solution, everyone speaks.
        ready = {e.name: e.readiness(scene, ws) if ws.bindings(e.op) else 0.0 for e in bench.operators}
        total = sum(ready.values())
        top = getattr(self, "_top", 1)
        quiet = 0.0 if search or top > 1 else self.config.speak_at * total
        for e in bench.steppers:
            if isinstance(e, OperatorExpert):
                props = [] if not allow_steps or ready[e.name] < quiet else \
                    e.propose(scene, ws, self.config.search_alternatives if search else top)
            else:
                props = e.propose(scene, ws)
            cost += e.cost
            spoken.append((e, props))
        for e, props in spoken:
            if isinstance(e, OperatorExpert):
                for p in props:
                    e.settle_share(p, total)
            for p in props:
                if p.step.op not in TERMINAL and not allow_steps:
                    continue
                if p.step.op == STOP and kinds is not None and (not ws.kinds or ws.kinds[-1] not in kinds):
                    continue  # not the kind of thing the question asks for
                key = _key(p.step)
                c = pool.get(key)
                if c is None:
                    c = pool[key] = Candidate(p.step if p.step.op in TERMINAL else canon(p.step), p.value)
                c.props.append(p)
        if not allow_steps and ws.steps and STOP not in pool and (kinds is None or ws.kinds[-1] in kinds):
            pool[STOP] = Candidate(ANSWER, ws.answer)
        if self.domain.missing_info and INSUFFICIENT not in pool:  # always an option, backed or not
            pool[INSUFFICIENT] = Candidate(CANT, UNKNOWABLE)
        cands = sorted(pool.values(), key=lambda c: c.token)
        for c in cands:
            sig = []
            for r in bench.reviewers:
                sig.extend(f"{r.name}:{s}" for s in r.review(scene, ws, c.step, c.value))
                cost += r.cost
            c.reviews = tuple(sig)
            c.fam = fam
            c.feats = self.features(scene, ws, c)
        return cands, cost

    def features(self, scene, ws, c) -> dict:
        t = min(len(ws.steps), 5)
        prev = ws.steps[-1].op if ws.steps else "none"
        open_now = [r for r in ws.unused if r[0] != "S"]
        f = {}
        if c.step.op == STOP:
            f.update({"stop": 1.0, f"stop|open:{min(len(open_now), 3)}": 1.0,
                      f"stop|last-used:{int(ws.last in ws.used)}": 1.0})
            if self.config.stop_habits:
                f.update({f"stop|t:{t}": 1.0, f"stop|prev:{prev}": 1.0})
        elif c.step.op == INSUFFICIENT:
            f.update({"cant": 1.0, f"cant|t:{t}": 1.0, f"cant|open:{min(len(open_now), 3)}": 1.0,
                      f"cant|facts:{scene.slots}": 1.0})
        else:
            fresh = sum(1 for a in c.step.args if a in ws.unused)
            left = len([r for r in open_now if r not in c.step.args])
            f.update({"step": 1.0, f"fresh|{fresh}/{len(c.step.args)}": 1.0, f"left|{min(left, 3)}": 1.0,
                      f"uses-last|{int(ws.last in c.step.args) if ws.last else 'none'}": 1.0})
        if self.domain.describes:  # what the result would look like (the domain's perception)
            if c.step.op == STOP and ws.steps:
                f.update({f"stop|last:{t}": 1.0 for t in self.domain.describe(ws, ws.fact(ws.last))})
            elif c.step.op not in TERMINAL and c.value is not None:
                w2 = ws.apply(c.step, c.value)
                f.update({f"res:{t}": 1.0 for t in self.domain.describe(w2, w2.fact(w2.last))})
                if c.value in ws.values or any(x.value == c.value for x in ws.facts.values()):
                    f["res:already-known"] = 1.0
        n = len(c.props)
        neural = sum(p.kind == NEURAL for p in c.props)
        f[f"n|{min(n, 6)}"] = 1.0
        f[f"nn|{min(neural, 4)}"] = 1.0
        f[f"ns|{min(n - neural, 4)}"] = 1.0
        logits = []
        fam = getattr(c, "fam", 0)
        f[f"fam:{fam}"] = 1.0
        for p in c.props:
            f[f"by|{p.expert}"] = 1.0
            f[f"by|{p.expert}|f{fam}"] = 1.0
            f[f"by|{p.expert}|c{min(int(p.confidence * 10), 9)}"] = 1.0
            f[f"by|{p.expert}|{'/'.join(p.evidence[:2])}"] = 1.0
            logits.append(_logit(p.confidence))
        if logits:
            f["conf:max"] = max(logits) / 4.0
            f["conf:mean"] = sum(logits) / len(logits) / 4.0
        for s in c.reviews:
            f[f"v|{s}"] = 1.0
        return f

    @staticmethod
    def none_features(ws) -> dict:
        return {"null": 1.0, f"null|t:{min(len(ws.steps), 5)}": 1.0}

    def gate(self, ws, cands) -> list:
        return softmax([self.judge.score(self.none_features(ws))] + [self.judge.score(c.feats) for c in cands])

    # -- deliberation ------------------------------------------------------
    def deliberate(self, scene: Scene, width: int, bench: Bench):
        cfg = self.config
        routes = [Route(0.0, scene.workspace())]
        done, cost, moments = [], 0.0, {}
        for depth in range(cfg.max_steps + 1):
            nxt = []
            for r in routes:
                cands, c_cost = self.candidates(scene, r.ws, bench, allow_steps=depth < cfg.max_steps)
                cost += c_cost
                if not cands:
                    continue
                gates = self.gate(r.ws, cands)
                m = Moment(r.ws, cands, gates)
                moments[r.ws.history] = m
                order = sorted(range(len(cands)), key=lambda k: -gates[k + 1])[:width]
                for k in order:
                    g = gates[k + 1]
                    trail = r.trail + [(m, k)]
                    c = cands[k]
                    if c.step.op in TERMINAL:
                        done.append(Route(r.logp + math.log(g), r.ws, trail))
                    else:
                        nxt.append(Route(r.logp + math.log(g), r.ws.apply(c.step, c.value), trail))
            nxt.sort(key=lambda r: -r.logp)
            seen, routes = set(), []
            for r in nxt:
                if r.ws.history not in seen:
                    seen.add(r.ws.history)
                    routes.append(r)
                if len(routes) >= width:
                    break
            if not routes:
                break
        return done, cost, moments

    def answer(self, scene: Scene, width: Optional[int] = None, benches=None) -> Result:
        """Each bench deliberates; answers pool across routes and across benches."""
        res = Result(scene.question, threshold=self.objective.deliver_threshold(0.0))
        benches = benches or self.benches
        pooled: dict = {}
        res._moments = {}
        for bench in benches:
            done, cost, moments = self.deliberate(scene, width or self.config.beam, bench)
            res.cost += cost
            res._moments.update(moments)
            for r in done:
                v = r.outcome
                p, best, n = pooled.get(v, (0.0, None, 0))
                pooled[v] = (p + math.exp(r.logp) / len(benches), r if best is None or r.logp > best.logp else best, n + 1)
        ranked = sorted(pooled.items(), key=lambda kv: -kv[1][0])
        res.answers = [(v, p, n) for v, (p, _, n) in ranked]
        if self.domain.verifiable and scene.target is not None:
            return self._verified(scene, res, ranked, benches[-1])
        if ranked:
            v, (p, best, _) = ranked[0]
            res.route, res.probability = best, p
            if p >= res.threshold:
                res.answer = v
        if res.answer is None and self.config.think_harder and getattr(self, "_top", 1) == 1:
            return self._harder(scene, res, benches)
        return res

    def _harder(self, scene, res, benches) -> Result:
        """Unsure: deliberate again with a wider beam and more ways for each
        operator to apply itself, wider each time, until an answer is clear."""
        for beam, top in self.config.think_harder:
            self._top = top
            try:
                again = self.answer(scene, beam, benches)
            finally:
                self._top = 1
            again.cost += res.cost
            again.effort = beam
            res = again
            if res.answer is not None:
                break
        return res

    def _verified(self, scene, res, ranked, bench) -> Result:
        """A problem that says how to check its answer (e.g. examples a program
        must pass): deliver the most probable route that passes; if none of the
        open routes does, search for one, guided by the room itself."""
        for v, (p, best, _) in ranked:
            if self.domain.matches(v, scene.target):
                res.route, res.probability, res.answer, res.verified = best, p, v, True
                return res
        cfg = self.config
        keep = (cfg.search_width, cfg.search_alternatives)
        path = None
        try:  # think harder only while nothing passes: a wider search each time
            for level, (width, alternatives) in enumerate(cfg.escalate):
                cfg.search_width, cfg.search_alternatives = width, alternatives
                path = self.search(scene, scene.target, bench, fallback=level == 0)
                res.cost += self.search_cost + 0.02 * scene.cache.pop("fallback_runs", 0)
                res.effort = width
                if path is not None:
                    break
        finally:
            cfg.search_width, cfg.search_alternatives = keep
        res.searched = True
        if path is not None:
            route, cost = self._route(scene, path, bench)
            res.cost += cost
            res.route, res.probability, res.answer, res.verified = route, math.exp(route.logp), route.ws.answer, True
            res.answers = [(res.answer, res.probability, 1)] + res.answers
        elif ranked:
            res.route, res.probability = ranked[0][1][1], ranked[0][1][0]
        return res

    def _route(self, scene, path, bench):
        """A worked path as a route with its deliberation (what was on the table
        at each step, and how the judge weighed it)."""
        trail, logp, cost = [], 0.0, 0.0
        for ws, step in path:
            allow = step.op not in TERMINAL or len(ws.steps) < self.config.max_steps
            cands, c = self.candidates(scene, ws, bench, allow_steps=allow)
            cost += c
            key = _key(step)
            k = next((i for i, x in enumerate(cands) if x.token == key), None)
            if k is None:  # found by the fallback search: nobody proposed it
                x = Candidate(step if step.op in TERMINAL else canon(step), ws.answer if step.op == STOP else ws.run(step))
                x.feats = self.features(scene, ws, x)
                cands = cands + [x]
                k = len(cands) - 1
            gates = self.gate(ws, cands)
            trail.append((Moment(ws, cands, gates), k))
            logp += math.log(max(gates[k + 1], 1e-9))
        return Route(logp, path[-1][0], trail), cost

    def grade(self, task, res) -> str:
        """right / wrong / abstain, as the domain judges it."""
        return self.domain.verdict(task, res)

    # -- one question, end to end -----------------------------------------
    def handle(self, task, width: Optional[int] = None) -> Result:
        res = self._handle(task, width)
        if self.config.learn and task.split == "train" and self.inventor is not None:
            self.seen += 1
            self.inventor.after(self, task, res)
        return res

    def _handle(self, task, width: Optional[int] = None) -> Result:
        scene = Scene(task.question, self.domain)
        training = self.config.learn and task.split == "train"
        outsider = self.outsider(scene)
        if training and task.labeled and len(self.benches) > 1 and self.rng.random() < 0.5:
            # The answer will be revealed, so (half the time) let the bench that
            # has never learned this wording try it: the judge and the
            # self-models learn what the experts are worth on new ground.
            res = self.answer(scene, width or self.config.train_beam, [outsider])
            res._bench = outsider
        else:
            # Otherwise the room's best: anything it teaches itself from an
            # unlabeled question must come from the bench that knows the most.
            res = self.answer(scene, width or (self.config.train_beam if training else self.config.beam), [self.full])
            res._bench = self.full
        if not self.config.learn:
            return res
        if self.domain.verifiable and scene.target is not None:  # the problem checks itself
            res.label = scene.target
            path = self._retell(scene, res.route and self._path(res.route) if res.verified else None)
            if path is not None:
                res.reference = path
                self.teach(scene, path, "label", res)
                if self.inventor is not None:
                    self.inventor.library.record(scene, path)
        elif task.labeled:
            res.label = task.target if getattr(task, "answerable", True) else UNKNOWABLE
            path = self._retell(scene, self.reference(scene, res.label, res, res._bench))
            if path is not None:
                res.reference = path
                self.teach(scene, path, "label", res)
                if self.inventor is not None:
                    self.inventor.library.record(scene, path)
        elif res.answer is not None and res.probability >= self.config.teach_at:
            res.certified = True
            self.stats["certified"] += 1
            self.teach(scene, self._retell(scene, self._path(res.route)), "certified", res)
        return res

    def _retell(self, scene, path):
        """A worked solution in the room's current vocabulary: with every
        procedure it has invented used wherever it fits (so what the room
        learns from is always its most compact account of the solution)."""
        if path is None or not self.procedures:
            return path
        tokens = tuple(s.token for _, s in path if s.op != STOP)
        new = replay_path(scene, tokens, self.procedures)
        return path if new is None else new

    @staticmethod
    def _path(route: Route) -> list:
        return [(m.ws, m.cands[k].step) for m, k in route.trail]

    # -- finding a worked solution for a revealed answer -------------------
    def reference(self, scene: Scene, label, res: Result, bench: Bench):
        if res.route is not None and self.domain.matches(res.route.outcome, label):
            self.stats["own_solution"] += 1
            return self._path(res.route)
        if label is UNKNOWABLE:  # the move it needed: say so at the start
            self.stats["told_insufficient"] += 1
            return [(scene.workspace(), CANT)]
        self.stats["searched"] += 1
        found = self.search(scene, label, bench)
        if found is not None:
            self.stats["found"] += 1
        return found

    def search(self, scene: Scene, label: float, bench: Bench, fallback: bool = True):
        """The route the room itself finds most likely among those that reach
        the revealed answer: a beam search scored by the judge's own step
        probabilities. A route only gets less likely as it grows, so once the
        best route found beats every route still open, nothing can overtake it
        and the search stops. Short, plausible chains win; nothing rewards
        using every number (some numbers in a question are beside the point).
        If the room's own guidance finds nothing, fall back on exhaustive
        search of short programs, fewest steps first."""
        cfg = self.config
        best = None  # (log probability, workspace)
        routes = [(0.0, scene.workspace())]
        self.search_cost = 0.0  # compute spent, so searching is never free
        for depth in range(cfg.max_steps):
            nxt = []
            for lp, ws in routes:
                cands, c_cost = self.candidates(scene, ws, bench, search=True)
                self.search_cost += c_cost
                gates = self.gate(ws, cands)
                for k, c in enumerate(cands):
                    if c.step.op in TERMINAL or c.value is UNKNOWABLE:  # an unknown can't lead to a number
                        continue
                    lp2 = lp + math.log(gates[k + 1] + 1e-9)
                    if best is not None and lp2 <= best[0]:
                        continue
                    w2 = ws.apply(c.step, c.value)
                    if self.domain.matches(c.value, label):
                        best = (lp2, w2)
                    else:
                        nxt.append((lp2, w2))
            nxt.sort(key=lambda t: -t[0])
            seen, routes = set(), []
            for lp, ws in nxt:
                key = (tuple(sorted(ws.values, key=repr)), frozenset(ws.used))  # same results, same facts used
                if key not in seen:
                    seen.add(key)
                    routes.append((lp, ws))
                if len(routes) >= cfg.search_width:
                    break
            if not routes or (best is not None and best[0] >= routes[0][0]):
                break
        if best is None and not fallback:
            return None
        if best is None:
            found = []
            for prog in self.domain.fallback(scene, label):
                self.search_cost += 0.02 * scene.cache.get("fallback_runs", 0)
                scene.cache["fallback_runs"] = 0
                ws = scene.workspace()
                for step in program_to_steps(prog):
                    v = ws.run(step)
                    if v is None:
                        break
                    ws = ws.apply(step, v)
                else:
                    if self.domain.matches(ws.answer, label):
                        found.append((len(ws.steps), len(found), ws))
            if not found:
                return None
            best = (None, min(found, key=lambda t: t[:2])[2])
        path, ws = [], scene.workspace()
        for step, v in zip(best[1].steps, best[1].values):
            path.append((ws, step))
            ws = ws.apply(step, v)
        path.append((ws, ANSWER))
        return path

    # -- learning from a worked solution ------------------------------------
    def teach(self, scene: Scene, path: list, source: str, res: Result) -> None:
        """Broadcast a worked solution. The bench that owns this wording learns
        it; the judge and the self-models learn from the other bench, which
        met it as new."""
        bench = getattr(res, "_bench", self.full)
        moments = getattr(res, "_moments", {})
        labeled = source == "label"
        if labeled:
            for ws, step in path:
                m = moments.get(ws.history)
                if m is None:
                    allow = step.op not in TERMINAL or len(ws.steps) < self.config.max_steps
                    cands, _ = self.candidates(scene, ws, bench, allow_steps=allow)
                    m = Moment(ws, cands, self.gate(ws, cands))
                target = _key(step)
                k = next((i for i, c in enumerate(m.cands) if c.token == target), None)
                res.surprise -= math.log(max(m.gates[k + 1] if k is not None else 0.0, 1e-4))
                self._train_judge(scene, ws, m.cands, target)
                # self-knowledge: how often was my proposal the step the solution needed?
                for c in m.cands:
                    for p in c.props:
                        bench.by_name[p.expert].settle(p.evidence, c.token == target)
        for learner in self.learners(scene):
            weights = self._responsibilities(scene, path, learner) if self.config.specialize else None
            for e in learner.steppers:
                w = weights.get(e.name) if weights is not None else None
                e.learn(scene, path, source, w)
            if labeled:
                for r in learner.reviewers:
                    r.learn_review(scene, path, res.label)

    def _train_judge(self, scene, ws, cands, target) -> None:
        """The judge learns whom to trust at this step: maximise the probability
        of the step the worked solution took (or "none" if nobody proposed it).
        Each proposal is left out with some probability, so the judge can't
        lean on the crowd and has to learn what each expert's word is worth."""
        p = self.config.dropout
        if p > 0:
            kept = []
            for c in cands:
                props = [q for q in c.props if self.rng.random() >= p]
                if props or not c.props:  # an option nobody backs (e.g. "not enough information") stays
                    d = Candidate(c.step, c.value)
                    d.props, d.reviews, d.fam = props, c.reviews, c.fam
                    d.feats = self.features(scene, ws, d)
                    kept.append(d)
            cands = kept
        idx = next((i + 1 for i, c in enumerate(cands) if c.token == target), 0)
        gates = self.gate(ws, cands)
        feats = [self.none_features(ws)] + [c.feats for c in cands]
        for i, f in enumerate(feats):
            self.judge.step(f, gates[i] - (1.0 if i == idx else 0.0))

    def _responsibilities(self, scene, path, bench: Bench) -> dict:
        """Mixture of experts: share each step out among the neural pool in
        proportion to how well each network already predicts it."""
        n = len(bench.neural)
        if not n:
            return {}
        out = {e.name: [] for e in bench.neural}
        for ws, step in path:
            tok = _key(step)
            ps = np.array([e.prob_of(scene, ws, tok) for e in bench.neural]) + 1e-6
            h = ps / ps.sum()
            for e, hi in zip(bench.neural, h):
                out[e.name].append(float(min(n * hi, 4.0)))
        return out


    # -- sleeping and inventing ---------------------------------------------
    def sleep(self, solutions) -> None:
        """Replay past worked solutions, in the room's current vocabulary, and
        learn from them as if they had just been found: judge, experts,
        self-models and reviewers alike."""
        for question, _, tokens in solutions:
            scene = Scene(question, self.domain)
            path = replay_path(scene, tokens, self.procedures)
            if path is None:
                continue
            res = Result(question)
            res._bench, res._moments = self.full, {}
            res.label = UNKNOWABLE if path[-1][1].op == INSUFFICIENT else path[-1][0].answer
            self.teach(scene, path, "label", res)

    def adopt(self, proc) -> None:
        """Take on an invented procedure: register it, give every bench an
        expert for it (the neural experts get a word for it) and re-express
        memory with it. What it's worth is learned in sleep and on new questions."""
        register(proc)
        self.procedures.append(proc)
        shared = None
        for b, bench in enumerate(self.benches):
            e = OperatorExpert(proc.name, seed=1000 + len(self.procedures) * 10 + b)
            if shared is None:
                shared = e.competence
            e.competence = shared
            bench.add(e)
            for name, attr in (("memory", "book"), ("analogy", "solutions")):
                book = getattr(bench.by_name.get(name), attr, None)
                if book is None:
                    continue
                for sk in list(book):
                    new = type(book[sk])()
                    for tokens, n in book[sk].items():
                        new[retell(tokens, self.procedures)] += n
                    book[sk] = new
        self.experts = [e for b in self.benches for e in b.experts]


@dataclass
class Trial:
    room: "Room"  # the copy that has the new procedure
    proc: object
    wins: int = 0  # relevant questions the copy got right and the room didn't
    losses: int = 0  # ... and the other way round
    both: int = 0
    relevant: int = 0  # answered questions where the procedure fits a worked solution or the copy used it
    surprise: tuple = (0.0, 0.0)  # total surprise at the worked solutions: room, copy
    left: int = 0
    used: int = 0  # the copy's right answers that used the procedure
    cost: tuple = (0.0, 0.0)


class Inventor:
    """The room's notebook, its sleep, and its trials of new procedures (see
    procedures.py). Every ``invent_every`` questions the room sleeps on a
    sample of its recent worked solutions. If the notebook suggests a
    procedure, a copy of the room adopts it and sleeps on the same solutions
    re-expressed with it, so the two rooms differ only in that one word.
    Both then meet the next ``trial_length`` questions before learning from
    them. The copy replaces the room only if it was less surprised by the
    worked solutions of those questions (prequential description length: the
    room that finds the right solutions more likely needs a smaller search to
    find them), used the procedure, and lost no more answers than it won."""

    def __init__(self):
        self.library = Library()
        self.trial: Optional[Trial] = None
        self.last = 0
        self.log: list = []

    def after(self, room: "Room", task, res: Result) -> None:
        cfg = room.config
        t = self.trial
        if t is not None:
            other = t.room._handle(task)
            t.left -= 1
            t.cost = (t.cost[0] + res.cost, t.cost[1] + other.cost)
            if task.labeled:
                t.surprise = (t.surprise[0] + res.surprise, t.surprise[1] + other.surprise)
                a, b = room.grade(task, res) == "right", room.grade(task, other) == "right"
                name = t.proc.name
                mine = res.reference and uses(_contracted([s.token for _, s in res.reference], t.proc), t.proc)
                theirs = any(s.op == name for _, s in (other.reference or ())) or any(s.op == name for s in other.steps)
                if mine or theirs:
                    t.relevant += 1
                    t.wins += b and not a
                    t.losses += a and not b
                    t.both += a and b
                t.used += b and any(s.op == name for s in other.steps)
            if t.left <= 0:
                self._decide(room, t)
            return
        if room.seen >= cfg.invent_from and room.seen - self.last >= cfg.invent_every:
            self._start(room)

    def _sample(self, room, proc):
        recent = list(self.library.recent)
        n = room.config.warmup
        rng = np.random.default_rng(len(self.log) + room.seen)
        if proc is None:
            idx = rng.choice(len(recent), min(len(recent), n), replace=False) if recent else []
            return [recent[i] for i in sorted(idx)]
        hit = [s for s in recent if uses(_contracted(s[2], proc), proc)]
        rest = [s for s in recent if not uses(_contracted(s[2], proc), proc)]
        idx = rng.choice(len(rest), min(len(rest), max(n - len(hit), len(hit))), replace=False) if rest else []
        return hit + [rest[i] for i in sorted(idx)]

    def _start(self, room: "Room") -> None:
        self.last = room.seen
        found = self.library.candidates(top=1, procs=room.procedures) if room.config.invent else []
        if not found:
            room.sleep(self._sample(room, None))
            self.log.append({"procedure": None, "at": room.seen})
            return
        saving, proc, wordings, occurrences = found[0]
        self.library.tried.add(proc.body)
        sample = self._sample(room, proc)
        mine = room.inventor
        room.inventor = None
        clone = copy.deepcopy(room)
        room.inventor = mine
        room.sleep(sample)
        clone.adopt(proc)
        clone.sleep(sample)
        self.trial = Trial(clone, proc, left=room.config.trial_length)
        self.log.append({"procedure": proc.name, "body": proc.describe(), "saving": saving, "wordings": wordings,
                         "occurrences": occurrences, "at": room.seen})

    def _decide(self, room: "Room", t: Trial) -> None:
        # Keep it if the copy explains what came next more compactly (it found
        # the worked solutions more likely, so a search of the same width finds
        # them sooner), actually used the procedure, and lost no more answers
        # than it won.
        keep = t.surprise[1] < t.surprise[0] and t.used >= 3 and t.wins >= t.losses
        self.log[-1].update({"wins": t.wins, "losses": t.losses, "both": t.both, "relevant": t.relevant,
                             "used": t.used, "kept": keep, "surprise": (round(t.surprise[0], 1), round(t.surprise[1], 1)),
                             "cost": (round(t.cost[0], 1), round(t.cost[1], 1))})
        self.trial = None
        self.last = room.seen
        if keep:  # the copy becomes the room (keeping this notebook and the count)
            mine = room.inventor
            room.__dict__.update({k: v for k, v in t.room.__dict__.items() if k not in ("inventor", "seen")})
            room.inventor = mine


def _contracted(tokens, proc):
    steps = [Step.parse(x) for x in tokens]
    if not steps or any(s.op in TERMINAL for s in steps):
        return ("N", 0)
    prog = tree(steps)
    return ("N", 0) if prog is None else rewrite(prog, proc)


def make_room(n_neural: int = 8, seed: int = 0, crossfit: bool = False, config: RoomConfig | None = None,
              invent: bool = True, domain=None, **kw) -> Room:
    """A room with one bench of experts, or, cross-fitted, two sparring benches
    plus the full bench that answers. Experts in the same role share one
    self-model, learned from what they did on wordings new to them."""
    from .experts import population
    names = ["sparring-a", "sparring-b", "full"] if crossfit else ["full"]
    benches = []
    for b, name in enumerate(names):
        experts = population(n_neural, seed=seed * 7 + b, domain=domain, **kw)
        benches.append(Bench(experts, name=name))
    for e in benches[-1].experts:  # one self-model per role
        for other in benches[:-1]:
            if e.name in other.by_name:
                other.by_name[e.name].competence = e.competence
    config = config or RoomConfig()
    config.invent = invent and config.invent
    return Room(benches, config=config, seed=seed, domain=domain)
