"""A 40-question exam, written by hand, on curriculum topics.

None of these questions come from the generator: the numbers are new, and many
phrasings never appear in training ("new" below). "familiar" means the wording
matches a training template, with numbers the system hasn't seen. Some numbers
are deliberately outside the training ranges (e.g. 3^7, 45 squared, sqrt(2209)).

The council is trained on the curriculum only (no test phase, no teacher), then
frozen for the exam: no certified-answer learning and no exploration, and each
question is answered by a fresh copy, so order can't matter.
"""
from __future__ import annotations

import copy
import os
import time
from collections import Counter

from ..protocol import Task
from ..transcript import render
from .experiment import run_maths
from .mathlang import context, features, read
from .world import MathScenario, MathWorld

# (topic, phrasing, question, answer)
EXAM = [
    ("arithmetic", "familiar", "What is 348 plus 279?", 627),
    ("arithmetic", "new", "Find the difference between 900 and 456.", 444),
    ("arithmetic", "new", "What is 64 multiplied by 25?", 1600),
    ("arithmetic", "new", "How much is 144 divided by 12?", 12),
    ("arithmetic", "familiar", "What is 12 * (7 + 8) - 30?", 150),
    ("remainders", "familiar", "What is the remainder when 523 is divided by 9?", 1),
    ("remainders", "new", "When 250 is divided by 7, what is the remainder?", 5),
    ("gcd / lcm", "familiar", "What is the greatest common divisor of 252 and 198?", 18),
    ("gcd / lcm", "new", "Find the highest common factor of 91 and 65.", 13),
    ("gcd / lcm", "new", "What is the smallest number that is a multiple of both 9 and 15?", 45),
    ("primes", "familiar", "Is 391 a prime number?", 0),
    ("primes", "new", "Tell me whether 211 is prime.", 1),
    ("powers / roots", "familiar", "What is 3 to the power of 7?", 2187),
    ("powers / roots", "familiar", "What is 45 squared?", 2025),
    ("powers / roots", "familiar", "What is the square root of 2209?", 47),
    ("equations", "familiar", "Solve 7*x - 12 = 23 for x.", 5),
    ("equations", "familiar", "What is y in 4*y + 9 = 2*y - 7?", -8),
    ("equations", "new", "If 3*m + 15 = 0, what is m?", -5),
    ("functions", "familiar", "Let g(x) = 3*x^2 - 2*x + 4. What is g(3)?", 25),
    ("functions", "familiar", "What is the value of 2*t^3 - t when t = 2?", 14),
    ("derivatives", "familiar", "Let h(x) = x^3 - 5*x^2 + 2*x. What is the derivative of h at x = 4?", 10),
    ("derivatives", "familiar", "Differentiate 6*k^2 + 3*k - 1 with respect to k and evaluate at k = -2.", -21),
    ("sequences", "familiar", "What comes next: 5, 11, 17, 23, 29, 35?", 41),
    ("sequences", "familiar", "What is the next term in 3, 6, 12, 24, 48, 96?", 192),
    ("sequences", "new", "Give the next number: 1, 1, 2, 3, 5, 8.", 13),
    ("statistics", "familiar", "What is the mean of 12, 18, 25, 33 and 37?", 25),
    ("statistics", "familiar", "What is the median of 7, 3, 19, 11 and 5?", 7),
    ("statistics", "new", "What is the biggest of 14, -3, 27, 8 and 19?", 27),
    ("comparisons", "familiar", "Which is bigger: -12 or -15?", -12),
    ("comparisons", "new", "Is 45 more than 54?", 0),
    ("units", "familiar", "How many minutes are there in 2.5 hours?", 150),
    ("units", "new", "How many centimeters make 7 meters?", 700),
    ("units", "familiar", "How many weeks are there in 63 days?", 9),
    ("word problems", "new", "Leila has 23 stickers. She gets 15 more. How many stickers does Leila have now?", 38),
    ("word problems", "new", "A baker puts 48 rolls into 6 equal trays. How many rolls are in each tray?", 8),
    ("word problems", "new", "There are 7 shelves with 9 books on each shelf. How many books are there altogether?", 63),
    ("two-step", "familiar", "Suppose 5*x - 3 = 22. What is x plus 10?", 15),
    ("two-step", "new", "Suppose 2*k + 1 = 15. What is k times 3?", 21),
    ("two-step", "new", "Let f(x) = 2*x + 5. What is f(3) plus 4?", 15),
    ("two-step", "new", "What is the least common multiple of 4 and 6, minus 5?", 7),
]


def train_curriculum_only(name: str = "synod", seed: int = 0):
    """Train on the 4000-question curriculum and nothing else."""
    r = run_maths(name, seed=seed, scenario=MathScenario(seed=seed, n_per_test_split=0))
    return r.orchestrator


