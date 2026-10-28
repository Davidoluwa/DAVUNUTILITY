"""The maths council: two symbolic and two neural nodes.

parser     symbolic  learns what wordings mean by searching for programs that
                     reproduce answers; generalises by analogy with known
                     wordings and by composing programs from learned word meanings
reader     neural    learns wording -> program from what the parser discovers;
                     generalises to paraphrases and new word problems
estimator  neural    number sense: predicts an answer's rough size, vetoes
                     answers that are wildly off
checker    symbolic  back-substitution and answer-shape checks, each with a
                     learned reliability
"""
from __future__ import annotations

import math
import zlib
from collections import Counter

import numpy as np

from ..beliefs import Competence, conf_bucket
from ..node import Node
from ..protocol import NEURAL, SYMBOLIC, Proposal, Verdict
from .mathlang import read
from .programs import (BINARY, CONSTANTS, LIST_OPS, UNARY, coverage, describe, enumerate_programs, explain,
                       matches, primitives, run, size)

FEATURE_DIM = 4096


def feature_strings(reading) -> set:
    toks = list(reading.skeleton)
    feats = {"s:" + reading.slots}
    feats.update("u:" + t for t in toks)
    feats.update(f"b:{a} {b}" for a, b in zip(toks, toks[1:]))
    return feats


def featurize(reading) -> np.ndarray:
    return np.array(sorted({zlib.crc32(f.encode()) % FEATURE_DIM for f in feature_strings(reading)}), dtype=np.int64)


def _num(v) -> str:
    v = float(v)
    return f"{v:g}" if abs(v - round(v)) > 1e-9 else str(int(round(v)))


class _MathNode(Node):
    def reading(self, view):
        sc = self.scratch(view)
        if "reading" not in sc:
            sc["reading"] = read(view.question)
        return sc["reading"]


