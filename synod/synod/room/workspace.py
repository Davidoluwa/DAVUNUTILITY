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

Nothing in the workspace, the experts or the room is specific to arithmetic:
a ``Domain`` says how to read a problem into facts, which operations exist
(with their signatures and how to run them), which constants are always on
the table, when two results match, and how to say a step. Arithmetic is one
domain (``ARITH``, below); code and algebra are others.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

from ..maths.mathlang import Reading
from ..maths.programs import BINARY, BIG, CONSTANTS, LIST_OPS, UNARY, _solve

NUM, CONST, LIST, EQ, FDEF, CALL, EXPR, POLY = "num", "const", "list", "eq", "fdef", "call", "expr", "poly"
STOP = "answer"  # the token for "the last result is the answer"
INSUFFICIENT = "insufficient"  # the token for "the question doesn't give enough to answer it"
TERMINAL = (STOP, INSUFFICIENT)


class _Unknowable:
    """The outcome "not enough information": a claim about the question, not a
    number, and not the same as abstaining (which is "I'm not sure")."""

    __slots__ = ()

    def __repr__(self):
        return "UNKNOWABLE"

    def __reduce__(self):
        return "UNKNOWABLE"


UNKNOWABLE = _Unknowable()


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
    out: str = "num"  # the kind of fact its result is
    run: object = None  # vals -> value or None (arithmetic operations run through ``execute``)
    shows: object = None  # (input texts, result text) -> a line of a worked solution


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
ARITH_OPS = list(OPS)  # the arithmetic domain's operations, in a fixed order


def register_ops(ops) -> list:
    """Add a domain's operations to the table every workspace runs from (names
    are unique across domains)."""
    for o in ops:
        if o.name in OPS and OPS[o.name] != o:
            raise ValueError(f"operation {o.name} already defined differently")
        OPS[o.name] = o
    return [o.name for o in ops]


@dataclass(frozen=True)
class Procedure:
    """An operation the room invented: a chain of exact operations with
    parameters ("$", i) and constants ("K", k), e.g. ("div", ("mul", ("$", 0),
    ("$", 1)), ("K", 100)). It runs exactly like the operations it is made of."""
    name: str
    body: tuple
    sig: tuple  # accepted fact kinds per parameter
    comm: bool = False

    def run(self, vals):
        def ev(p):
            if p[0] == "$":
                return vals[p[1]]
            if p[0] == "K":
                return Fraction(p[1])
            args = [ev(a) for a in p[1:]]
            if any(a is None for a in args):
                return None
            return run_op(p[0], args)
        return ev(self.body)

    def describe(self) -> str:
        """The body in maths notation, e.g. "(a × b) ÷ 100"."""
        letters = "abcdefgh"

        def show(p, top=False):
            if p[0] == "$":
                return letters[p[1]]
            if p[0] == "K":
                return str(p[1])
            args = [show(a) for a in p[1:]]
            if p[0] in SYMBOL and len(args) == 2:
                out = f"{args[0]} {SYMBOL[p[0]]} {args[1]}"
                return out if top else f"({out})"
            return f"{p[0]}({', '.join(args)})"
        return show(self.body, True)


PROCS: dict = {}  # name -> Procedure, for every procedure any room in this process has invented


def register(proc: Procedure) -> Procedure:
    PROCS[proc.name] = proc
    return proc


def op_info(name: str):
    """The signature of an operation, built in or invented (None if unknown)."""
    return OPS.get(name) or PROCS.get(name)


def run_op(name: str, vals):
    if any(v is UNKNOWABLE for v in vals):  # a quantity the question doesn't give
        return UNKNOWABLE
    proc = PROCS.get(name)
    if proc is not None:
        v = proc.run(vals)
        return v if v is None or not isinstance(v, Fraction) or abs(v) < BIG else None
    op = OPS.get(name)
    if op is not None and op.run is not None:
        try:
            return op.run(vals)
        except (ZeroDivisionError, OverflowError, ValueError, TypeError, IndexError, AttributeError, KeyError):
            return None
    return execute(name, vals)


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
        return self.op if self.op in TERMINAL else f"{self.op}({','.join(self.args)})"

    @staticmethod
    def parse(token: str) -> "Step":
        if token in TERMINAL:
            return Step(token)
        op, rest = token.split("(", 1)
        return Step(op, tuple(a for a in rest[:-1].split(",") if a))


ANSWER = Step(STOP)
CANT = Step(INSUFFICIENT)