def freeze(orch):
    if hasattr(orch, "config"):
        orch.config.learn = False  # router and judge stay as trained
        orch.config.exchange = False  # no learning from its own answers during the exam
        orch.config.help_budget = 0
        orch.teacher = None
    return orch


def sit(orch, exam=EXAM):
    """Each question is answered by a fresh copy of the frozen council."""
    out = []
    for i, (topic, phrasing, q, ans) in enumerate(exam):
        r = read(q)
        task = Task(900_000 + i, (), 1e-6 * max(1.0, abs(ans)), float(ans), "", False,
                    question=q, context=context(r), split="exam", features=features(r))
        rec = copy.deepcopy(orch).handle(task)
        given = rec.final.value if rec.final is not None else None
        verdict = "abstain" if given is None else ("right" if task.is_correct(given) else "wrong")
        out.append({"topic": topic, "phrasing": phrasing, "question": q, "answer": ans, "given": given,
                    "verdict": verdict, "by": rec.final.node if rec.final else "-",
                    "belief": rec.final_belief, "transcript": render(task, rec)})
    return out


def leaked(seed: int = 0):
    """Exam questions that appear word for word in the training stream (should be none)."""
    seen = {t.question for t in MathWorld(MathScenario(seed=seed, n_per_test_split=0)).train_stream()}
    return [q for _, _, q, _ in EXAM if q in seen]


def _num(v):
    return "—" if v is None else (str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:.4g}")


def score(rows):
    c = Counter(r["verdict"] for r in rows)
    return c["right"], c["wrong"], c["abstain"]


def write_report(main, extra, path, seconds):
    right, wrong, abst = score(main)
    L = ["# Synod - 40-question maths exam\n",
         "Hand-written questions on curriculum topics: new numbers throughout, many in phrasings never seen in "
         "training, some with numbers outside the training ranges. The council was trained on the 4000-question "
         "curriculum only (no teacher), then frozen for the exam.\n",
         f"## Score: {right}/40 right, {wrong} wrong, {abst} abstained\n"]
    by_phr = {p: score([r for r in main if r["phrasing"] == p]) for p in ("familiar", "new")}
    L.append(f"- Familiar wording (new numbers): {by_phr['familiar'][0]}/{sum(by_phr['familiar'])} right, "
             f"{by_phr['familiar'][1]} wrong")
    L.append(f"- New wording: {by_phr['new'][0]}/{sum(by_phr['new'])} right, {by_phr['new'][1]} wrong")
    if extra:
        L.append("\nSame exam, other set-ups (each trained the same way):\n")
        L.append("| set-up | right | wrong | abstained |")
        L.append("|---|---|---|---|")
        for name, rows in extra.items():
            r_, w_, a_ = score(rows)
            L.append(f"| {name} | {r_} | {w_} | {a_} |")
    L.append("\n## Every question\n")
    L.append("| # | topic | wording | question | key | Synod said | |")
    L.append("|---|---|---|---|---|---|---|")
    mark = {"right": "✅", "wrong": "❌", "abstain": "🤷 abstained"}
    for i, r in enumerate(main, 1):
        L.append(f"| {i} | {r['topic']} | {r['phrasing']} | {r['question']} | {_num(r['answer'])} | "
                 f"{_num(r['given'])} | {mark[r['verdict']]} |")
    L.append("\n## Deliberations worth reading\n")
    picks = [r for r in main if r["verdict"] != "right"]
    picks += [r for r in main if r["verdict"] == "right" and r["phrasing"] == "new"][:4]
    for r in picks:
        L.append(f"```text\n{r['transcript']}\n```\n")
    L.append(f"_Exam run took {seconds:.0f}s._")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main(seed: int = 0, compare: bool = True, path: str = os.path.join("results", "EXAM_REPORT.md")):
    t0 = time.time()
    leaks = leaked(seed)
    if leaks:
        print("warning: these exam questions appear in training:", leaks)
    council = freeze(train_curriculum_only("synod", seed))
    main_rows = sit(council)
    extra = {}
    if compare:
        for name in ("parser alone (symbolic)", "reader alone (neural)", "hand-written gate"):
            extra[name] = sit(freeze(train_curriculum_only(name, seed)))
    write_report(main_rows, extra, path, time.time() - t0)
    right, wrong, abst = score(main_rows)
    print(f"Synod: {right}/40 right, {wrong} wrong, {abst} abstained")
    for name, rows in extra.items():
        r_, w_, a_ = score(rows)
        print(f"{name}: {r_}/40 right, {w_} wrong, {a_} abstained")
    print(f"report written to {path}")
    return main_rows, extra
