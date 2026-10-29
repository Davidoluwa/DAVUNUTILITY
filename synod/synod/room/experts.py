"""The room's population: many small experts, each volunteering what it can do.

Every expert reads the same scene (the question) and the same workspace (the
steps taken so far) and, at every step, proactively puts forward what it
thinks should happen next, with how sure it is and why:

* **operator experts** (symbolic, one per exact operation: add, solve, gcd,
  round, ...). Each knows its own maths perfectly and nothing else. What it
  learns is *when* it is the right next move and *which facts* to apply it to,
  from the words around them ("from #", "by #", "# percent of").
* **neural experts** (a pool of small networks, identical in design, each
  reading the question through its own random view). They predict *what*
  should happen next (which operation, or that the solution is finished); the
  operator expert for that operation decides *what to apply it to*. They are
  trained like a mixture of experts: each example is shared out in proportion
  to how well each network already explains it, so the pool divides the work
  among itself without being told how.
* **memory** (symbolic) recalls worked solutions of the exact same wording;
  **analogy** (symbolic) borrows them from the most similar wordings.
* **goal** learns when a solution is finished.
* **checker** (symbolic) and **estimator** (neural) review results: whole-number
  and yes/no checks with learned reliability, and a learned sense of size.

Nobody tells an expert what to do. They all learn in the same room, from the
same signals: the worked solutions the room discovers on answered questions,
and the answers it is sure enough of to teach from.
"""
from __future__ import annotations

import itertools
import math
import zlib
from collections import Counter, defaultdict
from itertools import repeat

import numpy as np

from ..beliefs import Competence, conf_bucket
from ..learner import SparseLogLinear, sigmoid, softmax
from ..maths.mathlang import read
from ..maths.nodes import _SparseMLP, numeric_features, squash
from ..protocol import NEURAL, SYMBOLIC
from .workspace import (ANSWER, ARITH, ARITH_OPS, CANT, CONST, INSUFFICIENT, NUM, STOP, TERMINAL, UNKNOWABLE, Step,
                        Workspace, canon)

FEATURE_DIM = 4096


# ----------------------------------------------------------------------------
# What everyone perceives
# ----------------------------------------------------------------------------
class Scene:
    """The question as the room perceives it, computed once."""

    def __init__(self, question: str, domain=None):
        domain = domain or ARITH
        self.domain = domain.pick(question) if hasattr(domain, "pick") else domain  # a room of many domains routes it
        self.question = question
        self.reading = self.domain.read(question)
        r = self.reading
        self.skeleton = r.skeleton
        self.words = tuple(sorted(set(r.skeleton)))
        self.wfeats = tuple(f"w:{t}" for t in self.words)
        self.bigrams = tuple(sorted({f"b:{a}_{b}" for a, b in zip(r.skeleton, r.skeleton[1:])}))
        self.context = self.domain.context(r)
        self.slots = r.slots
        self.target = self.domain.target(r)  # what a verifiable problem's answer must be
        self._hash: dict = {}
        self.cache: dict = {}  # per-question scratch (e.g. an operator's best bindings in a state)

    def workspace(self) -> Workspace:
        return Workspace(self.reading, domain=self.domain)

    def around(self, fact) -> list:
        """The words just before and after each place a fact is mentioned
        (e.g. 'from #', '# percent of'): [(left, two to the left, right)]."""
        sk = self.skeleton
        return [(sk[p - 1] if p >= 1 else "^", sk[p - 2] if p >= 2 else "^", sk[p + 1] if p + 1 < len(sk) else "$")
                for p in fact.where]

    def hashed(self, salt: int, names) -> np.ndarray:
        key = (salt, names)
        if key not in self._hash:
            self._hash[key] = _hash(salt, self._family(names))
        return self._hash[key]

    def _family(self, names):
        out = []
        if "u" in names:
            out += [f"u:{t}" for t in self.skeleton]
        if "b" in names:
            out += list(self.bigrams)
        if "s" in names:
            out.append(f"s:{self.slots}")
        if "c" in names:
            out += [f"c:{c}" for c in self.context]
        return out


_BUCKET: dict = {}  # (salt, feature) -> hashed input unit, worked out once per process


def _bucket(salt: int, s: str) -> int:
    k = (salt, s)
    v = _BUCKET.get(k)
    if v is None:
        if len(_BUCKET) > 2_000_000:
            _BUCKET.clear()
        v = _BUCKET[k] = zlib.crc32(f"{salt}|{s}".encode()) % FEATURE_DIM
    return v


def _hash(salt: int, strings) -> np.ndarray:
    return np.array(sorted({_bucket(salt, s) for s in strings}), dtype=np.int64)