# =============================================================================
# Parser (symbolic)
# =============================================================================
class ParserNode(_MathNode):
    kind = SYMBOLIC
    lexical_cost = 3.0

    def __init__(self, name: str = "parser", seed: int = 0):
        super().__init__(name, seed)
        self.memory: dict = {}  # skeleton -> {program: [hits, misses]}
        self.by_slots: dict = {}  # slot signature -> set of skeletons
        self.word_prim: Counter = Counter()
        self.word_n: Counter = Counter()
        self.prim_n: Counter = Counter()
        self.lex_total = 0.0
        self.skel_df: Counter = Counter()
        self._pending: dict = {}

    # -- memory of wordings ----------------------------------------------
    def ranked(self, skel, r):
        entry = self.memory.get(skel)
        if not entry:
            return []
        items = []
        for prog, (h, m) in entry.items():
            v = run(prog, r)
            if v is not None:
                items.append((h - 3 * m, coverage(prog, r), -size(prog), prog, v))
        items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        return items

    # -- word meanings ---------------------------------------------------
    def assoc(self, word, prim) -> float:
        """How strongly a word implies a primitive: P(prim | word) * PMI.
        Plain PMI over-rates rare primitives; weighting by P(prim | word)
        keeps 'how many' from 'meaning' a unit conversion it once sat next to."""
        c = self.word_prim[(word, prim)]
        if c <= 0:
            return 0.0
        p_given_w = c / (self.word_n[word] + 1.0)
        pmi = math.log((c * self.lex_total) / ((self.word_n[word] + 1.0) * (self.prim_n[prim] + 1.0)))
        return max(0.0, p_given_w * pmi)

    def cues(self, r):
        """table[prim] = [(word, strength)] and strength[word] = its strongest pull."""
        words = sorted(set(r.words))
        table, strength = {}, {}
        for p in self.prim_n:
            for w in words:
                a = self.assoc(w, p)
                if a > 0.05:
                    table.setdefault(p, []).append((w, a))
                    strength[w] = max(strength.get(w, 0.0), a)
        return table, strength

    def _lex_score(self, prog, cues):
        """Each word may justify at most one primitive (explaining away); every
        primitive costs 1; strongly operational words left unexplained cost too."""
        table, strength = cues
        prims = primitives(prog)
        pairs = sorted(((a, w, i) for i, p in enumerate(prims) for w, a in table.get(p, ())), reverse=True)
        used_w, used_i, total, why = set(), set(), 0.0, []
        for a, w, i in pairs:
            if w in used_w or i in used_i:
                continue
            used_w.add(w)
            used_i.add(i)
            total += a
            why.append((prims[i], w))
        present = set(prims)
        ignored = sum(v for w, v in strength.items()
                      if w not in used_w and v >= 1.0 and self._top_prim(w, table) not in present)
        return total - 1.0 * len(prims) - 0.7 * ignored, why

    @staticmethod
    def _top_prim(word, table):
        best, top = 0.0, None
        for p, pairs in table.items():
            for w, a in pairs:
                if w == word and a > best:
                    best, top = a, p
        return top

    @staticmethod
    def edits(prog):
        """Programs one change away: swap an operation for a sibling, flip
        argument order, or change a constant."""
        out = []
        op = prog[0]
        if op in ("N", "K", "L", "Q", "F", "C", "X"):
            if op == "K":
                out += [("K", k) for k in CONSTANTS if k != prog[1]]
            return out
        sibs = []
        if op in BINARY and len(prog) == 3:
            sibs = [o for o in BINARY if o != op]
            out.append((op, prog[2], prog[1]))
        elif op in UNARY:
            sibs = [o for o in UNARY if o != op]
        elif op in LIST_OPS:
            sibs = [o for o in LIST_OPS if o != op]
        elif op in ("at", "slope"):
            sibs = ["slope" if op == "at" else "at"]
        out += [(o,) + prog[1:] for o in sibs]
        for i, arg in enumerate(prog[1:], start=1):
            out += [prog[:i] + (e,) + prog[i + 1:] for e in ParserNode.edits(arg)]
        return out

    def similar(self, r, k=3):
        cands = sorted(self.by_slots.get(r.slots, ()))  # sorted: ties must not depend on set order
        S = len(self.memory)
        mine = set(r.skeleton)

        def w(t):
            return math.log(1 + S / (1 + self.skel_df[t]))

        scored = []
        for skel in cands:
            other = set(skel)
            union = sum(w(t) for t in mine | other)
            scored.append((sum(w(t) for t in mine & other) / union if union else 0.0, skel))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]

    def analogize(self, r):
        """Answer an unfamiliar wording: start from similar known wordings (and
        programs one edit away from theirs), or compose a fresh program, and
        let learned word meanings pick. Returns (mode, prog, value, why, margin, spent)."""
        cues = self.cues(r)
        cands = {}  # prog -> (score, value, mode, why, word alignment)
        spent = 0.6

        def offer(prog, bonus, mode, why, sim=0.0):
            v = run(prog, r)
            if v is None:
                return
            score, align = self._lex_score(prog, cues)
            score += bonus
            if prog not in cands or cands[prog][0] < score:
                cands[prog] = (score, v, mode, why, align, sim)

        for sim, skel in self.similar(r):
            items = self.ranked(skel, r)
            if not items or items[0][0] <= 0:
                continue
            base = items[0][3]
            like = f"like '{' '.join(skel)}' ({sim:.2f})"
            offer(base, 2.0 * sim, "analogy", like, sim)
            for e in self.edits(base):
                if coverage(e, r) == 1.0:
                    offer(e, 2.0 * sim - 0.75, "analogy-edit", like + ", with one change", sim)
        best_analogy = max((c[0] for c in cands.values()), default=-9.0)
        if best_analogy < 2.0 and self.lex_total > 0:
            spent += self.lexical_cost
            table = cues[0]
            for prog, v in enumerate_programs(r, depth=2):
                if coverage(prog, r) < 1.0:
                    continue
                prims = primitives(prog)
                if prims and sum(p not in table for p in prims) <= 1:
                    offer(prog, 0.0, "lexical", "composed from word meanings")
        if not cands:
            return None
        ranked = sorted(cands.items(), key=lambda kv: kv[1][0], reverse=True)
        prog, (score, value, mode, why, align, sim) = ranked[0]
        rival = next((c for p, c in ranked[1:] if not matches(c[1], float(value))), None)
        margin = score - rival[0] if rival else 5.0
        if align:
            why += "; cues: " + ", ".join(f"'{w}'->{p}" for p, w in align)
        closeness = "near" if sim >= 0.6 else "far" if sim > 0 else "none"
        return mode, prog, value, why, (closeness, "clear" if margin > 1.0 else "close"), spent

    # -- capabilities ----------------------------------------------------
    def glance(self, view):
        r = self.reading(view)
        sc = self.scratch(view)
        items = self.ranked(r.skeleton, r)
        if items and items[0][0] > 0:
            top = items[0]
            rivals = [it for it in items[1:] if it[0] == top[0] and not matches(it[4], float(top[4]))]
            sup = top[0]
            sc["plan"] = ("known", top[3], top[4], f"wording seen before ({sup:g} confirmations)")
            return ("known", "1" if sup < 2 else "2-4" if sup < 5 else "5+",
                    "ambiguous" if rivals else "unique"), 0.2, 0.0
        found = self.analogize(r)
        if found is None:
            sc["plan"] = None
            return ("none",), 0.6, 0.0
        mode, prog, value, why, quality, spent = found
        sc["plan"] = (mode, prog, value, why)
        return (mode,) + quality, spent, 0.0

    def solve(self, view) -> Proposal:
        sc = self.scratch(view)
        cost = 0.0
        if "plan" not in sc:
            ev, spent, _ = self.glance(view)
            sc["glance_ev"] = ev
            cost += spent
        ev = sc.get("glance_ev") or ("none",)
        plan = sc["plan"]
        if plan is None:
            return Proposal(self.name, self.kind, float("nan"), 0.0, cost, "no idea what this asks", ("none",))
        mode, prog, value, why = plan
        sc["program"] = prog
        conf = min(self.competence.mean(("p",) + tuple(ev) + view.context), 0.99)
        return Proposal(self.name, self.kind, float(value), conf, cost, f"{describe(prog)}  [{why}]", tuple(ev), prog)

    # -- learning --------------------------------------------------------
    def explain(self, record):
        """For a labeled task, share which programs explain the answer."""
        if record.label is None:
            return None
        view = record.view
        r = read(view.question)
        entry = self.memory.get(r.skeleton, {})
        consistent = [p for p in entry if (v := run(p, r)) is not None and matches(v, record.label)]
        searched = False
        if not consistent:
            consistent = explain(r, record.label)
            searched = True
            self.maintenance_cost += 2.0
        self._pending[view.id] = (r, consistent, searched)
        if not consistent:
            return None
        if searched:
            top = consistent[0]
            best = [p for p in consistent if coverage(p, r) == coverage(top, r) and size(p) == size(top)]
        else:
            def after(p):
                h, m = entry[p]
                return h + 1 - 3 * m
            hi = max(after(p) for p in consistent)
            best = [p for p in consistent if after(p) == hi]
        return {"best": best, "searched": searched}

    def learn(self, view, value, source, record) -> None:
        if source in ("label", "asked"):
            r, consistent, searched = self._pending.pop(view.id, (None, None, None))
            if r is None:
                return
            entry = self.memory.setdefault(r.skeleton, {})
            if not entry:
                self.by_slots.setdefault(r.slots, set()).add(r.skeleton)
                for t in set(r.skeleton):
                    self.skel_df[t] += 1
            for p in list(entry):
                if p in consistent:
                    entry[p][0] += 1
                else:
                    entry[p][1] += 1
                    if entry[p][1] > entry[p][0] + 2:
                        del entry[p]
            if searched:
                for p in consistent:
                    entry.setdefault(p, [1, 0])
            note = record.notes.get(self.name)
            if note:
                self._learn_words(r, note["best"], 1.0)
        elif source == "certified" and record.final is not None and record.final.program is not None:
            # The council was confident enough to teach from this answer:
            # remember it (weakly) as a meaning for a wording I didn't know.
            r = read(view.question)
            prog = record.final.program
            v = run(prog, r)
            if v is None or not matches(v, value) or r.skeleton in self.memory:
                return
            entry = self.memory.setdefault(r.skeleton, {})
            if not entry:
                self.by_slots.setdefault(r.slots, set()).add(r.skeleton)
                for t in set(r.skeleton):
                    self.skel_df[t] += 1
                self.stats["wordings_learned_from_council"] += 1
            entry.setdefault(prog, [0.0, 0.0])[0] += 0.5
            self._learn_words(r, [prog], 0.5)

    def _learn_words(self, r, progs, weight):
        if not progs:
            return
        share = weight / len(progs)
        words = set(r.words)
        for prog in progs:
            prims = set(primitives(prog))
            for p in prims:
                self.prim_n[p] += share
                for w in words:
                    self.word_prim[(w, p)] += share
        for w in words:
            self.word_n[w] += weight
        self.lex_total += weight

    def meanings(self, top: int = 3):
        """The strongest learned word -> primitive associations."""
        out = {}
        for p in sorted(self.prim_n, key=lambda p: -self.prim_n[p]):
            ws = sorted(self.word_n, key=lambda w: -self.assoc(w, p))[:top]
            ws = [w for w in ws if self.assoc(w, p) > 0.5]
            if ws:
                out[p] = ws
        return out


