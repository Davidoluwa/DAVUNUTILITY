"""A curriculum of list programs, described in words, with examples.

Every kind of task is defined by the program that solves it, over the input
``xs`` and the numbers its description mentions (``a``, ``b``), e.g.
``("take", ("sort_desc", "xs"), "a")`` for "Keep the {a} largest numbers,
biggest first." A task shows three examples; the program is graded on four
hidden inputs of other lengths and ranges, so a program that only fits the
examples fails.

Nobody shows the room a program. It has the examples, and it must find a
program that passes them; that is all it ever learns from.

Test sets:
  seen        the training kinds of task, new examples
  paraphrase  descriptions worded in ways never seen in training
  compose     combinations of familiar steps never seen together
  longer      four-step programs, longer than anything in training
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from ..protocol import Task
from ..room.workspace import canonical_program
from .lang import _TABLE, _one

FN = {name: fn for name, _, _, fn, _, _ in _TABLE}
K = lambda k: ("K", k)  # noqa: E731


@dataclass
class Family:
    name: str
    program: tuple
    train: list
    test: list = field(default_factory=list)
    group: str = "core"  # core | multi | comp_test | long
    a: tuple = (1, 4)  # range of the first number in the description
    b: tuple = (1, 9)
    want: str = ""  # something the inputs must contain for the task to make sense ("neg", "dup")


F = Family
FAMILIES = [
    # one step -----------------------------------------------------------
    F("sort", ("sort", "xs"), ["Sort the numbers from smallest to largest.", "Put the numbers in increasing order."],
      ["Arrange the list in ascending order."]),
    F("sort_desc", ("sort_desc", "xs"), ["Sort the numbers from largest to smallest.", "Put the numbers in decreasing order."],
      ["Arrange the list in descending order."]),
    F("reverse", ("reverse", "xs"), ["Reverse the numbers.", "Write the numbers backwards."],
      ["Give the list in reverse order."]),
    F("unique", ("unique", "xs"), ["Remove the repeated numbers.", "Keep each number only once."],
      ["Drop the duplicates, keeping the first of each."], want="dup"),
    F("evens", ("evens", "xs"), ["Keep only the even numbers.", "Remove the odd numbers."],
      ["Filter the list down to its even values."]),
    F("odds", ("odds", "xs"), ["Keep only the odd numbers.", "Remove the even numbers."],
      ["Filter the list down to its odd values."]),
    F("positives", ("positives", "xs"), ["Keep only the positive numbers.", "Remove the numbers that are not positive."],
      ["Filter the list down to its positive values."], want="neg"),
    F("squares", ("squares", "xs"), ["Square every number.", "Replace each number by its square."],
      ["Give the square of each value."]),
    F("take", ("take", "xs", "a"), ["Keep the first {a} numbers.", "Return the first {a} numbers."],
      ["Give only the leading {a} values."], a=(2, 4)),
    F("drop", ("drop", "xs", "a"), ["Remove the first {a} numbers.", "Skip the first {a} numbers."],
      ["Give everything after the leading {a} values."], a=(2, 4)),
    F("add_each", ("add_each", "xs", "a"), ["Add {a} to every number.", "Increase each number by {a}."],
      ["Give each value plus {a}."], a=(1, 9)),
    F("mul_each", ("mul_each", "xs", "a"), ["Multiply every number by {a}.", "Scale each number by {a}."],
      ["Give each value times {a}."], a=(3, 9)),
    F("double", ("mul_each", "xs", K(2)), ["Double every number.", "Make each number twice as big."],
      ["Give each value doubled."]),
    F("above", ("above", "xs", "a"), ["Keep the numbers greater than {a}.", "Remove the numbers that are not greater than {a}."],
      ["Filter the list down to values above {a}."], a=(2, 12)),
    F("below", ("below", "xs", "a"), ["Keep the numbers less than {a}.", "Remove the numbers that are not less than {a}."],
      ["Filter the list down to values under {a}."], a=(2, 12)),
    F("without", ("without", "xs", "a"), ["Remove every {a}.", "Delete each copy of {a}."],
      ["Give the list with every copy of {a} taken out."], a=(1, 9), want="has_a"),
    F("total", ("total", "xs"), ["Add up the numbers.", "Find the sum of the numbers."], ["Give the total of the list."]),
    F("length", ("length", "xs"), ["Count the numbers.", "Find how many numbers there are."], ["Give the size of the list."]),
    F("largest", ("largest", "xs"), ["Find the largest number.", "Find the biggest number."],
      ["Give the maximum of the list."]),
    F("smallest", ("smallest", "xs"), ["Find the smallest number.", "Find the lowest number."],
      ["Give the minimum of the list."]),
    F("first", ("first", "xs"), ["Return the first number.", "Find the number at the front."], ["Give the leading value."]),
    F("last", ("last", "xs"), ["Return the last number.", "Find the number at the end."], ["Give the final value."]),
    F("nth", ("nth", "xs", "a"), ["Return the number in position {a}.", "Find number {a} of the list."],
      ["Give the value at place {a}."], a=(2, 4)),
    F("drop_first", ("drop", "xs", K(1)), ["Remove the first number.", "Skip the number at the front."],
      ["Give everything after the leading value."]),
    # two or three steps --------------------------------------------------
    F("top", ("take", ("sort_desc", "xs"), "a"), ["Keep the {a} largest numbers, biggest first.",
                                                  "Find the {a} biggest numbers, largest first."],
      ["Give the top {a} values in descending order."], "multi", a=(2, 4)),
    F("bottom", ("take", ("sort", "xs"), "a"), ["Keep the {a} smallest numbers, smallest first.",
                                                "Find the {a} lowest numbers, lowest first."],
      ["Give the bottom {a} values in ascending order."], "multi", a=(2, 4)),
    F("count_above", ("length", ("above", "xs", "a")), ["Count the numbers greater than {a}.",
                                                         "Find how many numbers are greater than {a}."],
      ["Give the number of values above {a}."], "multi", a=(2, 12)),
    F("sum_evens", ("total", ("evens", "xs")), ["Add up the even numbers.", "Find the sum of the even numbers."],
      ["Give the total of the even values."], "multi"),
    F("sum_squares", ("total", ("squares", "xs")), ["Add up the squares of the numbers.", "Find the sum of the squares."],
      ["Give the total of the squared values."], "multi"),
    F("count_unique", ("length", ("unique", "xs")), ["Count the different numbers.",
                                                     "Find how many different numbers there are."],
      ["Give the number of distinct values."], "multi", want="dup"),
    F("sorted_unique", ("sort", ("unique", "xs")), ["Sort the different numbers from smallest to largest."],
      ["Arrange the distinct values in ascending order."], "multi", want="dup"),
    F("range", ("minus", ("largest", "xs"), ("smallest", "xs")), ["Find the largest number minus the smallest number.",
                                                                   "Find the difference between the biggest and lowest numbers."],
      ["Give the maximum of the list minus its minimum."], "multi"),
    F("count_positive", ("length", ("positives", "xs")), ["Count the positive numbers."],
      ["Give the number of positive values."], "multi", want="neg"),
    F("last_few", ("take", ("reverse", "xs"), "a"), ["Return the last {a} numbers, last first."],
      ["Give the final {a} values in reverse order."], "multi", a=(2, 4)),
    F("largest_even", ("largest", ("evens", "xs")), ["Find the largest even number."],
      ["Give the maximum of the even values."], "multi"),
    F("sorted_evens", ("sort", ("evens", "xs")), ["Sort the even numbers from smallest to largest."],
      ["Arrange the even values in ascending order."], "multi"),
    F("ends", ("plus", ("first", "xs"), ("last", "xs")), ["Add the first number to the last number."],
      ["Give the leading value plus the final value."], "multi"),
    F("sum_top", ("total", ("take", ("sort_desc", "xs"), "a")), ["Add up the {a} largest numbers."],
      ["Give the total of the top {a} values."], "multi", a=(2, 4)),
    F("sum_after", ("total", ("drop", "xs", "a")), ["Add up the numbers after the first {a}."],
      ["Give the total of everything after the leading {a} values."], "multi", a=(2, 3)),
    F("sum_doubled", ("total", ("mul_each", "xs", K(2))), ["Double every number and add them up."],
      ["Give the total of the doubled values."], "multi"),
    # combinations never seen in training ---------------------------------
    F("sum_odds", ("total", ("odds", "xs")), ["Add up the odd numbers."], [], "comp_test"),
    F("count_below", ("length", ("below", "xs", "a")), ["Count the numbers less than {a}."], [], "comp_test", a=(2, 12)),
    F("largest_square", ("largest", ("squares", "xs")), ["Find the largest square of the numbers."], [], "comp_test"),
    F("sum_unique", ("total", ("unique", "xs")), ["Add up the different numbers."], [], "comp_test", want="dup"),
    F("sum_bottom", ("total", ("take", ("sort", "xs"), "a")), ["Add up the {a} smallest numbers."], [], "comp_test",
      a=(2, 4)),
    F("sum_above", ("total", ("above", "xs", "a")), ["Add up the numbers greater than {a}."], [], "comp_test", a=(2, 12)),
    F("sorted_positives", ("sort", ("positives", "xs")), ["Sort the positive numbers from smallest to largest."], [],
      "comp_test", want="neg"),
    F("count_odds", ("length", ("odds", "xs")), ["Count the odd numbers."], [], "comp_test"),
    F("smallest_odd", ("smallest", ("odds", "xs")), ["Find the smallest odd number."], [], "comp_test"),
    # four steps, longer than anything in training ------------------------
    F("sum_top_unique", ("total", ("take", ("sort_desc", ("unique", "xs")), "a")),
      ["Add up the {a} largest different numbers."], [], "long", a=(2, 3), want="dup"),
    F("top_even_squares", ("take", ("sort_desc", ("squares", ("evens", "xs"))), "a"),
      ["Square the even numbers and keep the {a} largest, biggest first."], [], "long", a=(2, 3)),
    F("sum_above_plus", ("total", ("add_each", ("above", "xs", "a"), "b")),
      ["Keep the numbers greater than {a}, add {b} to each, then add them up."], [], "long", a=(2, 9), b=(2, 9)),
    F("sum_odd_squares_above", ("total", ("squares", ("odds", ("above", "xs", "a")))),
      ["Add up the squares of the odd numbers greater than {a}."], [], "long", a=(2, 9)),
]
BY_NAME = {f.name: f for f in FAMILIES}
_BLANK = re.compile(r"{(\w+)}")
SPLITS = ("seen", "paraphrase", "compose", "longer")
_WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()


def evaluate(prog, xs, values):
    """Run a program on one input list."""
    if isinstance(prog, str):
        return xs if prog == "xs" else values[prog]
    if prog[0] == "K":
        return prog[1]
    args = [evaluate(a, xs, values) for a in prog[1:]]
    if any(a is None for a in args):
        return None
    try:
        return FN[prog[0]](*args)
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None


def ground(program, template):
    """Blanks become the description's numbers in order of appearance; the input is I1."""
    order = list(dict.fromkeys(b for b in _BLANK.findall(template) if b in ("a", "b")))

    def walk(p):
        if isinstance(p, str):
            return ("I", 0) if p == "xs" else ("N", order.index(p))
        if p[0] == "K":
            return p
        return (p[0], *[walk(a) for a in p[1:]])
    return canonical_program(walk(program))


