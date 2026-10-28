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

Learning happens in the same room, from the same signals. When an answer is
revealed, the room looks for a worked solution that reaches it: its own, if
it was right; otherwise a search guided by its own experts and judge. That
solution is broadcast. Every expert learns its part from it, the judge learns
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

import math
import zlib
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

import numpy as np

from ..learner import SparseLogLinear, softmax
from ..maths.programs import explain
from ..objective import Objective
from ..protocol import NEURAL
from .experts import NeuralExpert, OperatorExpert, Scene
from .workspace import ANSWER, STOP, Workspace, canon, program_to_steps


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
    judge_lr: float = 0.3
    dropout: float = 0.3  # judge trains with random experts left out, so it learns what each is worth alone


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

    @property
    def steps(self) -> list:
        return [] if self.route is None else [m.cands[k].step for m, k in self.route.trail]


def _matches(v, target) -> bool:
    return v is not None and abs(float(v) - float(target)) <= 1e-6 * max(1.0, abs(float(target)))


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


class Room:
    def __init__(self, benches, objective: Objective | None = None, config: RoomConfig | None = None, seed=0):
        self.benches = list(benches)
        self.experts = [e for b in self.benches for e in b.experts]
        self.objective = objective or Objective()
        self.config = config or RoomConfig()
        self.judge = SparseLogLinear(lr=self.config.judge_lr)
        self.rng = np.random.default_rng(seed + 13)
        self.stats: dict = {"searched": 0, "found": 0, "own_solution": 0, "certified": 0}
        # with cross-fitting: [sparring a, sparring b, full]; otherwise one bench does everything
        self.full = self.benches[-1]
        self.folds = self.benches[:-1] or [self.full]

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
        fam = self.familiar(scene, bench)
        cost = 0.0
        spoken = []
        for e in bench.steppers:
            if isinstance(e, OperatorExpert):
                props = e.propose(scene, ws, self.config.search_alternatives if search else 1)
            else:
                props = e.propose(scene, ws)
            cost += e.cost
            spoken.append((e, props))
        # Operators' readiness is read relative to each other (a softmax over
        # experts rather than independent votes): on unfamiliar ground the right
        # operator is often only mildly ready, but far more ready than the rest.
        total = sum(max((p.raw[0] for p in props), default=0.0) for e, props in spoken if isinstance(e, OperatorExpert))
        for e, props in spoken:
            if isinstance(e, OperatorExpert):
                for p in props:
                    e.settle_share(p, total)
            for p in props:
                if p.step.op != STOP and not allow_steps:
                    continue
                key = canon(p.step).token if p.step.op != STOP else STOP
                c = pool.get(key)
                if c is None:
                    c = pool[key] = Candidate(canon(p.step) if p.step.op != STOP else ANSWER, p.value)
                c.props.append(p)
        if not allow_steps and ws.steps and STOP not in pool:
            pool[STOP] = Candidate(ANSWER, ws.answer)
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
            f.update({"stop": 1.0, f"stop|t:{t}": 1.0, f"stop|open:{min(len(open_now), 3)}": 1.0,
                      f"stop|prev:{prev}": 1.0, f"stop|last-used:{int(ws.last in ws.used)}": 1.0})
        else:
            fresh = sum(1 for a in c.step.args if a in ws.unused)
            left = len([r for r in open_now if r not in c.step.args])
            f.update({"step": 1.0, f"fresh|{fresh}/{len(c.step.args)}": 1.0, f"left|{min(left, 3)}": 1.0,
                      f"uses-last|{int(ws.last in c.step.args) if ws.last else 'none'}": 1.0})
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
                    if c.step.op == STOP:
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
                v = r.ws.answer
                p, best, n = pooled.get(v, (0.0, None, 0))
                pooled[v] = (p + math.exp(r.logp) / len(benches), r if best is None or r.logp > best.logp else best, n + 1)
        ranked = sorted(pooled.items(), key=lambda kv: -kv[1][0])
        res.answers = [(v, p, n) for v, (p, _, n) in ranked]
        if ranked:
            v, (p, best, _) = ranked[0]
            res.route, res.probability = best, p
            if p >= res.threshold:
                res.answer = v
        return res

    # -- one question, end to end -----------------------------------------
    def handle(self, task, width: Optional[int] = None) -> Result:
        scene = Scene(task.question)
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
        if task.labeled:
            res.label = task.target
            path = self.reference(scene, task.target, res, res._bench)
            if path is not None:
                res.reference = path
                self.teach(scene, path, "label", res)
        elif res.answer is not None and res.probability >= self.config.teach_at:
            res.certified = True
            self.stats["certified"] += 1
            self.teach(scene, self._path(res.route), "certified", res)
        return res

    @staticmethod
    def _path(route: Route) -> list:
        return [(m.ws, m.cands[k].step) for m, k in route.trail]

    # -- finding a worked solution for a revealed answer -------------------
    def reference(self, scene: Scene, label: float, res: Result, bench: Bench):
        if res.route is not None and _matches(res.route.ws.answer, label) and self._coverage(res.route.ws) == 1.0:
            self.stats["own_solution"] += 1
            return self._path(res.route)
        self.stats["searched"] += 1
        found = self.search(scene, label, bench)
        if found is not None:
            self.stats["found"] += 1
        return found

    @staticmethod
    def _coverage(ws: Workspace) -> float:
        q = [r for r in ws.facts]
        return 1.0 if not q else sum(r in ws.used for r in q) / len(q)

    def search(self, scene: Scene, label: float, bench: Bench):
        """Look for steps that reach the revealed answer, guided by the room's
        own experts and judge; fall back on exhaustive search of short programs.
        Solutions that use every fact in the question are preferred."""
        cfg = self.config
        hits = []
        routes = [(0.0, scene.workspace())]
        for depth in range(cfg.max_steps):
            nxt = []
            for lp, ws in routes:
                cands, _ = self.candidates(scene, ws, bench, search=True)
                cands = [c for c in cands if c.step.op != STOP]
                if not cands:
                    continue
                gates = self.gate(ws, cands)
                for k, c in enumerate(cands):
                    w2 = ws.apply(c.step, c.value)
                    lp2 = lp + math.log(gates[k + 1] + 1e-9)
                    if _matches(c.value, label):
                        hits.append((self._coverage(w2), -len(w2.steps), lp2, w2))
                    nxt.append((lp2, w2))
            if any(h[0] == 1.0 for h in hits):
                break
            nxt.sort(key=lambda t: -t[0])
            seen, routes = set(), []
            for lp, ws in nxt:
                key = (tuple(sorted(ws.values)), frozenset(ws.used))
                if key not in seen:
                    seen.add(key)
                    routes.append((lp, ws))
                if len(routes) >= cfg.search_width:
                    break
        if not any(h[0] == 1.0 for h in hits):
            for prog in explain(scene.reading, float(label), limit=5):
                ws = scene.workspace()
                ok = True
                for step in program_to_steps(prog):
                    v = ws.run(step)
                    if v is None:
                        ok = False
                        break
                    ws = ws.apply(step, v)
                if ok and _matches(ws.answer, label):
                    hits.append((self._coverage(ws), -len(ws.steps), -50.0, ws))
        if not hits:
            return None
        hits.sort(key=lambda h: (-h[0], -h[1], -h[2]))
        best = hits[0][3]
        path, ws = [], scene.workspace()
        for step, v in zip(best.steps, best.values):
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
                    allow = step.op != STOP or len(ws.steps) < self.config.max_steps
                    cands, _ = self.candidates(scene, ws, bench, allow_steps=allow)
                    m = Moment(ws, cands, self.gate(ws, cands))
                target = canon(step).token if step.op != STOP else STOP
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
                if props:
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
            tok = canon(step).token if step.op != STOP else STOP
            ps = np.array([e.prob_of(scene, ws, tok) for e in bench.neural]) + 1e-6
            h = ps / ps.sum()
            for e, hi in zip(bench.neural, h):
                out[e.name].append(float(min(n * hi, 4.0)))
        return out


def make_room(n_neural: int = 8, seed: int = 0, crossfit: bool = False, config: RoomConfig | None = None, **kw) -> Room:
    """A room with one bench of experts, or, cross-fitted, two sparring benches
    plus the full bench that answers. Experts in the same role share one
    self-model, learned from what they did on wordings new to them."""
    from .experts import population
    names = ["sparring-a", "sparring-b", "full"] if crossfit else ["full"]
    benches = []
    for b, name in enumerate(names):
        experts = population(n_neural, seed=seed * 7 + b, **kw)
        benches.append(Bench(experts, name=name))
    for e in benches[-1].experts:  # one self-model per role
        for other in benches[:-1]:
            if e.name in other.by_name:
                other.by_name[e.name].competence = e.competence
    return Room(benches, config=config, seed=seed)