# =============================================================================
# Reader (neural)
# =============================================================================
class _SparseMLP:
    def __init__(self, hidden, rng, dense=0, n_out=0, lr=0.05):
        self.rng, self.lr = rng, lr
        self.W1 = rng.normal(0, 0.05, (FEATURE_DIM, hidden))
        self.b1 = np.zeros(hidden)
        self.Wd = rng.normal(0, 0.1, (dense, hidden)) if dense else None
        self.W2 = rng.normal(0, 0.05, (hidden, n_out))
        self.b2 = np.zeros(n_out)

    def grow(self, n):
        extra = n - self.W2.shape[1]
        if extra > 0:
            self.W2 = np.hstack([self.W2, self.rng.normal(0, 0.05, (self.W2.shape[0], extra))])
            self.b2 = np.concatenate([self.b2, np.zeros(extra)])

    def hidden(self, idx, dense=None):
        a = self.W1[idx].sum(0) + self.b1
        if self.Wd is not None and dense is not None:
            a = a + dense @ self.Wd
        return np.tanh(a)

    def forward(self, idx, dense=None):
        h = self.hidden(idx, dense)
        return h, h @ self.W2 + self.b2

    def step(self, idx, dense, h, grad_out):
        gh = (self.W2 @ grad_out) * (1 - h ** 2)
        self.W2 -= self.lr * np.outer(h, grad_out)
        self.b2 -= self.lr * grad_out
        self.W1[idx] -= self.lr * gh
        self.b1 -= self.lr * gh
        if self.Wd is not None and dense is not None:
            self.Wd -= self.lr * np.outer(dense, gh)


