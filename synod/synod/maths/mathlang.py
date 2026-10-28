"""Reading maths notation (not English).

This is the built-in knowledge of the symbolic side: it can read numbers,
lists, polynomial expressions, equations and function definitions/calls, and
do exact rational arithmetic on them. It knows *nothing* about what the words
around the notation mean - "remainder", "subtract ... from", "how many minutes
in" all have to be learned from answered questions.

A question becomes a ``Reading``: typed slots (numbers N, lists L, equations Q,
function definitions F, calls C, expressions X) plus a *skeleton*, the wording
with every piece of notation replaced by a placeholder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

TOKEN = re.compile(r"\d+\.\d+|\d+|[A-Za-z]+(?:'[a-z]+)?|[+\-*/^=(),?.!:;]")
OPS = set("+-*/^=()")


class Poly:
    """A polynomial in (at most) one variable with exact rational coefficients."""

    __slots__ = ("c", "var")

    def __init__(self, coeffs=None, var: Optional[str] = None):
        self.c = {k: v for k, v in (coeffs or {}).items() if v != 0}
        self.var = var

    @staticmethod
    def const(v) -> "Poly":
        return Poly({0: Fraction(v)})

    @staticmethod
    def variable(name: str) -> "Poly":
        return Poly({1: Fraction(1)}, name)

    def _join(self, other):
        if self.var and other.var and self.var != other.var:
            raise ValueError("more than one variable")
        return self.var or other.var

    def __add__(self, o):
        var = self._join(o)
        out = dict(self.c)
        for k, v in o.c.items():
            out[k] = out.get(k, 0) + v
        return Poly(out, var)

    def __neg__(self):
        return Poly({k: -v for k, v in self.c.items()}, self.var)

    def __sub__(self, o):
        return self + (-o)

    def __mul__(self, o):
        var = self._join(o)
        out: dict = {}
        for a, x in self.c.items():
            for b, y in o.c.items():
                out[a + b] = out.get(a + b, 0) + x * y
        return Poly(out, var)

    def power(self, n: int) -> "Poly":
        out = Poly.const(1)
        for _ in range(n):
            out = out * self
        return out

    @property
    def degree(self) -> int:
        return max(self.c) if self.c else 0

    @property
    def is_const(self) -> bool:
        return self.degree == 0

    @property
    def value(self) -> Fraction:
        return self.c.get(0, Fraction(0))

    def at(self, x) -> Fraction:
        return sum((v * Fraction(x) ** k for k, v in self.c.items()), Fraction(0))

    def derivative(self) -> "Poly":
        return Poly({k - 1: v * k for k, v in self.c.items() if k > 0}, self.var)

    def __repr__(self):
        return f"Poly({self.c}, {self.var})"


class _Parser:
    """Recursive descent over notation tokens. Raises ValueError if it can't."""

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self) -> Poly:
        p = self.expr()
        if self.peek() is not None:
            raise ValueError(f"trailing {self.peek()}")
        return p

    def expr(self):
        p = self.term()
        while self.peek() in ("+", "-"):
            p = p + self.term() if self.take() == "+" else p - self.term()
        return p

    def _starts_atom(self, tok):
        return tok is not None and (tok == "(" or _is_num(tok) or (tok.isalpha() and len(tok) == 1))

    def term(self):
        p = self.unary()
        while True:
            tok = self.peek()
            if tok in ("*", "/"):
                self.take()
                q = self.unary()
                if tok == "*":
                    p = p * q
                else:
                    if not q.is_const or q.value == 0:
                        raise ValueError("division by non-constant")
                    p = p * Poly.const(1 / q.value)
            elif self._starts_atom(tok):  # implicit multiplication: 3x, 2(x+1)
                p = p * self.unary()
            else:
                return p

    def unary(self):
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == "^":
            self.take()
            e = self.unary()
            if not e.is_const or e.value.denominator != 1 or not 0 <= e.value <= 12:
                raise ValueError("bad exponent")
            if base.is_const:
                return Poly.const(base.value ** int(e.value))
            return base.power(int(e.value))
        return base

    def atom(self):
        tok = self.take()
        if tok is None:
            raise ValueError("unexpected end")
        if _is_num(tok):
            return Poly.const(Fraction(tok))
        if tok == "(":
            p = self.expr()
            if self.take() != ")":
                raise ValueError("unbalanced")
            return p
        if tok.isalpha() and len(tok) == 1:
            return Poly.variable(tok)
        raise ValueError(f"unexpected {tok}")


