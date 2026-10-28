"""Compare the room with the question->answer council and ablations; write a report."""
from __future__ import annotations

import os

import numpy as np

from .experiment import STRATEGIES, division_of_labour, run_room, specialisation
from .transcript import render
from .world import SPLITS, BY_NAME

SPLIT_NAMES = {
    "seen": "familiar wording, new numbers",
    "paraphrase": "wording never seen in training",
    "big": "numbers ~100x bigger than training",
    "story": "word problems (1-3 steps): new names, objects and phrasings",
    "compose": "combinations of familiar steps never seen together (2-3 steps)",
    "longer": "four-step problems, longer than anything in training",
}


def _job(args):
    name, seed = args
    r = run_room(name, seed=seed, keep=(lambda t: t.split != "train") if seed == 0 and name == "room" else None)
    out = {s: r.summary(s) for s in SPLITS}
    extra = {}
    if name.startswith("room"):
        extra = {"labour": {k: dict(v) for k, v in division_of_labour(r).items()}, "special": specialisation(r),
                 "curve": r.curve(), "experts": len(r.orchestrator.experts),
                 "steppers": len(r.orchestrator.full.steppers) + len(r.orchestrator.full.reviewers)}
    if seed == 0 and name == "room":
        extra["showcase"] = showcase(r)
        extra["stats"] = dict(r.orchestrator.stats)
    return name, seed, out, extra


def compare(seeds, names=None, processes=4):
    names = names or list(STRATEGIES)
    jobs = [(n, s) for n in names for s in seeds]
    try:
        from multiprocessing import Pool
        with Pool(processes) as pool:
            out = pool.map(_job, jobs)
    except (OSError, ImportError):
        out = [_job(j) for j in jobs]
    table, extras = {}, {}
    for n in names:
        rows = [o for o in out if o[0] == n]
        table[n] = {s: {k: float(np.mean([r[2][s][k] for r in rows])) for k in ("accuracy", "wrong", "abstain", "method", "cost")}
                    for s in SPLITS}
        for s in SPLITS:
            table[n][s]["range"] = (min(r[2][s]["accuracy"] for r in rows), max(r[2][s]["accuracy"] for r in rows))
        extras[n] = {r[1]: r[3] for r in rows}
    return table, extras


def showcase(run):
    picks, used = [], set()
    tests = [
        ("A three-step word problem, every expert in its lane", lambda t, r: t.split == "story" and r.answer is not None
         and t.is_correct(float(r.answer)) and len(r.steps) >= 3),
        ("A combination never seen in training", lambda t, r: t.split == "compose" and r.answer is not None
         and t.is_correct(float(r.answer))),
        ("Four steps, longer than anything in training", lambda t, r: t.split == "longer" and r.answer is not None
         and t.is_correct(float(r.answer))),
        ("Two routes, one answer", lambda t, r: t.split != "train" and r.answer is not None and t.is_correct(float(r.answer))
         and r.answers and r.answers[0][2] >= 2),
        ("Numbers far bigger than training, exact anyway", lambda t, r: t.split == "big" and r.answer is not None
         and t.is_correct(float(r.answer)) and len(r.steps) >= 2),
        ("Not sure enough, so it abstains", lambda t, r: t.split != "train" and r.answer is None and r.route is not None),
        ("A confident mistake", lambda t, r: t.split != "train" and r.answer is not None and not t.is_correct(float(r.answer))),
    ]
    for title, test in tests:
        for tid in sorted(run.transcripts):
            task, res = run.transcripts[tid]
            if tid not in used and test(task, res):
                used.add(tid)
                picks.append((title, render(task, res, judge=run.orchestrator.judge)))
                break
    return picks


def _p(x):
    return f"{100 * x:.0f}%"


def write(table, extras, seeds, path, exam=None):
    room = extras["room"][0]
    L = ["# The room: a large council that solves maths step by step\n",
         f"{room['experts']} experts in the room. The curriculum has "
         f"{len(BY_NAME)} kinds of question needing one to four steps. 8000 practice questions, half with the answer "
         "revealed afterwards and never the method; then six test sets with no answers at all. The room is frozen "
         "for testing.\n",
         f"Averaged over {len(seeds)} seeds (range across seeds in brackets).\n",
         "## Right answers on each test set (wrong in brackets; the rest are abstentions)\n"]
    L.append("| strategy | " + " | ".join(SPLITS) + " |")
    L.append("|---|" + "---|" * len(SPLITS))
    for name, t in table.items():
        L.append(f"| {name} | " + " | ".join(f"{_p(t[s]['accuracy'])} ({_p(t[s]['wrong'])})" for s in SPLITS) + " |")
    L.append("\n" + "\n".join(f"- **{s}**: {SPLIT_NAMES[s]}" for s in SPLITS))
    L.append("\nSpread across seeds for the room (lowest-highest accuracy):\n")
    t = table["room"]
    L.append("| | " + " | ".join(SPLITS) + " |")
    L.append("|---|" + "---|" * len(SPLITS))
    L.append("| room | " + " | ".join(f"{_p(t[s]['range'][0])}-{_p(t[s]['range'][1])}" for s in SPLITS) + " |")
    L.append("\n## Right for the right reason\n")
    L.append("Of the right answers, how many used the same method as the hidden reference program "
             "(commutative arguments aside)? A different valid method also counts as right above.\n")
    L.append("| strategy | " + " | ".join(SPLITS) + " |")
    L.append("|---|" + "---|" * len(SPLITS))
    for name, t in table.items():
        if name.startswith("room"):
            L.append(f"| {name} | " + " | ".join(_p(t[s]["method"]) for s in SPLITS) + " |")
    L.append("\n## Division of labour (seed 0)\n")
    L.append("Share of the steps in right test solutions that each kind of expert backed (a step can have several backers).\n")
    lab = room["labour"]
    kinds = ["operator", "neural", "memory", "analogy", "goal"]
    L.append("| test set | " + " | ".join(kinds) + " |")
    L.append("|---|" + "---|" * len(kinds))
    for s in SPLITS:
        c = lab.get(s, {})
        n = max(c.get("steps", 0), 1)
        L.append(f"| {s} | " + " | ".join(_p(c.get(k, 0) / n) for k in kinds) + " |")
    sp = room["special"]
    if sp:
        L.append("\nThe neural pool is trained as a mixture of experts: each worked step is shared out in proportion "
                 "to how well each network already predicts it. Where each network's correct backing concentrates "
                 "(seed 0):\n")
        L.append("| expert | most backed kind of question | share | entropy (bits) |")
        L.append("|---|---|---|---|")
        for n, d in sorted(sp.items()):
            L.append(f"| {n} | {d['top']} | {_p(d['share'])} | {d['entropy']:.2f} |")
    if exam:
        L.append("\n## The 40-question exam\n")
        L.append("The hand-written exam from `maths/exam.py` (new numbers, 18 new wordings), now answered step by step.\n")
        L.append("| | right | wrong | abstained |")
        L.append("|---|---|---|---|")
        for name, (r_, w_, a_) in exam.items():
            L.append(f"| {name} | {r_} | {w_} | {a_} |")
    L.append("\nTraining accuracy per 1000 questions (room, seed 0): " + ", ".join(_p(x) for x in room["curve"]))
    L.append(f"\nSeed 0: {room['stats']}\n")
    L.append("## Sample deliberations (seed 0, auto-picked)\n")
    for title, text in room.get("showcase", []):
        L.append(f"### {title}\n\n```text\n{text}\n```\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
