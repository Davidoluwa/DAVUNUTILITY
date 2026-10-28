"""Run the full comparison and write a human-readable report."""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

import numpy as np

from .experiment import STRATEGIES, routing_table, run
from .transcript import render
from .world import Scenario

WINDOWS = {"after memory fault": (550, 590), "after symbolic bug": (1250, 1300)}


def _job(args):
    name, seed = args
    r = run(name, seed=seed)
    windows = {k: r.summary(*v) for k, v in WINDOWS.items()}
    timeline = [r.summary(lo, lo + 100)["utility"] for lo in range(0, len(r.rows), 100)]
    return name, seed, r.summary(), windows, timeline, r.maintenance / max(len(r.rows), 1)


def compare(seeds, processes: int = 4):
    jobs = [(n, s) for n in STRATEGIES for s in seeds]
    try:
        from multiprocessing import Pool

        with Pool(processes) as pool:
            out = pool.map(_job, jobs)
    except (OSError, ImportError):
        out = [_job(j) for j in jobs]
    table = {}
    for name in STRATEGIES:
        rows = [o for o in out if o[0] == name]
        agg = {k: float(np.mean([r[2][k] for r in rows])) for k in rows[0][2]}
        agg["utility_sd"] = float(np.std([r[2]["utility"] for r in rows]))
        agg["maintenance"] = float(np.mean([r[5] for r in rows]))
        for w in WINDOWS:
            agg[w] = float(np.mean([r[3][w]["utility"] for r in rows]))
            agg[w + " (wrong)"] = float(np.mean([r[3][w]["wrong"] for r in rows]))
        agg["timeline"] = list(np.mean([r[4] for r in rows], axis=0))
        table[name] = agg
    return table


def _pick(transcripts, test, after=300):
    for t in sorted(transcripts):
        if t >= after:
            task, rec = transcripts[t]
            if test(task, rec):
                return task, rec
    return None


def showcase(transcripts):
    """Auto-pick deliberations that show the protocol doing interesting things."""
    exact = {"arithmetic", "geometric", "fibonacci", "quadratic", "affine", "interleaved"}

    def ok(task, rec):
        return rec.final is not None and task.is_correct(rec.final.value)

    def split(r):  # the judge had rival answers to choose between
        return len(r.notes.get("council", {}).get("groups", [])) > 1

    picks = [
        ("A symbolic law the judge trusts on sight", lambda t, r: ok(t, r) and r.final.node == "inducer"
         and "concept" in r.final.rationale),
        ("The router skips a member that rarely helps here", lambda t, r: ok(t, r) and any(
            "router" in d.reason for d in r.declined)),
        ("Neural intuition handles a noisy nonlinear series", lambda t, r: ok(t, r)
         and r.final.node == "intuition" and t.family in ("saturating", "wave")),
        ("Members disagree; the judge picks the right one", lambda t, r: ok(t, r) and split(r)),
        ("Honest abstention instead of a wrong answer", lambda t, r: r.final is None and r.proposals
         and not any(p.value == p.value and t.is_correct(p.value) for p in r.proposals)),
        ("Inducer quarantined: the others cover what they can", lambda t, r: 1285 <= t.id < 1400
         and t.family in exact and r.final is not None and r.final.node != "inducer"),
    ]
    out, used = [], set()
    for title, test in picks:
        hit = _pick(transcripts, lambda t, r, test=test: t.id not in used and test(t, r),
                    after=1285 if "quarantined" in title else 300)
        if hit:
            used.add(hit[0].id)
            out.append((title, render(*hit)))
    return out


def detail_run(seed: int = 0):
    r = run("synod", seed=seed, keep_transcripts=range(Scenario().n_tasks))
    by = {n.name: n for n in r.nodes}
    timeline = [(t, "world", note) for t, note in r.events]
    for n in r.nodes:
        timeline.extend((t, n.name, msg) for t, msg in n.journal if "false alarm" not in msg)
    false_alarms = {n.name: sum("false alarm" in m for _, m in n.journal) for n in r.nodes}
    reviews = Counter()
    for task, rec in r.transcripts.values():
        for rv in rec.reviews:
            v = rv.verdict.endorses
            verdict = "no trusted constraint" if v is None else ("all trusted kept" if v else "a trusted one broken")
            truth = "candidate right" if task.is_correct(rv.proposal.value) else "candidate wrong"
            reviews[(rv.reviewer, verdict, truth)] += 1
    inducer, critic = by["inducer"], by["critic"]
    approx_ctx = [sig for sig in list(inducer.exact_exists._c) if len(sig) == 4
                  and inducer.exact_exists.count(sig) >= 10 and inducer.exact_exists.mean(sig) < 0.05]
    return {
        "run": r,
        "timeline": sorted(timeline),
        "false_alarms": false_alarms,
        "routing_before": routing_table(r, 300, 550),
        "routing_end": routing_table(r, 1450, 1600),
        "concepts": inducer.describe_knowledge(8),
        "approx_contexts": approx_ctx,
        "constraints": critic.describe_knowledge(),
        "reviews": reviews,
        "showcase": showcase(r.transcripts),
        "status": {n.name: dict(n.stats) for n in r.nodes},
    }


