"""Compare the room with the question->answer council and ablations; write a report."""
from __future__ import annotations

import os

import numpy as np

from .experiment import division_of_labour, run_room, specialisation
from .room import verdict
from .transcript import render
from .world import SPLITS, BY_NAME

SPLIT_NAMES = {
    "seen": "familiar wording, new numbers",
    "paraphrase": "wording never seen in training",
    "big": "numbers ~100x bigger than training",
    "story": "word problems (1-3 steps): new names, objects and phrasings",
    "compose": "combinations of familiar steps never seen together (2-3 steps)",
    "longer": "four-step problems, longer than anything in training",
    "distract": "word problems with one or two sentences that don't matter (new ones, some with numbers, some vague)",
    "missing": "word problems missing a number they need (\"buys some packs\"): the right outcome is \"not enough information\"; "
               "kinds of question never seen incomplete in training",
}


REPORTED = ["room", "room, without inventing procedures", "room, one neural expert",
            "operators alone (no neural, memory or analogy)", "search alone, no learning", "council v2 (question -> answer)"]


def _job(args):
    name, seed, keep_room = args
    r = run_room(name, seed=seed, keep=(lambda t: t.split != "train") if seed == 0 and name == "room" else None)
    out = {s: r.summary(s) for s in SPLITS}
    extra = {"seconds": r.seconds}
    room = r.orchestrator
    if hasattr(room, "full") and name != "search alone, no learning":
        extra.update({"labour": {k: dict(v) for k, v in division_of_labour(r).items()}, "special": specialisation(r),
                      "curve": r.curve(), "experts": len(room.experts),
                      "steppers": len(room.full.steppers) + len(room.full.reviewers)})
        inv = getattr(room, "inventor", None)
        if inv is not None:
            extra["inventions"] = [dict(e) for e in inv.log if e.get("procedure")]
            extra["kept"] = [(p.name, p.describe()) for p in room.procedures]
            extra["proc_use"] = {s: sum(any(st.startswith("proc_") for st in row.get("ops", ())) for row in r.rows
                                        if row["split"] == s and row["correct"]) / max(1, sum(row["correct"] for row in r.rows if row["split"] == s))
                                 for s in SPLITS}
    if seed == 0 and name == "room":
        extra["showcase"] = showcase(r)
        extra["stats"] = dict(r.orchestrator.stats)
        if keep_room:  # the same stream as training on the curriculum alone; frozen for the test sets
            import pickle
            os.makedirs(os.path.dirname(keep_room) or ".", exist_ok=True)
            with open(keep_room, "wb") as fh:
                pickle.dump(r.orchestrator, fh)
    return name, seed, out, extra


def compare(seeds, names=None, processes=4, keep_room=None):
    names = names or REPORTED
    jobs = [(n, s, keep_room) for n in names for s in seeds]
    jobs.sort(key=lambda j: j[0] == "search alone, no learning")  # the quick one last
    try:
        from multiprocessing import Pool
        with Pool(processes) as pool:
            out = pool.map(_job, jobs)
    except (OSError, ImportError):
        out = [_job(j) for j in jobs]
    table, extras = {}, {}
    for n in names:
        rows = [o for o in out if o[0] == n]
        table[n] = {s: {k: float(np.mean([r[2][s][k] for r in rows]))
                        for k in ("accuracy", "wrong", "abstain", "method", "cost", "said_missing")} for s in SPLITS}
        for s in SPLITS:
            table[n][s]["range"] = (min(r[2][s]["accuracy"] for r in rows), max(r[2][s]["accuracy"] for r in rows))
        extras[n] = {r[1]: r[3] for r in rows}
    return table, extras


