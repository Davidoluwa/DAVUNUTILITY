"""A synthetic world of "what comes next?" tasks.

Some families are governed by exact laws and demand exact answers (symbolic
turf). Others are noisy or nonlinear and only need to be roughly right (neural
turf). Nodes never see the family; they have to discover their own strengths.

The default scenario also breaks things on purpose:
* a correlated fault in the neural ensemble (confidently wrong, not noisy);
* a distribution shift that introduces a law nobody has seen yet;
* a bug in the symbolic inducer, later hot-fixed by an "operator".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .protocol import Task

LENGTH = 8


def _ints(rng, lo, hi, exclude_zero=False):
    while True:
        v = int(rng.integers(lo, hi + 1))
        if not (exclude_zero and v == 0):
            return v


def gen_arithmetic(rng):
    a, d = _ints(rng, -20, 20), _ints(rng, -9, 9, True)
    return [a + d * k for k in range(LENGTH + 1)], 0.5


def gen_geometric(rng):
    a = _ints(rng, 1, 5) * int(rng.choice([-1, 1]))
    r = int(rng.choice([2, 3, -2]))
    return [a * r**k for k in range(LENGTH + 1)], 0.5


def gen_fibonacci(rng):
    x = [_ints(rng, -30, 40), _ints(rng, 1, 50)]
    while len(x) < LENGTH + 1:
        x.append(x[-1] + x[-2])
    return x, 0.5


def gen_quadratic(rng):
    a, b, c = _ints(rng, -6, 6, True), _ints(rng, -25, 25), _ints(rng, -40, 40)
    return [a * k * k + b * k + c for k in range(LENGTH + 1)], 0.5


def gen_affine(rng):
    a, b, x = int(rng.choice([2, 3])), _ints(rng, -5, 5, True), _ints(rng, -5, 5)
    seq = [x]
    while len(seq) < LENGTH + 1:
        seq.append(a * seq[-1] + b)
    return seq, 0.5


def gen_interleaved(rng):
    x = [_ints(rng, -40, 40), _ints(rng, -40, 40)]
    d = _ints(rng, -12, 12, True)
    while len(x) < LENGTH + 1:
        x.append(x[-2] + d)
    return x, 0.5


def gen_noisy_trend(rng):
    a, s, sigma = rng.uniform(-20, 20), rng.uniform(-5, 5), rng.uniform(0.5, 2.0)
    clean = [a + s * k for k in range(LENGTH + 1)]
    return clean, 1.5 * sigma, sigma


def gen_wave(rng):
    amp, w, ph, c = rng.uniform(5, 20), rng.uniform(0.4, 1.0), rng.uniform(0, 2 * math.pi), rng.uniform(-10, 10)
    clean = [c + amp * math.sin(w * k + ph) for k in range(LENGTH + 1)]
    return clean, 0.2 * amp, 0.03 * amp


def gen_saturating(rng):
    top, k, t0, off = rng.uniform(20, 100), rng.uniform(0.6, 1.4), rng.uniform(2, 6), rng.uniform(-10, 10)
    clean = [off + top / (1 + math.exp(-k * (t - t0))) for t in range(LENGTH + 1)]
    return clean, 0.04 * top, 0.01 * top


EXACT = {
    "arithmetic": gen_arithmetic,
    "geometric": gen_geometric,
    "fibonacci": gen_fibonacci,
    "quadratic": gen_quadratic,
    "affine": gen_affine,
    "interleaved": gen_interleaved,
}
NOISY = {"noisy_trend": gen_noisy_trend, "wave": gen_wave, "saturating": gen_saturating}

BASE_MIX = {
    "arithmetic": 0.12, "geometric": 0.10, "fibonacci": 0.10, "quadratic": 0.10, "affine": 0.08,
    "noisy_trend": 0.18, "wave": 0.16, "saturating": 0.16,
}
SHIFT_MIX = {
    "arithmetic": 0.09, "geometric": 0.08, "fibonacci": 0.08, "quadratic": 0.08, "affine": 0.07,
    "interleaved": 0.16, "noisy_trend": 0.15, "wave": 0.15, "saturating": 0.14,
}


@dataclass
class Event:
    at: int
    action: str  # "fault" | "clear_fault" | "shift"
    node: str = ""
    note: str = ""


@dataclass
class Scenario:
    n_tasks: int = 1600
    label_rate: float = 0.35
    events: list = field(default_factory=lambda: [
        Event(550, "fault", "recall", "neural memory index corrupted (confidently wrong)"),
        Event(1000, "shift", note="new family appears: interleaved sequences"),
        Event(1250, "fault", "inducer", "bug in symbolic evaluator (+1 offset)"),
        Event(1400, "clear_fault", "inducer", "operator ships a hotfix"),
    ])

    def phase(self, t: int) -> str:
        label = "warm-up"
        for e in sorted(self.events, key=lambda e: e.at):
            if t >= e.at:
                label = {"fault": f"{e.node} broken", "clear_fault": "recovered", "shift": "shifted"}[e.action]
        return label


class World:
    def __init__(self, seed: int = 0, scenario: Scenario | None = None):
        self.rng = np.random.default_rng(seed)
        self.scenario = scenario or Scenario()
        self.mix = dict(BASE_MIX)

    def make(self, task_id: int, family: str) -> Task:
        gen = EXACT.get(family) or NOISY[family]
        out = gen(self.rng)
        if family in NOISY:
            clean, tol, sigma = out
            obs = [v + float(self.rng.normal(0, sigma)) for v in clean[:LENGTH]]
            history, target = tuple(obs), float(clean[LENGTH])
        else:
            seq, tol = out
            history, target = tuple(float(v) for v in seq[:LENGTH]), float(seq[LENGTH])
        labeled = bool(self.rng.random() < self.scenario.label_rate)
        return Task(task_id, history, float(tol), target, family, labeled)

    def stream(self):
        for t in range(self.scenario.n_tasks):
            for e in self.scenario.events:
                if e.at == t and e.action == "shift":
                    self.mix = dict(SHIFT_MIX)
            names = list(self.mix)
            probs = np.array([self.mix[n] for n in names])
            family = names[int(self.rng.choice(len(names), p=probs / probs.sum()))]
            yield t, self.make(t, family)
