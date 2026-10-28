"""Compare strategies on the maths curriculum and write a report."""
from __future__ import annotations

import os
from collections import Counter, defaultdict

import numpy as np

from ..transcript import render
from .experiment import SPLITS, STRATEGIES, run_maths

SPLIT_NAMES = {
    "seen": "familiar wording, new numbers",
    "paraphrase": "wording never seen in training",
    "big": "numbers ~100x bigger than training",
    "story": "word problems: new names, objects, phrasing",
    "compose": "two-step combinations never seen",
}

# (strategy, teacher budget, freeze the council after training)
CONFIGS = [("synod", 0, True)] + [
    (name, 0, False) for name in STRATEGIES if not name.startswith("synod")] + [("synod", 0, False), ("synod", 40, False)]


def label(name, budget, frozen=False):
    if not name.startswith("synod"):
        return name
    if frozen:
        return f"{name} (frozen after training)"
    return f"synod + teacher (asks ≤{budget})" if budget else "synod (keeps learning from its confident answers)"


def _job(args):
    name, budget, frozen, seed = args
    r = run_maths(name, seed=seed, help_budget=budget, freeze_at_test=frozen)
    return (name, budget, frozen, seed, {s: r.summary(s) for s in SPLITS}, r.curve(),
            sum(x["asked"] for x in r.rows))


def compare(seeds, processes=4):
    jobs = [(n, b, f, s) for n, b, f in CONFIGS for s in seeds]
    try:
        from multiprocessing import Pool
        with Pool(processes) as pool:
            out = pool.map(_job, jobs)
    except (OSError, ImportError):
        out = [_job(j) for j in jobs]
    table = {}
    for n, b, f in CONFIGS:
        rows = [o for o in out if o[0] == n and o[1] == b and o[2] == f]
        key = label(n, b, f)
        table[key] = {
            s: {k: float(np.mean([r[4][s][k] for r in rows])) for k in ("accuracy", "wrong", "abstain", "ceiling")}
            for s in SPLITS}
        table[key]["curve"] = list(np.mean([r[5] for r in rows], axis=0))
        table[key]["asked"] = float(np.mean([r[6] for r in rows]))
    return table


def showcase(run):
    picks = []

    def first(test):
        for tid in sorted(run.transcripts):
            task, rec = run.transcripts[tid]
            if test(task, rec):
                return task, rec
        return None

    ok = lambda t, r: r.final is not None and t.is_correct(r.final.value)
    tests = [
        ("Exact on numbers far bigger than anything in training", lambda t, r: t.split == "big" and ok(t, r)
         and t.family in ("mul", "solve", "slope", "gcd") and r.final.node == "parser"),
        ("A word problem with a new name, object and phrasing", lambda t, r: t.split == "story" and ok(t, r)),
        ("A paraphrase, handled by analogy with a known wording", lambda t, r: t.split == "paraphrase" and ok(t, r)
         and r.final.node == "parser" and "like '" in r.final.rationale),
        ("A paraphrase the neural reader gets", lambda t, r: t.split == "paraphrase" and ok(t, r) and r.final.node == "reader"),
        ("A never-seen combination, composed from word meanings", lambda t, r: t.split == "compose" and ok(t, r)
         and r.final.node == "parser" and "cues" in r.final.rationale and not t.labeled and r.label is None),
        ("Stuck, so it abstains and asks the teacher", lambda t, r: t.split != "train" and r.label is not None and not t.labeled),
        ("Peers disagree; the council works it out", lambda t, r: t.split != "train" and ok(t, r) and any(
            rv.verdict.endorses is False for rv in r.reviews)),
    ]
    for title, test in tests:
        hit = first(test)
        if hit:
            picks.append((title, render(*hit)))
    return picks


def detail(seed=0, budget=40):
    r = run_maths("synod", seed=seed, help_budget=budget, keep=lambda t: t.split != "train")
    parser = next(n for n in r.nodes if n.name == "parser")
    routing = defaultdict(Counter)
    for row in r.rows:
        if row["split"] != "train":
            routing[row["split"]][row["final"]] += 1
    asked = Counter(row["family"] for row in r.rows if row["asked"])
    return {"run": r, "meanings": parser.meanings(3), "routing": routing, "asked": asked,
            "wordings": len(parser.memory), "programs": len(next(n for n in r.nodes if n.name == "reader").programs),
            "showcase": showcase(r), "stats": {n.name: dict(n.stats) for n in r.nodes}}


def _p(x):
    return f"{100 * x:.0f}%"


def write(table, det, seeds, path):
    L = ["# Synod does maths - run report\n",
         "Nobody tells the system what any wording means. It gets 4000 practice questions (half with the answer revealed "
         "afterwards), then five test sets with **no answers at all**. The teacher variant may ask for the answer to "
         "questions it couldn't settle, after answering them, up to a small budget.\n",
         f"Averaged over {len(seeds)} seeds.\n",
         "## Accuracy on each test set (wrong answers in brackets; the rest are abstentions)\n"]
    head = "| strategy | " + " | ".join(SPLITS) + " |"
    L += [head, "|---|" + "---|" * len(SPLITS)]
    for name, t in table.items():
        L.append(f"| {name} | " + " | ".join(f"{_p(t[s]['accuracy'])} ({_p(t[s]['wrong'])})" for s in SPLITS) + " |")
    L.append("\n" + "\n".join(f"- **{s}**: {SPLIT_NAMES[s]}" for s in SPLITS))
    L.append("\n## How much of what its members knew did the council use?\n")
    L.append("Ceiling = at least one consulted member proposed the right answer. The gap is the judge's to close.\n")
    L.append("| strategy | " + " | ".join(SPLITS) + " |")
    L.append("|---|" + "---|" * len(SPLITS))
    for name, t in table.items():
        if name.startswith("synod"):
            L.append(f"| {name} | " + " | ".join(f"{_p(t[s]['accuracy'])} of {_p(t[s]['ceiling'])}" for s in SPLITS) + " |")
    teach = next(v for k, v in table.items() if "teacher" in k)
    L.append(f"\nThe teacher variant asked {teach['asked']:.0f} questions on average (out of 1250 test questions).\n")
    L.append("Training accuracy per 500 questions (synod): " + ", ".join(
        _p(x) for x in table["synod (frozen after training)"]["curve"]) + "\n")
    L.append("## Inside one run (seed 0, with teacher)\n")
    L.append(f"- Wordings the parser knows: {det['wordings']}; programs the reader can produce: {det['programs']}.")
    L.append(f"- Questions it asked the teacher about, by hidden type: " +
             (", ".join(f"{k} {v}" for k, v in det["asked"].most_common()) or "none") + ".")
    st = det["stats"]
    L.append(f"- The parser learned {st['parser'].get('wordings_learned_from_council', 0)} new wordings from answers "
             f"the council was confident enough to teach from.\n")
    L.append("Who answered each test set:\n")
    L.append("| test set | answered by |")
    L.append("|---|---|")
    for s in SPLITS:
        c = det["routing"][s]
        tot = sum(c.values())
        L.append(f"| {s} | " + ", ".join(f"{k} {_p(v / tot)}" for k, v in c.most_common()) + " |")
    L.append("\nWhat the parser thinks words mean (learned, strongest cues per operation):\n")
    for prim, words in list(det["meanings"].items())[:24]:
        L.append(f"- `{prim}`: {', '.join(words)}")
    L.append("\n## Sample deliberations (seed 0, auto-picked)\n")
    for title, text in det["showcase"]:
        L.append(f"### {title}\n\n```text\n{text}\n```\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