def open_context(scene: "Scene", ws: Workspace, window: int = 3) -> list:
    """The words around the facts nobody has used yet: what the question still
    says about the work that's left ("times #", "# percent of", "remainder ...").
    This is the room's locality bias: the next step is read from the part of
    the question that hasn't been dealt with, not from the question as a whole."""
    key = ("open", ws.history, window)
    if key in scene.cache:
        return scene.cache[key]
    out = set()
    sk = scene.skeleton
    for ref in ws.unused:
        f = ws.fact(ref)
        if f is None:
            continue
        out.add(f"o:{ref[0]}")
        out.update(f"oD:{t}" for t in scene.domain.describe(ws, f))
        for left, left2, right in scene.around(f):
            out.update((f"oL:{left}", f"oLL:{left2}_{left}", f"oR:{right}"))
        for p in f.where:
            for j in range(max(0, p - window), min(len(sk), p + window + 1)):
                if j != p:
                    out.add(f"oW:{sk[j]}")
    out = scene.cache[key] = sorted(out)
    return out


def state_features(ws: Workspace) -> list:
    """Where the solution stands: step number, the last operation, and which
    kinds of fact are still unused."""
    if "state" in ws._memo:
        return ws._memo["state"]
    t = len(ws.steps)
    prev = ws.steps[-1].op if ws.steps else "none"
    free = Counter(r[0] for r in ws.unused)
    out = [f"t:{min(t, 5)}", f"prev:{prev}"]
    out += [f"free:{k}{min(n, 3)}" for k, n in sorted(free.items())]
    if not free:
        out.append("free:none")
    ws._memo["state"] = out
    return out


# ----------------------------------------------------------------------------
# Signals
# ----------------------------------------------------------------------------
class Proposal:
    __slots__ = ("expert", "kind", "step", "value", "confidence", "evidence", "note", "raw")

    def __init__(self, expert, kind, step, value, confidence, evidence=(), note="", raw=None):
        self.expert, self.kind, self.step, self.value = expert, kind, step, value
        self.confidence, self.evidence, self.note, self.raw = confidence, tuple(evidence), note, raw

    @property
    def token(self):
        return self.step.token


class Expert:
    kind = SYMBOLIC
    role = "step"  # step | review
    cost = 0.02
    domains = None  # the domains whose problems it works on (None: all)

    def __init__(self, name: str, seed: int = 0):
        self.name = name
        self.rng = np.random.default_rng(seed)
        self.competence = Competence(prior_mean=0.3, strength=4.0, decay=0.998)
        self.stats: Counter = Counter()

    # Step experts --------------------------------------------------------
    def propose(self, scene: Scene, ws: Workspace) -> list:
        return []

    def learn(self, scene: Scene, path: list, source: str, weights=None) -> None:
        """path: [(workspace before, step taken)] ending with the answer step.
        source: "label" (a worked solution the room confirmed against a
        revealed answer) or "certified" (one it was sure enough of)."""

    def calibrated(self, evidence, raw: float) -> float:
        """Self-knowledge: how often proposals with this evidence turned out
        to be the step the solution needed."""
        return min(self.competence.mean(("p",) + tuple(evidence)), 0.99)

    def settle(self, evidence, ok: bool) -> None:
        self.competence.update(("p",) + tuple(evidence), 1.0 if ok else 0.0)
        self.stats["settled"] += 1
        self.stats["settled_ok"] += int(ok)

    # Reviewers ------------------------------------------------------------
    def review(self, scene: Scene, ws: Workspace, step: Step, value) -> tuple:
        """Signals about a candidate step (or, for the answer step, the finished solution)."""
        return ()

    def learn_review(self, scene: Scene, path: list, answer) -> None:
        pass


def _run(ws: Workspace, step: Step):
    if step.op == STOP:
        return ws.answer if ws.steps else None
    if step.op == INSUFFICIENT:
        return UNKNOWABLE
    return ws.run(step)


# ----------------------------------------------------------------------------
# Operator experts (symbolic)
# ----------------------------------------------------------------------------
class _KeyedPairs(dict):
    """Pair features computed on first use for a state (a dict keyed by (a, b))."""

    __slots__ = ("ws",)

    def __init__(self, ws):
        super().__init__()
        self.ws = ws

    def __missing__(self, refs):
        ws = self.ws
        table = ws.table
        names = self[refs] = OperatorExpert._pair_feats(ws, table[refs[0]], table[refs[1]])
        return names


