"""Render a deliberation record as a human-readable transcript."""
from __future__ import annotations


def _num(v: float) -> str:
    if v != v:
        return "?"
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        return str(int(round(v)))
    return f"{v:.4g}"


def render(task, rec) -> str:
    if task.question:
        hidden = f"  (hidden type: {task.family})" if task.family else ""
        lines = [f"Q #{task.id}: {task.question}{hidden}"]
    else:
        hist = ", ".join(_num(v) for v in task.history)
        lines = [f"task #{task.id}  [{hist}, ?]  tolerance ±{task.tolerance:.2g}  (hidden family: {task.family})"]
    if rec.view.pressure > 0:
        lines.append(f"  system pressure {rec.view.pressure:.2f} -> everyone is more cautious")
    for d in rec.declined:
        lines.append(f"  {d.node:9s} declines: {d.reason}")
    for b in rec.bids:
        lines.append(f"  {b.node:9s} bids p={b.p_success:.2f} (calibrated {b.p_mean:.2f}), needs {b.cost:.1f} more compute")
    for p in rec.proposals:
        lines.append(f"  -> {p.node} leads: {_num(p.value)}  conf {p.confidence:.2f}  because {p.rationale}")
        for r in rec.reviews:
            if r.proposal is not p:
                continue
            v = r.verdict
            verdict = "abstains" if v.endorses is None else ("endorses" if v.endorses else "REJECTS")
            note = ""
            if v.endorses and r.belief_after < r.belief_before:
                note = "  [this reviewer endorses nearly everything here, so a yes means little]"
            lines.append(f"     {p.node} asks {r.reviewer} for review -> {verdict}: {v.rationale}"
                         f"   (belief {r.belief_before:.2f} -> {r.belief_after:.2f}){note}")
            if v.counter is not None:
                lines.append(f"     {r.reviewer} counter-proposes {_num(v.counter.value)} (conf {v.counter.confidence:.2f})")
        if not any(r.proposal is p for r in rec.reviews):
            lines.append(f"     {p.node} skips review (not worth the compute at this confidence)")
    known = task.target is not None
    truth = f"truth {_num(task.target)}" if known else "no answer key"
    if rec.final is None:
        lines.append(f"  => council abstains (no answer it believes enough)   [{truth}]")
    else:
        mark = (": correct" if task.is_correct(rec.final.value) else ": WRONG") if known else ""
        lines.append(f"  => answers {_num(rec.final.value)} from {rec.final.node} (belief {rec.final_belief:.2f})"
                     f"  [{truth}{mark}]  compute {rec.cost:.1f}")
    if rec.certified is not None:
        lines.append("     (unlabeled task: answer certified as teaching signal for the others)")
    return "\n".join(lines)
