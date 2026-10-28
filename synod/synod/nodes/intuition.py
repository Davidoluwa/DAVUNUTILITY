"""Intuition: a small neural ensemble. Fast, approximate, knows how unsure it is.

It works in a shape-only frame (translate + scale the window), predicts the next
step, and reports a predictive spread from ensemble disagreement plus a learned
residual noise level. It learns from labels *and* from answers the council has
certified, which is how slow symbolic reasoning gets compiled into fast intuition.
"""
from __future__ import annotations

import math

import numpy as np

from ..beliefs import conf_bucket, erf_conf
from ..node import Node
from ..perception import normalize_window
from ..protocol import NEURAL, Proposal


class Ensemble:
    """M independent 2-hidden-layer tanh MLPs, vectorised over members, trained with Adam."""

    def __init__(self, members: int, d_in: int, hidden: int, rng, lr: float = 3e-3):
        self.M, self.d_in, self.hidden, self.rng, self.lr = members, d_in, hidden, rng, lr
        self.reset()

    def reset(self) -> None:
        M, d, h, r = self.M, self.d_in, self.hidden, self.rng
        self.p = {
            "W1": r.normal(0, 1 / math.sqrt(d), (M, d, h)),
            "b1": np.zeros((M, 1, h)),
            "W2": r.normal(0, 1 / math.sqrt(h), (M, h, h)),
            "b2": np.zeros((M, 1, h)),
            "W3": r.normal(0, 1 / math.sqrt(h), (M, h, 1)),
            "b3": np.zeros((M, 1, 1)),
        }
        self.m = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.t = 0

    def forward(self, X):
        if X.ndim == 2:
            X = np.broadcast_to(X, (self.M,) + X.shape)
        p = self.p
        h1 = np.tanh(X @ p["W1"] + p["b1"])
        h2 = np.tanh(h1 @ p["W2"] + p["b2"])
        return (h2 @ p["W3"] + p["b3"])[..., 0], (X, h1, h2)

    def step(self, X, y, clip: float = 3.0) -> float:
        out, (X, h1, h2) = self.forward(X)
        p = self.p
        err = out - y
        g = (np.clip(err, -clip, clip) / y.shape[1])[..., None]  # Huber gradient
        grads = {"W3": h2.transpose(0, 2, 1) @ g, "b3": g.sum(1, keepdims=True)}
        g2 = (g @ p["W3"].transpose(0, 2, 1)) * (1 - h2**2)
        grads["W2"], grads["b2"] = h1.transpose(0, 2, 1) @ g2, g2.sum(1, keepdims=True)
        g1 = (g2 @ p["W2"].transpose(0, 2, 1)) * (1 - h1**2)
        grads["W1"], grads["b1"] = X.transpose(0, 2, 1) @ g1, g1.sum(1, keepdims=True)
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        for k in p:
            self.m[k] = b1 * self.m[k] + (1 - b1) * grads[k]
            self.v[k] = b2 * self.v[k] + (1 - b2) * grads[k] ** 2
            mh = self.m[k] / (1 - b1**self.t)
            vh = self.v[k] / (1 - b2**self.t)
            p[k] -= self.lr * mh / (np.sqrt(vh) + eps)
        return float(np.mean(err**2))


