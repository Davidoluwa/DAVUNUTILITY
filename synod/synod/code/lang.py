"""Code as a domain of the room: write a small list program from a
description and examples.

A problem is a description and some examples::

    Keep the 3 largest numbers, biggest first.
    Examples: [5, 1, 4, 9, 2] -> [9, 5, 4]; [3, 8, 1, 7] -> [8, 7, 3]

The facts are the input (``I1``, one list per example), the numbers in the
description (``N1, …``) and two small constants. Every step applies one list
operation to all the examples at once, so a worked solution is a program,
and every program can be written out as Python. The examples are the check:
the room only delivers a program that passes them, and is graded on hidden
inputs it has never seen (does the program generalise beyond its examples?).

Everything here is the domain's part: what the operations are and how to
run and print them, and how to read a problem. Deliberation, search,
learning and invention are the room's, unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

from ..maths.mathlang import _spans
from ..room.workspace import CONST, NUM, STOP, Domain, Fact, Op, register_ops

SEQ, VEC = "seq", "vec"  # a list per example; a number per example
_S, _V, _K, _VK = (SEQ,), (VEC,), (NUM, CONST), (VEC, NUM, CONST)


def _int(k):
    if isinstance(k, Fraction):
        if k.denominator != 1:
            raise ValueError("not a whole number")
        return int(k)
    return k


def _lift(fn):
    """Run a per-example function over every example (numbers from the
    description are the same for all of them)."""
    def run(vals):
        n = max(len(v) for v in vals if isinstance(v, tuple))
        out = []
        for i in range(n):
            r = fn(*[v[i] if isinstance(v, tuple) else _int(v) for v in vals])
            if r is None:
                return None
            out.append(r)
        return tuple(out)
    return run


def _nonempty(f):
    return lambda xs: f(xs) if xs else None


def _shows(py):
    return lambda args, result: f"{py.format(*args)}  →  {result}"


# name, signature, result kind, per-example function, Python, commutative
_TABLE = [
    ("sort", (_S,), SEQ, lambda xs: tuple(sorted(xs)), "sorted({0})", False),
    ("sort_desc", (_S,), SEQ, lambda xs: tuple(sorted(xs, reverse=True)), "sorted({0}, reverse=True)", False),
    ("reverse", (_S,), SEQ, lambda xs: xs[::-1], "{0}[::-1]", False),
    ("unique", (_S,), SEQ, lambda xs: tuple(dict.fromkeys(xs)), "list(dict.fromkeys({0}))", False),
    ("evens", (_S,), SEQ, lambda xs: tuple(v for v in xs if v % 2 == 0), "[v for v in {0} if v % 2 == 0]", False),
    ("odds", (_S,), SEQ, lambda xs: tuple(v for v in xs if v % 2), "[v for v in {0} if v % 2 == 1]", False),
    ("positives", (_S,), SEQ, lambda xs: tuple(v for v in xs if v > 0), "[v for v in {0} if v > 0]", False),
    ("squares", (_S,), SEQ, lambda xs: tuple(v * v for v in xs), "[v * v for v in {0}]", False),
    ("take", (_S, _K), SEQ, lambda xs, k: xs[:k] if k >= 0 else None, "{0}[:{1}]", False),
    ("drop", (_S, _K), SEQ, lambda xs, k: xs[k:] if k >= 0 else None, "{0}[{1}:]", False),
    ("add_each", (_S, _K), SEQ, lambda xs, k: tuple(v + k for v in xs), "[v + {1} for v in {0}]", False),
    ("mul_each", (_S, _K), SEQ, lambda xs, k: tuple(v * k for v in xs), "[v * {1} for v in {0}]", False),
    ("above", (_S, _K), SEQ, lambda xs, k: tuple(v for v in xs if v > k), "[v for v in {0} if v > {1}]", False),
    ("below", (_S, _K), SEQ, lambda xs, k: tuple(v for v in xs if v < k), "[v for v in {0} if v < {1}]", False),
    ("without", (_S, _K), SEQ, lambda xs, k: tuple(v for v in xs if v != k), "[v for v in {0} if v != {1}]", False),
    ("concat", (_S, _S), SEQ, lambda xs, ys: xs + ys, "{0} + {1}", False),
    ("total", (_S,), VEC, lambda xs: sum(xs), "sum({0})", False),
    ("length", (_S,), VEC, lambda xs: len(xs), "len({0})", False),
    ("largest", (_S,), VEC, _nonempty(max), "max({0})", False),
    ("smallest", (_S,), VEC, _nonempty(min), "min({0})", False),
    ("first", (_S,), VEC, _nonempty(lambda xs: xs[0]), "{0}[0]", False),
    ("last", (_S,), VEC, _nonempty(lambda xs: xs[-1]), "{0}[-1]", False),
    ("nth", (_S, _K), VEC, lambda xs, k: xs[k - 1] if 1 <= k <= len(xs) else None, "{0}[{1} - 1]", False),
    ("plus", (_V, _VK), VEC, lambda a, b: a + b, "{0} + {1}", True),
    ("minus", (_V, _VK), VEC, lambda a, b: a - b, "{0} - {1}", False),
    ("times", (_V, _VK), VEC, lambda a, b: a * b, "{0} * {1}", True),
]
PYTHON = {name: py for name, _, _, _, py, _ in _TABLE}
OPS_LIST = [Op(name, sig, comm, out, _lift(fn), _shows(py)) for name, sig, out, fn, py, comm in _TABLE]
CODE_OPS = register_ops(OPS_LIST)

_EXAMPLE = re.compile(r"\[([^\]]*)\]\s*->\s*(\[[^\]]*\]|-?\d+)")


def _ints(text):
    return tuple(int(t) for t in re.findall(r"-?\d+", text))


@dataclass
class CodeReading:
    text: str
    skeleton: tuple
    sentences: tuple
    words: tuple
    nums: list = field(default_factory=list)  # (value, position, as written)
    inputs: tuple = ()  # one list per example
    outputs: tuple = ()  # what each example should give
    description: str = ""

    @property
    def slots(self) -> str:
        return f"I1N{len(self.nums)}" if self.nums else "I1"


def read(text: str) -> CodeReading:
    """The description, read like any question (numbers, also written as words,
    become facts), and the examples, parsed exactly."""
    m = re.search(r"\bexamples?\s*:", text, re.I)
    desc, ex = (text[:m.start()], text[m.end():]) if m else (text, "")
    skel, sent, words, nums = [], [], [], []
    k = 0
    for t, a, b in _spans(desc):
        if t in ".?!":
            k += 1
            continue
        if t[0].isdigit():
            nums.append((int(t) if "." not in t else Fraction(t), len(skel), desc[a:b]))
            skel.append("#")
        elif t.isalpha():
            skel.append(t.lower())
            words.append(t.lower())
        else:
            continue
        sent.append(k)
    pairs = _EXAMPLE.findall(ex)
    inputs = tuple(_ints(i) for i, _ in pairs)
    outputs = tuple(_ints(o) if o.startswith("[") else int(o) for _, o in pairs)
    return CodeReading(text, tuple(skel), tuple(sent), tuple(words), nums, inputs, outputs, desc.strip())


def fmt(v, limit: int = 2) -> str:
    """A value as the room shows it: the first examples' values."""
    if v is None:
        return "?"
    if isinstance(v, tuple) and v and all(isinstance(x, (tuple, int, Fraction)) for x in v):
        shown = [_one(x) for x in v[:limit]]
        return ", ".join(shown) + (", …" if len(v) > limit else "")
    return _one(v)


