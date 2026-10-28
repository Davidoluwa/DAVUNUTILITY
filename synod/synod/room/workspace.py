"""The room's shared workspace: what is known about a question so far.

A question's notation becomes typed facts: numbers (N), lists (L), equations
(Q), function definitions (F), calls (C) and expressions (X). A step applies
one exact operation to facts already on the table and adds the result as a
new number fact (S1, S2, ...). A solution is a sequence of steps; the last
result is the answer. Small constants (K2, K60, ...) are always on the table
for the operations that scale or round.

Facts are referred to by position, not value ("the second number in the
question", "the result of step 1"), so a step like ``sub(N2,S1)`` means the
same thing in every question with that shape. That is what lets experts
learn steps from one question and reuse them on another.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

from ..maths.mathlang import Reading
from ..maths.programs import BINARY, BIG, CONSTANTS, LIST_OPS, UNARY, _solve

NUM, CONST, LIST, EQ, FDEF, CALL, EXPR, POLY = "num", "const", "list", "eq", "fdef", "call", "expr", "poly"
STOP = "answer"  # the token for "the last result is the answer"


def _round(a: Fraction, k: Fraction) -> Optional[Fraction]:
    if k <= 0:
        return None
    q = abs(a) / k
    return (1 if a > 0 else -1) * Fraction(math.floor(q + Fraction(1, 2))) * k if a else Fraction(0)


def _abs(a):
    return abs(a)


@dataclass(frozen=True)
class Op:
    name: str
    sig: tuple  # accepted fact kinds per argument position
    comm: bool = False


_N = (NUM,)
_NK = (NUM, CONST)
OPS = {o.name: o for o in [
    Op("add", (_N, _N), True), Op("sub", (_N, _N)), Op("mul", (_N, _NK), True), Op("div", (_N, _NK)),
    Op("mod", (_N, _N)), Op("gcd", (_N, _N), True), Op("lcm", (_N, _N), True), Op("pow", (_N, _NK)),
    Op("max", (_N, _N), True), Op("min", (_N, _N), True), Op("gt", (_N, _N)), Op("round", (_N, _NK)),
    Op("is_prime", (_N,)), Op("square", (_N,)), Op("sqrt", (_N,)), Op("neg", (_N,)), Op("abs", (_N,)),
    Op("sum", ((LIST,),)), Op("mean", ((LIST,),)), Op("median", ((LIST,),)), Op("lmax", ((LIST,),)),
    Op("lmin", ((LIST,),)), Op("next", ((LIST,),)),
    Op("solve", ((EQ,),)), Op("calc", ((EXPR,),)), Op("apply", ((FDEF,), (CALL,))),
    Op("at", ((FDEF, POLY), _N)), Op("slope", ((FDEF, POLY), _N)),
]}
_EXTRA_UNARY = {"abs": _abs}


@dataclass(frozen=True)
class Fact:
    ref: str
    kind: str
    value: object
    pos: int = -1  # where it sits in the question's skeleton (question facts only)
    text: str = ""  # the notation as written in the question
    where: tuple = ()  # every place in the question this fact is about (results inherit them)


@dataclass(frozen=True)
class Step:
    op: str
    args: tuple = ()

    @property
    def token(self) -> str:
        return STOP if self.op == STOP else f"{self.op}({','.join(self.args)})"

    @staticmethod
    def parse(token: str) -> "Step":
        if token == STOP:
            return Step(STOP)
        op, rest = token.split("(", 1)
        return Step(op, tuple(a for a in rest[:-1].split(",") if a))


ANSWER = Step(STOP)

_ORDER = {"N": 0, "S": 1, "L": 2, "Q": 3, "F": 4, "C": 5, "X": 6, "K": 7}


def ref_key(ref: str):
    return _ORDER[ref[0]], int(ref[1:])


def canon(step: Step) -> Step:
    """Commutative operations list their arguments in a fixed order."""
    if step.op in OPS and OPS[step.op].comm and len(step.args) == 2 and ref_key(step.args[1]) < ref_key(step.args[0]):
        return Step(step.op, (step.args[1], step.args[0]))
    return step


def execute(op: str, vals: list) -> Optional[Fraction]:
    """Run one exact operation. None if it doesn't apply to these values."""
    try:
        if op in BINARY:
            v = BINARY[op][0](vals[0], vals[1])
        elif op == "round":
            v = _round(vals[0], vals[1])
        elif op in UNARY:
            v = UNARY[op](vals[0])
        elif op in _EXTRA_UNARY:
            v = _EXTRA_UNARY[op](vals[0])
        elif op in LIST_OPS:
            v = LIST_OPS[op](vals[0])
        elif op == "solve":
            v = _solve(vals[0])
        elif op == "calc":
            v = vals[0].value if vals[0].is_const else None
        elif op == "apply":
            (fname, poly), (cname, x) = vals
            v = poly.at(x) if fname == cname else None
        elif op in ("at", "slope"):
            poly = vals[0][1] if isinstance(vals[0], tuple) else vals[0]
            v = poly.at(vals[1]) if op == "at" else poly.derivative().at(vals[1])
        else:
            return None
    except (ZeroDivisionError, OverflowError, ValueError, TypeError, IndexError, AttributeError):
        return None
    if v is None:
        return None
    v = Fraction(v)
    return v if abs(v) < BIG else None