class ReaderNode(_MathNode):
    kind = NEURAL

    def __init__(self, name: str = "reader", seed: int = 0, hidden: int = 64, steps: int = 5, members: int = 3):
        super().__init__(name, seed)
        self.nets = [_SparseMLP(hidden, np.random.default_rng(seed * 101 + m)) for m in range(members)]
        self.programs: list = []
        self.index: dict = {}
        self.buffer: list = []
        self.steps = steps
        self.structures: set = set()  # combinations of words-that-matter seen in training
        self.vocab: set = set()
        self._recent: list = []  # recent training readings, to recompute structures
        self._threshold = None
        self._since_threshold = 0

    def _pid(self, prog):
        if prog not in self.index:
            self.index[prog] = len(self.programs)
            self.programs.append(prog)
            for net in self.nets:
                net.grow(len(self.programs))
        return self.index[prog]

    def importance(self, word) -> float:
        """How much my networks rely on a word (norm of its learned input weights)."""
        i = zlib.crc32(("u:" + word).encode()) % FEATURE_DIM
        return float(np.mean([np.linalg.norm(net.W1[i]) for net in self.nets]))

    def structure(self, r):
        """The question's shape as *I* see it: its notation plus the words my
        networks actually rely on. New names or objects don't change it; a new
        combination of operation words does."""
        if self._threshold is None:
            return (r.slots,)
        return (r.slots,) + tuple(sorted({w for w in r.words if self.importance(w) >= self._threshold}))

    def _refresh_threshold(self):
        imps = [self.importance(w) for w in self.vocab]
        self._threshold = float(np.percentile(imps, 70)) if imps else None
        self.structures = {self.structure(r) for r in self._recent}

    def predict(self, view):
        """(program, value, mean prob, members agree?, novel structure?) or None."""
        sc = self.scratch(view)
        if "pred" in sc:
            return sc["pred"]
        r = self.reading(view)
        pred = None
        if self.programs:
            idx = featurize(r)
            probs = []
            for net in self.nets:
                _, z = net.forward(idx)
                p = np.exp(z - z.max())
                probs.append(p / p.sum())
            mean = np.mean(probs, axis=0)
            order = np.argsort(-mean)[:12]
            live = {int(k): v for k in order if (v := run(self.programs[int(k)], r)) is not None}
            if live:
                keys = list(live)
                m = mean[keys] / mean[keys].sum()
                k = keys[int(np.argmax(m))]
                votes = {keys[int(np.argmax(p[keys]))] for p in probs}
                novel = self.structure(r) not in self.structures
                pred = (self.programs[k], live[k], float(m.max()), len(votes) == 1, novel)
        sc["pred"] = pred
        return pred

    def _evidence(self, pred):
        _, _, prob, agree, novel = pred
        # Novelty first: "how good am I on new ground" must be learned from new
        # ground, not borrowed from my (excellent) record on familiar questions.
        return ("r", "novel" if novel else "familiar", "agree" if agree else "split", conf_bucket(prob))

    def solve(self, view) -> Proposal:
        sc = self.scratch(view)
        cost = 0.0 if "pred" in sc else 0.5
        pred = self.predict(view)
        if pred is None:
            return Proposal(self.name, self.kind, float("nan"), 0.0, cost, "nothing learned yet", ("r", "none"))
        prog, v, prob, agree, novel = pred
        ev = self._evidence(pred)
        conf = min(self.competence.mean(("p",) + ev + view.context), 0.99)
        note = ("ensemble agrees" if agree else "ensemble split") + (", never seen this combination" if novel else "")
        return Proposal(self.name, self.kind, float(v), conf, cost,
                        f"{describe(prog)}  [reads like it, p={prob:.2f}, {note}]", ev, prog)

    def learn(self, view, value, source, record) -> None:
        r = read(view.question)
        targets = None
        if source in ("label", "asked"):
            note = record.notes.get("parser")
            if note and note["best"]:
                targets = note["best"]
            else:  # self-supervised: does my own reading reproduce the label?
                pred = self.predict(view)
                if pred and matches(pred[1], value):
                    targets = [pred[0]]
        elif record.final is not None and record.final.program is not None:
            targets = [record.final.program]
        if not targets:
            return
        idx = featurize(r)
        self.vocab.update(r.words)
        self._recent.append(r)
        if len(self._recent) > 6000:
            self._recent.pop(0)
        self._since_threshold += 1
        if self._threshold is None or self._since_threshold >= 250:
            self._since_threshold = 0
            self._refresh_threshold()
        self.structures.add(self.structure(r))
        self.buffer.append((idx, [self._pid(p) for p in targets]))
        if len(self.buffer) > 6000:
            self.buffer.pop(0)
        for net in self.nets:
            for _ in range(self.steps):
                i, ids = self.buffer[int(self.rng.integers(len(self.buffer)))]
                h, z = net.forward(i)
                p = np.exp(z - z.max())
                p /= p.sum()
                target = np.zeros_like(p)
                target[ids] = 1.0 / len(ids)
                net.step(i, None, h, p - target)