def _is_num(tok) -> bool:
    return tok is not None and tok[0].isdigit()


def parse_poly(tokens) -> Optional[Poly]:
    try:
        return _Parser(list(tokens)).parse()
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


@dataclass
class Reading:
    text: str
    skeleton: tuple
    nums: list = field(default_factory=list)  # Fraction
    lists: list = field(default_factory=list)  # list[list[Fraction]]
    eqs: list = field(default_factory=list)  # Poly == 0
    fdefs: list = field(default_factory=list)  # (name, Poly)
    calls: list = field(default_factory=list)  # (name, Fraction)
    exprs: list = field(default_factory=list)  # Poly
    words: tuple = ()
    texts: dict = field(default_factory=dict)  # (slot kind, index) -> the notation as written

    @property
    def slots(self) -> str:
        parts = [(k, len(v)) for k, v in (("N", self.nums), ("L", self.lists), ("Q", self.eqs),
                                          ("F", self.fdefs), ("C", self.calls), ("X", self.exprs)) if v]
        return "".join(f"{k}{n}" for k, n in parts) or "none"

    def all_numbers(self):
        out = list(self.nums)
        for lst in self.lists:
            out.extend(lst)
        for p in self.eqs + [f for _, f in self.fdefs] + self.exprs:
            out.extend(p.c.values())
        out.extend(v for _, v in self.calls)
        return out


def _spans(text):
    return [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)]


