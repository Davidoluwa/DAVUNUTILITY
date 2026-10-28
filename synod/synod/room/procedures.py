"""Inventing procedures: recurring sub-chains of worked solutions become new
operations, each with its own expert, and a procedure stays only if it earns
its place.

1. **Notice.** The room keeps its recent worked solutions (those confirmed
   against a revealed answer). Every connected piece of two or three steps is
   abstracted: the facts it reads become parameters, constants stay inside
   ("× then ÷100" is the same piece whatever was multiplied). A piece is worth
   having in proportion to how many steps it would save, counted over distinct
   wordings (as in DreamCoder's library learning: the best abstraction is the
   one that shortens the corpus most).
2. **Try.** The room copies itself and gives the copy the best new procedure
   as an operation of its own, with an expert that knows nothing yet except
   what it can learn from the room's past solutions rewritten to use it (and
   the neural experts get a new word in their vocabulary for it). The copy's
   memory is rewritten the same way.
3. **Keep it only if it helps.** Both rooms then meet the same next questions,
   at the same search budget, before either learns from them. If the copy
   gets more of them right than the original does, the copy becomes the room;
   otherwise the procedure is dropped.

Nothing here knows any procedure in advance, or which kinds of question have
which shape. Pieces are found by counting what the room itself did.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict, deque

from .workspace import (ANSWER, CONST, EQ, FDEF, CALL, EXPR, LIST, NUM, POLY, TERMINAL, Procedure,
                        Step, op_info, program_to_steps, steps_to_program)

_LEAF_KIND = {"N": NUM, "L": LIST, "Q": EQ, "F": FDEF, "C": CALL, "K": CONST}


def tree(steps) -> tuple:
    """A solution's steps as one program tree (results inlined)."""
    return steps_to_program([s for s in steps if s.op not in TERMINAL])


def _is_leaf(p) -> bool:
    return p[0] in ("N", "L", "Q", "F", "C", "X", "K")


def _ops(p) -> int:
    return 0 if _is_leaf(p) else 1 + sum(_ops(a) for a in p[1:])


def _shape(p) -> str:
    """A key for ordering commutative arguments that ignores which parameter is which."""
    if p[0] == "$":
        return "$"
    if p[0] == "K":
        return repr(p)
    return p[0] + "(" + ",".join(_shape(a) for a in p[1:]) + ")"


def _sorted(p):
    """Commutative arguments in a fixed order (parameters keep their numbers)."""
    if p[0] in ("$", "K"):
        return p
    args = [_sorted(a) for a in p[1:]]
    op = op_info(p[0])
    if op is not None and op.comm:
        args.sort(key=_shape)
    return (p[0], *args)


def _renumber(body):
    """Parameters numbered by first use: (body, {old number: new number})."""
    order = {}

    def walk(p):
        if p[0] == "$":
            order.setdefault(p[1], len(order))
            return ("$", order[p[1]])
        if p[0] == "K":
            return p
        return (p[0], *[walk(a) for a in p[1:]])
    return walk(body), order


def canonical(body) -> tuple:
    return _renumber(_sorted(body))[0]


def fragments(prog, max_ops: int = 3):
    """Every connected piece of a program with 2..max_ops operations, abstracted:
    [(body, kinds per parameter)]."""
    out = []

    def cuts(p):
        """Ways to take p as the top of a piece: [(body with ("@", sub) holes, ops)]."""
        if _is_leaf(p):
            return [(("@", p), 0)]
        options = [[(("@", a), 0)] + ([] if _is_leaf(a) else cuts(a)) for a in p[1:]]
        res = [((p[0],), 1)]
        for opts in options:
            res = [(body + (b,), n + m) for body, n in res for b, m in opts if n + m <= max_ops]
        return res

    def visit(p):
        if _is_leaf(p):
            return
        for body, n in cuts(p):
            if n >= 2:
                ab = _abstract(body)
                if ab is not None:
                    out.append(ab)
        for a in p[1:]:
            visit(a)

    visit(prog)
    return out


def _abstract(body):
    """Holes become parameters (the same fact twice is the same parameter);
    constants stay. Kinds come from the operations' signatures."""
    params, kinds = {}, {}

    def walk(p, accept):
        if p[0] == "@":
            sub = p[1]
            if sub[0] == "K":
                return sub
            key = sub if _is_leaf(sub) else ("result", sub)
            i = params.setdefault(key, len(params))
            k = kinds.get(i)
            accept = tuple(x for x in accept if x != CONST)  # constants stay inside the procedure
            kinds[i] = accept if k is None else tuple(x for x in k if x in accept)
            return ("$", i)
        op = op_info(p[0])
        if op is None:
            return None
        args = []
        for a, acc in zip(p[1:], op.sig):
            w = walk(a, acc)
            if w is None:
                return None
            args.append(w)
        return (p[0], *args)

    out = walk(body, None)
    if out is None or not params or any(not kinds[i] for i in kinds):
        return None
    canon, order = _renumber(_sorted(out))
    sig = tuple(kinds[old] for old, _ in sorted(order.items(), key=lambda kv: kv[1]))
    return canon, sig


def name_of(body) -> str:
    return "proc_" + hashlib.md5(repr(body).encode()).hexdigest()[:5]


def make(body, sig) -> Procedure:
    return Procedure(name_of(body), body, tuple(tuple(k) for k in sig))