class OperatorExpert(Expert):
    """Knows one exact operation. Learns when it's the right next step and
    which facts to apply it to."""

    kind = SYMBOLIC
    cost = 0.02

    def __init__(self, op: str, seed: int = 0):
        super().__init__(op, seed)
        self.op = op
        self.fire = SparseLogLinear(lr=0.3)
        self.bind = SparseLogLinear(lr=0.3)

    # -- features ----------------------------------------------------------
    @staticmethod
    def _fire_names(scene, ws) -> list:
        """What every operator reads to decide whether it's the next move (the
        same for all of them, so it's worked out once per state)."""
        key = ("fire", ws.history)
        names = scene.cache.get(key)
        if names is None:
            names = scene.cache[key] = list(dict.fromkeys(
                list(scene.wfeats) + state_features(ws) + open_context(scene, ws) + ["bias"]))
        return names

    def _fire_feats(self, scene, ws):
        return dict.fromkeys(self._fire_names(scene, ws), 1.0)

    @staticmethod
    def _arg_names(scene, ws, i, fact) -> list:
        """What an operator reads about a fact in argument position i (the
        same for every operator, so it's worked out once)."""
        key = ("arg", ws.history, i, fact.ref)
        names = scene.cache.get(key)
        if names is None:
            names = scene.cache[key] = list(dict.fromkeys(OperatorExpert._arg_feats(scene, ws, i, fact)))
        return names

    @staticmethod
    def _arg_feats(scene, ws, i, fact):
        kind = fact.ref[0]
        out = [f"{i}|{kind}", f"{i}|{'free' if fact.ref in ws.unused else 'used'}"]
        if fact.ref == ws.last:
            out.append(f"{i}|last")
        if kind == "K":
            k = fact.ref
            out.append(f"{i}|{k}")
            out += [f"{i}|{k}|{w}" for w in scene.wfeats]
        else:
            if kind == "S":
                out.append(f"{i}|S-{len(ws.values) - int(fact.ref[1:])}")
                out.append(f"{i}|from:{ws.steps[int(fact.ref[1:]) - 1].op}")
            # what the question says around it, not which number it happens to be
            for left, left2, right in scene.around(fact):
                out += [f"{i}|L:{left}", f"{i}|LL:{left2}_{left}", f"{i}|R:{right}"]
        out += [f"{i}|d:{t}" for t in scene.domain.describe(ws, fact)]  # what it looks like
        return out

    @staticmethod
    def _pair_feats(ws, a, b):
        key = ("pair", a.ref, b.ref)
        out = ws._memo.get(key)
        if out is None:
            out = [f"p|{a.ref[0]}{b.ref[0]}"]
            if a.where and b.where:
                out.append("p|inorder" if min(a.where) < min(b.where) else "p|reversed")
            if a.value is UNKNOWABLE or b.value is UNKNOWABLE:
                out.append("p|unknown")
            elif a.kind == NUM and b.kind in (NUM, CONST):
                out.append("p|a>b" if ws.size(a.ref) > ws.size(b.ref) else "p|a<=b")
            ws._memo[key] = out
        return out

    def _bindings(self, scene, ws):
        """(binding refs, feature dict) for every type-correct binding (for learning)."""
        out = []
        for refs in ws.bindings(self.op):
            facts = [ws.fact(r) for r in refs]
            f = {}
            for i, fact in enumerate(facts):
                for name in self._arg_names(scene, ws, i, fact):
                    f[name] = 1.0
            for pair in itertools.combinations(range(len(facts)), 2):
                for name in self._pair_names(ws)[tuple(refs[k] for k in pair)]:
                    f[name if pair == (0, 1) else f"{pair}{name}"] = 1.0
            out.append((refs, f))
        return out

    def _scored(self, scene, ws):
        """[(binding refs, score)] for every type-correct binding. The binding
        model is linear and each argument position has its own features, so a
        binding's score is the sum of its arguments' scores and the pair's:
        each fact is scored once per position, not once per pairing."""
        binds = ws.bindings(self.op)
        if not binds:
            return []
        get = self.bind.w.get
        table = ws.table
        names = self._arg_names
        zero = repeat(0.0)
        p0 = {}
        if len(binds[0]) == 1:
            out = []
            for refs in binds:
                r = refs[0]
                s0 = p0.get(r)
                if s0 is None:
                    s0 = p0[r] = sum(map(get, names(scene, ws, 0, table[r]), zero))
                out.append((refs, s0))
            return out
        if len(binds[0]) > 2:
            return self._scored_n(scene, ws, binds)
        p1 = {}
        pairs = self._pair_names(ws)
        out = []
        for refs in binds:
            a, b = refs
            s0 = p0.get(a)
            if s0 is None:
                s0 = p0[a] = sum(map(get, names(scene, ws, 0, table[a]), zero))
            s1 = p1.get(b)
            if s1 is None:
                s1 = p1[b] = sum(map(get, names(scene, ws, 1, table[b]), zero))
            out.append((refs, s0 + s1 + sum(map(get, pairs[refs], zero))))
        return out

    def _scored_n(self, scene, ws, binds):
        """The same for an invented procedure with three or more parameters."""
        get = self.bind.w.get
        table = ws.table
        zero = repeat(0.0)
        pos = [{} for _ in binds[0]]
        pairs = self._pair_names(ws)
        combos = list(itertools.combinations(range(len(binds[0])), 2))
        out = []
        for refs in binds:
            total = 0.0
            for i, r in enumerate(refs):
                s0 = pos[i].get(r)
                if s0 is None:
                    s0 = pos[i][r] = sum(map(get, self._arg_names(scene, ws, i, table[r]), zero))
                total += s0
            for pair in combos:
                names = pairs[(refs[pair[0]], refs[pair[1]])]
                total += sum(map(get, names if pair == (0, 1) else [f"{pair}{n}" for n in names], zero))
            out.append((refs, total))
        return out

    @staticmethod
    def _pair_names(ws) -> dict:
        """(a, b) -> pair features, for every pair of facts (once per state)."""
        out = ws._memo.get("pairs")
        if out is None:
            out = ws._memo["pairs"] = _KeyedPairs(ws)
        return out

    # -- proposing ---------------------------------------------------------
    def readiness(self, scene, ws) -> float:
        key = (id(self), "ready", ws.history)
        v = scene.cache.get(key)
        if v is None:
            v = scene.cache[key] = sigmoid(sum(map(self.fire.w.get, self._fire_names(scene, ws), repeat(0.0))))
        return v

    def candidates(self, scene, ws, top: int = 1):
        """My best ways to act here: [(step, value, p_fire, p_binding)]."""
        key = (id(self), ws.history, top)
        if key not in scene.cache:
            scene.cache[key] = self._candidates(scene, ws, top)
        return scene.cache[key]

    def _candidates(self, scene, ws, top):
        p_fire = self.readiness(scene, ws)
        binds = self._scored(scene, ws)
        if not binds:
            return []
        probs = softmax([s for _, s in binds])
        best = max(range(len(probs)), key=probs.__getitem__)
        out = []
        # usually the most likely binding runs; sort the rest only if it doesn't
        order = [best] if top == 1 else sorted(range(len(binds)), key=lambda k: -probs[k])
        for k in self._fallback(order, probs, best):
            step = canon(Step(self.op, binds[k][0]))
            v = ws.run(step)
            if v is not None:
                out.append((step, v, p_fire, probs[k]))
                if len(out) >= top:
                    break
        return out

    @staticmethod
    def _fallback(order, probs, best):
        yield from order
        if len(order) == 1:
            yield from (k for k in sorted(range(len(probs)), key=lambda k: -probs[k]) if k != best)

    def propose(self, scene, ws, top: int = 1):
        """Operators speak as a group: each one's readiness is read relative to
        all the others' (see Room.candidates), like a softmax over experts."""
        return [Proposal(self.name, self.kind, step, v, 0.0, (), f"{self.op} fits {p_fire:.0%}, these facts {p_bind:.0%}",
                         raw=(p_fire, p_bind)) for step, v, p_fire, p_bind in self.candidates(scene, ws, top)]

    def settle_share(self, prop: Proposal, total: float) -> None:
        """Set a proposal's evidence and calibrated confidence from my share of
        the operators' total readiness at this step."""
        p_fire, p_bind = prop.raw
        share = p_fire / total if total > 0 else 0.0
        prop.evidence = (f"share:{conf_bucket(share)}", f"bind:{conf_bucket(p_bind)}", f"fire:{conf_bucket(p_fire)}")
        prop.confidence = self.calibrated(prop.evidence, share * p_bind)
        prop.note = f"{self.op}: {share:.0%} of the operators' readiness, these facts {p_bind:.0%}"

    # -- learning ----------------------------------------------------------
    def learn(self, scene, path, source, weights=None):
        for ws, step in path:
            f = self._fire_feats(scene, ws)
            y = 1.0 if step.op == self.op else 0.0
            self.fire.step(f, sigmoid(self.fire.score(f)) - y)
            if y:
                binds = self._bindings(scene, ws)
                target = canon(step).args
                idx = next((k for k, (refs, _) in enumerate(binds) if canon(Step(self.op, refs)).args == target), None)
                if idx is None:
                    continue
                probs = softmax([self.bind.score(f2) for _, f2 in binds])
                for k, (_, f2) in enumerate(binds):
                    g = probs[k] - (1.0 if k == idx else 0.0)
                    if abs(g) > 1e-4:
                        self.bind.step(f2, g)
                self.stats["learned"] += 1


