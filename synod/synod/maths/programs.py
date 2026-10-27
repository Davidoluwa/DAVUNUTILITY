"""Exact maths primitives, programs over a question's slots, and search.

A program is a nested tuple, e.g. ``("mod", ("N", 0), ("N", 1))`` or
``("mul", ("gcd", ("N", 0), ("N", 1)), ("N", 2))``. Leaves refer to slots of a
``Reading`` (N numbers, L lists, Q equations, F function definitions, C calls,
X expressions) or to small constants K that unit facts are made of.

``explain`` is the expensive, deliberate step: enumerate programs up to depth 2
and keep the ones that reproduce a known answer. It's how the symbolic side
learns what a wording means without being told.
"""
from __future__ import annotations

import math
from fractions import Fraction
from functools import lru_cache
from statistics import median
from typing import Optional

import numpy as np

from ..nodes.inducer import GRAMMAR, fit_template

CONSTANTS = (2, 3, 4, 5, 7, 10, 12, 24, 60, 100, 1000)
BIG = 10 ** 12


def _int(v: Fraction) -> Optional[int]:
    return v.numerator if v.denominator == 1 else None


def _ok(v):
    return v is not None and abs(v) < BIG


@lru_cache(maxsize=4096)
def _prime(n: int) -> bool:
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    r = int(math.isqrt(n))
    return all(n % d for d in range(3, r + 1, 2))


def _pow(a, b):
    if b.denominator != 1 or abs(b) > 64 or (a == 0 and b < 0):
        return None
    if a != 0 and abs(b) * math.log10(max(abs(float(a)), 1e-9)) > 12:
        return None  # result would be out of range
    return a ** int(b)


def _mod(a, b):
    ia, ib = _int(a), _int(b)
    return Fraction(ia % ib) if ia is not None and ib not in (None, 0) else None


def _gcd(a, b):
    ia, ib = _int(a), _int(b)
    return Fraction(math.gcd(ia, ib)) if ia is not None and ib is not None and (ia or ib) else None