# =============================================================================
# Estimator (neural number sense)
# =============================================================================
def _lg(x) -> float:
    return math.log10(1 + abs(float(x)))


def numeric_features(r) -> np.ndarray:
    f = []
    nums = [float(x) for x in r.nums[:3]]
    nums += [0.0] * (3 - len(nums))
    for x in nums:
        f += [np.sign(x), _lg(x)]
    f.append(len(r.nums) / 3)
    if r.lists:
        xs = [float(x) for x in r.lists[0]]
        f += [_lg(xs[-1]), _lg(np.mean(np.abs(xs))), np.sign(xs[-1]), _lg(xs[-1] - xs[-2])]
    else:
        f += [0.0] * 4
    if r.eqs:
        c = r.eqs[0].c
        f += [_lg(c.get(0, 0)), _lg(c.get(1, 0))]
    else:
        f += [0.0, 0.0]
    polys = [p for _, p in r.fdefs] + [p for p in r.exprs if not p.is_const]
    f += [polys[0].degree / 3, _lg(max(abs(v) for v in polys[0].c.values()))] if polys else [0.0, 0.0]
    f.append(_lg(r.calls[0][1]) if r.calls else 0.0)
    consts = [p for p in r.exprs if p.is_const]
    f += [np.sign(float(consts[0].value)), _lg(consts[0].value)] if consts else [0.0, 0.0]
    return np.array(f, dtype=float)


def squash(v: float) -> float:
    return math.copysign(math.log10(1 + abs(v)), v)


