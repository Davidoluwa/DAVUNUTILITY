"""Algebra as a domain of the room: solve equations and systems of equations
by general moves, writing out every line.

A problem gives equations as written (``3(x + 4) - 2 = 5x - 6``) and asks
for a quantity ("What is x?", "What is x plus y?"). The facts are the
equations (``Q1, Q2, …``) and the variables (``V1, V2, …``). A step applies
one general algebraic move and adds the equation (or number) it gives:

  expand(Q)            multiply out brackets and collect like terms on each side
  gather(Q)            subtract to put the variables on the left and the numbers on the right
  divide(Q)            divide both sides by the coefficient of a lone variable
  isolate(Q, V)        rewrite Q as V = (an expression in the other variables)
  substitute(E, Q)     replace V in Q by what E says it equals (E: V = …)
  eliminate(Q, R, V)   subtract a multiple of R from a multiple of Q so that V cancels
  value(Q)             read off a number from Q: V = number
  add, sub, mul        arithmetic on numbers already found

Every move is exact and keeps the equations true, so every line of a
derivation follows from the problem. There is no "solve" move: which moves
to make, in what order, on what, is the room's to learn.

The domain also says what each equation looks like (raw or simplified,
gathered, how many variables, isolated, solved, whether it involves what the
question asks about), the way a person glances at an equation before
deciding what to do with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ..maths.mathlang import _spans
from ..room.workspace import NUM, OPS, STOP, Domain, Fact, Op, fmt as fmt_num, register_ops

EQN, VAR = "equation", "var"


# ----------------------------------------------------------------------------
# Expressions: trees as written, and linear normal forms
# ----------------------------------------------------------------------------
def lin(e):
    """A linear form ({var: coefficient}, constant) of an expression tree."""
    k = e[0]
    if k == "n":
        return {}, e[1]
    if k == "v":
        return {e[1]: Fraction(1)}, Fraction(0)
    if k == "neg":
        v, c = lin(e[1])
        return {x: -a for x, a in v.items()}, -c
    if k in "+-":
        (v1, c1), (v2, c2) = lin(e[1]), lin(e[2])
        s = 1 if k == "+" else -1
        out = dict(v1)
        for x, a in v2.items():
            out[x] = out.get(x, 0) + s * a
        return {x: a for x, a in out.items() if a != 0}, c1 + s * c2
    if k == "*":
        (v1, c1), (v2, c2) = lin(e[1]), lin(e[2])
        if v1 and v2:
            raise ValueError("not linear")
        if v1:
            return {x: a * c2 for x, a in v1.items() if a * c2 != 0}, c1 * c2
        return {x: a * c1 for x, a in v2.items() if a * c1 != 0}, c1 * c2
    raise ValueError(k)


def normal(v: dict, c: Fraction):
    """The tree of a linear form, terms in alphabetical order, then the number."""
    terms = [("*", ("n", v[x]), ("v", x)) if v[x] != 1 else ("v", x) for x in sorted(v)]
    if c != 0 or not terms:
        terms.append(("n", c))
    out = terms[0]
    for t in terms[1:]:
        out = ("+", out, t)
    return out


def is_normal(e) -> bool:
    """Already simplified: it reads the same as its normal form (x - y counts)."""
    return text(e) == text(normal(*lin(e)))


def text(e, top: bool = True) -> str:
    """An expression as a person would write it: 3x + 10, 2(y - 1) + 3y, -x."""
    k = e[0]
    if k == "n":
        return fmt_num(e[1])
    if k == "v":
        return e[1]
    if k == "neg":
        return "-" + text(e[1], False)
    if k == "*":
        a, b = e[1], e[2]
        if a[0] == "n" and b[0] == "v":
            c = a[1]
            return b[1] if c == 1 else f"-{b[1]}" if c == -1 else \
                (f"{fmt_num(c)}{b[1]}" if c.denominator == 1 else f"({fmt_num(c)}){b[1]}")
        if a[0] == "n":
            return f"{fmt_num(a[1])}({text(b)})"
        return f"({text(a)})({text(b)})"
    if k in "+-":
        left = text(e[1])
        r = e[2]
        neg = (r[0] == "n" and r[1] < 0) or (r[0] == "*" and r[1][0] == "n" and r[1][1] < 0)
        if k == "+" and neg:
            flipped = ("n", -r[1]) if r[0] == "n" else ("*", ("n", -r[1][1]), r[2])
            return f"{left} - {text(flipped)}"
        right = text(r, False)
        if k == "-" and r[0] in "+-":
            right = f"({right})"
        return f"{left} {k} {right}"
    return "?"


def subst(e, var: str, by):
    if e[0] == "v":
        return by if e[1] == var else e
    if e[0] == "n":
        return e
    return (e[0], *[subst(a, var, by) for a in e[1:]])


def variables(e) -> set:
    if e[0] == "v":
        return {e[1]}
    if e[0] == "n":
        return set()
    out = set()
    for a in e[1:]:
        out |= variables(a)
    return out


@dataclass(frozen=True)
class Eq:
    l: tuple
    r: tuple

    def text(self) -> str:
        return f"{text(self.l)} = {text(self.r)}"

    @property
    def vars(self) -> set:
        return variables(self.l) | variables(self.r)

    def diff(self):
        """Everything moved to one side: (vars, constant) of left - right."""
        (v1, c1), (v2, c2) = lin(self.l), lin(self.r)
        out = dict(v1)
        for x, a in v2.items():
            out[x] = out.get(x, 0) - a
        return {x: a for x, a in out.items() if a != 0}, c1 - c2

    @property
    def simplified(self) -> bool:
        return is_normal(self.l) and is_normal(self.r)

    @property
    def gathered(self) -> bool:
        if not self.simplified:
            return False
        (v1, c1), (v2, _) = lin(self.l), lin(self.r)
        return bool(v1) and c1 == 0 and not v2

    def solved_for(self):
        """V if this reads V = number."""
        if self.l[0] == "v" and self.r[0] == "n":
            return self.l[1]
        return None

    def isolated(self):
        """V if this reads V = (something without V)."""
        if self.l[0] == "v" and self.l[1] not in variables(self.r) and is_normal(self.r):
            return self.l[1]
        return None


def _gathered(v: dict, c: Fraction) -> Eq:
    """vars = number, from vars + c = 0."""
    return Eq(normal(v, Fraction(0)), ("n", -c))


# ----------------------------------------------------------------------------
# The moves
# ----------------------------------------------------------------------------
def expand(q: Eq):
    if q.simplified:
        return None
    return Eq(normal(*lin(q.l)), normal(*lin(q.r)))


def gather(q: Eq):
    if not q.simplified or q.gathered:
        return None
    v, c = q.diff()
    return _gathered(v, c) if v else None


def divide(q: Eq):
    if not q.simplified:
        return None
    v1, c1 = lin(q.l)
    if len(v1) != 1 or c1 != 0:
        return None
    (x, a), = v1.items()
    if a == 1:
        return None
    v2, c2 = lin(q.r)
    return Eq(("v", x), normal({y: b / a for y, b in v2.items()}, c2 / a))


def isolate(q: Eq, x: str):
    if not q.simplified or q.isolated() == x:
        return None
    v, c = q.diff()
    if x not in v or len(v) < 2:
        return None
    a = v[x]
    rest = {y: -b / a for y, b in v.items() if y != x}
    return Eq(("v", x), normal(rest, -c / a))


def substitute(e: Eq, q: Eq):
    x = e.isolated()
    if x is None or e == q or x not in q.vars:
        return None
    return Eq(subst(q.l, x, e.r), subst(q.r, x, e.r))


def eliminate(q: Eq, r: Eq, x: str):
    if not (q.simplified and r.simplified) or q == r:
        return None
    (v1, c1), (v2, c2) = q.diff(), r.diff()
    if x not in v1 or x not in v2:
        return None
    a, b = v1[x], v2[x]
    out = {}
    for y in set(v1) | set(v2):
        t = b * v1.get(y, 0) - a * v2.get(y, 0)
        if t != 0:
            out[y] = t
    if not out:
        return None
    return _gathered(out, b * c1 - a * c2)


def value(q: Eq):
    if q.solved_for() is None:
        return None
    return q.r[1]


def _shows(verb):
    return lambda args, result: verb(args, result)


ALGEBRA_TABLE = [
    Op("expand", ((EQN,),), out=EQN, run=lambda v: expand(v[0]),
       shows=lambda a, r: f"expand {a[0]}:   {r}"),
    Op("gather", ((EQN,),), out=EQN, run=lambda v: gather(v[0]),
       shows=lambda a, r: f"gather terms of {a[0]}:   {r}"),
    Op("divide", ((EQN,),), out=EQN, run=lambda v: divide(v[0]),
       shows=lambda a, r: f"divide both sides of {a[0]}:   {r}"),
    Op("isolate", ((EQN,), (VAR,)), out=EQN, run=lambda v: isolate(v[0], v[1]),
       shows=lambda a, r: f"isolate {a[1]} in {a[0]}:   {r}"),
    Op("substitute", ((EQN,), (EQN,)), out=EQN, run=lambda v: substitute(v[0], v[1]),
       shows=lambda a, r: f"substitute {a[0]} into {a[1]}:   {r}"),
    Op("eliminate", ((EQN,), (EQN,), (VAR,)), out=EQN, run=lambda v: eliminate(v[0], v[1], v[2]),
       shows=lambda a, r: f"eliminate {a[2]} from {a[0]} and {a[1]}:   {r}"),
    Op("value", ((EQN,),), out=NUM, run=lambda v: value(v[0]),
       shows=lambda a, r: f"so the value is {r}   (from {a[0]})"),
]
ALGEBRA_OPS = register_ops(ALGEBRA_TABLE) + ["add", "sub", "mul"]


# ----------------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------------
_OPS = set("+-*/=()")


def _parse(tokens):
    """Recursive descent over math tokens, with implicit multiplication (3x, 2(x + 1))."""
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        t = peek()
        pos[0] += 1
        return t

    def expr():
        e = term()
        while peek() in ("+", "-"):
            op = take()
            e = (op, e, term())
        return e

    def term():
        e = factor()
        while True:
            t = peek()
            if t == "*":
                take()
                e = ("*", e, factor())
            elif t == "/":
                take()
                d = factor()
                if d[0] != "n" or d[1] == 0:
                    raise ValueError("divide by a number only")
                e = ("*", e, ("n", 1 / d[1]))
            elif t is not None and (t == "(" or t.isalpha() or t[0].isdigit()):
                e = ("*", e, factor())  # implicit: 3x, 2(x + 1), (x + 1)(2)
            else:
                return e

    def factor():
        t = take()
        if t is None:
            raise ValueError("unexpected end")
        if t == "-":
            f = factor()
            return ("n", -f[1]) if f[0] == "n" else ("neg", f)
        if t[0].isdigit():
            return ("n", Fraction(t))
        if t.isalpha() and len(t) == 1:
            return ("v", t)
        if t == "(":
            e = expr()
            if take() != ")":
                raise ValueError("unbalanced")
            return e
        raise ValueError(t)

    e = expr()
    if pos[0] != len(tokens):
        raise ValueError("trailing tokens")
    lin(e)  # linear, or not ours
    return e


@dataclass
class AlgebraReading:
    text: str
    skeleton: tuple
    sentences: tuple
    words: tuple
    eqs: list = field(default_factory=list)  # (Eq, position, as written)
    variables: list = field(default_factory=list)  # in order of first appearance
    mentions: dict = field(default_factory=dict)  # skeleton position -> variable mentioned there
    nums: list = field(default_factory=list)  # loose numbers: (value, position, as written)

    @property
    def slots(self) -> str:
        return f"Q{len(self.eqs)}V{len(self.variables)}"


def read(text: str) -> AlgebraReading:
    toks = _spans(text.replace("−", "-").replace("×", "*"))
    n = len(toks)

    def is_letter(i):
        return toks[i][0].isalpha() and len(toks[i][0]) == 1

    def glued(i, j):
        return 0 <= i < n and 0 <= j < n and toks[i][2] == toks[j][1]

    math = [False] * n
    for i, (t, _, _) in enumerate(toks):
        if t[0].isdigit() or t in _OPS:
            math[i] = True
    for i in range(n):  # letters next to notation are variables in notation
        if is_letter(i) and toks[i][0].lower() != "a":
            prev = toks[i - 1][0] if i > 0 else None
            nxt = toks[i + 1][0] if i + 1 < n else None
            if (prev is not None and (prev in _OPS or prev[0].isdigit())) or (nxt is not None and nxt in _OPS) \
                    or glued(i - 1, i):
                math[i] = True
    segs, i = [], 0
    while i < n:
        if math[i]:
            j = i
            while j + 1 < n and math[j + 1]:
                j += 1
            segs.append((i, j))
            i = j + 1
        else:
            i += 1
    eq_at = {}
    loose_num = set()
    for a, b in segs:
        ts = [toks[k][0] for k in range(a, b + 1)]
        while ts and ts[-1] in ".,;":
            ts.pop()
        if ts.count("=") == 1:
            k = ts.index("=")
            try:
                eq_at[a] = (Eq(_parse(ts[:k]), _parse(ts[k + 1:])), b, text[toks[a][1]:toks[b][2]])
            except (ValueError, ZeroDivisionError):
                pass
        elif len(ts) == 1 and ts[0][0].isdigit():
            loose_num.add(a)
    covered = {k for a, (_, b, _) in eq_at.items() for k in range(a, b + 1)}
    order = []
    for a in sorted(eq_at):
        for v in sorted(eq_at[a][0].vars, key=lambda v: eq_at[a][2].index(v)):
            if v not in order:
                order.append(v)
    r = AlgebraReading(text, (), (), ())
    skel, sent, words = [], [], []
    k = 0
    i = 0
    while i < n:
        t = toks[i][0]
        if i in eq_at:
            eq, b, written = eq_at[i]
            r.eqs.append((eq, len(skel), written))
            skel.append("<eq>")
            sent.append(k)
            i = b + 1
            continue
        if i in covered:
            i += 1
            continue
        if t in ".?!":
            k += 1
        elif i in loose_num:
            r.nums.append((Fraction(t), len(skel), t))
            skel.append("#")
            sent.append(k)
        elif t.isalpha() and len(t) == 1 and t in order:
            r.mentions[len(skel)] = t
            skel.append("<var>")
            sent.append(k)
        elif t.isalpha():
            skel.append(t.lower())
            words.append(t.lower())
            sent.append(k)
        i += 1
    r.skeleton, r.sentences, r.words, r.variables = tuple(skel), tuple(sent), tuple(words), order
    return r


# ----------------------------------------------------------------------------
# The domain
# ----------------------------------------------------------------------------
def fmt(v) -> str:
    if v is None:
        return "?"
    if isinstance(v, Eq):
        return v.text()
    if isinstance(v, str):
        return v
    return fmt_num(v)


class Algebra(Domain):
    """Equations and systems of equations, solved by general moves."""

    name = "algebra"
    ops = ALGEBRA_OPS
    constants = ()
    missing_info = False
    answer_kinds = (NUM,)  # the question asks for a number
    describes = True

    def read(self, text):
        return read(text)

    def facts(self, reading) -> dict:
        facts = {}
        for i, (eq, p, written) in enumerate(reading.eqs):
            facts[f"Q{i + 1}"] = Fact(f"Q{i + 1}", EQN, eq, p, written, (p,))
        for i, v in enumerate(reading.variables):
            where = tuple(p for p, x in sorted(reading.mentions.items()) if x == v)
            facts[f"V{i + 1}"] = Fact(f"V{i + 1}", VAR, v, -1, v, where)
        for i, (v, p, written) in enumerate(reading.nums):
            facts[f"N{i + 1}"] = Fact(f"N{i + 1}", NUM, v, p, written, (p,))
        return facts

    def context(self, reading) -> tuple:
        return (reading.slots, "asks:" + ("many" if len(set(reading.mentions.values())) > 1 else "one"))

    def grounding(self, ws, step):
        """A number read off "V = 3" is about every mention of V in the question."""
        if step.op == "value":
            q = ws.fact(step.args[0])
            x = q.value.solved_for() if q is not None and isinstance(q.value, Eq) else None
            mentions = tuple(p for p, v in sorted(ws.reading.mentions.items()) if v == x)
            if mentions:
                return mentions
        return None

    def describe(self, ws, fact) -> tuple:
        """What an equation looks like, at a glance."""
        if fact.kind == VAR:
            n_in = sum(1 for f in ws.table.values() if f.kind == EQN and fact.value in f.value.vars)
            return ("var", f"in:{min(n_in, 3)}", "asked" if fact.where else "not-asked")
        if fact.kind == NUM:  # a number found: is it about something the question asks?
            return ("number", "asked" if fact.where else "not-asked")
        if fact.kind != EQN:
            return ()
        q = fact.value
        out = ["raw" if not q.simplified else "gathered" if q.gathered else "simplified", f"vars:{min(len(q.vars), 3)}"]
        if q.solved_for():
            out.append("solved")
            asked = any(v == q.solved_for() for v in ws.reading.mentions.values())
            out.append("asked" if asked else "not-asked")
        elif q.isolated():
            out.append("isolated")
        if q.simplified and len(q.vars) == 1:
            v1, c1 = lin(q.l)
            if len(v1) == 1 and c1 == 0 and next(iter(v1.values())) != 1:
                out.append("scaled")
        return tuple(out)

    def matches(self, v, target) -> bool:
        if v is None or target is None or isinstance(v, (Eq, str)):
            return False
        return abs(float(v) - float(target)) <= 1e-9 * max(1.0, abs(float(target)))

    def fallback(self, scene, label, cap: int = 4000):
        """Breadth-first search over moves (how the room gets its first worked
        solutions, before its own experts can guide a search)."""
        from ..room.workspace import Step, steps_to_program
        start = scene.workspace()
        frontier, seen, runs = [start], {frozenset()}, 0
        for _ in range(8):
            nxt = []
            for ws in frontier:
                for op in self.ops:
                    for refs in ws.bindings(op):
                        st = Step(op, refs)
                        runs += 1
                        v = ws.run(st)
                        if v is None:
                            continue
                        if self.matches(v, label):
                            scene.cache["fallback_runs"] = runs
                            yield steps_to_program(list(ws.steps) + [st])
                            return
                        key = frozenset(ws.values + (v,))
                        if key in seen:
                            continue
                        seen.add(key)
                        nxt.append(ws.apply(st, v))
                        if runs > cap:
                            scene.cache["fallback_runs"] = runs
                            return
            frontier = nxt
        scene.cache["fallback_runs"] = runs

    def fmt(self, v) -> str:
        return fmt(v)

    def say(self, ws, step, value=None) -> str:
        if step.op == STOP:
            return f"the answer is {fmt(ws.answer)}"
        op = OPS[step.op]
        val = value if value is not None else ws.run(step)
        shown = []
        for a in step.args:
            f = ws.fact(a)
            shown.append(fmt(f.value) if f is not None else a)
        if step.op in ("add", "sub", "mul"):
            sym = {"add": "+", "sub": "-", "mul": "×"}[step.op]
            return f"{shown[0]} {sym} {shown[1]} = {fmt(val)}"
        return op.shows(shown, fmt(val))


ALGEBRA = Algebra()