def read(text: str) -> Reading:
    text = text.replace("×", "*").replace("÷", "/").replace("−", "-").replace("**", "^")
    toks = _spans(text)
    n = len(toks)
    kinds = [None] * n  # "math" for notation tokens

    def tok(i):
        return toks[i][0] if 0 <= i < n else None

    def glued(i, j):  # no whitespace between tokens i and j
        return 0 <= i < n and 0 <= j < n and toks[i][2] == toks[j][1]

    for i, (t, _, _) in enumerate(toks):
        if _is_num(t) or t in OPS:
            kinds[i] = "math"
        elif t.isalpha() and len(t) == 1:
            prev, nxt = tok(i - 1), tok(i + 1)
            if (nxt == "(" and glued(i, i + 1)) or (prev is not None and _is_num(prev) and glued(i - 1, i)) \
                    or (prev in OPS) or (nxt in OPS):
                kinds[i] = "math"
    # A '(' or ')' only counts as notation if it touches other notation.
    for i, (t, _, _) in enumerate(toks):
        if t in "()" and not ((i > 0 and kinds[i - 1] == "math" and tok(i - 1) not in "()")
                              or (i + 1 < n and kinds[i + 1] == "math" and tok(i + 1) not in "()")):
            kinds[i] = None

    # Group consecutive notation tokens into segments.
    segs, i = [], 0
    while i < n:
        if kinds[i] == "math":
            j = i
            while j + 1 < n and kinds[j + 1] == "math":
                j += 1
            segs.append((i, j))
            i = j + 1
        else:
            i += 1

    def seg_tokens(s):
        return [toks[k][0] for k in range(s[0], s[1] + 1)]

    def seg_text(a, b):
        return text[toks[a][1]:toks[b][2]]

    def as_number(ts):
        if len(ts) == 1 and _is_num(ts[0]):
            return Fraction(ts[0])
        if len(ts) == 2 and ts[0] == "-" and _is_num(ts[1]):
            return -Fraction(ts[1])
        return None

    # Lists: >= 3 numbers separated by commas (optionally "and" before the last).
    list_of = {}
    k = 0
    while k < len(segs):
        if as_number(seg_tokens(segs[k])) is None:
            k += 1
            continue
        run = [k]
        m = k
        while m + 1 < len(segs) and as_number(seg_tokens(segs[m + 1])) is not None:
            gap = [toks[q][0].lower() for q in range(segs[m][1] + 1, segs[m + 1][0])]
            if gap in ([","], [",", "and"], ["and"]):
                run.append(m + 1)
                m += 1
            else:
                break
        if len(run) >= 3:
            for r in run:
                list_of[r] = run[0]
        k = m + 1

    r = Reading(text, ())
    placeholder = {}  # token index -> placeholder string (first token of a segment)
    covered = set()
    fn_names, var_names = set(), set()
    for si, s in enumerate(segs):
        ts = seg_tokens(s)
        covered.update(range(s[0], s[1] + 1))
        if si in list_of:
            if list_of[si] == si:
                run = [q for q, head in list_of.items() if head == si]
                r.lists.append([as_number(seg_tokens(segs[q])) for q in sorted(run)])
                placeholder[s[0]] = "<list>"
                # swallow separators inside the list
                last = segs[max(run)]
                r.texts[("L", len(r.lists) - 1)] = seg_text(s[0], last[1])
                covered.update(range(s[0], last[1] + 1))
            continue
        num = as_number(ts)
        if num is not None:
            r.nums.append(num)
            r.texts[("N", len(r.nums) - 1)] = seg_text(*s)
            placeholder[s[0]] = "#"
            continue
        if ts.count("=") == 1:
            lhs, rhs = ts[: ts.index("=")], ts[ts.index("=") + 1:]
            if len(lhs) == 4 and lhs[0].isalpha() and lhs[1] == "(" and lhs[2].isalpha() and lhs[3] == ")":
                body = parse_poly(rhs)
                if body is not None:
                    r.fdefs.append((lhs[0], body))
                    r.texts[("F", len(r.fdefs) - 1)] = seg_text(*s)
                    fn_names.add(lhs[0])
                    var_names.add(lhs[2])
                    placeholder[s[0]] = "<fdef>"
                    continue
            pl, pr = parse_poly(lhs), parse_poly(rhs)
            if pl is not None and pr is not None:
                try:
                    eq = pl - pr
                except ValueError:
                    eq = None
                if eq is not None:
                    r.eqs.append(eq)
                    r.texts[("Q", len(r.eqs) - 1)] = seg_text(*s)
                    if eq.var:
                        var_names.add(eq.var)
                    placeholder[s[0]] = "<eq>"
                    continue
        if len(ts) >= 4 and ts[0].isalpha() and ts[1] == "(" and ts[-1] == ")":
            arg = parse_poly(ts[2:-1])
            if arg is not None and arg.is_const:
                r.calls.append((ts[0], arg.value))
                r.texts[("C", len(r.calls) - 1)] = seg_text(*s)
                fn_names.add(ts[0])
                placeholder[s[0]] = "<call>"
                continue
        p = parse_poly(ts)
        if p is not None:
            r.exprs.append(p)
            r.texts[("X", len(r.exprs) - 1)] = seg_text(*s)
            if p.var:
                var_names.add(p.var)
            placeholder[s[0]] = "<expr>" if p.is_const else "<poly>"
            continue
        placeholder[s[0]] = "<?>"

    skel, words = [], []
    for i, (t, _, _) in enumerate(toks):
        if i in placeholder:
            skel.append(placeholder[i])
        elif i in covered:
            continue
        elif t.isalpha():
            w = t.lower()
            if len(t) == 1 and t in var_names:
                w = "<var>"
            elif len(t) == 1 and t in fn_names:
                w = "<fn>"
            skel.append(w)
            if not w.startswith("<"):
                words.append(w)
    r.skeleton = tuple(skel)
    r.words = tuple(words)
    return r


def magnitude_bucket(reading: Reading) -> str:
    nums = [abs(v) for v in reading.all_numbers()]
    top = max(nums) if nums else 0
    return "small" if top < 100 else "medium" if top < 10_000 else "large"


def context(reading: Reading) -> tuple:
    """Shared coarse perception of a maths question: notation shape, size of
    the numbers, and whether it's a one-liner or a little story."""
    sentences = len(re.findall(r"[.?!](?:\s|$)", reading.text.strip() + " "))
    return (reading.slots, magnitude_bucket(reading), "multi" if sentences > 1 else "single")


def features(reading: Reading) -> tuple:
    """Perception features for the council's learned router and judge: the
    coarse context plus every token of the skeleton (like the token features
    an MoE gate sees)."""
    return tuple(f"ctx:{c}" for c in context(reading)) + tuple(sorted({f"w:{t}" for t in reading.skeleton}))