# ----------------------------------------------------------------------------
# Neural experts
# ----------------------------------------------------------------------------
VIEWS = ("u", "b", "s", "c")


OP_TOKENS = list(ARITH_OPS) + [STOP, INSUFFICIENT]


class NeuralExpert(Expert):
    """A small network that reads the question (through its own view) and the
    steps so far, and predicts what should happen next: which operation (or
    that the solution is finished). Which facts to apply it to is the job of
    that operation's own expert, whose reading of the question binds the
    arguments - so a neural hunch becomes a concrete step only through a
    symbolic expert, and positional habits can't leak into longer problems."""

    kind = NEURAL
    cost = 0.2

    def __init__(self, name: str, seed: int = 0, tokens=None):
        super().__init__(name, seed)
        tokens = list(tokens) if tokens is not None else list(OP_TOKENS)
        rng = np.random.default_rng(seed * 7919 + 11)
        self.salt = int(rng.integers(1 << 30))
        extra = [v for v in VIEWS[1:] if rng.random() < 0.6]
        self.view = ("u",) + tuple(extra)
        self.hidden = int(rng.choice([32, 48, 64]))
        self.tokens = tokens  # what it can say comes next (grows when the room invents an operation)
        self.net = _SparseMLP(self.hidden, rng, n_out=len(self.tokens), lr=0.05)
        self.binders: dict = {}  # op -> that operation's expert (set by the bench)

    def add_token(self, op: str) -> None:
        if op not in self.tokens:
            self.tokens.append(op)
            self.net.grow(len(self.tokens))

    def learn_token(self, scene, path, op: str) -> None:
        """Learn when a new word comes next, from past solutions, without
        relearning anything else: only that word's output weights move."""
        j = self.tokens.index(op)
        net = self.net
        for ws, step in path:
            idx, (h, p) = self.distribution(scene, ws)
            g = p[j] - (1.0 if step.op == op else 0.0)
            net.W2[:, j] -= net.lr * g * h
            net.b2[j] -= net.lr * g

    def _input(self, scene, ws):
        key = ("nin", self.salt, self.view, ws.history)
        idx = scene.cache.get(key)
        if idx is None:
            st = state_features(ws) + open_context(scene, ws) + [f"h{k}:{tok}" for k, tok in enumerate(ws.history[-3:])]
            base = scene.hashed(self.salt, self.view)
            idx = scene.cache[key] = np.unique(np.concatenate([base, _hash(self.salt + 1, st)]))
        return idx

    def distribution(self, scene, ws):
        idx = self._input(scene, ws)
        h, z = self.net.forward(idx)
        p = np.exp(z - z.max())
        return idx, (h, p / p.sum())

    def propose(self, scene, ws):
        idx, out = self.distribution(scene, ws)
        if out is None:
            return []
        _, p = out
        return self._propose_op(scene, ws, p)

    def _propose_op(self, scene, ws, p):
        for k in np.argsort(-p)[:3]:
            op, pk = self.tokens[int(k)], float(p[k])
            if op == STOP:
                if ws.steps:
                    ev = ("n", conf_bucket(pk))
                    return [Proposal(self.name, self.kind, ANSWER, ws.answer, self.calibrated(ev, pk), ev,
                                     f"thinks it's finished ({pk:.0%})")]
                continue
            if op == INSUFFICIENT:
                ev = ("n", conf_bucket(pk), "cant")
                return [Proposal(self.name, self.kind, CANT, UNKNOWABLE, self.calibrated(ev, pk), ev,
                                 f"thinks the question doesn't give enough ({pk:.0%})")]
            binder = self.binders.get(op)
            found = binder.candidates(scene, ws, 1) if binder is not None else []
            if not found:
                continue
            step, v, _, p_bind = found[0]
            ev = ("n", conf_bucket(pk), f"bind:{conf_bucket(p_bind)}")
            return [Proposal(self.name, self.kind, step, v, self.calibrated(ev, pk * p_bind), ev,
                             f"says {op} next ({pk:.0%}); {op} applies it as {step.token}")]
        return []

    def _index(self, token):
        op = token if token in TERMINAL else token.split("(")[0]
        return self.tokens.index(op) if op in self.tokens else None

    def prob_of(self, scene, ws, token) -> float:
        idx, out = self.distribution(scene, ws)
        i = self._index(token)
        if out is None or i is None:
            return 0.0
        return float(out[1][i])

    def learn(self, scene, path, source, weights=None):
        for k, (ws, step) in enumerate(path):
            tok = step.token
            i = self._index(tok)
            if i is None:
                continue
            m = 1.0 if weights is None else weights[k]
            if m <= 1e-3:
                continue
            idx, (h, p) = self.distribution(scene, ws)
            g = p.copy()
            g[i] -= 1.0
            lr = self.net.lr
            self.net.lr = lr * m
            self.net.step(idx, None, h, g)
            self.net.lr = lr
        self.stats["learned"] += 1