def _shorter(prog):
    """The program with one step left out (keeping that step's first input), to
    check that the examples need every step."""
    def variants(p):
        if isinstance(p, str) or p[0] == "K":
            return
        first = p[1]
        if first == "xs" or (isinstance(first, tuple) and first[0] != "K"):
            yield first
        for i, a in enumerate(p[1:], 1):
            for v in variants(a):
                yield p[:i] + (v,) + p[i + 1:]
    return list(variants(prog))


@dataclass
class CodeScenario:
    n_train: int = 4000
    n_per_test_split: int = 150
    seed: int = 0
    words_rate: float = 0.2
    shown: int = 3
    hidden: int = 4


class CodeWorld:
    def __init__(self, scenario: CodeScenario | None = None):
        self.sc = scenario or CodeScenario()
        self.rng = np.random.default_rng(self.sc.seed)

    def i(self, lo, hi):
        return int(self.rng.integers(lo, hi + 1))

    def pick(self, xs):
        return xs[int(self.rng.integers(len(xs)))]

    def _list(self, lo_len, hi_len, lo, hi):
        return [self.i(lo, hi) for _ in range(self.i(lo_len, hi_len))]

    def _ok(self, fam, xs, values, shown=True):
        out = evaluate(fam.program, xs, values)
        if out is None or (isinstance(out, tuple) and shown and not out):
            return None
        return out

    def make(self, fam: Family, held_out: bool = False):
        """(question, hidden-check problem, grounded program)."""
        pool = fam.test if held_out and fam.test else fam.train
        tpl = pool[self.i(0, len(pool) - 1)]
        for _ in range(200):
            values = {"a": self.i(*fam.a), "b": self.i(*fam.b)}
            shown = []
            for _ in range(self.sc.shown):
                xs = self._list(5, 8, -5, 20)
                if fam.want == "dup":
                    xs[self.i(0, len(xs) - 1)] = xs[0]
                if fam.want == "neg":
                    xs[self.i(0, len(xs) - 1)] = -self.i(1, 5)
                if fam.want == "has_a":
                    xs[self.i(0, len(xs) - 1)] = values["a"]
                out = self._ok(fam, tuple(xs), values)
                if out is None:
                    break
                shown.append((tuple(xs), out))
            if len(shown) < self.sc.shown:
                continue
            # the examples must need every step: leaving one out changes some output
            if any(all(evaluate(p, xs, values) == out for xs, out in shown) for p in _shorter(fam.program)):
                continue
            hidden = []
            for _ in range(50):
                xs = tuple(self._list(3, 11, -9, 30))
                out = self._ok(fam, xs, values, shown=False)
                if out is not None:
                    hidden.append((xs, out))
                if len(hidden) >= self.sc.hidden:
                    break
            if len(hidden) < self.sc.hidden:
                continue
            desc = self._describe(tpl, values)
            return self._text(desc, shown), self._text(desc, hidden), ground(fam.program, tpl)
        raise ValueError(f"{fam.name}: no valid examples")

    def _describe(self, tpl, values):
        shown = {}
        for k, v in values.items():
            shown[k] = _WORDS[v] if 0 <= v < len(_WORDS) and self.rng.random() < self.sc.words_rate else str(v)
        text = tpl.format(**shown)
        return text[0].upper() + text[1:]

    @staticmethod
    def _text(desc, pairs):
        return f"{desc} Examples: " + "; ".join(f"{_one(xs)} -> {_one(out)}" for xs, out in pairs)

    def _task(self, tid, fam, held, split):
        q, checks, prog = self.make(fam, held)
        return Task(tid, (), 0.0, None, fam.name, True, question=q, split=split, solution=prog, checks=checks)

    def menu(self, groups):
        return [f for f in FAMILIES if f.group in groups]

    def train_stream(self):
        menu = self.menu(["core"]) + self.menu(["multi"]) * 2
        for t in range(self.sc.n_train):
            yield self._task(t, self.pick(menu), False, "train")

    def test_tasks(self, start_id: int):
        plan = {"seen": (self.menu(["core", "multi"]), False), "paraphrase": (self.menu(["core", "multi"]), True),
                "compose": (self.menu(["comp_test"]), False), "longer": (self.menu(["long"]), False)}
        out, tid = [], start_id
        for split in SPLITS:
            fams, held = plan[split]
            for _ in range(self.sc.n_per_test_split):
                out.append(self._task(tid, self.pick(fams), held, split))
                tid += 1
        order = self.rng.permutation(len(out))
        return [out[i] for i in order]