class Workspace:
    """Immutable-ish: ``apply`` returns a new workspace, so the room can keep
    several partial solutions alive at once (beam search)."""

    __slots__ = ("reading", "facts", "steps", "values", "used", "where")

    def __init__(self, reading: Reading, facts=None, steps=(), values=(), used=frozenset(), where=()):
        self.reading = reading
        self.facts = facts if facts is not None else _question_facts(reading)
        self.steps = tuple(steps)  # Step
        self.values = tuple(values)  # Fraction per step
        self.used = used  # refs of question facts some step has used
        self.where = tuple(where)  # per step result: the places in the question it is about

    # -- what's on the table ---------------------------------------------
    def fact(self, ref: str) -> Optional[Fact]:
        if ref[0] == "K":
            k = int(ref[1:])
            return Fact(ref, CONST, Fraction(k)) if k in CONSTANTS else None
        if ref[0] == "S":
            i = int(ref[1:]) - 1
            return Fact(ref, NUM, self.values[i], where=self.where[i]) if 0 <= i < len(self.values) else None
        return self.facts.get(ref)

    def of_kind(self, kinds) -> list:
        out = [f for f in self.facts.values() if f.kind in kinds]
        if NUM in kinds:
            out += [Fact(f"S{i + 1}", NUM, v, where=self.where[i]) for i, v in enumerate(self.values)]
        if CONST in kinds:
            out += [Fact(f"K{k}", CONST, Fraction(k)) for k in CONSTANTS]
        return out

    @property
    def unused(self) -> list:
        """Question facts no step has used yet, plus the last result if nothing used it."""
        out = [r for r in self.facts if r not in self.used]
        if self.values and f"S{len(self.values)}" not in self.used:
            out.append(f"S{len(self.values)}")
        return out

    @property
    def last(self) -> Optional[str]:
        return f"S{len(self.values)}" if self.values else None

    @property
    def answer(self) -> Optional[Fraction]:
        return self.values[-1] if self.values else None

    @property
    def history(self) -> tuple:
        return tuple(s.token for s in self.steps)

    # -- doing things ------------------------------------------------------
    def run(self, step: Step) -> Optional[Fraction]:
        op = OPS.get(step.op)
        if op is None or len(step.args) != len(op.sig) or len(set(step.args)) != len(step.args):
            return None
        vals = []
        for ref, kinds in zip(step.args, op.sig):
            f = self.fact(ref)
            if f is None or f.kind not in kinds:
                return None
            vals.append(f.value)
        return execute(step.op, vals)

    def apply(self, step: Step, value: Fraction) -> "Workspace":
        used = self.used | {a for a in step.args if a[0] in "NLQFCXS"}
        return Workspace(self.reading, self.facts, self.steps + (step,), self.values + (value,), used,
                         self.where + (self._grounding(step),))

    def _grounding(self, step: Step) -> tuple:
        """Where in the question a result is talked about. Solving an equation
        gives the variable, so its result is about every mention of that
        variable ("Is t a prime number?"); evaluating f(3) is about the call;
        anything else is about the facts it was made from."""
        sk = self.reading.skeleton
        if step.op == "solve":
            mentions = tuple(i for i, t in enumerate(sk) if t == "<var>")
            if mentions:
                return mentions
        if step.op == "apply" and len(step.args) == 2:
            c = self.fact(step.args[1])
            if c is not None and c.where:
                return c.where
        out = []
        for a in step.args:
            f = self.fact(a)
            if f is not None:
                out.extend(f.where)
        return tuple(sorted(set(out)))

    def bindings(self, op_name: str) -> list:
        """Every type-correct way to apply an operation here (canonical order
        for commutative operations, no fact used twice in one step)."""
        op = OPS[op_name]
        pools = [self.of_kind(kinds) for kinds in op.sig]
        out = []
        if len(pools) == 1:
            return [(f.ref,) for f in pools[0]]
        for a in pools[0]:
            for b in pools[1]:
                if a.ref == b.ref:
                    continue
                if op.comm and a.kind != CONST and b.kind != CONST and ref_key(b.ref) < ref_key(a.ref):
                    continue
                out.append((a.ref, b.ref))
        return out


