"""A denser maths curriculum: one to four steps per question.

Every question type is defined by the program that solves it, written over the
template's named blanks, e.g. ``("sub", ("add", "a", ("mul", "b", "c")), "d")``
for "Ann has {a} apples, buys {b} bags of {c} and gives away {d}...". The world
maps blanks to the question's notation (numbers in order of appearance, the
equation, the function, ...) and computes the answer by running that program.

Nobody in the room ever sees the program. Half the training questions reveal
their answer afterwards; the room has to discover the steps itself. The
program is kept on the task only so that evaluation can check whether the room
solved a question *the right way*, not just whether its number was right.

Test sets probe different kinds of generalisation:
  seen        familiar wording, new numbers
  paraphrase  wording never seen in training
  big         familiar wording, numbers ~100x bigger
  story       word problems (1-3 steps) with new names, objects and phrasings
  compose     combinations of familiar steps never seen together (2-3 steps)
  longer      four-step problems, longer than anything in training
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..maths.mathlang import context, features, read
from ..maths.world import NAMES_TEST, NAMES_TRAIN, OBJ_TEST, OBJ_TRAIN, UNITS, _isprime, _poly_text
from ..protocol import Task
from .workspace import Workspace, canonical_program, program_to_steps

NUMERIC = ("a", "b", "c", "d", "e", "p")
SLOTS = {"eq": ("Q", 0), "fdef": ("F", 0), "call": ("C", 0), "poly": ("X", 0), "x": ("X", 0), "list": ("L", 0)}


@dataclass
class Family:
    name: str
    program: tuple  # over blank names
    train: list
    test: list = field(default_factory=list)
    sample: Callable = None  # (world, big) -> dict of blank values
    group: str = "core"  # core | multi | story | comp | comp_test | long
    big: bool = True  # can appear in the "big numbers" test

    @property
    def depth(self) -> int:
        def d(p):
            return 1 + max((d(a) for a in p[1:] if isinstance(a, tuple) and a[0] != "K"), default=0) \
                if isinstance(p, tuple) and p[0] != "K" else 0
        return d(self.program)


# ----------------------------------------------------------------------------
# Samplers
# ----------------------------------------------------------------------------
def two(w, big):
    s = w.scale(big)
    return {"a": w.i(2, 99) * s, "b": w.i(2, 99) * s}


def sub_pair(w, big):
    d = two(w, big)
    if w.rng.random() < 0.3:
        d["a"], d["b"] = d["b"], d["a"]
    return d


def div_pair(w, big):
    b, q = w.i(2, 25) * (w.scale(big) if big else 1), w.i(2, 40) * w.scale(big)
    return {"a": b * q, "b": b}


def calc(w, big):
    s = w.scale(big)
    a, b, c, d = (w.i(1, 30) * s for _ in range(4))
    forms = [f"{a} + {b} * {c}", f"({a} + {b}) * {c}", f"{a} * {b} - {c}", f"{a} - {b} + {c} - {d}", f"{a} * ({b} - {c})"]
    return {"x": forms[w.i(0, len(forms) - 1)]}


def mod_pair(w, big):
    return {"a": w.i(10, 300) * w.scale(big), "b": w.i(2, 19)}


def gcd_pair(w, big):
    g = w.i(2, 15)
    a, b = g * w.i(1, 12) * w.scale(big), g * w.i(1, 12)
    return {"a": a, "b": b + g if a == b else b}


def prime(w, big):
    hi = 200 * w.scale(big)
    if w.rng.random() < 0.5:
        while True:
            a = w.i(2, hi)
            if _isprime(a):
                return {"a": a}
    return {"a": w.i(2, int(hi ** 0.5)) * w.i(2, int(hi ** 0.5))}


def pow_pair(w, big):
    return {"a": w.i(2, 9) * (10 if big else 1), "b": w.i(2, 5)}


def one(lo, hi):
    def f(w, big):
        return {"a": w.i(lo, hi) * w.scale(big)}
    return f


def square_root(w, big):
    r = w.i(2, 40) * w.scale(big)
    return {"a": r * r}


def equation(w, big):
    eq, v, x = w.eq(big)
    return {"eq": eq, "v": v, "_x": x}


def function(w, big):
    while True:  # a bare "x" or "-x" doesn't read as notation
        coeffs, var = w.poly(big)
        if len(_poly_text(coeffs, var)) > 2:
            break
    return {"f": w.pick("fghp"), "v": var, "poly": _poly_text(coeffs, var),
            "ca": w.i(-5, 6) * (10 if big else 1), "a": w.i(-5, 6) * (10 if big else 1)}


def sequence(w, big):
    xs, _ = w.seq(big)
    return {"list": ", ".join(map(str, xs))}


def numbers_list(w, big, mean=False):
    n = w.i(4, 6)
    xs = [w.i(-20, 60) * w.scale(big) for _ in range(n)]
    if mean:
        xs[-1] += (-sum(xs)) % n
    text = ", ".join(map(str, xs[:-1])) + " and " + str(xs[-1]) if w.rng.random() < 0.5 else ", ".join(map(str, xs))
    return {"list": text}


def compare(w, big):
    s = w.scale(big)
    a, b = w.i(-50, 99) * s, w.i(-50, 99) * s
    return {"a": a, "b": b + 1 if a == b else b}


def unit_up(w, big):
    small, bigu, k = w.pick(UNITS)
    return {"s": small, "u": bigu, "a": w.i(2, 30) * w.scale(big), "k": ("K", k)}


def unit_down(w, big):
    small, bigu, k = w.pick(UNITS)
    return {"s": small, "u": bigu, "a": w.i(1, 20) * k * w.scale(big), "k": ("K", k)}


def rounding(w, big):
    b = w.pick([10, 100, 1000])
    return {"a": w.i(11, 9999) * w.scale(big), "b": b}


def negative(w, big):
    return {"a": -w.i(2, 999) * w.scale(big)}


def even(w, big):
    return {"a": 2 * w.i(2, 400) * w.scale(big)}


def percent(w, big):
    return {"p": w.pick([5, 10, 15, 20, 25, 30, 40, 50, 60, 75]), "b": 20 * w.i(1, 30) * w.scale(big)}


def pair_even_sum(w, big):
    s = w.scale(big)
    a = w.i(2, 99) * s
    b = w.i(2, 99) * s
    return {"a": a, "b": b + s if (a + b) % 2 else b}


def sides(w, big):
    s = w.scale(big)
    a, b = w.i(2, 40) * s, w.i(2, 40) * s
    return {"a": a, "b": b + s if (a * b) % 2 else b}


def side(w, big):
    return {"a": w.i(2, 40) * w.scale(big)}


def speed(w, big):
    b, v = w.i(2, 9), w.i(3, 90) * w.scale(big)
    return {"a": b * v, "b": b}


def travel(w, big):
    return {"a": w.i(3, 90) * w.scale(big), "b": w.i(2, 9)}


def who(w, test=False):
    return {"n": w.pick(NAMES_TEST if test else NAMES_TRAIN), "o": w.pick(OBJ_TEST if test else OBJ_TRAIN)}


def story(fn):
    def f(w, big, test=False):
        d = fn(w)
        d.update(who(w, test))
        return d
    f.story = True
    return f


@story
def st_two(w):
    return {"a": w.i(10, 60), "b": w.i(2, 9)}


@story
def st_div(w):
    b, q = w.i(2, 9), w.i(2, 15)
    return {"a": b * q, "b": b}


@story
def st_buy(w):
    return {"a": w.i(5, 60), "b": w.i(2, 9), "c": w.i(2, 12)}


@story
def st_gain_lose(w):
    a, b = w.i(10, 60), w.i(2, 30)
    return {"a": a, "b": b, "c": w.i(1, a)}


@story
def st_share(w):
    c, q = w.i(2, 9), w.i(2, 15)
    a = w.i(1, c * q - 1)
    return {"a": a, "b": c * q - a, "c": c}


@story
def st_change(w):
    while True:
        a, b, c = w.i(2, 9), w.i(1, 9), w.pick([20, 50, 100])
        if a * b < c:
            return {"a": a, "b": b, "c": c}


@story
def st_three(w):
    a, b, c = w.i(5, 60), w.i(2, 9), w.i(2, 12)
    return {"a": a, "b": b, "c": c, "d": w.i(1, a + b * c - 1)}


@story
def st_four(w):
    while True:
        a, b, c, e = w.i(5, 60), w.i(2, 9), w.i(2, 12), w.i(2, 9)
        total = a + b * c
        d = w.i(1, total - 1)
        if (total - d) % e == 0:
            return {"a": a, "b": b, "c": c, "d": d, "e": e}


@story
def st_change_two(w):
    while True:
        a, b, c, d, e = w.i(2, 6), w.i(1, 9), w.i(2, 6), w.i(1, 9), w.pick([50, 100])
        if a * b + c * d < e:
            return {"a": a, "b": b, "c": c, "d": d, "e": e}


def eq_plus(w, big):
    d = equation(w, big)
    d["c"] = w.i(2, 12)
    return d


def eq_prime(w, big):
    while True:
        d = equation(w, big)
        if _isprime(d["_x"]) or w.rng.random() < 0.4:
            d["c"] = w.i(2, 12)
            return d


def eq_square_div(w, big):
    while True:
        d = equation(w, big)
        c, dd = w.i(2, 12), w.i(2, 9)
        if (d["_x"] ** 2 + c) % dd == 0:
            d["c"], d["d"] = c, dd
            return d


def fn_plus(w, big):
    d = function(w, big)
    d["c"] = w.i(2, 12)
    d.pop("a")
    return d


def gcd_plus(w, big):
    d = gcd_pair(w, False)
    d["c"] = w.i(2, 12)
    return d


def three(w, big):
    return {"a": w.i(2, 60), "b": w.i(2, 60), "c": w.i(2, 12)}


def sum_div(w, big):
    c = w.i(2, 9)
    a = w.i(2, 60)
    b = c * w.i(2, 15) - a
    return {"a": a, "b": b if b > 0 else b + c * 10, "c": c}


def mean_plus(w, big):
    d = numbers_list(w, big, mean=True)
    d["c"] = w.i(2, 12)
    return d


def pct_sum(w, big):
    p = w.pick([10, 20, 25, 50])
    a = 20 * w.i(1, 15)
    return {"p": p, "a": a, "b": 20 * w.i(1, 15)}


def rect_square(w, big):
    return {"a": w.i(5, 30), "b": w.i(5, 30), "c": w.i(2, 12)}


# ----------------------------------------------------------------------------
# The families
# ----------------------------------------------------------------------------
K = lambda k: ("K", k)  # noqa: E731

FAMILIES = [
    # one step -------------------------------------------------------------
    Family("add", ("add", "a", "b"), ["What is {a} plus {b}?", "Calculate {a} plus {b}.", "Add {a} and {b}.",
                                      "What is the sum of {a} and {b}?", "Find the sum of {a} and {b}."],
           ["Work out {a} plus {b}.", "What do you get if you add {a} and {b}?"], two),
    Family("sub", ("sub", "a", "b"), ["What is {a} minus {b}?", "Calculate {a} minus {b}.", "Subtract {b} from {a}.",
                                      "What is {a} take away {b}?"],
           ["Work out {a} minus {b}.", "What do you get if you subtract {b} from {a}?"], sub_pair),
    Family("mul", ("mul", "a", "b"), ["What is {a} times {b}?", "Multiply {a} by {b}.", "What is the product of {a} and {b}?",
                                      "Calculate {a} multiplied by {b}."],
           ["Work out {a} times {b}.", "Find the product of {a} and {b}."], two),
    Family("div", ("div", "a", "b"), ["What is {a} divided by {b}?", "Divide {a} by {b}.", "Calculate {a} divided by {b}."],
           ["Work out {a} divided by {b}.", "What do you get if you divide {a} by {b}?"], div_pair),
    Family("calc", ("calc", "x"), ["What is {x}?", "Calculate {x}.", "Evaluate {x}."], ["Work out {x}.", "Compute {x}."], calc),
    Family("mod", ("mod", "a", "b"), ["What is the remainder when {a} is divided by {b}?", "What is {a} modulo {b}?"],
           ["Find the remainder when {a} is divided by {b}.", "What remains when {a} is divided by {b}?"], mod_pair),
    Family("gcd", ("gcd", "a", "b"), ["What is the greatest common divisor of {a} and {b}?",
                                      "Calculate the highest common factor of {a} and {b}."],
           ["Find the greatest common divisor of {a} and {b}."], gcd_pair),
    Family("lcm", ("lcm", "a", "b"), ["What is the least common multiple of {a} and {b}?",
                                      "Calculate the lowest common multiple of {a} and {b}."],
           ["Find the least common multiple of {a} and {b}."], gcd_pair),
    Family("prime", ("is_prime", "a"), ["Is {a} a prime number?", "Is {a} prime?"],
           ["Is the number {a} prime?", "Determine whether {a} is a prime number."], prime, big=False),
    Family("pow", ("pow", "a", "b"), ["What is {a} to the power of {b}?", "Calculate {a} raised to the power {b}."],
           ["Work out {a} to the power of {b}."], pow_pair),
    Family("square", ("square", "a"), ["What is the square of {a}?", "What is {a} squared?"], ["Calculate {a} squared."],
           one(2, 40)),
    Family("cube", ("pow", "a", K(3)), ["What is {a} cubed?", "What is the cube of {a}?"], ["Calculate {a} cubed."], one(2, 20)),
    Family("sqrt", ("sqrt", "a"), ["What is the square root of {a}?", "Calculate the square root of {a}."],
           ["Find the square root of {a}."], square_root),
    Family("half", ("div", "a", K(2)), ["What is half of {a}?", "Halve {a}."], ["Find half of {a}."], even),
    Family("double", ("mul", "a", K(2)), ["What is double {a}?", "Double {a}."], ["What is twice {a}?"], one(2, 400)),
    Family("abs", ("abs", "a"), ["What is the absolute value of {a}?"], ["Find the absolute value of {a}."], negative),
    Family("round", ("round", "a", "b"), ["Round {a} to the nearest {b}.", "What is {a} rounded to the nearest {b}?"],
           ["Round {a} off to the nearest {b}."], rounding, big=False),
    Family("solve", ("solve", "eq"), ["Solve {eq} for {v}.", "What is {v} in {eq}?", "Find {v} if {eq}."],
           ["Solve for {v}: {eq}.", "Given {eq}, what is {v}?"], equation),
    Family("apply", ("apply", "fdef", "call"), ["Let {f}({v}) = {poly}. What is {f}({ca})?",
                                                "Let {f}({v}) = {poly}. Calculate {f}({ca})."],
           ["Suppose {f}({v}) = {poly}. Find {f}({ca}).", "Define {f}({v}) = {poly}. What is {f}({ca})?"], function),
    Family("at", ("at", "poly", "a"), ["What is the value of {poly} when {v} is {a}?", "Evaluate {poly} when {v} is {a}."],
           ["Find the value of {poly} when {v} is {a}."], function),
    Family("slope", ("slope", "fdef", "a"), ["Let {f}({v}) = {poly}. What is the derivative of {f} when {v} is {a}?"],
           ["Suppose {f}({v}) = {poly}. Find the derivative of {f} when {v} is {a}."], function),
    Family("next", ("next", "list"), ["What comes next: {list}?", "What is the next term in {list}?"],
           ["Continue the sequence: {list}.", "Find the next term of {list}."], sequence),
    Family("mean", ("mean", "list"), ["What is the mean of {list}?", "Calculate the average of {list}."],
           ["Find the mean of {list}."], lambda w, big: numbers_list(w, big, mean=True)),
    Family("median", ("median", "list"), ["What is the median of {list}?"], ["Find the median of {list}."], numbers_list),
    Family("lsum", ("sum", "list"), ["What is the total of {list}?", "Calculate the total of {list}."],
           ["Add up {list}."], numbers_list),
    Family("lmax", ("lmax", "list"), ["What is the largest number in {list}?", "What is the biggest value in {list}?"],
           ["Which is the largest of {list}?"], numbers_list),
    Family("lmin", ("lmin", "list"), ["What is the smallest number in {list}?", "What is the lowest value in {list}?"],
           ["Which is the smallest of {list}?"], numbers_list),
    Family("bigger", ("max", "a", "b"), ["Which is bigger: {a} or {b}?", "Which is greater: {a} or {b}?"],
           ["Which is larger, {a} or {b}?"], compare),
    Family("smaller", ("min", "a", "b"), ["Which is smaller: {a} or {b}?", "Which is less: {a} or {b}?"],
           ["Which is lower, {a} or {b}?"], compare),
    Family("gt", ("gt", "a", "b"), ["Is {a} greater than {b}?", "Is {a} bigger than {b}?"], ["Is {a} larger than {b}?"],
           compare),
    Family("unit_up", ("mul", "a", "k"), ["How many {s} are there in {a} {u}?", "Convert {a} {u} to {s}."],
           ["How many {s} are in {a} {u}?", "Express {a} {u} in {s}."], unit_up),
    Family("unit_down", ("div", "a", "k"), ["How many {u} are there in {a} {s}?", "Convert {a} {s} to {u}."],
           ["How many {u} are in {a} {s}?", "Express {a} {s} in {u}."], unit_down),
    # several steps, plain wording -------------------------------------
    Family("percent", ("div", ("mul", "p", "b"), K(100)), ["What is {p} percent of {b}?", "Calculate {p} percent of {b}."],
           ["Find {p} percent of {b}.", "How much is {p} percent of {b}?"], percent, "multi", big=False),
    Family("pct_up", ("add", "b", ("div", ("mul", "p", "b"), K(100))), ["Increase {b} by {p} percent.",
                                                                         "What is {b} increased by {p} percent?"],
           ["What do you get if you increase {b} by {p} percent?"], percent, "multi", big=False),
    Family("pct_down", ("sub", "b", ("div", ("mul", "p", "b"), K(100))), ["Decrease {b} by {p} percent.",
                                                                           "What is {b} decreased by {p} percent?"],
           ["What do you get if you decrease {b} by {p} percent?"], percent, "multi", big=False),
    Family("avg2", ("div", ("add", "a", "b"), K(2)), ["What is the average of {a} and {b}?", "Find the average of {a} and {b}."],
           ["What is the mean of {a} and {b}?"], pair_even_sum, "multi", big=False),
    Family("range", ("sub", ("lmax", "list"), ("lmin", "list")), ["What is the range of {list}?"],
           ["Find the range of {list}."], numbers_list, "multi", big=False),
    Family("rect_area", ("mul", "a", "b"), ["A rectangle is {a} cm long and {b} cm wide. What is its area?"],
           ["What is the area of a rectangle measuring {a} cm by {b} cm?"], sides, "multi", big=False),
    Family("rect_perim", ("mul", ("add", "a", "b"), K(2)), ["A rectangle is {a} cm long and {b} cm wide. What is its perimeter?"],
           ["What is the perimeter of a rectangle measuring {a} cm by {b} cm?"], sides, "multi", big=False),
    Family("tri_area", ("div", ("mul", "a", "b"), K(2)),
           ["A triangle has a base of {a} cm and a height of {b} cm. What is its area?"],
           ["Find the area of a triangle with base {a} cm and height {b} cm."], sides, "multi", big=False),
    Family("sq_area", ("square", "a"), ["A square has sides of {a} cm. What is its area?"],
           ["What is the area of a square with sides of {a} cm?"], side, "multi", big=False),
    Family("sq_perim", ("mul", "a", K(4)), ["A square has sides of {a} cm. What is its perimeter?"],
           ["What is the perimeter of a square with sides of {a} cm?"], side, "multi", big=False),
    Family("speed", ("div", "a", "b"), ["A car travels {a} km in {b} hours. What is its average speed in km per hour?"],
           ["What is the average speed of a cyclist who rides {a} km in {b} hours?"], speed, "multi", big=False),
    Family("distance", ("mul", "a", "b"), ["A train travels at {a} km per hour for {b} hours. How far does it travel?"],
           ["How far does a bus go in {b} hours at {a} km per hour?"], travel, "multi", big=False),
    # word problems (training templates use training names and objects) -
    Family("story_add", ("add", "a", "b"), ["{n} has {a} {o}. {n} gets {b} more. How many {o} does {n} have now?",
                                            "There are {a} {o} in a box and {b} more are added. How many {o} are in the box?"],
           ["{n} starts with {a} {o} and finds {b} more. How many {o} does {n} have?"], st_two, "story"),
    Family("story_sub", ("sub", "a", "b"), ["{n} has {a} {o} and gives away {b}. How many {o} are left?",
                                            "{n} had {a} {o}. {n} lost {b} of them. How many {o} does {n} have left?"],
           ["{n} had {a} {o} and used {b}. How many {o} remain?"], st_two, "story"),
    Family("story_mul", ("mul", "a", "b"), ["There are {a} bags with {b} {o} in each bag. How many {o} are there altogether?",
                                            "{n} buys {a} packs of {o}. Each pack has {b} {o}. How many {o} does {n} buy?"],
           ["Each of {a} boxes holds {b} {o}. How many {o} are there in total?"], st_two, "story"),
    Family("story_div", ("div", "a", "b"), ["{a} {o} are shared equally between {b} friends. How many {o} does each friend get?",
                                            "{n} puts {a} {o} into {b} equal groups. How many {o} are in each group?"],
           ["Split {a} {o} equally among {b} people. How many {o} does each person get?"], st_div, "story"),
    Family("story_buy", ("add", "a", ("mul", "b", "c")),
           ["{n} has {a} {o}. {n} buys {b} packs with {c} {o} in each pack. How many {o} does {n} have now?"],
           ["{n} owns {a} {o} and then gets {b} boxes of {c} {o}. How many {o} does {n} own now?"], st_buy, "story"),
    Family("story_gain_lose", ("sub", ("add", "a", "b"), "c"),
           ["{n} has {a} {o}, finds {b} more and then loses {c}. How many {o} does {n} have?"],
           ["{n} collected {a} {o}, was given {b} more, then gave {c} away. How many {o} does {n} have left?"],
           st_gain_lose, "story"),
    Family("story_share", ("div", ("add", "a", "b"), "c"),
           ["{n} has {a} {o} and gets {b} more. {n} shares them equally among {c} friends. How many {o} does each friend get?"],
           ["{n} has {a} {o} and a friend has {b}. They put them together and split them equally into {c} piles. "
            "How many {o} are in each pile?"], st_share, "story"),
    Family("story_change", ("sub", "c", ("mul", "a", "b")),
           ["{n} buys {a} {o} at {b} dollars each and pays with a {c} dollar note. How much change does {n} get?"],
           ["{n} pays for {a} {o} costing {b} dollars each with {c} dollars. How much money is left over?"],
           st_change, "story"),
    Family("story_three", ("sub", ("add", "a", ("mul", "b", "c")), "d"),
           ["{n} has {a} {o}. {n} buys {b} bags with {c} {o} in each bag, then gives away {d}. How many {o} does {n} have now?"],
           ["{n} starts with {a} {o}, buys {b} packs of {c} {o} and then uses {d}. How many {o} remain?"], st_three, "story"),
    # compositions seen in training --------------------------------------
    Family("gcd_mul", ("mul", ("gcd", "a", "b"), "c"), ["What is the greatest common divisor of {a} and {b}, multiplied by {c}?"],
           [], gcd_plus, "comp"),
    Family("solve_add", ("add", ("solve", "eq"), "c"), ["Suppose {eq}. What is {v} plus {c}?"], [], eq_plus, "comp"),
    Family("solve_mod", ("mod", ("solve", "eq"), "c"), ["Suppose {eq}. What is the remainder when {v} is divided by {c}?"],
           [], eq_plus, "comp"),
    Family("solve_square", ("square", ("solve", "eq")), ["Suppose {eq}. What is {v} squared?"], [], equation, "comp"),
    Family("solve_sq_add", ("add", ("square", ("solve", "eq")), "c"), ["Suppose {eq}. What is {v} squared plus {c}?"],
           [], eq_plus, "comp"),
    Family("apply_mul", ("mul", ("apply", "fdef", "call"), "c"), ["Let {f}({v}) = {poly}. What is {f}({ca}) times {c}?"],
           [], fn_plus, "comp"),
    Family("apply_square", ("square", ("apply", "fdef", "call")), ["Let {f}({v}) = {poly}. What is {f}({ca}) squared?"],
           [], function, "comp"),
    Family("sum_div", ("div", ("add", "a", "b"), "c"), ["What is the sum of {a} and {b}, divided by {c}?"], [], sum_div, "comp"),
    Family("add_mod", ("mod", ("add", "a", "b"), "c"), ["What is the remainder when {a} plus {b} is divided by {c}?"],
           [], three, "comp"),
    Family("mul_sub", ("sub", ("mul", "a", "b"), "c"), ["What is {a} times {b}, minus {c}?"], [], three, "comp"),
    Family("mean_add", ("add", ("mean", "list"), "c"), ["What is the mean of {list}, plus {c}?"], [], mean_plus, "comp"),
    # combinations never seen in training ------------------------------
    Family("solve_mul", ("mul", ("solve", "eq"), "c"), ["Suppose {eq}. What is {v} times {c}?"], [], eq_plus, "comp_test"),
    Family("lcm_sub", ("sub", ("lcm", "a", "b"), "c"), ["What is the least common multiple of {a} and {b}, minus {c}?"],
           [], gcd_plus, "comp_test"),
    Family("solve_prime", ("is_prime", ("solve", "eq")), ["Suppose {eq}. Is {v} a prime number?"], [], eq_prime, "comp_test"),
    Family("apply_add", ("add", ("apply", "fdef", "call"), "c"), ["Let {f}({v}) = {poly}. What is {f}({ca}) plus {c}?"],
           [], fn_plus, "comp_test"),
    Family("solve_sq_sub", ("sub", ("square", ("solve", "eq")), "c"), ["Suppose {eq}. What is {v} squared minus {c}?"],
           [], eq_plus, "comp_test"),
    Family("mean_mul", ("mul", ("mean", "list"), "c"), ["What is the mean of {list}, multiplied by {c}?"], [], mean_plus,
           "comp_test"),
    Family("pct_of_sum", ("div", ("mul", "p", ("add", "a", "b")), K(100)), ["What is {p} percent of the sum of {a} and {b}?"],
           [], pct_sum, "comp_test"),
    Family("rect_minus_square", ("sub", ("mul", "a", "b"), ("square", "c")),
           ["A rectangle is {a} cm long and {b} cm wide. A square has sides of {c} cm. "
            "How much bigger is the area of the rectangle than the area of the square?"], [], rect_square, "comp_test"),
    # four steps, longer than anything in training -----------------------
    Family("solve_sq_add_div", ("div", ("add", ("square", ("solve", "eq")), "c"), "d"),
           ["Suppose {eq}. What is {v} squared plus {c}, divided by {d}?"], [], eq_square_div, "long"),
    Family("story_four", ("div", ("sub", ("add", "a", ("mul", "b", "c")), "d"), "e"),
           ["{n} has {a} {o}. {n} buys {b} bags with {c} {o} in each bag, then gives away {d}. "
            "{n} shares the rest equally among {e} friends. How many {o} does each friend get?"], [], st_four, "long"),
    Family("story_change_two", ("sub", "e", ("add", ("mul", "a", "b"), ("mul", "c", "d"))),
           ["{n} buys {a} {o} at {b} dollars each and {c} more {o} at {d} dollars each, and pays with a {e} dollar note. "
            "How much change does {n} get?"], [], st_change_two, "long"),
]
BY_NAME = {f.name: f for f in FAMILIES}


# ----------------------------------------------------------------------------
# Filling templates and grounding the program in the question's notation
# ----------------------------------------------------------------------------
_BLANK = re.compile(r"{(\w+)}")


def ground(program, template: str, values: dict):
    """Replace blank names in the program with the question's slots: numeric
    blanks become N1, N2, ... in the order they appear in the template."""
    order = [b for b in _BLANK.findall(template) if b in NUMERIC]
    order = list(dict.fromkeys(order))

    def walk(p):
        if isinstance(p, str):
            if p in NUMERIC:
                return ("N", order.index(p))
            if p in SLOTS:
                return SLOTS[p]
            v = values[p]  # a constant chosen by the sampler, e.g. ("K", 60)
            return v
        if p[0] == "K":
            return p
        return (p[0], *[walk(a) for a in p[1:]])

    return walk(program)


def fill(template: str, values: dict) -> str:
    text = template.format(**{k: v for k, v in values.items() if not k.startswith("_")})
    return text[0].upper() + text[1:]


@dataclass
class RoomScenario:
    n_train: int = 8000
    n_per_test_split: int = 200
    label_rate: float = 0.5
    seed: int = 0


SPLITS = ("seen", "paraphrase", "big", "story", "compose", "longer")


class RoomWorld:
    def __init__(self, scenario: RoomScenario | None = None):
        self.sc = scenario or RoomScenario()
        self.rng = np.random.default_rng(self.sc.seed)

    # -- helpers used by samplers ----------------------------------------
    def i(self, lo, hi):
        return int(self.rng.integers(lo, hi + 1))

    def pick(self, xs):
        return xs[int(self.rng.integers(len(xs)))]

    @staticmethod
    def scale(big):
        return 100 if big else 1

    def eq(self, big):
        v = self.pick("xyzkmnpqtw")
        a = self.pick([i for i in range(-9, 10) if i not in (0, 1)])
        x = self.i(-12, 12) * self.scale(big)
        b = self.i(-30, 30) * self.scale(big)
        c = a * x + b
        form = self.i(0, 2)
        if form == 0:
            eq = f"{_poly_text({1: a, 0: b}, v)} = {c}"
        elif form == 1:
            eq = f"{c} = {_poly_text({1: a, 0: b}, v)}"
        else:
            d = self.pick([i for i in range(-5, 6) if i not in (0, a)])
            eq = f"{_poly_text({1: a, 0: b}, v)} = {_poly_text({1: d, 0: c - d * x}, v)}"
        return eq, v, x

    def poly(self, big):
        var = self.pick("xytk")
        deg = self.i(1, 3)
        coeffs = {k: self.i(-6, 6) for k in range(deg + 1)}
        coeffs[deg] = self.pick([1, 2, 3, -1, -2, 4, 5])
        return coeffs, var

    def seq(self, big):
        from ..maths.world import MathWorld
        mw = MathWorld.__new__(MathWorld)
        mw.rng = self.rng
        return MathWorld._seq(mw, big)

    # -- making questions ------------------------------------------------
    def make(self, fam: Family, held_out: bool = False, big: bool = False):
        """(question, answer, reference program grounded in the question's slots)."""
        pool = fam.test if held_out and fam.test else fam.train
        tpl = pool[self.i(0, len(pool) - 1)]
        sampler = fam.sample
        values = sampler(self, big, held_out) if getattr(sampler, "story", False) else sampler(self, big)
        q = fill(tpl, values)
        prog = ground(fam.program, tpl, values)
        r = read(q)
        ws = Workspace(r)
        for step in program_to_steps(prog):
            v = ws.run(step)
            if v is None:
                raise ValueError(f"{fam.name}: step {step.token} doesn't run on {q!r}")
            ws = ws.apply(step, v)
        return q, ws.answer, canonical_program(prog)

    def _task(self, tid, fam, held_out, big, labeled, split):
        q, ans, prog = self.make(fam, held_out, big)
        r = read(q)
        return Task(tid, (), 1e-6 * max(1.0, abs(float(ans))), float(ans), fam.name, labeled, question=q,
                    context=context(r), split=split, features=features(r), solution=prog)

    def menu(self, groups):
        return [f for f in FAMILIES if f.group in groups]

    def train_stream(self):
        core, multi, stories, comps = (self.menu([g]) for g in ("core", "multi", "story", "comp"))
        menu = core + multi + stories * 2 + comps * 2
        for t in range(self.sc.n_train):
            fam = self.pick(menu)
            yield self._task(t, fam, False, False, bool(self.rng.random() < self.sc.label_rate), "train")

    def test_tasks(self, start_id: int):
        core, multi, stories, comps = (self.menu([g]) for g in ("core", "multi", "story", "comp"))
        out, tid = [], start_id
        plan = {
            "seen": (core + multi + stories + comps, False, False),
            "paraphrase": ([f for f in core + multi if f.test], True, False),
            "big": ([f for f in core if f.big], False, True),
            "story": (stories, True, False),
            "compose": (self.menu(["comp_test"]), True, False),
            "longer": (self.menu(["long"]), True, False),
        }
        for split in SPLITS:
            fams, held, big = plan[split]
            for _ in range(self.sc.n_per_test_split):
                out.append(self._task(tid, self.pick(fams), held, big, False, split))
                tid += 1
        order = self.rng.permutation(len(out))
        return [out[i] for i in order]
