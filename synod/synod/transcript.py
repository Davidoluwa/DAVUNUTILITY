"""Render a deliberation record as a human-readable transcript."""
from __future__ import annotations


def _num(v: float) -> str:
    if v != v:
        return "?"
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        return str(int(round(v)))
    return f"{v:.4g}"


def _reason(feature: str, weight: float) -> str:
    sign = "+" if weight >= 0 else "−"
    return f"{sign}{abs(weight):.1f} {feature}"


def render(task, rec) -> str:
    if task.question:
        hidden = f"  (hidden type: {task.family})" if task.family else ""
        lines = [f"Q #{task.id}: {task.question}{hidden}"]
    else:
        hist = ", ".join(_num(v) for v in task.history)
        lines = [f"task #{task.id}  [{hist}, ?]  tolerance ±{task.tolerance:.2g}  (hidden family: {task.family})"]
    note = rec.notes.get("council", {})
    routed = note.get("routed", {})

    # who was consulted
    for d in rec.declined:
        lines.append(f"  {d.node:9s} not consulted ({d.reason})")
    gate = {(c["node"]): c for c in note.get("candidates", [])}
    for p in rec.proposals:
        pi = routed.get(p.node)
        route = f"router {pi:.0%}" if pi is not None else ""
        if p.value != p.value:
            lines.append(f"  {p.node:9s} consulted ({route}): nothing to offer")
            continue
        g = gate.get(p.node, {}).get("gate")
        lines.append(f"  {p.node:9s} consulted ({route}): {_num(p.value)}  self-confidence {p.confidence:.2f}"
                     + (f"  gate {g:.2f}" if g is not None else "") + f"  because {p.rationale}")

    # what the reviewers reported
    for r in rec.reviews:
        lines.append(f"     {r.reviewer} on {_num(r.proposal.value)}: {r.verdict.rationale}")

    # the judge
    if note.get("groups"):
        pooled = "  ".join(f"{_num(gr['value'])} ← {'+'.join(gr['nodes'])}: {gr['p']:.2f}" for gr in note["groups"])
        lines.append(f"  judge: {pooled}   none of these: {note.get('none', 0):.2f}   (deliver at ≥ {note.get('threshold', 0.5):.2f})")
        if rec.final is not None:
            why = next((c["reasons"] for c in note["candidates"] if c["node"] == rec.final.node), [])
            if why:
                lines.append("     why it trusted " + rec.final.node + ": " + ", ".join(_reason(f, w) for f, w in why))
        elif note.get("none_reasons"):
            lines.append("     why it held back: " + ", ".join(_reason(f, w) for f, w in note["none_reasons"]))

    known = task.target is not None
    truth = f"truth {_num(task.target)}" if known else "no answer key"
    if rec.final is None:
        lines.append(f"  => council abstains   [{truth}]")
    else:
        mark = (": correct" if task.is_correct(rec.final.value) else ": WRONG") if known else ""
        lines.append(f"  => answers {_num(rec.final.value)} from {rec.final.node} (probability {rec.final_belief:.2f})"
                     f"  [{truth}{mark}]  compute {rec.cost:.1f}")
    if rec.certified is not None:
        lines.append("     (confident enough to teach the members from this answer)")
    return "\n".join(lines)