def _question_facts(r: Reading) -> dict:
    """The question's notation as facts, each tied to its place in the skeleton."""
    marks = {"#": [], "<list>": [], "<eq>": [], "<fdef>": [], "<call>": [], "<expr>": [], "<poly>": []}
    for i, t in enumerate(r.skeleton):
        if t in marks:
            marks[t].append(i)
    xpos = sorted(marks["<expr>"] + marks["<poly>"])

    def at(lst, i):
        return lst[i] if i < len(lst) else -1

    texts = getattr(r, "texts", {}) or {}
    facts = {}
    for key, kind, values, pos in (("N", NUM, r.nums, marks["#"]), ("L", LIST, r.lists, marks["<list>"]),
                                   ("Q", EQ, r.eqs, marks["<eq>"]), ("F", FDEF, r.fdefs, marks["<fdef>"]),
                                   ("C", CALL, r.calls, marks["<call>"]), ("X", None, r.exprs, xpos)):
        for i, v in enumerate(values):
            k = kind or (EXPR if v.is_const else POLY)
            p = at(pos, i)
            facts[f"{key}{i + 1}"] = Fact(f"{key}{i + 1}", k, v, p, texts.get((key, i), ""), (p,) if p >= 0 else ())
    return facts


# ----------------------------------------------------------------------------
# Programs (nested tuples, as in maths/programs.py) <-> steps
# ----------------------------------------------------------------------------
_LEAVES = ("N", "L", "Q", "F", "C", "X")


def program_to_steps(prog) -> list:
    """Post-order: each operation in the program becomes one step."""
    steps = []

    def walk(p):
        if p[0] in _LEAVES:
            return f"{p[0]}{p[1] + 1}"
        if p[0] == "K":
            return f"K{p[1]}"
        args = tuple(walk(a) for a in p[1:])
        steps.append(canon(Step(p[0], args)))
        return f"S{len(steps)}"

    walk(prog)
    return steps


def steps_to_program(steps):
    """The nested program a list of steps computes (its last step), commutative
    arguments sorted, so two solutions can be compared by method."""
    built = []

    def leaf(ref):
        if ref[0] == "S":
            return built[int(ref[1:]) - 1]
        if ref[0] == "K":
            return ("K", int(ref[1:]))
        return (ref[0], int(ref[1:]) - 1)

    for s in steps:
        if s.op == STOP:
            continue
        args = [leaf(a) for a in s.args]
        if s.op in OPS and OPS[s.op].comm:
            args.sort(key=repr)
        built.append((s.op, *args))
    return built[-1] if built else None