# ----------------------------------------------------------------------------
# Rewriting solutions to use a procedure
# ----------------------------------------------------------------------------
def _kind_of(p):
    if p[0] in _LEAF_KIND:
        return _LEAF_KIND[p[0]]
    if p[0] == "X":
        return None  # expression or polynomial: either
    return NUM


def _match(pat, p, binding, proc):
    if pat[0] == "$":
        i = pat[1]
        if i in binding:
            return binding[i] == p
        k = _kind_of(p)
        if k is None:
            k = (EXPR, POLY)
        if not any(x in proc.sig[i] for x in (k if isinstance(k, tuple) else (k,))):
            return False
        binding[i] = p
        return True
    if pat[0] == "K" or _is_leaf(p):
        return pat == p
    if pat[0] != p[0] or len(pat) != len(p):
        return False
    op = op_info(pat[0])
    orders = [list(p[1:])]
    if op is not None and op.comm and len(p) == 3:
        orders.append([p[2], p[1]])
    for args in orders:
        b = dict(binding)
        if all(_match(x, y, b, proc) for x, y in zip(pat[1:], args)):
            binding.clear()
            binding.update(b)
            return True
    return False


def rewrite(prog, proc: Procedure):
    """The program with every occurrence of the procedure's body contracted."""
    if _is_leaf(prog):
        return prog
    b = {}
    if _match(proc.body, prog, b, proc):
        return (proc.name, *[rewrite(b[i], proc) for i in range(len(proc.sig))])
    return (prog[0], *[rewrite(a, proc) for a in prog[1:]])


def rewrite_all(prog, procs):
    """Contract every procedure, biggest first (so a procedure built from a
    smaller one isn't hidden by it)."""
    for proc in sorted(procs, key=lambda p: -_ops(_as_prog(p.body))):
        prog = rewrite(prog, proc)
    return prog


def retell(tokens, procs) -> tuple:
    """A stored solution's tokens, re-expressed with the given procedures."""
    steps = [Step.parse(t) for t in tokens]
    if not steps or any(s.op in TERMINAL for s in steps):
        return tuple(tokens)
    prog = tree(steps)
    if prog is None:
        return tuple(tokens)
    return tuple(s.token for s in program_to_steps(rewrite_all(prog, procs)))


def replay_path(scene, tokens, procs=()):
    """A stored solution as a worked path [(workspace, step)] ending with the
    answer, written in the given vocabulary of procedures (each occurrence of
    a procedure's body contracted). None if it doesn't run."""
    steps = [Step.parse(t) for t in tokens]
    if any(s.op in TERMINAL for s in steps):
        ws = scene.workspace()
        return [(ws, steps[-1])] if steps else None
    prog = tree(steps)
    if prog is None:
        return None
    prog = rewrite_all(prog, procs)
    path, ws = [], scene.workspace()
    for step in program_to_steps(prog):
        v = ws.run(step)
        if v is None:
            return None
        path.append((ws, step))
        ws = ws.apply(step, v)
    path.append((ws, ANSWER))
    return path


def uses(prog, proc: Procedure) -> bool:
    if _is_leaf(prog):
        return False
    return prog[0] == proc.name or any(uses(a, proc) for a in prog[1:])


# ----------------------------------------------------------------------------
# The room's notebook of worked solutions
# ----------------------------------------------------------------------------
class Library:
    def __init__(self, size: int = 3000, min_wordings: int = 5, max_ops: int = 3):
        self.recent = deque(maxlen=size)  # (question, skeleton, solution tokens)
        self.min_wordings = min_wordings
        self.max_ops = max_ops
        self.tried: set = set()  # procedure bodies already tried
        self.log: list = []  # one entry per trial

    def record(self, scene, path) -> None:
        tokens = tuple(s.token for _, s in path if s.op != "answer")
        if tokens:
            self.recent.append((scene.question, scene.skeleton, tokens))

    def candidates(self, top: int = 5, procs=()) -> list:
        """[(saving, procedure, wordings, occurrences)], best first. Pieces are
        counted in the room's current vocabulary, so a new procedure can be
        built from ones it already has."""
        wordings = defaultdict(set)
        count = Counter()
        sigs = {}
        for _, sk, tokens in self.recent:
            steps = [Step.parse(t) for t in tokens]
            if any(s.op in TERMINAL for s in steps):
                continue
            prog = tree(steps)
            if prog is None:
                continue
            prog = rewrite_all(prog, procs)
            for body, sig in set(fragments(prog, self.max_ops)):
                wordings[body].add(sk)
                count[body] += 1
                sigs[body] = sig
        out = []
        for body, sks in wordings.items():
            if body in self.tried or len(sks) < self.min_wordings:
                continue
            saving = (_ops(_as_prog(body)) - 1) * count[body]  # steps it would save over the notebook
            out.append((saving, make(body, sigs[body]), len(sks), count[body]))
        out.sort(key=lambda t: (-t[0], repr(t[1].body)))
        return out[:top]


def _as_prog(body):
    """Count operations in a body (parameters count as leaves)."""
    if body[0] in ("$", "K"):
        return ("N", 0)
    return (body[0], *[_as_prog(a) for a in body[1:]])


# kinds a procedure parameter may have, for tests and display
KINDS = {NUM: "number", CONST: "constant", LIST: "list", EQ: "equation", FDEF: "function", CALL: "call",
         EXPR: "expression", POLY: "polynomial"}

__all__ = ["Library", "fragments", "rewrite", "rewrite_all", "retell", "replay_path", "make", "canonical", "uses"]