# ----------------------------------------------------------------------------
# Memory and analogy (symbolic)
# ----------------------------------------------------------------------------
class MemoryExpert(Expert):
    """Recalls worked solutions of the exact same wording."""

    kind = SYMBOLIC
    cost = 0.02

    def __init__(self, name="memory", seed=0):
        super().__init__(name, seed)
        self.book: dict = defaultdict(Counter)  # skeleton -> Counter(solution tokens)

    def _next(self, solutions, history):
        votes = Counter()
        for sol, n in solutions.items():
            if sol[:len(history)] == history:
                votes[sol[len(history)] if len(sol) > len(history) else STOP] += n
        return votes

    def propose(self, scene, ws):
        sols = self.book.get(scene.skeleton)
        if not sols:
            return []
        votes = self._next(sols, ws.history)
        for tok, n in votes.most_common(3):
            step = Step.parse(tok)
            v = _run(ws, step)
            if v is None:
                continue
            share = n / sum(votes.values())
            ev = ("exact", "seen1" if n == 1 else "seen2-4" if n < 5 else "seen5+", "unique" if share == 1 else "split")
            return [Proposal(self.name, self.kind, step, v, self.calibrated(ev, share), ev,
                             f"same wording solved {n}x this way")]
        return []

    def learn(self, scene, path, source, weights=None):
        tokens = tuple(s.token for _, s in path if s.op != STOP)
        self.book[scene.skeleton][tokens] += 1


