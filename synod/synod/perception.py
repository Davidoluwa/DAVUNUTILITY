"""Shared, cheap perception of a task's *shape*.

This is the coarse context every node conditions its self-model on. It does not
say which node should handle a task; it only gives nodes a vocabulary for
remembering where they have been good or bad.
"""
from __future__ import annotations

import numpy as np


def signature(history, tolerance) -> tuple:
    h = np.asarray(history, dtype=float)
    d1 = np.diff(h)
    d2 = np.diff(d1)
    scale = float(np.mean(np.abs(d1))) + 1e-9
    integral = bool(np.all(np.abs(h - np.round(h)) < 1e-9))
    precision = "tight" if tolerance / scale < 0.25 else "loose"
    early = float(np.mean(np.abs(d1[:2]))) + 1e-9
    late = float(np.mean(np.abs(d1[-2:]))) + 1e-9
    g = late / early
    growth = "explosive" if g > 4 else ("steady" if g > 0.5 else "decaying")
    flips = int(np.sum(np.sign(d2[1:]) != np.sign(d2[:-1])))
    rough = "rough" if flips >= 3 else "smooth"
    # Ordered from most to least informative: self-models back off along it.
    return (precision, "int" if integral else "real", rough, growth)


def normalize_window(history, width: int):
    """Translate/scale the last ``width`` values into a shape-only frame."""
    w = np.asarray(history[-width:], dtype=float)
    anchor = w[-1]
    scale = float(np.mean(np.abs(np.diff(w))))
    scale = max(scale, 1e-3 * (abs(anchor) + 1.0))
    return (w - anchor) / scale, anchor, scale
