"""A curriculum of equations and systems of equations.

Training: single linear equations of four shapes (``3x + 4 = 19``,
``5x - 2 = 2x + 7``, ``4(x - 3) = 8``, ``2(x + 5) - 3 = 4x - 1``) and systems
of two (``2x + 3y = 13`` and ``x - y = -1``, or ``y = 2x + 1`` and
``3x + y = 16``), asking for x, for y, or for x plus y. Variables are x and y.
Half the questions reveal their answer afterwards, never the derivation.

Test sets:
  seen        the training kinds, new numbers
  paraphrase  questions worded in ways never seen in training
  forms       equation shapes never seen in training (brackets on both
              sides, two brackets on one side), with other variable letters
  compose     systems whose equations need multiplying out first (moves seen,
              never together)
  longer      three equations in three unknowns: longer derivations than
              anything in training
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from ..protocol import Task
from .lang import normal, read, text

SPLITS = ("seen", "paraphrase", "forms", "compose", "longer")

ONE_TRAIN = ["Solve {e}. What is {v}?", "Find {v} if {e}.", "What is {v} if {e}?"]
ONE_TEST = ["Work out the value of {v} when {e}.", "Suppose {e}. What does {v} equal?"]
TWO_TRAIN = ["Given {e1} and {e2}, what is {v}?", "Solve {e1} and {e2}. What is {v}?", "If {e1} and {e2}, find {v}."]
TWO_TEST = ["Suppose {e1} and {e2}. What does {v} equal?", "Work out {v} when {e1} and {e2}."]
SUM_TRAIN = ["Given {e1} and {e2}, what is {v1} plus {v2}?", "If {e1} and {e2}, find {v1} plus {v2}."]
SUM_TEST = ["Suppose {e1} and {e2}. What is the sum of {v1} and {v2}?"]
THREE = ["Given {e1}, {e2} and {e3}, what is {v}?", "Solve {e1}, {e2} and {e3}. What is {v}?"]

LETTERS_TRAIN = ("x", "y")
LETTERS_TEST = ("m", "n", "p", "q", "t", "k", "u", "w")


def lin_text(coef: dict, c) -> str:
    return text(normal({v: Fraction(a) for v, a in coef.items() if a != 0}, Fraction(c)))


def _bracket(a, v, b) -> str:
    """a(v + b) as written: 3(x - 2), -(x + 4), 2(x + 5)."""
    inner = f"{v} + {b}" if b > 0 else f"{v} - {-b}"
    return f"{'-' if a == -1 else '' if a == 1 else a}({inner})"


def _plus(s: str, c) -> str:
    return s if c == 0 else f"{s} + {c}" if c > 0 else f"{s} - {-c}"


@dataclass
class AlgebraScenario:
    n_train: int = 4000
    n_per_test_split: int = 150
    label_rate: float = 0.5
    seed: int = 0


class AlgebraWorld:
    def __init__(self, scenario: AlgebraScenario | None = None):
        self.sc = scenario or AlgebraScenario()
        self.rng = np.random.default_rng(self.sc.seed)

    def i(self, lo, hi):
        return int(self.rng.integers(lo, hi + 1))

    def nz(self, lo, hi):
        while True:
            k = self.i(lo, hi)
            if k != 0:
                return k

    def pick(self, xs):
        return xs[int(self.rng.integers(len(xs)))]

    # -- single equations --------------------------------------------------
    def one(self, form: str, v: str):
        x = self.i(-9, 9)
        while True:
            if form == "ax+b=c":
                a, b = self.nz(-9, 9), self.i(-20, 20)
                if abs(a) == 1:
                    continue
                return f"{lin_text({v: a}, b)} = {a * x + b}", x
            if form == "ax+b=cx+d":
                a, b, c = self.nz(-9, 9), self.i(-20, 20), self.nz(-9, 9)
                if a == c:
                    continue
                return f"{lin_text({v: a}, b)} = {lin_text({v: c}, (a - c) * x + b)}", x
            if form == "a(x+b)=c":
                a, b = self.nz(-6, 6), self.nz(-9, 9)
                if abs(a) == 1:
                    continue
                return f"{_bracket(a, v, b)} = {a * (x + b)}", x
            if form == "a(x+b)+c=dx+e":
                a, b, c, d = self.nz(-6, 6), self.nz(-9, 9), self.nz(-12, 12), self.nz(-9, 9)
                if a == d or abs(a) == 1:
                    continue
                e = a * (x + b) + c - d * x
                return f"{_plus(_bracket(a, v, b), c)} = {lin_text({v: d}, e)}", x
            # shapes never seen in training
            if form == "a(x+b)=c(x+d)":
                a, b, c = self.nz(-6, 6), self.nz(-9, 9), self.nz(-6, 6)
                if a == c or abs(c) == 1:
                    continue
                num = a * (x + b) - c * x
                if num % c:
                    continue
                return f"{_bracket(a, v, b)} = {_bracket(c, v, num // c)}", x
            if form == "a(x+b)-c(x+d)=e":
                a, b, c, d = self.nz(-6, 6), self.nz(-9, 9), self.nz(2, 6), self.nz(-9, 9)
                if a == c:
                    continue
                e = a * (x + b) - c * (x + d)
                return f"{_bracket(a, v, b)} - {_bracket(c, v, d)} = {e}", x
            raise ValueError(form)

    # -- systems -------------------------------------------------------------
    def two(self, form: str, v1: str, v2: str):
        x, y = self.i(-9, 9), self.i(-9, 9)
        while True:
            if form == "standard":
                a, b, d, e = (self.nz(-6, 6) for _ in range(4))
                if a * e - b * d == 0:
                    continue
                return (f"{lin_text({v1: a, v2: b}, 0)} = {a * x + b * y}",
                        f"{lin_text({v1: d, v2: e}, 0)} = {d * x + e * y}"), (x, y)
            if form == "isolated":
                a, b, c, d = self.nz(-5, 5), self.i(-9, 9), self.nz(-6, 6), self.nz(-6, 6)
                y = a * x + b
                if c + d * a == 0:
                    continue
                return (f"{v2} = {lin_text({v1: a}, b)}", f"{lin_text({v1: c, v2: d}, 0)} = {c * x + d * y}"), (x, y)
            if form == "brackets":  # never seen in training: expand first
                a, b, c, d, e = self.nz(2, 5), self.nz(-5, 5), self.nz(-5, 5), self.nz(-6, 6), self.nz(-6, 6)
                # a(b x + c y) = k, d x + e y = m
                if b * e - c * d == 0:
                    continue
                inner = lin_text({v1: b, v2: c}, 0)
                return (f"{a}({inner}) = {a * (b * x + c * y)}", f"{lin_text({v1: d, v2: e}, 0)} = {d * x + e * y}"), (x, y)
            raise ValueError(form)

    def three(self, v1, v2, v3):
        while True:
            sol = [self.i(-6, 6) for _ in range(3)]
            rows = [[self.nz(-4, 4) for _ in range(3)] for _ in range(3)]
            m = np.array(rows, dtype=float)
            if abs(np.linalg.det(m)) < 0.5:
                continue
            eqs = tuple(f"{lin_text(dict(zip((v1, v2, v3), r)), 0)} = {sum(a * s for a, s in zip(r, sol))}" for r in rows)
            return eqs, tuple(sol)

    # -- questions ------------------------------------------------------------
    def make(self, split: str):
        """(question, answer, kind of question)."""
        held = split == "paraphrase"
        letters = LETTERS_TEST if split == "forms" else LETTERS_TRAIN
        kind = self.pick(["one", "one", "two", "two", "sum"]) if split in ("seen", "paraphrase", "train") else \
            {"forms": "one", "compose": self.pick(["two", "sum"]), "longer": "three"}[split]
        if kind == "one":
            v = self.pick(letters)
            forms = ["a(x+b)=c(x+d)", "a(x+b)-c(x+d)=e"] if split == "forms" else \
                ["ax+b=c", "ax+b=cx+d", "a(x+b)=c", "a(x+b)+c=dx+e"]
            form = self.pick(forms)
            e, x = self.one(form, v)
            return self.pick(ONE_TEST if held else ONE_TRAIN).format(e=e, v=v), Fraction(x), f"one:{form}"
        if kind == "three":
            vs = ("x", "y", "z")
            eqs, sol = self.three(*vs)
            k = self.i(0, 2)
            return self.pick(THREE).format(e1=eqs[0], e2=eqs[1], e3=eqs[2], v=vs[k]), Fraction(sol[k]), "three"
        v1, v2 = (self.pick(letters), None)
        v2 = self.pick([c for c in letters if c != v1]) if len(letters) > 2 else [c for c in letters if c != v1][0]
        v1, v2 = sorted((v1, v2))
        form = "brackets" if split == "compose" else self.pick(["standard", "standard", "isolated"])
        (e1, e2), (x, y) = self.two(form, v1, v2)
        if self.rng.random() < 0.5:
            e1, e2 = e2, e1
        if kind == "sum":
            q = self.pick(SUM_TEST if held else SUM_TRAIN).format(e1=e1, e2=e2, v1=v1, v2=v2)
            return q, Fraction(x + y), f"sum:{form}"
        k = self.i(0, 1)
        q = self.pick(TWO_TEST if held else TWO_TRAIN).format(e1=e1, e2=e2, v=(v1, v2)[k])
        return q, Fraction((x, y)[k]), f"two:{form}"

    def _task(self, tid, split, labeled):
        while True:
            q, ans, fam = self.make(split)
            r = read(q)
            n_eq = {"three": 3}.get(fam, 1 if fam.startswith("one") else 2)
            if len(r.eqs) == n_eq:  # the question reads back as written
                break
        return Task(tid, (), 1e-9 * max(1.0, abs(float(ans))), float(ans), fam, labeled, question=q, split=split)

    def train_stream(self):
        for t in range(self.sc.n_train):
            yield self._task(t, "train", bool(self.rng.random() < self.sc.label_rate))

    def test_tasks(self, start_id: int):
        out, tid = [], start_id
        for split in SPLITS:
            for _ in range(self.sc.n_per_test_split):
                out.append(self._task(tid, split, False))
                tid += 1
        order = self.rng.permutation(len(out))
        return [out[i] for i in order]