def showcase(run):
    picks, used = [], set()
    tests = [
        ("A three-step word problem, every expert in its lane", lambda t, r: t.split == "story" and verdict(t, r.answer) == "right" and len(r.steps) >= 3),
        ("A combination never seen in training", lambda t, r: t.split == "compose" and verdict(t, r.answer) == "right"),
        ("Four steps, longer than anything in training", lambda t, r: t.split == "longer" and verdict(t, r.answer) == "right"),
        ("Two routes, one answer", lambda t, r: t.split != "train" and verdict(t, r.answer) == "right"
         and r.answers and r.answers[0][2] >= 2),
        ("Numbers far bigger than training, exact anyway", lambda t, r: t.split == "big" and verdict(t, r.answer) == "right" and len(r.steps) >= 2),
        ("A sentence that doesn't matter, left alone", lambda t, r: t.split == "distract" and verdict(t, r.answer) == "right"
         and len(r.steps) >= 3),
        ("Not enough information, worked out", lambda t, r: t.split == "missing" and verdict(t, r.answer) == "right"
         and len(r.steps) >= 3),
        ("An invented procedure at work", lambda t, r: t.split != "train" and verdict(t, r.answer) == "right"
         and any(s.op.startswith("proc_") for s in r.steps)),
        ("Not sure enough, so it abstains", lambda t, r: t.split != "train" and r.answer is None and r.route is not None),
        ("A confident mistake", lambda t, r: t.split != "train" and verdict(t, r.answer) == "wrong"),
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


def _table(L, names, table, cell):
    L.append("| strategy | " + " | ".join(SPLITS) + " |")
    L.append("|---|" + "---|" * len(SPLITS))
    for name in names:
        t = table[name]
        L.append(f"| {name} | " + " | ".join(cell(t[s]) for s in SPLITS) + " |")


def write(table, extras, seeds, path, exam=None):
    room = extras["room"][0]
    names = list(table)
    rooms = [n for n in names if n in extras and extras[n].get(0, {}).get("experts")]
    L = ["# The room: a large council that solves maths step by step\n",
         f"{room['experts'] - len(room.get('kept', []))} experts in the room at the start (seed 0 ended with "
         f"{room['experts']}, after inventing {len(room.get('kept', []))} procedures). The curriculum has "
         f"{len(BY_NAME)} kinds of question needing one to four steps; a quarter of the word problems carry a sentence "
         "that doesn't matter, and some questions leave out a number they need. 8000 practice questions, half with "
         "the answer revealed afterwards (never the method); then eight test sets with no answers at all. The room is "
         "frozen for testing.\n",
         f"Averaged over {len(seeds)} seeds (range across seeds below).\n",
         "## Right answers on each test set (wrong in brackets; the rest are abstentions)\n"]
    _table(L, names, table, lambda c: f"{_p(c['accuracy'])} ({_p(c['wrong'])})")
    L.append("\n" + "\n".join(f"- **{s}**: {SPLIT_NAMES[s]}" for s in SPLITS))
    L.append("\nSpread across seeds (lowest-highest accuracy):\n")
    _table(L, rooms, table, lambda c: f"{_p(c['range'][0])}-{_p(c['range'][1])}")

    L.append("\n## Relevance and missing information\n")
    L.append("How often each room said \"not enough information\". On the missing set that's the right answer; "
             "anywhere else it's a false alarm (and counted as wrong above).\n")
    _table(L, [n for n in rooms if n != "search alone, no learning"], table, lambda c: _p(c["said_missing"]))

    L.append("\n## Inventing procedures\n")
    L.append("Every 1000 practice questions the room sleeps on 300 of its past worked solutions. If its notebook "
             "shows a recurring piece, a copy of the room adopts it as a new operation (with its own expert) and "
             "sleeps on the same solutions re-expressed with it. Both then meet the next 500 questions before "
             "learning from them. The copy replaces the room only if it was less surprised by the worked solutions "
             "(total -log probability, in nats), used the procedure, and lost no more answers than it won.\n")
    for seed in seeds:
        inv = extras["room"].get(seed, {}).get("inventions", [])
        if not inv:
            continue
        L.append(f"Seed {seed}:\n")
        L.append("| at question | procedure | seen in notebook | surprise: room / copy | answers won-lost | copy used it | kept |")
        L.append("|---|---|---|---|---|---|---|")
        for e in inv:
            sr, sc = e.get("surprise", (0, 0))
            L.append(f"| {e['at']} | `{e['body']}` | {e['occurrences']}x in {e['wordings']} wordings | {sr} / {sc} | "
                     f"{e.get('wins', 0)}-{e.get('losses', 0)} | {e.get('used', 0)} | {'**kept**' if e.get('kept') else 'dropped'} |")
        L.append("")
    use = [extras["room"][s].get("proc_use") for s in seeds if extras["room"].get(s, {}).get("proc_use")]
    if use:
        L.append("Share of right test answers that used an invented procedure (mean over seeds):\n")
        L.append("| | " + " | ".join(SPLITS) + " |")
        L.append("|---|" + "---|" * len(SPLITS))
        L.append("| room | " + " | ".join(_p(float(np.mean([u[s] for u in use]))) for s in SPLITS) + " |")
    if "room, without inventing procedures" in table:
        a, b = table["room"], table["room, without inventing procedures"]
        L.append("\nUseful invention: the room minus the same room that never invents (right answers, same beam):\n")
        L.append("| | " + " | ".join(SPLITS) + " |")
        L.append("|---|" + "---|" * len(SPLITS))
        L.append("| difference | " + " | ".join(f"{100 * (a[s]['accuracy'] - b[s]['accuracy']):+.0f}" for s in SPLITS) + " |")

    L.append("\n## Right for the right reason\n")
    L.append("Of the right answers, how many used the same method as the hidden reference program "
             "(commutative arguments aside; invented procedures written out)? On the distract set that means it "
             "left the sentences that don't matter alone.\n")
    _table(L, [n for n in rooms if n != "search alone, no learning"], table, lambda c: _p(c["method"]))
    L.append("\n## Division of labour (seed 0)\n")
    L.append("Share of the steps in right test solutions that each kind of expert backed (a step can have several backers).\n")
    lab = room["labour"]
    kinds = ["operator", "neural", "memory", "analogy", "goal"]
    L.append("| test set | " + " | ".join(kinds) + " |")
    L.append("|---|" + "---|" * len(kinds))
    for s_ in SPLITS:
        c = lab.get(s_, {})
        n = max(c.get("steps", 0), 1)
        L.append(f"| {s_} | " + " | ".join(_p(c.get(k, 0) / n) for k in kinds) + " |")
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
    L.append("Wall-clock per run (practice + all test sets, one core each, four at a time): " + ", ".join(
        f"{n} {np.mean([extras[n][s_]['seconds'] for s_ in seeds]):.0f}s" for n in names) + "\n")
    L.append("## Sample deliberations (seed 0, auto-picked)\n")
    for title, text in room.get("showcase", []):
        L.append(f"### {title}\n\n```text\n{text}\n```\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