_ORDER = {"N": 0, "S": 1, "L": 2, "Q": 3, "F": 4, "C": 5, "X": 6, "K": 7, "I": 8, "V": 9, "E": 10}


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

    __slots__ = ("reading", "facts", "steps", "values", "used", "where", "kinds", "domain", "_memo")

    def __init__(self, reading, facts=None, steps=(), values=(), used=frozenset(), where=(), domain=None, kinds=()):
        self.domain = domain or ARITH
        self.reading = reading
        self.facts = facts if facts is not None else self.domain.facts(reading)
        self.steps = tuple(steps)  # Step
        self.values = tuple(values)  # one result per step
        self.kinds = tuple(kinds) or tuple(NUM for _ in self.values)  # the kind of each result
        self.used = used  # refs of question facts some step has used
        self.where = tuple(where)  # per step result: the places in the question it is about
        self._memo = {}  # a workspace never changes, so anything derived from it is computed once

    def __getstate__(self):
        return {k: getattr(self, k) for k in self.__slots__ if k != "_memo"}

    def __setstate__(self, state):
        for k, v in state.items():
            setattr(self, k, v)
        self._memo = {}

    # -- what's on the table ---------------------------------------------
    @property
    def table(self) -> dict:
        """Every fact on the table (question facts, results, constants) by ref."""
        t = self._memo.get("table")
        if t is None:
            t = dict(self.facts)
            for i, v in enumerate(self.values):
                t[f"S{i + 1}"] = Fact(f"S{i + 1}", self.kinds[i], v, where=self.where[i])
            for c in self.domain.constants:
                t[c.ref] = c
            self._memo["table"] = t
        return t

    def fact(self, ref: str) -> Optional[Fact]:
        return self.table.get(ref)

    def size(self, ref: str) -> float:
        """|value| as a float, for quick comparisons."""
        m = self._memo.setdefault("size", {})
        if ref not in m:
            f = self.fact(ref)
            known = f is not None and f.kind in (NUM, CONST) and isinstance(f.value, (Fraction, int))
            m[ref] = abs(float(f.value)) if known else 0.0
        return m[ref]

    def of_kind(self, kinds) -> list:
        key = ("kind", kinds)
        out = self._memo.get(key)
        if out is None:
            out = [f for f in self.facts.values() if f.kind in kinds]
            out += [self.table[f"S{i + 1}"] for i in range(len(self.values)) if self.kinds[i] in kinds]
            out += [c for c in self.domain.constants if c.kind in kinds]
            self._memo[key] = out
        return out

    @property
    def unused(self) -> list:
        """Question facts no step has used yet, plus the last result if nothing used it."""
        out = self._memo.get("unused")
        if out is None:
            out = [r for r in self.facts if r not in self.used]
            if self.values and f"S{len(self.values)}" not in self.used:
                out.append(f"S{len(self.values)}")
            self._memo["unused"] = out
        return out

    @property
    def last(self) -> Optional[str]:
        return f"S{len(self.values)}" if self.values else None

    @property
    def answer(self):
        return self.values[-1] if self.values else None

    @property
    def history(self) -> tuple:
        h = self._memo.get("history")
        if h is None:
            h = self._memo["history"] = tuple(s.token for s in self.steps)
        return h

    # -- doing things ------------------------------------------------------
    def run(self, step: Step):
        memo = self._memo.get("run")
        if memo is None:
            memo = self._memo["run"] = {}
        key = (step.op, step.args)
        if key not in memo:
            memo[key] = self._run(step)
        return memo[key]

    def _run(self, step: Step):
        op = op_info(step.op)
        if op is None or len(step.args) != len(op.sig) or len(set(step.args)) != len(step.args):
            return None
        vals = []
        for ref, kinds in zip(step.args, op.sig):
            f = self.fact(ref)
            if f is None or f.kind not in kinds:
                return None
            vals.append(f.value)
        return run_op(step.op, vals)

    def apply(self, step: Step, value) -> "Workspace":
        used = self.used | {a for a in step.args if a[0] != "K"}
        op = op_info(step.op)
        kind = getattr(op, "out", NUM) if op is not None else NUM
        return Workspace(self.reading, self.facts, self.steps + (step,), self.values + (value,), used,
                         self.where + (self._grounding(step),), self.domain, self.kinds + (kind,))

    def _grounding(self, step: Step) -> tuple:
        """Where in the question a result is talked about: by default, the
        places its inputs came from (a domain can say more)."""
        special = self.domain.grounding(self, step)
        if special:
            return special
        out = []
        for a in step.args:
            f = self.fact(a)
            if f is not None:
                out.extend(f.where)
        return tuple(sorted(set(out)))

    def bindings(self, op_name: str) -> list:
        """Every type-correct way to apply an operation here (canonical order
        for commutative operations, no fact used twice in one step)."""
        key = ("bind", op_name)
        if key not in self._memo:
            self._memo[key] = self._bindings(op_name)
        return self._memo[key]

    def _bindings(self, op_name: str) -> list:
        op = op_info(op_name)
        pools = [self.of_kind(kinds) for kinds in op.sig]
        out = []
        if len(pools) == 1:
            return [(f.ref,) for f in pools[0]]
        if len(pools) == 2:
            for a in pools[0]:
                for b in pools[1]:
                    if a.ref == b.ref:
                        continue
                    if op.comm and a.kind != CONST and b.kind != CONST and ref_key(b.ref) < ref_key(a.ref):
                        continue
                    out.append((a.ref, b.ref))
            return out
        for combo in itertools.product(*pools):  # invented procedures can take more
            refs = tuple(f.ref for f in combo)
            if len(set(refs)) == len(refs):
                out.append(refs)
        return out