def canonical_program(prog):
    if prog is None or prog[0] in _LEAVES or prog[0] == "K":
        return prog
    args = [canonical_program(a) for a in prog[1:]]
    if prog[0] in OPS and OPS[prog[0]].comm:
        args.sort(key=repr)
    return (prog[0], *args)


# ----------------------------------------------------------------------------
# Saying a step in words
# ----------------------------------------------------------------------------
def fmt(v) -> str:
    if v is None:
        return "?"
    v = Fraction(v)
    if v.denominator == 1:
        return str(v.numerator)
    f = float(v)
    return f"{f:.6g}" if abs(f) >= 1e-3 else str(v)


def poly_text(p) -> str:
    var = p.var or "x"
    terms = []
    for k in sorted(p.c, reverse=True):
        c = p.c[k]
        mag = abs(c)
        cs = fmt(mag)
        body = cs if k == 0 else (var if mag == 1 else f"{cs}{var}") + (f"^{k}" if k > 1 else "")
        terms.append(("-" if c < 0 else "+", body))
    if not terms:
        return "0"
    out = ("-" if terms[0][0] == "-" else "") + terms[0][1]
    for sgn, body in terms[1:]:
        out += f" {sgn} {body}"
    return out


SYMBOL = {"add": "+", "sub": "−", "mul": "×", "div": "÷", "pow": "^"}


def say(ws: Workspace, step: Step, value=None) -> str:
    """A step as a line of a worked solution, e.g. '5 × 6 = 30'."""
    if step.op == STOP:
        return f"the answer is {fmt(ws.answer)}"
    v = fmt(value if value is not None else ws.run(step))
    f = [ws.fact(a) for a in step.args]
    x = [fmt(a.value) if a is not None and a.kind in (NUM, CONST) else "?" for a in f]
    op = step.op
    if op in SYMBOL:
        return f"{x[0]} {SYMBOL[op]} {x[1]} = {v}"
    if op == "mod":
        return f"{x[0]} mod {x[1]} = {v}  (remainder of {x[0]} ÷ {x[1]})"
    if op in ("gcd", "lcm", "max", "min"):
        return f"{op}({x[0]}, {x[1]}) = {v}"
    if op == "gt":
        return f"is {x[0]} > {x[1]}? {'yes' if v == '1' else 'no'} ({v})"
    if op == "round":
        return f"{x[0]} rounded to the nearest {x[1]} = {v}"
    if op == "is_prime":
        return f"is {x[0]} prime? {'yes' if v == '1' else 'no'} ({v})"
    if op == "square":
        return f"{x[0]}² = {v}"
    if op == "sqrt":
        return f"√{x[0]} = {v}"
    if op == "neg":
        return f"−({x[0]}) = {v}"
    if op == "abs":
        return f"|{x[0]}| = {v}"
    if op in LIST_OPS:
        name = {"sum": "total", "lmax": "largest", "lmin": "smallest", "next": "next term"}.get(op, op)
        return f"{name} of {f[0].text or 'the list'} = {v}" if f[0] is not None else f"{name} = {v}"
    if op == "solve":
        eq = f[0].value if f[0] is not None else None
        var = eq.var if eq is not None and eq.var else "x"
        shown = f[0].text if f[0] is not None and f[0].text else (poly_text(eq) + " = 0" if eq is not None else "?")
        return f"solve {shown} for {var}: {var} = {v}"
    if op == "calc":
        shown = f[0].text if f[0] is not None and f[0].text else (poly_text(f[0].value) if f[0] is not None else "?")
        return f"{shown} = {v}"
    if op == "apply":
        name = f[0].value[0] if f[0] is not None else "f"
        arg = fmt(f[1].value[1]) if f[1] is not None else "?"
        return f"{name}({arg}) = {v}"
    if op in ("at", "slope"):
        if f[0] is not None and f[0].kind == FDEF:
            name = f[0].value[0]
            return f"{name}{chr(39) if op == 'slope' else ''}({x[1]}) = {v}"
        body = f[0].text if f[0] is not None and f[0].text else "the expression"
        return (f"derivative of {body} at {x[1]} = {v}" if op == "slope" else f"{body} at {x[1]} = {v}")
    return f"{step.token} = {v}"