class IntuitionNode(Node):
    kind = NEURAL
    width = 8
    min_focus = 0.15

    def __init__(self, name: str = "intuition", seed: int = 0, members: int = 5, hidden: int = 32,
                 unit_cost: float = 0.3, capacity: int = 3000, steps_per_example: int = 6):
        super().__init__(name, seed)
        self.net = Ensemble(members, self.width, hidden, self.rng)
        self.unit = unit_cost
        self.steps = steps_per_example
        self.X = np.zeros((capacity, self.width))
        self.y = np.zeros(capacity)
        self.valid = np.zeros(capacity, dtype=bool)
        self.author = np.array([""] * capacity, dtype=object)
        self.when = np.zeros(capacity, dtype=int)
        self.size = 0
        self._ptr = 0
        self.resid: dict = {}  # signature -> EMA of squared error (shape units)

    # -- perception ------------------------------------------------------
    in_scale, out_scale = 3.0, 4.0  # keep tanh units out of saturation

    def _encode(self, history):
        z, anchor, scale = normalize_window(history, self.width)
        return np.clip(z, -10, 10) / self.in_scale, anchor, scale

    def _outputs(self, view):
        sc = self.scratch(view)
        if "outs" not in sc:
            z, anchor, scale = self._encode(view.history)
            outs, _ = self.net.forward(z[None, :])
            sc["outs"], sc["anchor"], sc["scale"] = outs[:, 0] * self.out_scale, anchor, scale
        return sc

    def _estimate(self, view, members: int):
        sc = self._outputs(view)
        outs = sc["outs"][:members]
        sig = view.context
        spread = float(np.std(outs, ddof=1)) if members > 1 else 1.0
        noise = math.sqrt(self.resid.get(sig, 1.0))
        sd = math.hypot(spread, noise) * sc["scale"]
        value = sc["anchor"] + float(np.mean(outs)) * sc["scale"]
        return value, sd, erf_conf(view.tolerance, sd), sig

    # -- capabilities ----------------------------------------------------
    def solve(self, view) -> Proposal:
        sc = self.scratch(view)
        paid = sc.get("paid", 0)
        value, sd, raw, sig = self._estimate(view, self.net.M)
        sc["paid"] = self.net.M
        evidence = ("n5", conf_bucket(raw))
        conf = min(self.competence.mean(("p",) + evidence + sig), 0.99)
        return Proposal(self.name, self.kind, value, conf, (self.net.M - paid) * self.unit,
                        f"ensemble says {value:.2f} ± {sd:.2f}", evidence)

    # -- learning --------------------------------------------------------
    def focus(self, sig) -> float:
        """How much learning capacity to spend on this kind of task.

        A node serving the whole system should not burn capacity on situations
        where it is hopeless and others are reliable; it keeps a floor so it can
        still notice if it starts getting good there."""
        return float(np.clip(2.0 * self.competence.mean(("ctx",) + sig), self.min_focus, 1.0))

    def learn(self, view, value, source, record) -> None:
        z, anchor, scale = self._encode(view.history)
        t = float(np.clip((value - anchor) / scale, -20, 20))
        sig = view.context
        if source == "label":
            outs, _ = self.net.forward(z[None, :])
            err = min((float(np.mean(outs)) * self.out_scale - t) ** 2, 25.0)
            self.resid[sig] = 0.95 * self.resid.get(sig, 1.0) + 0.05 * err
        if self.rng.random() <= self.focus(sig):
            i = self._ptr
            self.X[i], self.y[i], self.valid[i] = z, t / self.out_scale, True
            self.author[i] = record.final.node if source == "certified" and record.final is not None else ""
            self.when[i] = self._clock
            self._ptr = (self._ptr + 1) % len(self.y)
            self.size = min(self.size + 1, len(self.y))
        else:
            self.stats["skipped_unfocused"] += 1
        self._train(self.steps)

    def _train(self, steps: int, batch: int = 32) -> None:
        pool = np.flatnonzero(self.valid[: self.size])
        if len(pool) < 8:
            return
        for _ in range(steps):
            idx = pool[self.rng.integers(0, len(pool), size=(self.net.M, batch))]  # bootstrap per member
            self.net.step(self.X[idx], self.y[idx])

    def retract(self, author: str, since: int) -> int:
        n = self.size
        bad = self.valid[:n] & (self.author[:n] == author) & (self.when[:n] >= since)
        self.valid[:n][bad] = False
        return int(bad.sum())

    # -- health ----------------------------------------------------------
    def repair(self) -> bool:
        """Weights are suspect, data is not: re-initialise and retrain from replay."""
        self.net.reset()
        self._train(900)
        self.maintenance_cost += 900 * self.unit
        return True

    def fault(self, kind: str = "weights") -> None:
        """A correlated corruption (think: bad shared update). Every member is
        hit the same way, so the ensemble stays *confident* while being wrong -
        the dangerous kind of failure."""
        self.net.p["b3"] += 1.0