def _lcm(a, b):
    ia, ib = _int(a), _int(b)
    return Fraction(abs(ia * ib) // math.gcd(ia, ib)) if ia and ib else None


def _sqrt(a):
    ia = _int(a)
    if ia is None or ia < 0:
        return None
    r = math.isqrt(ia)
    return Fraction(r) if r * r == ia else None


def _is_prime(a):
    ia = _int(a)
    if ia is None or ia >= 10 ** 9:
        return None
    return Fraction(int(_prime(ia))) if ia >= 0 else Fraction(0)


BINARY = {
    "add": (lambda a, b: a + b, True),
    "sub": (lambda a, b: a - b, False),
    "mul": (lambda a, b: a * b, True),
    "div": (lambda a, b: a / b if b != 0 else None, False),
    "mod": (_mod, False),
    "gcd": (_gcd, True),
    "lcm": (_lcm, True),
    "pow": (_pow, False),
    "max": (lambda a, b: max(a, b), True),
    "min": (lambda a, b: min(a, b), True),
    "gt": (lambda a, b: Fraction(int(a > b)), False),
}
UNARY = {
    "is_prime": _is_prime,
    "square": lambda a: a * a,
    "sqrt": _sqrt,
    "neg": lambda a: -a,
}


def _next_term(lst):
    h = np.array([float(v) for v in lst])
    best = None
    for t in GRAMMAR:
        f = fit_template(t, h)
        if f is not None and f.exact:
            best = f.prediction
            break
    if best is None:
        return None
    v = Fraction(best).limit_denominator(1000)
    return v if abs(float(v) - best) < 1e-6 * max(1, abs(best)) else None


LIST_OPS = {
    "sum": lambda xs: sum(xs, Fraction(0)),
    "mean": lambda xs: sum(xs, Fraction(0)) / len(xs),
    "median": lambda xs: Fraction(median(xs)),
    "lmax": max,
    "lmin": min,
    "next": _next_term,
}


def _solve(q):
    if q.degree != 1:
        return None
    return -q.c.get(0, Fraction(0)) / q.c[1]


def _poly_of(r, leaf):
    kind, i = leaf
    if kind == "F" and i < len(r.fdefs):
        return r.fdefs[i][1]
    if kind == "X" and i < len(r.exprs) and not r.exprs[i].is_const:
        return r.exprs[i]
    return None


def run(prog, r) -> Optional[Fraction]:
    """Execute a program against a Reading. None if it doesn't apply."""
    try:
        return _run(prog, r)
    except (ZeroDivisionError, OverflowError, ValueError, TypeError, IndexError):
        return None


def _run(prog, r):
    op = prog[0]
    if op == "N":
        return r.nums[prog[1]] if prog[1] < len(r.nums) else None
    if op == "K":
        return Fraction(prog[1])
    if op == "calc":
        i = prog[1][1]
        return r.exprs[i].value if i < len(r.exprs) and r.exprs[i].is_const else None
    if op == "solve":
        i = prog[1][1]
        return _solve(r.eqs[i]) if i < len(r.eqs) else None
    if op == "apply":
        (_, fi), (_, ci) = prog[1], prog[2]
        if fi < len(r.fdefs) and ci < len(r.calls) and r.fdefs[fi][0] == r.calls[ci][0]:
            return r.fdefs[fi][1].at(r.calls[ci][1])
        return None
    if op in ("at", "slope"):
        p = _poly_of(r, prog[1])
        x = _run(prog[2], r)
        if p is None or x is None:
            return None
        return p.at(x) if op == "at" else p.derivative().at(x)
    if op in LIST_OPS:
        i = prog[1][1]
        return LIST_OPS[op](r.lists[i]) if i < len(r.lists) else None
    if op in UNARY:
        a = _run(prog[1], r)
        return UNARY[op](a) if a is not None else None
    if op in BINARY:
        a = _run(prog[1], r)
        if a is None:
            return None
        b = _run(prog[2], r)
        if b is None:
            return None
        v = BINARY[op][0](a, b)
        return v if _ok(v) else None
    return None


# ----------------------------------------------------------------------------
# Enumeration
# ----------------------------------------------------------------------------
def _level1(r):
    """(program, value) pairs of depth 1."""
    out = []
    nums = [("N", i) for i in range(len(r.nums))]

    def add(p):
        v = run(p, r)
        if v is not None:
            out.append((p, v))

    for i in range(len(r.exprs)):
        add(("calc", ("X", i)))
    for i in range(len(r.eqs)):
        add(("solve", ("Q", i)))
    for fi in range(len(r.fdefs)):
        for ci in range(len(r.calls)):
            add(("apply", ("F", fi), ("C", ci)))
    for i in range(len(r.lists)):
        for op in LIST_OPS:
            add((op, ("L", i)))
    polys = [("F", i) for i in range(len(r.fdefs))] + [("X", i) for i in range(len(r.exprs)) if not r.exprs[i].is_const]
    for p in polys:
        for n in nums:
            add(("at", p, n))
            add(("slope", p, n))
    for n in nums:
        out.append((n, r.nums[n[1]]))
        for op in UNARY:
            add((op, n))
        for k in CONSTANTS:
            add(("mul", n, ("K", k)))
            add(("div", n, ("K", k)))
    for a in nums:
        for b in nums:
            if a == b:
                continue
            for op, (_, comm) in BINARY.items():
                if comm and a[1] > b[1]:
                    continue
                add((op, a, b))
    return out


def leaves(prog):
    if prog[0] in ("N", "K", "L", "Q", "F", "C", "X"):
        return [prog]
    out = []
    for p in prog[1:]:
        out.extend(leaves(p))
    return out


def size(prog) -> int:
    if prog[0] in ("N", "K", "L", "Q", "F", "C", "X"):
        return 0
    return 1 + sum(size(p) for p in prog[1:])


def coverage(prog, r) -> float:
    """Fraction of the question's slots the program actually uses."""
    used = {l for l in leaves(prog) if l[0] != "K"}
    total = len(r.nums) + len(r.lists) + len(r.eqs) + len(r.fdefs) + len(r.calls) + len(r.exprs)
    return len(used) / total if total else 1.0


def enumerate_programs(r, depth: int = 2):
    """Yield (program, value) for depth-1 programs, then depth-2 compositions."""
    l1 = _level1(r)
    yield from l1
    if depth < 2:
        return
    nums = [("N", i) for i in range(len(r.nums))]
    polys = [("F", i) for i in range(len(r.fdefs))] + [("X", i) for i in range(len(r.exprs)) if not r.exprs[i].is_const]
    for p, v in l1:
        if p[0] in ("N",):
            continue
        for op in UNARY:
            w = run((op, p), r)
            if w is not None:
                yield (op, p), w
        for k in CONSTANTS:
            for op in ("mul", "div"):
                w = run((op, p, ("K", k)), r)
                if w is not None:
                    yield (op, p, ("K", k)), w
        for n in nums:
            if n in leaves(p):
                continue
            for op, (fn, comm) in BINARY.items():
                for prog in ([(op, p, n)] if comm else [(op, p, n), (op, n, p)]):
                    w = run(prog, r)
                    if w is not None:
                        yield prog, w
        for poly in polys:
            if poly in leaves(p):
                continue
            for op in ("at", "slope"):
                w = run((op, poly, p), r)
                if w is not None:
                    yield (op, poly, p), w


def matches(v: Fraction, target: float) -> bool:
    return abs(float(v) - target) <= 1e-6 * max(1.0, abs(target))


def explain(r, target: float, limit: int = 40, depth: int = 2):
    """All programs (up to ``limit``) that reproduce ``target``, best first.

    Questions nearly always use all of their notation, so if no depth-1
    program uses every slot, depth-2 compositions are searched too."""
    found = [p for p, v in enumerate_programs(r, depth=1) if matches(v, target)]
    if depth >= 2 and not any(coverage(p, r) == 1.0 for p in found):
        found += [p for p, v in enumerate_programs(r, depth=2) if matches(v, target)]
    found = [p for p in dict.fromkeys(found) if p[0] != "N" or len(r.nums) == 1]
    found.sort(key=lambda p: (-coverage(p, r), size(p)))
    return found[:limit]


# ----------------------------------------------------------------------------
# Words for programs
# ----------------------------------------------------------------------------
def primitives(prog):
    """The building blocks of a program, as lexicon tokens. Constants and
    argument order are part of the vocabulary (e.g. 'mul*60', 'sub:rev')."""
    out = []
    if prog[0] in ("N", "K", "L", "Q", "F", "C", "X"):
        return out
    op, args = prog[0], prog[1:]
    tok = op
    if op in BINARY and len(args) == 2:
        a, b = args
        if b[0] == "K":
            tok = f"{op}*{b[1]}"
        elif a[0] == "N" and b[0] == "N" and a[1] > b[1]:
            tok = f"{op}:rev"
        elif a[0] == "N" and b[0] != "N":
            tok = f"{op}:rev"
    out.append(tok)
    for a in args:
        out.extend(primitives(a))
    return out


NAMES = {
    "add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^",
}


def describe(prog) -> str:
    op = prog[0]
    if op == "N":
        return f"n{prog[1] + 1}"
    if op == "K":
        return str(prog[1])
    if op in ("L", "Q", "F", "C", "X"):
        return {"L": "list", "Q": "equation", "F": "f", "C": "call", "X": "expr"}[op] + (str(prog[1] + 1) if prog[1] else "")
    args = [describe(a) for a in prog[1:]]
    if op in NAMES and len(args) == 2:
        return f"({args[0]} {NAMES[op]} {args[1]})"
    if op == "apply":
        return "f(call)"
    if op == "at":
        return f"{args[0]}({args[1]})"
    if op == "slope":
        return f"{args[0]}'({args[1]})"
    return f"{op}({', '.join(args)})"