class AnalogyExpert(Expert):
    """Borrows the solution of the most similar wordings it knows (same
    notation, most words in common, rare words weighted more)."""

    kind = SYMBOLIC
    cost = 0.1

    def __init__(self, name="analogy", seed=0, k=3):
        super().__init__(name, seed)
        self.k = k
        self.solutions: dict = defaultdict(Counter)  # skeleton -> Counter(solution)
        self.by_slots: dict = defaultdict(set)
        self.df: Counter = Counter()
        self.n = 0

    def _idf(self, w):
        cache = self.__dict__.setdefault("_idf_cache", {})
        if cache.get("_n") != self.n:
            cache.clear()
            cache["_n"] = self.n
        v = cache.get(w)
        if v is None:
            v = cache[w] = math.log((1 + self.n) / (1 + self.df[w]))
        return v

    def similar(self, scene):
        key = (id(self), "similar")
        if key in scene.cache:
            return scene.cache[key]
        mine = set(scene.skeleton)
        out = []
        for sk in sorted(self.by_slots.get(scene.slots, ())):
            if sk == scene.skeleton:
                continue
            other = set(sk)
            inter = sum(self._idf(w) for w in sorted(mine & other))
            union = sum(self._idf(w) for w in sorted(mine | other))
            if union > 0:
                out.append((inter / union, sk))
        out.sort(key=lambda t: (-t[0], t[1]))
        out = scene.cache[key] = out[:self.k]
        return out

    def propose(self, scene, ws):
        if scene.skeleton in self.solutions:
            return []  # memory covers it
        votes = Counter()
        best = 0.0
        for sim, sk in self.similar(scene):
            best = max(best, sim)
            for sol, n in self.solutions[sk].items():
                h = ws.history
                if sol[:len(h)] == h:
                    votes[sol[len(h)] if len(sol) > len(h) else STOP] += sim * n
        for tok, _ in votes.most_common(3):
            step = Step.parse(tok)
            v = _run(ws, step)
            if v is None:
                continue
            ev = ("analogy", f"sim{min(int(best * 5), 4)}")
            return [Proposal(self.name, self.kind, step, v, self.calibrated(ev, best), ev,
                             f"like a similar wording ({best:.2f})")]
        return []

    def learn(self, scene, path, source, weights=None):
        tokens = tuple(s.token for _, s in path if s.op != STOP)
        if scene.skeleton not in self.solutions:
            self.n += 1
            self.df.update(set(scene.skeleton))
            self.by_slots[scene.slots].add(scene.skeleton)
        self.solutions[scene.skeleton][tokens] += 1


# ----------------------------------------------------------------------------
# Goal: knows when a solution is finished
# ----------------------------------------------------------------------------
class GoalExpert(Expert):
    kind = SYMBOLIC
    cost = 0.02

    def __init__(self, name="goal", seed=0):
        super().__init__(name, seed)
        self.model = SparseLogLinear(lr=0.3)

    def _feats(self, scene, ws):
        f = dict.fromkeys(scene.wfeats, 1.0)
        f.update(dict.fromkeys(state_features(ws), 1.0))
        free = [r for r in ws.unused if r[0] != "S"]
        f[f"open:{min(len(free), 3)}"] = 1.0
        f["bias"] = 1.0
        return f

    def propose(self, scene, ws):
        if not ws.steps:
            return []
        p = sigmoid(self.model.score(self._feats(scene, ws)))
        ev = ("done", conf_bucket(p))
        return [Proposal(self.name, self.kind, ANSWER, ws.answer, self.calibrated(ev, p), ev,
                         f"looks finished ({p:.0%})")]

    def learn(self, scene, path, source, weights=None):
        for ws, step in path:
            if not ws.steps:
                continue
            f = self._feats(scene, ws)
            self.model.step(f, sigmoid(self.model.score(f)) - (1.0 if step.op == STOP else 0.0))


# ----------------------------------------------------------------------------
# Reviewers
# ----------------------------------------------------------------------------
def _whole(v) -> bool:
    return v is not None and v.denominator == 1


class CheckerExpert(Expert):
    """Answer-shape checks, each with a learned reliability for this kind of
    question. Reports pass/fail and whether it trusts the check here."""

    kind = SYMBOLIC
    role = "review"
    cost = 0.05
    trusted_at = 0.97
    CHECKS = ("whole-number", "yes-or-no", "not-negative")

    def __init__(self, name="checker", seed=0):
        super().__init__(name, seed)
        self.reliability = Competence(prior_mean=0.7, strength=4.0, decay=0.998)

    def _holds(self, check, v):
        if check == "whole-number":
            return _whole(v)
        if check == "yes-or-no":
            return v in (0, 1)
        return v >= 0

    def _key(self, check, scene, final):
        return (check, "final" if final else "step") + scene.context + (scene.skeleton,)

    def review(self, scene, ws, step, value):
        final = step.op == STOP
        if value is None or value is UNKNOWABLE:
            return ()
        out = []
        for c in self.CHECKS:
            if c == "yes-or-no" and not final:
                continue
            key = (id(self), c, final)
            rel = scene.cache.get(key)
            if rel is None:
                rel = scene.cache[key] = self.reliability.mean(self._key(c, scene, final))
            out.append(f"{c}:{'pass' if self._holds(c, value) else 'fail'}:{'trusted' if rel >= self.trusted_at else 'weak'}")
        return tuple(out)

    def learn_review(self, scene, path, answer):
        for ws, step in path:
            final = step.op == STOP
            v = ws.answer if final else ws.run(step)
            if v is None or v is UNKNOWABLE:
                continue
            for c in self.CHECKS:
                if c == "yes-or-no" and not final:
                    continue
                self.reliability.update(self._key(c, scene, final), 1.0 if self._holds(c, v) else 0.0)