def _question_facts(r: Reading) -> dict:
    """The question's notation as facts, each tied to its place in the skeleton."""
    marks = {"#": [], "<list>": [], "<eq>": [], "<fdef>": [], "<call>": [], "<expr>": [], "<poly>": [], "<some>": []}
    for i, t in enumerate(r.skeleton):
        if t in marks:
            marks[t].append(i)
    # numbers and vague quantities ("a few") are both quantities, numbered in order
    quantities, nums, vague = [], iter(r.nums), iter(getattr(r, "vague", ()))
    texts_in = getattr(r, "texts", {}) or {}
    n_seen = 0
    for i in sorted(marks["#"] + marks["<some>"]):
        if r.skeleton[i] == "#":
            quantities.append((next(nums), i, texts_in.get(("N", n_seen), "")))
            n_seen += 1
        else:
            quantities.append((UNKNOWABLE, i, next(vague, "some")))
    xpos = sorted(marks["<expr>"] + marks["<poly>"])

    def at(lst, i):
        return lst[i] if i < len(lst) else -1

    texts = getattr(r, "texts", {}) or {}
    facts = {}
    for i, (v, p, text) in enumerate(quantities):
        facts[f"N{i + 1}"] = Fact(f"N{i + 1}", NUM, v, p, text, (p,))
    for key, kind, values, pos in (("L", LIST, r.lists, marks["<list>"]),
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
_LEAVES = ("N", "L", "Q", "F", "C", "X", "I", "V", "E")  # fact refs (results S and constants K aside)


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

    def inline(p, args):  # an invented procedure, written out in the operations it's made of
        if p[0] == "$":
            return args[p[1]]
        if p[0] == "K":
            return p
        inner = [inline(a, args) for a in p[1:]]
        if p[0] in OPS and OPS[p[0]].comm:
            inner.sort(key=repr)
        return (p[0], *inner)

    for s in steps:
        if s.op in TERMINAL:
            continue
        args = [leaf(a) for a in s.args]
        if s.op in PROCS:
            built.append(inline(PROCS[s.op].body, args))
            continue
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
    if v is UNKNOWABLE:
        return "not enough information"
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
        if ws.answer is UNKNOWABLE:
            return "the answer depends on a quantity the question doesn't give: not enough information"
        return f"the answer is {fmt(ws.answer)}"
    if step.op == INSUFFICIENT:
        return "the question doesn't give enough information to answer it"
    val = value if value is not None else ws.run(step)
    v = "unknown" if val is UNKNOWABLE else fmt(val)
    f = [ws.fact(a) for a in step.args]
    x = [((f"[{a.text}]" if a.text else "?") if a.value is UNKNOWABLE else fmt(a.value)) if a is not None and a.kind in (NUM, CONST)
         else "?" for a in f]
    op = step.op
    if op in PROCS:
        return f"{op}({', '.join(x)}) = {v}  (invented: {PROCS[op].describe()})"
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


# ----------------------------------------------------------------------------
# Domains
# ----------------------------------------------------------------------------
_DOMAINS: dict = {}


def _domain(name):
    return _DOMAINS[name]


class Domain:
    """Everything the room needs to know about one kind of problem. The room,
    its experts and its learning never look past this interface."""

    name = "base"
    ops: list = []  # the operations its operator experts stand for (registered in OPS)
    constants: tuple = ()  # facts always on the table (e.g. K100)
    missing_info = False  # whether "there isn't enough information" is an outcome here
    verifiable = False  # whether a problem says how to check an answer (e.g. examples to pass)
    answer_kinds = None  # the kinds of fact an answer can be (None: any)
    describes = False  # whether describe() says anything (the judge then reads it too)
    max_steps = None  # longest solution worth trying (None: the room's setting)
    think_harder = None  # (beam, bindings per operator) retries while unsure (None: the room's setting)

    def __init__(self):
        _DOMAINS[self.name] = self

    def __reduce__(self):  # one instance per domain, also after pickling
        return (_domain, (self.name,))

    # reading
    def recognises(self, text) -> bool:
        """Is this a problem of mine? (How a room with many domains routes it.)"""
        return True

    def read(self, text):
        raise NotImplementedError

    def facts(self, reading) -> dict:
        raise NotImplementedError

    def context(self, reading) -> tuple:
        return ()

    def target(self, reading):
        """What a verifiable problem's answer must be (e.g. the examples' outputs)."""
        return None

    def unknowns(self, reading):
        """What the problem asks to be found, when finding it is a matter of
        derivation by sound moves (e.g. the variables a question asks about).
        A derived fact is then proved, not guessed: when unsure, the room can
        search for a derivation that reaches these and finish from there.
        None: the domain has no such notion."""
        return None

    # working
    def grounding(self, ws, step):
        return None

    def describe(self, ws, fact) -> tuple:
        """What a fact looks like at a glance, for the experts to read (e.g. an
        equation is raw, gathered, solved). Nothing, by default."""
        return ()

    def matches(self, value, target) -> bool:
        if value is UNKNOWABLE or target is UNKNOWABLE:
            return value is target
        return value is not None and value == target

    def reached(self, ws, goal) -> bool:
        """Has the workspace's latest step reached the goal: a revealed answer,
        a verifiable problem's target, or the problem's unknowns?"""
        return self.matches(ws.answer, goal)

    def fallback(self, scene, label):
        """Programs to try when the room's own search finds nothing (none by default)."""
        return ()

    def reviewers(self, seed: int) -> list:
        """Domain-specific reviewing experts (on top of the general ones)."""
        return []

    # judging and saying
    def verdict(self, task, res) -> str:
        return verdict_value(task, res.answer)

    def truth(self, task) -> str:
        """The right answer, as shown next to the room's."""
        return self.fmt(task.target if getattr(task, "answerable", True) else UNKNOWABLE)

    def fmt(self, v) -> str:
        return "?" if v is None else str(v)

    def say(self, ws, step, value=None) -> str:
        if step.op == STOP:
            return f"the answer is {self.fmt(ws.answer)}"
        if step.op == INSUFFICIENT:
            return "the question doesn't give enough information to answer it"
        op = OPS.get(step.op)
        val = value if value is not None else ws.run(step)
        args = [ws.fact(a) for a in step.args]
        shown = [a.text or self.fmt(a.value) if a is not None else "?" for a in args]
        if op is not None and op.shows is not None:
            return op.shows(shown, self.fmt(val))
        if step.op in PROCS:
            return f"{step.op}({', '.join(shown)}) = {self.fmt(val)}  (invented: {PROCS[step.op].describe()})"
        return f"{step.op}({', '.join(shown)}) = {self.fmt(val)}"


def verdict_value(task, answer) -> str:
    """right / wrong / abstain for a numeric answer. Saying "not enough
    information" is right only when that's true; on an answerable question it
    is a wrong claim."""
    if answer is None:
        return "abstain"
    answerable = getattr(task, "answerable", True)
    if answer is UNKNOWABLE:
        return "wrong" if answerable else "right"
    return "right" if answerable and task.is_correct(float(answer)) else "wrong"


class Arithmetic(Domain):
    """Maths questions in words and notation (the curriculum in world.py)."""

    name = "arith"
    ops = ARITH_OPS
    constants = tuple(Fact(f"K{k}", CONST, Fraction(k)) for k in CONSTANTS)
    missing_info = True

    def read(self, text):
        from ..maths.mathlang import read
        return read(text)

    def facts(self, reading) -> dict:
        return _question_facts(reading)

    def context(self, reading) -> tuple:
        from ..maths.mathlang import context
        return context(reading)

    def grounding(self, ws, step):
        """Solving an equation gives the variable, so its result is about every
        mention of that variable ("Is t a prime number?"); evaluating f(3) is
        about the call."""
        sk = ws.reading.skeleton
        if step.op == "solve":
            mentions = tuple(i for i, t in enumerate(sk) if t == "<var>")
            if mentions:
                return mentions
        if step.op == "apply" and len(step.args) == 2:
            c = ws.fact(step.args[1])
            if c is not None and c.where:
                return c.where
        return None

    def matches(self, v, target) -> bool:
        if v is UNKNOWABLE or target is UNKNOWABLE:
            return v is target
        return v is not None and abs(float(v) - float(target)) <= 1e-6 * max(1.0, abs(float(target)))

    def fallback(self, scene, label):
        from ..maths.programs import explain
        return explain(scene.reading, float(label), limit=5)

    def reviewers(self, seed: int) -> list:
        from .experts import CheckerExpert, EstimatorExpert
        out = [CheckerExpert(seed=seed), EstimatorExpert(seed=seed)]
        for e in out:
            e.domains = (self.name,)  # numeric checks: only for its own problems
        return out

    def fmt(self, v) -> str:
        return fmt(v)

    def say(self, ws, step, value=None) -> str:
        return say(ws, step, value)


ARITH = Arithmetic()
