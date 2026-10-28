"""Record every step of the room's deliberations as JSON for the viewer.

Nothing here changes behaviour: it reads the result the room returns (the
route it took, every candidate on the table at each step, who backed it, what
the reviewers said and how the judge weighed it) and turns it into plain data.
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter

from ..maths.trace import readable as _maths_readable
from .experts import NeuralExpert, OperatorExpert
from .exam import exam_tasks, train_curriculum_only
from .room import verdict as _verdict
from .workspace import STOP, UNKNOWABLE, fmt, say
from .world import RoomScenario, RoomWorld, SPLITS


def _f(v):
    if v is None:
        return None
    if v is UNKNOWABLE:
        return "not enough information"
    v = float(v)
    return None if v != v or math.isinf(v) else round(v, 6)


def kind_of(room, name: str) -> str:
    e = room.full.by_name.get(name)
    if isinstance(e, OperatorExpert):
        return "operator"
    if isinstance(e, NeuralExpert):
        return "neural"
    return name


def readable(feature: str) -> str:
    """The judge's features in plain words."""
    p = feature.split("|")
    k = p[0]
    if k == "by" and len(p) == 2:
        return f"{p[1]} backs it"
    if k == "by" and len(p) == 3 and p[2] in ("f0", "f1"):
        return f"{p[1]} backs it, on {'familiar' if p[2] == 'f1' else 'new'} ground"
    if k == "by" and len(p) == 3 and p[2].startswith("c") and p[2][1:].isdigit():
        lo = int(p[2][1:]) * 10
        return f"{p[1]} backs it, {lo}-{lo + 9}% sure"
    if k == "by" and len(p) == 3:
        return f"{p[1]} backs it ({p[2].replace('/', ', ')})"
    if k == "v":
        who, _, sig = p[1].partition(":")
        return f"{who}: {sig.replace(':', ' ')}"
    simple = {
        "conf:max": "how sure its surest backer is", "conf:mean": "how sure its backers are on average",
        "stop": "stopping here", "step": "taking another step", "null": "baseline caution",
        "fam:0": "this wording is new", "fam:1": "this wording is familiar",
    }
    if feature in simple:
        return simple[feature]
    if k.startswith("n") and len(p) == 2 and k in ("n", "nn", "ns"):
        what = {"n": "backers", "nn": "neural backers", "ns": "symbolic backers"}[k]
        return f"{p[1]} {what}"
    if k == "fresh":
        return f"uses {p[1].split('/')[0]} of {p[1].split('/')[1]} facts nobody has used yet"
    if k == "left":
        return f"leaves {p[1]} question facts unused"
    if k == "uses-last":
        return "builds on the last result" if p[1] == "1" else "ignores the last result"
    if k == "cant":
        return "saying there isn't enough information"
    if k.startswith("cant"):
        return feature.replace("cant|", "not enough information, ").replace("open:", "facts unused: ") \
            .replace("t:", "after step ").replace("facts:", "what the question gives: ")
    if k.startswith("stop"):
        return feature.replace("stop|", "stopping, ").replace("open:", "facts still unused: ").replace("t:", "after step ")
    if k.startswith("null"):
        return feature.replace("null|t:", "caution at step ")
    return _maths_readable(feature)


def case(room, task, res, source: str) -> dict:
    known = task.target is not None or not getattr(task, "answerable", True)
    verdict = _verdict(task, res.answer) if known else None
    truth = task.target if getattr(task, "answerable", True) else UNKNOWABLE
    out = {"question": task.question, "source": source, "family": task.family or "", "answer": _f(truth),
           "verdict": verdict, "given": _f(res.answer), "probability": round(res.probability, 3),
           "compute": round(res.cost, 1),
           "alternatives": [{"value": _f(v), "p": round(p, 3), "routes": n} for v, p, n in res.answers[:4]],
           "facts": [], "steps": []}
    if res.route is None:
        return out
    ws0 = res.route.trail[0][0].ws
    out["facts"] = [{"ref": f.ref, "text": f.text or fmt(f.value)} for f in ws0.facts.values()]
    for m, k in res.route.trail:
        order = sorted(range(len(m.cands)), key=lambda i: -m.gates[i + 1])
        shown = [k] + [i for i in order if i != k][:4]
        cands = []
        for i in shown:
            c = m.cands[i]
            cands.append({
                "token": c.token, "text": say(m.ws, c.step, c.value), "value": _f(c.value), "stop": c.step.op == STOP, "cant": c.step.op == "insufficient",
                "gate": round(m.gates[i + 1], 3), "chosen": i == k,
                "backers": [{"name": p.expert, "kind": kind_of(room, p.expert), "confidence": round(p.confidence, 2),
                             "note": p.note} for p in sorted(c.props, key=lambda p: -p.confidence)],
                "reviews": list(c.reviews),
                "reasons": [{"text": readable(f), "weight": round(w, 2)} for f, w in room.judge.reasons(c.feats, top=4)],
            })
        out["steps"].append({"none": round(m.gates[0], 3), "candidates": cands, "on_table": len(m.cands)})
    return out


def roster(room) -> list:
    out = []
    for e in room.full.experts:
        out.append({"name": e.name, "kind": kind_of(room, e.name), "role": e.role,
                    "family": "symbolic" if e.kind == "symbolic" else "neural"})
    return out


def export(path=os.path.join("results", "room_trace.json"), seed: int = 0, per_split: int = 3, room=None):
    room = room or train_curriculum_only(seed)
    cases = []
    for topic, phrasing, task in exam_tasks():
        c = case(room, task, room.handle(task), "exam")
        c["topic"], c["phrasing"] = topic, phrasing
        cases.append(c)
    world = RoomWorld(RoomScenario(n_train=0, n_per_test_split=40, seed=seed + 100))
    picked = Counter()
    for task in world.test_tasks(10 ** 6):
        if picked[task.split] < per_split and task.split in SPLITS:
            picked[task.split] += 1
            c = case(room, task, room.handle(task), task.split)
            c["topic"], c["phrasing"] = task.split, "test"
            cases.append(c)
    data = {"seed": seed, "experts": len(room.experts), "benches": len(room.benches), "bench": roster(room), "cases": cases}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=1)
    return data


def build_viewer(data, out=os.path.join("results", "room_viewer.html")):
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "viewer.html")) as fh:
        page = fh.read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    with open(out, "w") as fh:
        fh.write(page.replace("__DATA__", blob))
    return out
