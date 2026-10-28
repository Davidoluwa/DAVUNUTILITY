"""A maths curriculum in the spirit of DeepMind's Mathematics Dataset.

Every question type has *training* phrasings and *held-out* phrasings the
system never sees during training. Answers are computed here, by the world,
with ordinary Python - the nodes have to work out what each wording means.

Test splits probe different kinds of generalisation:
  seen        familiar wording, new numbers
  paraphrase  wording never seen in training
  big         familiar wording, numbers ~100x larger than anything in training
  story       word problems with new names, objects and phrasings
  compose     two-step questions whose particular combination was never seen
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from statistics import median

import numpy as np

from ..protocol import Task
from .mathlang import context, features, read

# ---------------------------------------------------------------------------
# Phrasings: (train, held_out)
# ---------------------------------------------------------------------------
P = {
    "add": (["What is {a} plus {b}?", "Calculate {a} plus {b}.", "Add {a} and {b}.", "What is the sum of {a} and {b}?",
             "Find the sum of {a} and {b}.", "Sum {a} and {b}."],
            ["Work out {a} plus {b}.", "What do you get if you add {a} and {b}?"]),
    "sub": (["What is {a} minus {b}?", "Calculate {a} minus {b}.", "Subtract {b} from {a}.", "What is {a} take away {b}?",
             "Find the difference when {b} is subtracted from {a}."],
            ["Work out {a} minus {b}.", "What do you get if you subtract {b} from {a}?"]),
    "mul": (["What is {a} times {b}?", "Multiply {a} by {b}.", "What is the product of {a} and {b}?",
             "Calculate {a} multiplied by {b}.", "Calculate {a} times {b}."],
            ["Work out {a} times {b}.", "Find the product of {a} and {b}."]),
    "div": (["What is {a} divided by {b}?", "Divide {a} by {b}.", "Calculate {a} divided by {b}.",
             "What is the quotient of {a} and {b}?"],
            ["Work out {a} divided by {b}.", "What do you get if you divide {a} by {b}?"]),
    "calc": (["What is {x}?", "Calculate {x}.", "Evaluate {x}."], ["Work out {x}.", "Compute {x}."]),
    "mod": (["What is the remainder when {a} is divided by {b}?", "Calculate the remainder of {a} divided by {b}.",
             "What is {a} modulo {b}?"],
            ["Find the remainder when {a} is divided by {b}.", "What remains when {a} is divided by {b}?"]),
    "gcd": (["What is the greatest common divisor of {a} and {b}?", "Calculate the highest common factor of {a} and {b}.",
             "What is the greatest common factor of {a} and {b}?"],
            ["Find the greatest common divisor of {a} and {b}.", "Calculate the greatest common divisor of {a} and {b}."]),
    "lcm": (["What is the least common multiple of {a} and {b}?", "Calculate the lowest common multiple of {a} and {b}.",
             "What is the smallest common multiple of {a} and {b}?"],
            ["Find the least common multiple of {a} and {b}.", "Calculate the least common multiple of {a} and {b}."]),
    "prime": (["Is {a} a prime number?", "Is {a} prime?"], ["Is the number {a} prime?", "Determine whether {a} is a prime number."]),
    "pow": (["What is {a} to the power of {b}?", "Calculate {a} raised to the power {b}."],
            ["Work out {a} to the power of {b}.", "What is {a} raised to the power of {b}?"]),
    "square": (["What is the square of {a}?", "What is {a} squared?"], ["Calculate {a} squared.", "Find the square of {a}."]),
    "sqrt": (["What is the square root of {a}?", "Calculate the square root of {a}."], ["Find the square root of {a}."]),
    "solve": (["Solve {eq} for {v}.", "What is {v} in {eq}?", "Find {v} if {eq}."],
              ["Solve for {v}: {eq}.", "Given {eq}, what is {v}?"]),
    "apply": (["Let {f}({v}) = {poly}. What is {f}({n})?", "Let {f}({v}) = {poly}. Calculate {f}({n})."],
              ["Suppose {f}({v}) = {poly}. Find {f}({n}).", "Define {f}({v}) = {poly}. What is {f}({n})?"]),
    "at": (["What is the value of {poly} when {v} = {n}?", "Evaluate {poly} at {v} = {n}."],
           ["Find the value of {poly} when {v} = {n}."]),
    "slope": (["Let {f}({v}) = {poly}. What is the derivative of {f} at {v} = {n}?",
               "Differentiate {poly} with respect to {v} and evaluate at {v} = {n}."],
              ["Find the derivative of {poly} at {v} = {n}."]),
    "next": (["What comes next: {list}?", "What is the next term in {list}?", "What is the next number in the sequence {list}?"],
             ["Continue the sequence: {list}.", "Find the next term of {list}."]),
    "mean": (["What is the mean of {list}?", "Calculate the average of {list}."], ["Find the mean of {list}.", "What is the average of {list}?"]),
    "median": (["What is the median of {list}?", "Calculate the median of {list}."], ["Find the median of {list}."]),
    "lsum": (["What is the total of {list}?", "Calculate the total of {list}."], ["Add up {list}.", "Find the total of {list}."]),
    "lmax": (["What is the largest number in {list}?", "What is the biggest value in {list}?"],
             ["Which is the largest of {list}?", "Find the biggest number in {list}."]),
    "lmin": (["What is the smallest number in {list}?", "What is the lowest value in {list}?"],
             ["Which is the smallest of {list}?", "Find the lowest number in {list}."]),
    "bigger": (["Which is bigger: {a} or {b}?", "Which is greater: {a} or {b}?"], ["Which is larger, {a} or {b}?"]),
    "smaller": (["Which is smaller: {a} or {b}?", "Which is less: {a} or {b}?"], ["Which is lower, {a} or {b}?"]),
    "gt": (["Is {a} greater than {b}?", "Is {a} bigger than {b}?"], ["Is {a} larger than {b}?"]),
}

UNITS = [  # (small unit, big unit, factor)
    ("minutes", "hours", 60), ("seconds", "minutes", 60), ("hours", "days", 24), ("days", "weeks", 7),
    ("months", "years", 12), ("grams", "kilograms", 1000), ("meters", "kilometers", 1000),
    ("centimeters", "meters", 100), ("millimeters", "centimeters", 10),
]
UNIT_P = {
    "up": (["How many {s} are there in {a} {b}?", "Convert {a} {b} to {s}."], ["How many {s} are in {a} {b}?", "Express {a} {b} in {s}."]),
    "down": (["How many {b} are there in {a} {s}?", "Convert {a} {s} to {b}."], ["How many {b} are in {a} {s}?", "Express {a} {s} in {b}."]),
}

NAMES_TRAIN = ["Ann", "Ben", "Chloe", "Dev", "Ella", "Femi", "Grace", "Hugo", "Ivy", "Jamal"]
NAMES_TEST = ["Kofi", "Lena", "Mateo", "Nia", "Omar", "Priya", "Quinn", "Rosa"]
OBJ_TRAIN = ["apples", "marbles", "pencils", "stickers", "cookies", "books", "coins", "shells"]
OBJ_TEST = ["oranges", "crayons", "stamps", "cards", "buttons", "beads"]
STORY = {
    "add": (["{n} has {a} {o}. {n} gets {b} more. How many {o} does {n} have now?",
             "There are {a} {o} in a box and {b} more are added. How many {o} are in the box?"],
            ["{n} starts with {a} {o} and finds {b} more. How many {o} does {n} have?"]),
    "sub": (["{n} has {a} {o} and gives away {b}. How many {o} are left?",
             "{n} had {a} {o}. {n} lost {b} of them. How many {o} does {n} have left?"],
            ["{n} had {a} {o} and used {b}. How many {o} remain?"]),
    "mul": (["There are {a} bags with {b} {o} in each bag. How many {o} are there altogether?",
             "{n} buys {a} packs of {o}. Each pack has {b} {o}. How many {o} does {n} buy?"],
            ["Each of {a} boxes holds {b} {o}. How many {o} are there in total?"]),
    "div": (["{a} {o} are shared equally between {b} friends. How many {o} does each friend get?",
             "{n} puts {a} {o} into {b} equal groups. How many {o} are in each group?"],
            ["Split {a} {o} equally among {b} people. How many {o} does each person get?"]),
}

COMPOSE_TRAIN = ["gcd_mul", "solve_add", "solve_mod", "apply_mul", "sum_div"]
COMPOSE_TEST = ["solve_mul", "lcm_sub", "solve_prime", "apply_add"]
COMPOSE = {
    "gcd_mul": "What is the greatest common divisor of {a} and {b}, multiplied by {c}?",
    "solve_add": "Suppose {eq}. What is {v} plus {c}?",
    "solve_mod": "Suppose {eq}. What is the remainder when {v} is divided by {c}?",
    "apply_mul": "Let {f}({v}) = {poly}. What is {f}({n}) times {c}?",
    "sum_div": "What is the sum of {a} and {b}, divided by {c}?",
    # never seen as a combination during training:
    "solve_mul": "Suppose {eq}. What is {v} times {c}?",
    "lcm_sub": "What is the least common multiple of {a} and {b}, minus {c}?",
    "solve_prime": "Suppose {eq}. Is {v} a prime number?",
    "apply_add": "Let {f}({v}) = {poly}. What is {f}({n}) plus {c}?",
}

SEQUENCES = ["arithmetic", "geometric", "fibonacci", "quadratic", "interleaved"]


def _isprime(n: int) -> bool:
    return n > 1 and all(n % d for d in range(2, int(n ** 0.5) + 1))


def _fmt(v) -> str:
    v = Fraction(v)
    if v.denominator == 1:
        return str(v.numerator)
    return f"{float(v):g}"


def _poly_text(coeffs, var):
    """coeffs: {power: int} -> '3*x^2 - 2*x + 5'"""
    terms = []
    for k in sorted(coeffs, reverse=True):
        c = coeffs[k]
        if c == 0:
            continue
        mag = abs(c)
        body = (f"{mag}" if k == 0 else (f"{var}" if mag == 1 else f"{mag}*{var}")) + (f"^{k}" if k > 1 else "")
        terms.append(("-" if c < 0 else "+", body))
    if not terms:
        return "0"
    out = ("-" if terms[0][0] == "-" else "") + terms[0][1]
    for sgn, body in terms[1:]:
        out += f" {sgn} {body}"
    return out


@dataclass
class MathScenario:
    n_train: int = 4000
    n_per_test_split: int = 250
    label_rate: float = 0.5
    seed: int = 0


class MathWorld:
    def __init__(self, scenario: MathScenario | None = None):
        self.sc = scenario or MathScenario()
        self.rng = np.random.default_rng(self.sc.seed)

    # -- helpers ---------------------------------------------------------
    def _i(self, lo, hi):
        return int(self.rng.integers(lo, hi + 1))

    def _pick(self, xs):
        return xs[int(self.rng.integers(len(xs)))]

    def _scale(self, big):
        return 100 if big else 1

    def _eq(self, big):
        v = self._pick("xyzkmnpqtw")
        a = self._pick([i for i in range(-9, 10) if i not in (0, 1)])
        x = self._i(-12, 12) * self._scale(big)
        b = self._i(-30, 30) * self._scale(big)
        c = a * x + b
        lhs = _poly_text({1: a, 0: b}, v)
        form = self._i(0, 2)
        if form == 0:
            eq = f"{lhs} = {c}"
        elif form == 1:
            eq = f"{c} = {lhs}"
        else:  # unknown on both sides
            d = self._pick([i for i in range(-5, 6) if i not in (0, a)])
            eq = f"{_poly_text({1: a, 0: b}, v)} = {_poly_text({1: d, 0: c - d * x}, v)}"
        return eq, v, x

    def _poly(self, big):
        var = self._pick("xytk")
        deg = self._i(1, 3)
        coeffs = {k: self._i(-6, 6) for k in range(deg + 1)}
        coeffs[deg] = self._pick([1, 2, 3, -1, -2, 4, 5])
        return coeffs, var

    def _seq(self, big):
        fam = self._pick(SEQUENCES)
        s = self._scale(big)
        if fam == "arithmetic":
            a, d = self._i(-20, 20) * s, self._pick([i for i in range(-9, 10) if i]) * s
            xs = [a + d * k for k in range(7)]
        elif fam == "geometric":
            a, r = self._i(1, 5) * s, self._pick([2, 3, -2])
            xs = [a * r ** k for k in range(7)]
        elif fam == "fibonacci":
            xs = [self._i(1, 9) * s, self._i(1, 9) * s]
            while len(xs) < 7:
                xs.append(xs[-1] + xs[-2])
        elif fam == "quadratic":
            a, b, c = self._pick([1, 2, -1, 3]), self._i(-5, 5), self._i(-10, 10) * s
            xs = [a * k * k + b * k + c for k in range(7)]
        else:
            x0, x1, d = self._i(-20, 20) * s, self._i(-20, 20) * s, self._pick([i for i in range(-9, 10) if i]) * s
            xs = [x0, x1]
            while len(xs) < 7:
                xs.append(xs[-2] + d)
        return xs[:6], xs[6]

    def _list(self, big):
        n = self._i(4, 6)
        return [self._i(-20, 60) * self._scale(big) for _ in range(n)]

    # -- question makers -------------------------------------------------
    def make(self, kind: str, phr: int, held_out: bool, big: bool = False):
        """Returns (question, answer, family)."""
        s = self._scale(big)
        pool = P[kind][1 if held_out else 0] if kind in P else None
        tpl = pool[phr % len(pool)] if pool else None
        if kind in ("add", "sub", "mul"):
            a, b = self._i(2, 99) * s, self._i(2, 99) * s
            if kind == "sub" and self.rng.random() < 0.3:
                a, b = b, a
            ans = {"add": a + b, "sub": a - b, "mul": a * b}[kind]
            return tpl.format(a=a, b=b), ans, kind
        if kind == "div":
            b, q = self._i(2, 25) * (s if big else 1), self._i(2, 40) * s
            return tpl.format(a=b * q, b=b), q, kind
        if kind == "calc":
            a, b, c, d = (self._i(1, 30) * s for _ in range(4))
            forms = [(f"{a} + {b} * {c}", a + b * c), (f"({a} + {b}) * {c}", (a + b) * c),
                     (f"{a} * {b} - {c}", a * b - c), (f"{a} - {b} + {c} - {d}", a - b + c - d),
                     (f"{a} * ({b} - {c})", a * (b - c))]
            x, ans = forms[self._i(0, len(forms) - 1)]
            return tpl.format(x=x), ans, kind
        if kind == "mod":
            a, b = self._i(10, 300) * s, self._i(2, 19)
            return tpl.format(a=a, b=b), a % b, kind
        if kind in ("gcd", "lcm"):
            g = self._i(2, 15)
            p, q = self._i(1, 12) * s, self._i(1, 12)
            a, b = g * p, g * q
            if a == b:
                b += g
            ans = math.gcd(a, b) if kind == "gcd" else a * b // math.gcd(a, b)
            return tpl.format(a=a, b=b), ans, kind
        if kind == "prime":
            hi = 200 * s
            if self.rng.random() < 0.5:  # a prime
                while True:
                    a = self._i(2, hi)
                    if _isprime(a):
                        break
            else:  # a composite
                a = self._i(2, int(hi ** 0.5)) * self._i(2, int(hi ** 0.5))
            return tpl.format(a=a), int(_isprime(a)), kind
        if kind == "pow":
            a, b = self._i(2, 9) * (10 if big else 1), self._i(2, 5)
            return tpl.format(a=a, b=b), a ** b, kind
        if kind == "square":
            a = self._i(2, 40) * s
            return tpl.format(a=a), a * a, kind
        if kind == "sqrt":
            r = self._i(2, 40) * s
            return tpl.format(a=r * r), r, kind
        if kind == "solve":
            eq, v, x = self._eq(big)
            return tpl.format(eq=eq, v=v), x, kind
        if kind in ("apply", "slope", "at"):
            coeffs, var = self._poly(big)
            f = self._pick("fghp")
            n = self._i(-5, 6) * (10 if big else 1)
            val = sum(c * n ** k for k, c in coeffs.items())
            der = sum(k * c * n ** (k - 1) for k, c in coeffs.items() if k > 0)
            ans = der if kind == "slope" else val
            return tpl.format(f=f, v=var, poly=_poly_text(coeffs, var), n=n), ans, kind
        if kind == "next":
            xs, nxt = self._seq(big)
            return tpl.format(list=", ".join(map(str, xs))), nxt, kind
        if kind in ("mean", "median", "lsum", "lmax", "lmin"):
            xs = self._list(big)
            if kind == "mean":
                xs[-1] += (-sum(xs)) % len(xs)  # keep the mean a whole number
            ans = {"mean": Fraction(sum(xs), len(xs)), "median": Fraction(median(xs)), "lsum": sum(xs),
                   "lmax": max(xs), "lmin": min(xs)}[kind]
            text = ", ".join(map(str, xs[:-1])) + " and " + str(xs[-1]) if self.rng.random() < 0.5 else ", ".join(map(str, xs))
            return tpl.format(list=text), ans, kind
        if kind in ("bigger", "smaller", "gt"):
            a, b = self._i(-50, 99) * s, self._i(-50, 99) * s
            if a == b:
                b += 1
            ans = {"bigger": max(a, b), "smaller": min(a, b), "gt": int(a > b)}[kind]
            return tpl.format(a=a, b=b), ans, kind
        if kind.startswith("unit"):
            small, bigu, k = self._pick(UNITS)
            direction = "up" if kind == "unit_up" else "down"
            tpls = UNIT_P[direction][1 if held_out else 0]
            t = tpls[phr % len(tpls)]
            if direction == "up":
                a = self._pick([self._i(2, 30), self._i(1, 19) + 0.5]) * s
                return t.format(s=small, b=bigu, a=_fmt(a)), Fraction(a).limit_denominator(10) * k, kind
            a = self._i(1, 20) * k * s
            return t.format(s=small, b=bigu, a=a), a // k, kind
        if kind.startswith("story_"):
            op = kind[6:]
            tpls = STORY[op][1 if held_out else 0]
            t = tpls[phr % len(tpls)]
            n = self._pick(NAMES_TEST if held_out else NAMES_TRAIN)
            o = self._pick(OBJ_TEST if held_out else OBJ_TRAIN)
            if op == "div":
                b, q = self._i(2, 9), self._i(2, 15)
                a, ans = b * q, q
            else:
                a, b = self._i(10, 60), self._i(2, 9)
                ans = {"add": a + b, "sub": a - b, "mul": a * b}[op]
            return t.format(n=n, o=o, a=a, b=b), ans, kind
        if kind.startswith("comp_"):
            c_kind = kind[5:]
            t = COMPOSE[c_kind]
            c = self._i(2, 12)
            if c_kind in ("gcd_mul", "lcm_sub"):
                g = self._i(2, 12)
                a, b = g * self._i(1, 9), g * self._i(1, 9)
                if a == b:
                    b += g
                inner = math.gcd(a, b) if c_kind == "gcd_mul" else a * b // math.gcd(a, b)
                ans = inner * c if c_kind == "gcd_mul" else inner - c
                return t.format(a=a, b=b, c=c), ans, kind
            if c_kind == "sum_div":
                c = self._i(2, 9)
                a = self._i(2, 60)
                b = c * self._i(2, 15) - a
                if b <= 0:
                    b += c * 10
                return t.format(a=a, b=b, c=c), Fraction(a + b, c), kind
            if c_kind.startswith("solve"):
                eq, v, x = self._eq(False)
                if c_kind == "solve_prime":
                    while not _isprime(x) and self.rng.random() < 0.6:
                        eq, v, x = self._eq(False)
                ans = {"solve_add": x + c, "solve_mod": x % c, "solve_mul": x * c,
                       "solve_prime": int(_isprime(x))}[c_kind]
                return t.format(eq=eq, v=v, c=c), ans, kind
            coeffs, var = self._poly(False)
            f = self._pick("fgh")
            n = self._i(-4, 5)
            val = sum(cf * n ** k for k, cf in coeffs.items())
            ans = val * c if c_kind == "apply_mul" else val + c
            return t.format(f=f, v=var, poly=_poly_text(coeffs, var), n=n, c=c), ans, kind
        raise ValueError(kind)

    # -- task streams ----------------------------------------------------
    def _task(self, tid, q, ans, fam, labeled, split):
        r = read(q)
        return Task(tid, (), 1e-6 * max(1.0, abs(float(ans))), float(ans), fam, labeled,
                    question=q, context=context(r), split=split, features=features(r))

    def kinds(self):
        base = list(P) + ["unit_up", "unit_down"]
        stories = [f"story_{op}" for op in STORY]
        return base, stories

    def train_stream(self):
        base, stories = self.kinds()
        comps = [f"comp_{k}" for k in COMPOSE_TRAIN]
        menu = base + stories * 2 + comps
        for t in range(self.sc.n_train):
            kind = self._pick(menu)
            q, ans, fam = self.make(kind, self._i(0, 9), held_out=False)
            yield self._task(t, q, ans, fam, bool(self.rng.random() < self.sc.label_rate), "train")

    def test_tasks(self, start_id: int):
        base, stories = self.kinds()
        tid = start_id
        out = []
        n = self.sc.n_per_test_split
        for split in ("seen", "paraphrase", "big", "story", "compose"):
            for _ in range(n):
                if split == "seen":
                    kind = self._pick(base + stories + [f"comp_{k}" for k in COMPOSE_TRAIN])
                    q, ans, fam = self.make(kind, self._i(0, 9), held_out=False)
                elif split == "paraphrase":
                    kind = self._pick(base)
                    q, ans, fam = self.make(kind, self._i(0, 9), held_out=True)
                elif split == "big":
                    kind = self._pick([k for k in base if k not in ("prime",)])
                    q, ans, fam = self.make(kind, self._i(0, 9), held_out=False, big=True)
                elif split == "story":
                    kind = self._pick(stories)
                    q, ans, fam = self.make(kind, self._i(0, 9), held_out=True)
                else:
                    kind = self._pick([f"comp_{k}" for k in COMPOSE_TEST])
                    q, ans, fam = self.make(kind, 0, held_out=True)
                out.append(self._task(tid, q, ans, fam, False, split))
                tid += 1
        order = self.rng.permutation(len(out))
        return [out[i] for i in order]