class EstimatorNode(_MathNode):
    kind = NEURAL
    solves = False

    def __init__(self, name: str = "estimator", seed: int = 0, hidden: int = 48):
        super().__init__(name, seed)
        self.net = _SparseMLP(hidden, self.rng, dense=len(numeric_features(read("1"))), n_out=1, lr=0.01)
        self.buffer: list = []
        self.resid: dict = {}
        self.familiar: set = set()

    def guess(self, view):
        sc = self.scratch(view)
        if "guess" not in sc:
            r = self.reading(view)
            _, out = self.net.forward(featurize(r), numeric_features(r))
            sc["guess"] = float(out[0])
        return sc["guess"]

    def critique(self, view, proposal) -> Verdict:
        """Report how far the candidate's size is from my guess, in my own
        standard deviations, and how familiar the question looks to me."""
        if len(self.buffer) < 150 or not math.isfinite(proposal.value):
            return Verdict(self.name, self.kind, None, 0.3, "no feel for this yet")
        feats = feature_strings(self.reading(view))
        unfamiliar = sum(f not in self.familiar for f in feats) / max(len(feats), 1)
        y = self.guess(view)
        sd = max(math.sqrt(self.resid.get(view.context, 1.0)), 0.15)
        z = abs(squash(proposal.value) - y) / sd
        gap = "close" if z <= 1 else "loose" if z <= 2.5 else "far" if z <= 5 else "way-off"
        familiarity = "familiar" if unfamiliar == 0 else "partly-new" if unfamiliar <= 0.15 else "new"
        guess = f"{math.copysign(10 ** abs(y) - 1, y):.3g}"
        return Verdict(self.name, self.kind, z <= 2.5, 0.3, f"I'd guess about {guess}; this is {gap} ({familiarity} question)",
                       evidence=(f"size:{gap}", f"seen:{familiarity}"))

    def learn(self, view, value, source, record) -> None:
        if source != "label":
            return
        r = read(view.question)
        idx, dense = featurize(r), numeric_features(r)
        self.familiar.update(feature_strings(r))
        y = squash(value)
        h, out = self.net.forward(idx, dense)
        err = float(out[0]) - y
        self.resid[view.context] = 0.95 * self.resid.get(view.context, 1.0) + 0.05 * min(err * err, 9.0)
        self.buffer.append((idx, dense, y))
        if len(self.buffer) > 6000:
            self.buffer.pop(0)
        for _ in range(4):
            i, d, t = self.buffer[int(self.rng.integers(len(self.buffer)))]
            h, out = self.net.forward(i, d)
            g = np.clip(out - t, -1.0, 1.0)
            self.net.step(i, d, h, g)


# =============================================================================
# Checker (symbolic)
# =============================================================================
def _is_whole(v):
    return abs(v - round(v)) < 1e-9


class CheckerNode(_MathNode):
    kind = SYMBOLIC
    solves = False
    trusted_at = 0.97

    CHECKS = ("satisfies-the-equation", "whole-number", "yes-or-no", "inside-the-list")

    def __init__(self, name: str = "checker", seed: int = 0):
        super().__init__(name, seed)
        self.reliability = Competence(prior_mean=0.7, strength=4.0, decay=0.998)

    def _applies(self, check, r):
        if check == "satisfies-the-equation":
            return len(r.eqs) == 1 and r.eqs[0].degree == 1
        if check == "whole-number":
            return all(v.denominator == 1 for v in r.all_numbers())
        if check == "yes-or-no":
            return True
        return bool(r.lists) and len(r.lists) + len(r.nums) + len(r.eqs) + len(r.exprs) == 1

    def _holds(self, check, r, v):
        if not math.isfinite(v):
            return False
        if check == "satisfies-the-equation":
            from fractions import Fraction
            return r.eqs[0].at(Fraction(v).limit_denominator(10 ** 6)) == 0
        if check == "whole-number":
            return _is_whole(v)
        if check == "yes-or-no":
            return v in (0.0, 1.0)
        xs = [float(x) for x in r.lists[0]]
        return min(xs) <= v <= max(xs)

    def critique(self, view, proposal) -> Verdict:
        """Report every applicable check: pass or fail, and whether its track
        record for this kind of question makes it one I'd stand behind."""
        r = self.reading(view)
        signals, broken_trusted, any_trusted = [], [], False
        for c in self.CHECKS:
            if not self._applies(c, r):
                continue
            rel = self.reliability.mean((c,) + view.context + (r.skeleton,))
            ok = self._holds(c, r, proposal.value)
            trust = "trusted" if rel >= self.trusted_at else "weak"
            any_trusted |= trust == "trusted"
            signals.append(f"{c}:{'pass' if ok else 'fail'}:{trust}")
            if trust == "trusted" and not ok:
                broken_trusted.append(c)
        endorses = None if not any_trusted else not broken_trusted
        why = ", ".join(s.replace(":", " ", 1) for s in signals) or "no check applies"
        return Verdict(self.name, self.kind, endorses, 0.1, why, evidence=tuple(signals))

    def learn(self, view, value, source, record) -> None:
        if source != "label":
            return
        r = read(view.question)
        for c in self.CHECKS:
            if self._applies(c, r):
                self.reliability.update((c,) + view.context + (r.skeleton,), 1.0 if self._holds(c, r, value) else 0.0)