def _one(x) -> str:
    if isinstance(x, tuple):
        return "[" + ", ".join(_one(y) for y in x) + "]"
    if isinstance(x, Fraction):
        return str(x.numerator) if x.denominator == 1 else str(x)
    return str(x)


class ListCode(Domain):
    """Small list programs from a description and examples."""

    name = "code"
    ops = CODE_OPS
    constants = (Fact("K1", CONST, 1), Fact("K2", CONST, 2))
    missing_info = False
    verifiable = True

    def recognises(self, text) -> bool:
        return bool(re.search(r"\bexamples?\s*:", text, re.I)) and "->" in text

    def read(self, text):
        return read(text)

    def facts(self, reading) -> dict:
        facts = {"I1": Fact("I1", SEQ, reading.inputs, -1, "xs", ())}
        for i, (v, p, text) in enumerate(reading.nums):
            facts[f"N{i + 1}"] = Fact(f"N{i + 1}", NUM, v, p, text, (p,))
        return facts

    def context(self, reading) -> tuple:
        out = reading.outputs
        kind = "none" if not out else "list" if isinstance(out[0], tuple) else "number"
        return (reading.slots, kind)

    def target(self, reading):
        return reading.outputs or None

    def matches(self, value, target) -> bool:
        return value is not None and target is not None and value == target

    def fallback(self, scene, label, limit: int = 3):
        """Exhaustive search of one- and two-step programs that pass the
        examples (how the room gets its first worked solutions, before its own
        experts can guide a search)."""
        from ..room.workspace import Step, steps_to_program
        ws0 = scene.workspace()
        first, found = [], 0
        for op in self.ops:
            for refs in ws0.bindings(op):
                st = Step(op, refs)
                scene.cache["fallback_runs"] = scene.cache.get("fallback_runs", 0) + 1
                v = ws0.run(st)
                if v is None:
                    continue
                if self.matches(v, label):
                    found += 1
                    yield steps_to_program([st])
                    if found >= limit:
                        return
                first.append((st, v))
        for st, v in first:
            ws1 = ws0.apply(st, v)
            for op in self.ops:
                for refs in ws1.bindings(op):
                    if "S1" not in refs:
                        continue
                    st2 = Step(op, refs)
                    scene.cache["fallback_runs"] = scene.cache.get("fallback_runs", 0) + 1
                    v2 = ws1.run(st2)
                    if v2 is not None and self.matches(v2, label):
                        found += 1
                        yield steps_to_program([st, st2])
                        if found >= limit:
                            return

    def verdict(self, task, res) -> str:
        """Right if the delivered program also passes the hidden inputs."""
        if res.answer is None or res.route is None:
            return "abstain"
        return "right" if passes(res.steps, task.checks) else "wrong"

    def truth(self, task) -> str:
        return "the hidden tests"

    def fmt(self, v) -> str:
        return fmt(v)

    def say(self, ws, step, value=None) -> str:
        """A step as a line of Python, with what it gives on the first examples."""
        if step.op == STOP:
            return f"return {python_name(len(ws.steps))}  →  {fmt(ws.answer)}"
        val = value if value is not None else ws.run(step)
        args = []
        for a in step.args:
            f = ws.fact(a)
            args.append("xs" if a == "I1" else f"s{a[1:]}" if a[0] == "S" else fmt(f.value) if f is not None else a)
        from ..room.workspace import PROCS
        if step.op in PROCS:
            body = _inline_python(PROCS[step.op].body, args) + f"  # invented: {step.op}"
        else:
            body = PYTHON[step.op].format(*args)
        return f"s{len(ws.steps) + 1} = {body}  →  {fmt(val)}"