def _pct(x):
    return f"{100 * x:.0f}%"


def write_report(table, detail, seeds, path):
    L = []
    sc = Scenario()
    L.append("# Synod - run report\n")
    L.append(f"Scenario: {sc.n_tasks} tasks, {_pct(sc.label_rate)} of them labeled after the fact. "
             "Scheduled trouble:\n")
    for e in sc.events:
        L.append(f"- t={e.at}: {e.note}")
    L.append(f"\nAveraged over {len(seeds)} seeds. Utility per task = +1 correct, -1 wrong, 0 abstain, "
             "minus 0.02 per unit of compute.\n")
    L.append("## Head to head\n")
    L.append("| strategy | utility | accuracy | wrong answers | abstained | compute/task | "
             "utility right after memory fault | utility right after symbolic bug |")
    L.append("|---|---|---|---|---|---|---|---|")
    top = max(a["utility"] for a in table.values())
    for name, a in table.items():
        u = f"{a['utility']:+.3f}"
        u = f"**{u}**" if a["utility"] == top else u
        L.append(f"| {name} | {u} ± {a['utility_sd']:.3f} | {_pct(a['accuracy'])} | "
                 f"{_pct(a['wrong'])} | {_pct(a['abstain'])} | {a['cost']:.2f} | "
                 f"{a['after memory fault']:+.2f} ({_pct(a['after memory fault (wrong)'])} wrong) | "
                 f"{a['after symbolic bug']:+.2f} ({_pct(a['after symbolic bug (wrong)'])} wrong) |")
    L.append("\nUtility per 100-task window (seed mean):\n")
    keys = ["synod", "symbolic-only", "hand-written gate", "synod w/o self-healing"]
    L.append("| window | " + " | ".join(keys) + " |")
    L.append("|---|" + "---|" * len(keys))
    for i in range(len(table["synod"]["timeline"])):
        L.append(f"| {i * 100}-{i * 100 + 99} | " + " | ".join(f"{table[k]['timeline'][i]:+.2f}" for k in keys) + " |")

    L.append("\n## Who ended up doing what (seed 0) - emergent, never programmed\n")
    L.append("Share of delivered answers per hidden family. Nodes never see the family.\n")
    fams = sorted(set(detail["routing_before"]) | set(detail["routing_end"]))

    def cell(c):
        tot = sum(c.values())
        return ", ".join(f"{k} {_pct(v / tot)}" for k, v in c.most_common()) if tot else "-"

    L.append("| family | t 300-549 (warmed up) | t 1450-1599 (after faults and shift) |")
    L.append("|---|---|---|")
    for f in fams:
        L.append(f"| {f} | {cell(detail['routing_before'].get(f, Counter()))} | {cell(detail['routing_end'].get(f, Counter()))} |")

    L.append("\n## What the nodes decided on their own (seed 0)\n")
    for t, who, msg in detail["timeline"]:
        L.append(f"- t={t} **{who}**: {msg}")
    fa = ", ".join(f"{k} {v}" for k, v in detail["false_alarms"].items() if v)
    if fa:
        L.append(f"\nSelf-checks that came back clean (false alarms, cost only maintenance compute): {fa}.")

    L.append("\n## What the symbolic side learned (seed 0)\n")
    L.append("Concepts the inducer invented (laws confirmed often enough to be checked first, almost for free):\n")
    for rule, n in detail["concepts"]:
        L.append(f"- `{rule}` (confirmed {n:.0f}x)")
    if detail["approx_contexts"]:
        L.append("\nSituations where it learned exact laws never turn up, so it stopped hunting for them "
                 "and switched to cheap approximate laws:\n")
        for sig in detail["approx_contexts"]:
            L.append(f"- {' / '.join(sig)}")
    L.append("\nCritic's learned trust in its own constraints (how often reality respected each one):\n")
    for name, rel, n in detail["constraints"]:
        L.append(f"- {name}: {_pct(rel)} (evidence {n:.0f})")

    L.append("\n## What the critic reported (seed 0)\n")
    L.append("The critic reports signals on every candidate; the judge learns what they're worth.\n")
    L.append("| reviewer | signal | candidate was | count |")
    L.append("|---|---|---|---|")
    for (who, verdict, truth), n in sorted(detail["reviews"].items()):
        L.append(f"| {who} | {verdict} | {truth} | {n} |")

    L.append("\n## Sample deliberations (seed 0, auto-picked)\n")
    for title, text in detail["showcase"]:
        L.append(f"### {title}\n\n```text\n{text}\n```\n")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def export_json(table, detail, path):
    data = {
        "table": table,
        "routing_before": {f: dict(c) for f, c in detail["routing_before"].items()},
        "routing_end": {f: dict(c) for f, c in detail["routing_end"].items()},
        "timeline": detail["timeline"],
        "concepts": detail["concepts"],
        "constraints": detail["constraints"],
        "showcase": detail["showcase"],
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=1, default=str)
