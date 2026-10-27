"""Inducer: symbolic program induction that *learns how to search*.

It explains a sequence with an explicit law from a small grammar (linear
recurrences, polynomials, periodicities, ...), fitted by least squares and
snapped to exact rationals. What keeps it from being a stiff rule engine:

* **learned search priors** - per situation it learns which kinds of laws tend
  to be true and tries those first, so familiar problems get cheap;
* **concept invention** - laws that keep being confirmed with the same
  coefficients (e.g. x[n] = x[n-1] + x[n-2]) are promoted to named concepts
  that are checked almost for free;
* **graded belief** - when no law fits exactly it still offers its best
  approximate law with an honest predictive spread, instead of failing hard;
* **self-revision** - each law's reliability is tracked per situation, so laws
  that keep getting refuted lose credibility where they fail;
* **knowing when not to reason exactly** - it learns where exact laws never
  turn up (noisy data) and switches to a cheap approximate mode there, using
  the approximate laws that have actually worked in that situation;
* it explains itself: every answer ships with the law that produced it.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..beliefs import Competence, conf_bucket, erf_conf
from ..node import Node
from ..protocol import SYMBOLIC, Proposal, Verdict


@dataclass(frozen=True)
class Template:
    name: str
    base_lag: int = 0  # fixed part x[n-base_lag] (0 = none)
    lags: tuple = ()  # free coefficients on x[n-l]
    const: bool = False
    powers: tuple = ()  # free coefficients on n**p
    complexity: int = 1

    @property
    def n_params(self) -> int:
        return len(self.lags) + int(self.const) + len(self.powers)

    @property
    def cost(self) -> float:
        return 0.3 + 0.2 * self.n_params

    @property
    def start(self) -> int:
        return max((self.base_lag,) + self.lags + (0,))

    def row(self, h, n):
        r = [h[n - l] for l in self.lags]
        if self.const:
            r.append(1.0)
        r.extend(float(n) ** p for p in self.powers)
        return r

    def base(self, h, n) -> float:
        return h[n - self.base_lag] if self.base_lag else 0.0

    def describe(self, coef) -> str:
        terms = [f"x[n-{self.base_lag}]"] if self.base_lag else []
        names = [f"x[n-{l}]" for l in self.lags] + (["1"] if self.const else []) + [f"n^{p}" for p in self.powers]
        for c, nm in zip(coef, names):
            if abs(c) < 1e-12:
                continue
            c_txt = _fmt(c)
            terms.append(c_txt if nm == "1" else (nm if c_txt == "1" else f"-{nm}" if c_txt == "-1" else f"{c_txt}*{nm}"))
        body = " + ".join(terms).replace("+ -", "- ") if terms else "0"
        return f"x[n] = {body}"


def _fmt(c: float) -> str:
    for den in (1, 2, 3, 4, 6):
        if abs(c * den - round(c * den)) < 1e-9:
            num = int(round(c * den))
            return str(num) if den == 1 else f"{num}/{den}"
    return f"{c:.3g}"


GRAMMAR = (
    Template("constant", const=True, complexity=1),
    Template("arithmetic", base_lag=1, const=True, complexity=2),
    Template("geometric", lags=(1,), complexity=2),
    Template("period-2", base_lag=2, complexity=2),
    Template("period-3", base_lag=3, complexity=2),
    Template("line", const=True, powers=(1,), complexity=2),
    Template("interleaved", base_lag=2, const=True, complexity=3),
    Template("affine", lags=(1,), const=True, complexity=3),
    Template("recurrence-2", lags=(1, 2), complexity=3),
    Template("quadratic", const=True, powers=(1, 2), complexity=3),
    Template("recurrence-2+c", lags=(1, 2), const=True, complexity=4),
    Template("recurrence-3", lags=(1, 2, 3), complexity=4),
    Template("cubic", const=True, powers=(1, 2, 3), complexity=4),
)


@dataclass
class Fit:
    template: Template
    coef: np.ndarray
    prediction: float
    exact: bool
    sd: float = 0.0
    score: float = 0.0  # lower is better (approximate fits only)
    concept: Optional[str] = None


def _snap(coef):
    out = coef.copy()
    for i, c in enumerate(coef):
        for den in (1, 2, 3, 4, 6):
            r = round(c * den) / den
            if abs(c - r) <= 1e-6 * max(1.0, abs(c)):
                out[i] = r
                break
    return out


def fit_template(t: Template, h: np.ndarray, coef: Optional[np.ndarray] = None) -> Optional[Fit]:
    L = len(h)
    rows = range(t.start, L)
    if len(rows) < t.n_params + 2:
        return None
    A = np.array([t.row(h, n) for n in rows], dtype=float).reshape(len(rows), t.n_params)
    y = np.array([h[n] - t.base(h, n) for n in rows], dtype=float)
    scale = 1.0 + float(np.max(np.abs(h)))
    nxt = np.array(t.row(h, L), dtype=float)
    if coef is None:
        coef = np.linalg.lstsq(A, y, rcond=None)[0] if t.n_params else np.zeros(0)
        snapped = _snap(coef)
        if np.max(np.abs(y - A @ snapped)) <= 1e-7 * scale:
            coef = snapped
    resid = y - A @ coef
    pred = t.base(h, L) + float(nxt @ coef)
    if np.max(np.abs(resid)) <= 1e-7 * scale:
        return Fit(t, coef, pred, True)
    n, p = len(y), t.n_params
    rss = float(resid @ resid)
    sigma2 = rss / max(n - p, 1)
    lever = float(nxt @ np.linalg.pinv(A.T @ A) @ nxt) if p else 0.0
    sd = math.sqrt(sigma2 * (1.0 + lever))
    # Prefer the law that predicts most tightly, with a mild Occam penalty.
    score = math.log(sd + 1e-12) + 0.1 * t.complexity
    return Fit(t, coef, pred, False, sd, score)


class InducerNode(Node):
    kind = SYMBOLIC
    concept_threshold = 4
    max_concepts = 6
    glance_templates = 2
    review_templates = 4
    approx_templates = 3
    explore_exact = 0.1

    def __init__(self, name: str = "inducer", seed: int = 0, concept_cost: float = 0.05):
        super().__init__(name, seed)
        self.grammar = GRAMMAR
        # Learned search prior: Dirichlet counts of confirmed laws, per situation.
        self.law_counts = defaultdict(Counter)
        # Learned: do exact laws exist at all in this situation? And which
        # approximate laws have actually been right here?
        self.exact_exists = Competence(prior_mean=0.5, strength=2.0, decay=0.99)
        self.approx_counts = defaultdict(Counter)
        self.concepts = Counter()  # (template name, coef tuple) -> confirmations
        self.concept_cost = concept_cost
        self.bias = 0.0  # simulation hook for faults

    # -- search strategy -------------------------------------------------
    def search_order(self, sig):
        local, glob = self.law_counts[sig], self.law_counts[None]

        def weight(t):
            simplicity = 2.0 * math.exp(-0.8 * t.complexity)
            return local[t.name] + 0.3 * glob[t.name] + simplicity

        return sorted(self.grammar, key=weight, reverse=True)

    def active_concepts(self):
        live = [(k, c) for k, c in self.concepts.items() if c >= self.concept_threshold]
        return [k for k, _ in sorted(live, key=lambda kv: -kv[1])[: self.max_concepts]]

    def _state(self, view):
        sc = self.scratch(view)
        if "h" not in sc:
            sc.update(h=np.asarray(view.history, dtype=float), tried=set(), exact=None, approx=[],
                      spent=0.0, order=self.search_order(view.context))
        return sc

    def _try_concepts(self, sc):
        if sc.get("concepts_tried"):
            return
        sc["concepts_tried"] = True
        by_name = {t.name: t for t in self.grammar}
        for name, coef in self.active_concepts():
            sc["spent"] += self.concept_cost
            f = fit_template(by_name[name], sc["h"], np.array(coef, dtype=float))
            if f is not None and f.exact:
                f.concept = f"{name}{list(coef)}"
                sc["exact"] = f
                return

    def _search(self, sc, budget: Optional[int]) -> None:
        done = 0
        for t in sc["order"]:
            if sc["exact"] is not None or (budget is not None and done >= budget):
                return
            if t.name in sc["tried"]:
                continue
            sc["tried"].add(t.name)
            sc["spent"] += t.cost
            done += 1
            f = fit_template(t, sc["h"])
            if f is None:
                continue
            if f.exact:
                sc["exact"] = f
            else:
                sc["approx"].append(f)

    def _remaining_cost(self, sc) -> float:
        return sum(t.cost for t in sc["order"] if t.name not in sc["tried"])

    def estimate_glance_cost(self) -> float:
        return self.concept_cost * len(self.active_concepts()) + 0.9

    # -- capabilities ----------------------------------------------------
    def glance(self, view):
        sc = self._state(view)
        before = sc["spent"]
        self._try_concepts(sc)
        sig = view.context
        if sc["exact"] is None and self._mode(sc, sig) == "approx":
            # Exact laws don't live here: look at how well my favourite
            # approximate laws fit *this* input and bid on that.
            self._search(sc, self.approx_templates)
            best = min(sc["approx"], key=lambda a: a.score) if sc["approx"] else None
            bucket = conf_bucket(erf_conf(view.tolerance, best.sd)) if best else "c0"
            return ("approx", bucket), sc["spent"] - before, 0.0
        self._search(sc, self.glance_templates)
        if sc["exact"] is not None:
            return ("exact", sc["exact"].template.name), sc["spent"] - before, 0.0
        return ("miss",), sc["spent"] - before, self._remaining_cost(sc)

    def _mode(self, sc, sig) -> str:
        """Decide once per task whether to hunt for exact laws or go approximate."""
        if "mode" not in sc:
            sc["mode"] = "approx" if self.approximate_mode(sig) else "exact"
            if sc["mode"] == "approx":
                local = self.approx_counts[sig]
                sc["order"] = sorted(self.grammar, key=lambda t: local[t.name] + math.exp(-0.8 * t.complexity),
                                     reverse=True)
        return sc["mode"]

    def _conclude(self, view, sc) -> Proposal:
        sig = view.context
        if sc["exact"] is not None:
            f = sc["exact"]
            evidence = ("exact", f.template.name)
            why = f.template.describe(f.coef) + (f"  (concept {f.concept})" if f.concept else "")
        elif sc["approx"]:
            f = min(sc["approx"], key=lambda a: a.score)
            evidence = ("approx", conf_bucket(erf_conf(view.tolerance, f.sd)))
            why = f"~{f.template.describe(f.coef)}  (best approximate law, sd {f.sd:.2f})"
        else:
            f = Fit(self.grammar[1], np.zeros(1), float(sc["h"][-1]), False, float("inf"))
            evidence = ("none",)
            why = "no law found"
        sc["fit"] = f
        conf = min(self.competence.mean(("p",) + evidence + sig), 0.99)
        return Proposal(self.name, self.kind, f.prediction + self.bias, conf, 0.0, why, evidence)

    def approximate_mode(self, sig) -> bool:
        return (self.exact_exists.count(sig) >= 10 and self.exact_exists.mean(sig) < 0.05
                and self.rng.random() > self.explore_exact)

    def solve(self, view) -> Proposal:
        sc = self._state(view)
        before = sc["spent"]
        sig = view.context
        self._try_concepts(sc)
        if sc["exact"] is None and self._mode(sc, sig) == "approx":
            self._search(sc, max(0, self.approx_templates - len(sc["tried"])))
        else:
            self._search(sc, None)
            self.exact_exists.update(sig, 1.0 if sc["exact"] is not None else 0.0)
        prop = self._conclude(view, sc)
        prop.cost = sc["spent"] - before
        return prop

    def review_cost(self, view) -> float:
        sc = self._state(view)
        if sc["exact"] is not None:
            return 0.0
        upcoming = [t for t in sc["order"] if t.name not in sc["tried"]][: self.review_templates]
        concepts = 0.0 if sc.get("concepts_tried") else self.concept_cost * len(self.active_concepts())
        return concepts + sum(t.cost for t in upcoming)

    def critique(self, view, proposal) -> Verdict:
        sc = self._state(view)
        before = sc["spent"]
        self._try_concepts(sc)
        self._search(sc, self.review_templates)
        cost = sc["spent"] - before
        if sc["exact"] is None:
            return Verdict(self.name, self.kind, None, cost, "no exact law found; cannot judge")
        mine = self._conclude(view, sc)
        if abs(mine.value - proposal.value) <= view.tolerance:
            return Verdict(self.name, self.kind, True, cost, f"agrees with law {mine.rationale}")
        return Verdict(self.name, self.kind, False, cost, f"law {mine.rationale} gives {mine.value:g}", counter=mine)

    # -- learning --------------------------------------------------------
    def learn(self, view, value, source, record) -> None:
        sc = self._scratch.get(view.id, {})
        f: Optional[Fit] = sc.get("fit")
        if f is None:
            return
        correct = abs(f.prediction + self.bias - value) <= view.tolerance
        if not f.exact:
            if source == "label" and correct:
                self.approx_counts[view.context][f.template.name] += 1
            return
        if source == "certified" and (record.final is None or record.final.node != self.name):
            return
        weight = 1.0 if source == "label" else 0.5
        if correct:
            sig = view.context
            self.law_counts[sig][f.template.name] += weight
            self.law_counts[None][f.template.name] += weight
            if f.template.n_params:
                self.concepts[(f.template.name, tuple(float(c) for c in f.coef))] += weight

    def describe_knowledge(self, top: int = 6):
        out = []
        by_name = {t.name: t for t in self.grammar}
        for (name, coef), n in self.concepts.most_common(top):
            if n >= self.concept_threshold:
                out.append((by_name[name].describe(coef), n))
        return out

    # -- health ----------------------------------------------------------
    def fault(self, kind: str = "bias") -> None:
        self.bias = 1.0

    def clear_fault(self) -> None:
        self.bias = 0.0