class EstimatorExpert(Expert):
    """Number sense: a learned guess of the answer's size."""

    kind = NEURAL
    role = "review"
    cost = 0.1

    def __init__(self, name="estimator", seed=0):
        super().__init__(name, seed)
        rng = np.random.default_rng(seed + 5)
        self.salt = int(rng.integers(1 << 30))
        self.net = _SparseMLP(48, rng, dense=len(numeric_features(read("1"))), n_out=1, lr=0.01)
        self.resid: dict = {}
        self.seen = 0

    def guess(self, scene):
        idx = scene.hashed(self.salt, ("u", "b", "s"))
        _, out = self.net.forward(idx, numeric_features(scene.reading))
        return float(out[0])

    def review(self, scene, ws, step, value):
        if step.op != STOP or value is None or value is UNKNOWABLE or self.seen < 200:
            return ()
        sd = max(math.sqrt(self.resid.get(scene.context, 1.0)), 0.15)
        z = abs(squash(float(value)) - self.guess(scene)) / sd
        return (f"size:{'close' if z <= 1 else 'loose' if z <= 2.5 else 'far' if z <= 5 else 'way-off'}",)

    def learn_review(self, scene, path, answer):
        if answer is None or answer is UNKNOWABLE:
            return
        idx = scene.hashed(self.salt, ("u", "b", "s"))
        dense = numeric_features(scene.reading)
        h, out = self.net.forward(idx, dense)
        y = squash(float(answer))
        err = float(out[0]) - y
        self.resid[scene.context] = 0.95 * self.resid.get(scene.context, 1.0) + 0.05 * min(err * err, 9.0)
        self.net.step(idx, dense, h, np.clip(out - y, -1.0, 1.0))
        self.seen += 1


def op_word(step: Step) -> str:
    """An operation as the lexicon sees it: scaling by a constant is its own word ("div:K100")."""
    k = [a for a in step.args if a[0] == "K"]
    return f"{step.op}:{k[0]}" if k else step.op


class LexiconExpert(Expert):
    """Learns which words go with which operations, from every worked solution
    (P(op | word) x PMI, as the maths parser does), and checks that a solution
    accounts for what the question says: which words a step explains, and
    which strongly operational words a finished solution leaves unexplained."""

    kind = SYMBOLIC
    role = "review"
    cost = 0.02

    def __init__(self, name="lexicon", seed=0, min_count: int = 3):
        super().__init__(name, seed)
        self.n = 0
        self.nw: Counter = Counter()
        self.no: Counter = Counter()
        self.nwo: Counter = Counter()
        self.min_count = min_count
        self._best: dict = {}

    def assoc(self, w, o) -> float:
        nwo = self.nwo[(w, o)]
        if nwo == 0 or self.nw[w] < self.min_count:
            return 0.0
        p = nwo / self.nw[w]
        pmi = math.log(nwo * self.n / (self.nw[w] * self.no[o]))
        return max(p * pmi, 0.0)

    def best(self, w):
        if w not in self._best:
            ops = self.__dict__.setdefault("ops_of", defaultdict(set)).get(w, ())
            scored = [(self.assoc(w, o), o) for o in sorted(ops)]
            self._best[w] = max(scored) if scored else (0.0, None)
        return self._best[w]

    def _meanings(self, scene):
        """(strength, best operation) for each word of the question, worked out once."""
        key = (id(self), "meanings", self.n)
        if key not in scene.cache:
            scene.cache[key] = [self.best(w) for w in sorted(set(scene.reading.words))]
        return scene.cache[key]

    @staticmethod
    def _bucket(x):
        return "0" if x < 0.25 else "lo" if x < 0.75 else "mid" if x < 1.5 else "hi"

    def review(self, scene, ws, step, value):
        if self.n < 50:
            return ()
        meanings = self._meanings(scene)
        done = {op_word(s) for s in ws.steps}
        if step.op == STOP:
            left = sum(s for s, o in meanings if o is not None and o not in done)
            return (f"unexplained:{self._bucket(left)}",)
        o = op_word(step)
        if o in done:
            return ("explains:repeat",)
        gain = sum(s for s, oo in meanings if oo == o)
        return (f"explains:{self._bucket(gain)}",)

    def learn_review(self, scene, path, answer):
        words = set(scene.reading.words)
        ops = {op_word(s) for _, s in path if s.op != STOP}
        self.n += 1
        self.nw.update(words)
        self.no.update(ops)
        self.nwo.update((w, o) for w in words for o in ops)
        index = self.__dict__.setdefault("ops_of", defaultdict(set))
        for w in words:
            index[w].update(ops)
        self._best.clear()