CODE = ListCode()


def python_name(i: int) -> str:
    return f"s{i}" if i else "xs"


def to_python(steps, reading=None) -> str:
    """A worked solution as a Python function."""
    lines = ["def solve(xs):"]
    names = {"I1": "xs"}
    consts = {"K1": "1", "K2": "2"}
    if reading is not None:
        for i, (v, _, _) in enumerate(reading.nums):
            consts[f"N{i + 1}"] = str(v)
    n = 0
    for s in steps:
        if s.op in (STOP, "insufficient"):
            continue
        from ..room.workspace import PROCS
        if s.op in PROCS:
            body = _inline_python(PROCS[s.op].body, [names.get(a) or consts.get(a, a) for a in s.args])
        else:
            body = PYTHON[s.op].format(*[names.get(a) or consts.get(a, a) for a in s.args])
        n += 1
        names[f"S{n}"] = f"s{n}"
        lines.append(f"    s{n} = {body}")
    lines.append(f"    return {python_name(n)}")
    return "\n".join(lines)


def _inline_python(body, args) -> str:
    if body[0] == "$":
        return args[body[1]]
    if body[0] == "K":
        return str(body[1])
    return "(" + PYTHON[body[0]].format(*[_inline_python(a, args) for a in body[1:]]) + ")"


def passes(steps, checks: str) -> bool:
    """Does this program give the right output on every hidden input?"""
    from ..room.workspace import Workspace
    r = read(checks)
    ws = Workspace(r, domain=CODE)
    for s in steps:
        if s.op in (STOP, "insufficient"):
            continue
        v = ws.run(s)
        if v is None:
            return False
        ws = ws.apply(s, v)
    return ws.answer is not None and ws.answer == r.outputs


def run_python(source: str, xs):
    """Run a generated program (only ever our own generated source)."""
    env: dict = {}
    exec(source, env)  # noqa: S102 - the room's own generated code, for checking it
    return env["solve"](list(xs))
