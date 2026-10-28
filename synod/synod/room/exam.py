"""The 40-question hand-written exam (maths/exam.py), answered step by step."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from ..maths.exam import EXAM
from ..maths.mathlang import context, features, read
from ..protocol import Task
from .room import make_room, verdict
from .transcript import render
from .world import RoomScenario, RoomWorld


def train_curriculum_only(seed: int = 0, **kw):
    room = make_room(seed=seed, **kw)
    for task in RoomWorld(RoomScenario(seed=seed, n_per_test_split=0)).train_stream():
        room.handle(task)
    room.config.learn = False
    return room


def exam_tasks():
    out = []
    for i, (topic, phrasing, q, ans) in enumerate(EXAM):
        r = read(q)
        out.append((topic, phrasing, Task(900_000 + i, (), 1e-6 * max(1.0, abs(ans)), float(ans), "", False, question=q,
                                          context=context(r), split="exam", features=features(r))))
    return out


def sit(room, verbose=False):
    rows = []
    for topic, phrasing, task in exam_tasks():
        res = room.handle(task)
        v = verdict(task, res.answer)
        rows.append({"topic": topic, "phrasing": phrasing, "question": task.question, "verdict": v, "res": res,
                     "task": task})
        if verbose:
            print(render(task, res, judge=room.judge), "\n")
    return rows


def score(rows):
    c = Counter(r["verdict"] for r in rows)
    return c["right"], c["wrong"], c["abstain"]


def sit_room(seed: int = 0, verbose: bool = False, room=None) -> dict:
    return {"room": score(sit(room or train_curriculum_only(seed), verbose))}


def sit_council(seed: int = 0) -> tuple:
    """The question->answer council (v2), trained on the same dense curriculum."""
    import copy
    from ..council import Council
    from ..maths.experiment import make_nodes
    council = Council(make_nodes(seed))
    for task in RoomWorld(RoomScenario(seed=seed, n_per_test_split=0)).train_stream():
        # it can only answer with a number, so an incomplete question can't teach it anything
        council.handle(task if task.answerable else replace(task, labeled=False))
    council.config.learn = False
    council.config.exchange = False
    rows = []
    for _, _, task in exam_tasks():
        rec = copy.deepcopy(council).handle(task)
        rows.append({"verdict": "abstain" if rec.final is None else
                     ("right" if task.is_correct(rec.final.value) else "wrong")})
    return score(rows)