def _rel_bucket(p: float) -> str:
    return "lo" if p < 0.3 else "mid" if p < 0.7 else "hi"


class RelevanceExpert(Expert):
    """Learns which numbers in a question matter, from which ones worked
    solutions actually used: P(used | the words around it, the words of its
    sentence, how much its sentence shares with the question being asked).
    Tells the judge when stopping would leave numbers that matter unused, and
    when a step uses one that doesn't."""

    kind = SYMBOLIC
    role = "review"
    cost = 0.02

    def __init__(self, name="relevance", seed=0):
        super().__init__(name, seed)
        self.model = SparseLogLinear(lr=0.3)
        self.n = 0
        self.df: Counter = Counter()  # how many questions each word appeared in

    def _idf(self, w) -> float:
        return math.log((1 + self.n) / (1 + self.df[w]))

    def _feats(self, scene, fact) -> dict:
        sk, sent = scene.skeleton, scene.reading.sentences
        f = {"bias": 1.0, f"unknown:{int(fact.value is UNKNOWABLE)}": 1.0}
        for left, left2, right in scene.around(fact):
            f[f"L:{left}"] = f[f"LL:{left2}_{left}"] = f[f"R:{right}"] = 1.0
        if fact.where and sent:
            p = fact.where[0]
            mine = {sk[j] for j in range(len(sk)) if sent[j] == sent[p] and not sk[j].startswith("<") and sk[j] != "#"}
            last = max(sent)
            if sent[p] == last:
                f["in-question"] = 1.0
            else:
                # how much its sentence shares with the question asked, rare words counting most
                asked = {sk[j] for j in range(len(sk)) if sent[j] == last and not sk[j].startswith("<") and sk[j] != "#"}
                shared = sum(self._idf(w) for w in sorted(mine & asked))
                f[f"shares:{0 if shared == 0 else 1 if shared < 1.5 else 2 if shared < 3 else 3 if shared < 5 else 4}"] = 1.0
            for w in mine:
                f[f"s:{w}"] = 1.0
        return f

    def relevance(self, scene, ws) -> dict:
        """P(used) for each number in the question."""
        key = (id(self), "rel", self.n)
        out = scene.cache.get(key)
        if out is None:
            out = scene.cache[key] = {r: sigmoid(self.model.score(self._feats(scene, f)))
                                      for r, f in ws.facts.items() if f.kind == NUM}
        return out

    def review(self, scene, ws, step, value):
        if self.n < 50:
            return ()
        rel = self.relevance(scene, ws)
        if step.op == STOP:
            open_ = [rel[r] for r in ws.unused if r in rel]
            left = sum(1 for p in open_ if p >= 0.5)
            return (f"open-relevant:{min(left, 2)}", f"open-max:{_rel_bucket(max(open_, default=0.0))}")
        if step.op in TERMINAL:
            return ()
        ps = [rel[a] for a in step.args if a in rel]
        if not ps:
            return ()
        return (f"uses:{_rel_bucket(min(ps))}",)

    def learn_review(self, scene, path, answer):
        if not path or path[-1][1].op == INSUFFICIENT:
            return
        ws0 = path[0][0]
        used = {a for _, s in path for a in s.args}
        for r, f in ws0.facts.items():
            if f.kind != NUM:
                continue
            feats = self._feats(scene, f)
            self.model.step(feats, sigmoid(self.model.score(feats)) - (1.0 if r in used else 0.0))
        self.n += 1
        self.df.update(set(scene.skeleton))


def population(n_neural: int = 8, seed: int = 0, operators=None, memory=True, analogy=True, lexicon=True,
               relevance=True, domain=None) -> list:
    """One bench of the room's members: an operator expert per operation of the
    domain, the neural pool, memory and analogy, the goal expert, the domain's
    own reviewers, and the general reviewers."""
    domain = domain or ARITH
    ops = list(domain.ops) if operators is None else list(operators)
    experts = [OperatorExpert(op, seed + i) for i, op in enumerate(ops)]
    binders = {e.op: e for e in experts}
    tokens = list(domain.ops) + [STOP] + ([INSUFFICIENT] if domain.missing_info else [])
    tokens = list(dict.fromkeys(tokens))
    for k in range(n_neural):
        n = NeuralExpert(f"neural-{k + 1}", seed * 101 + k, tokens=tokens)
        n.binders = binders
        experts.append(n)
    if memory:
        experts.append(MemoryExpert(seed=seed))
    if analogy:
        experts.append(AnalogyExpert(seed=seed))
    experts += [GoalExpert(seed=seed)] + domain.reviewers(seed)
    if lexicon:
        experts.append(LexiconExpert(seed=seed))
    if relevance:
        experts.append(RelevanceExpert(seed=seed))
    return experts
