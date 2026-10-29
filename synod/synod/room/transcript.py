"""Render the room's work as a worked solution with its deliberation."""
from __future__ import annotations

from .workspace import ARITH, INSUFFICIENT, STOP


def _who(c, top=4) -> str:
    props = sorted(c.props, key=lambda p: -p.confidence)
    names = [f"{p.expert} {p.confidence:.2f}" for p in props[:top]]
    more = len(props) - top
    return ", ".join(names) + (f" +{more} more" if more > 0 else "")


def render(task, res, alternatives: int = 2, reasons: bool = True, judge=None) -> str:
    """task: anything with .question (and optionally .target / .family)."""
    hidden = f"  (hidden type: {task.family})" if getattr(task, "family", "") else ""
    lines = [f"Q: {task.question}{hidden}"]
    if res.route is None:
        lines.append("  nobody could make a first step  => abstains")
        return "\n".join(lines)
    ws0 = res.route.trail[0][0].ws
    dom = getattr(ws0, "domain", ARITH)
    fmt = dom.fmt
    facts = ", ".join(f"{f.ref} = {f.text or fmt(f.value)}" for f in ws0.facts.values())
    lines.append(f"  on the table: {facts or '(nothing it can read)'}")
    for n, (m, k) in enumerate(res.route.trail, 1):
        c = m.cands[k]
        g = m.gates[k + 1]
        label = "Done" if c.step.op == STOP else "Stop" if c.step.op == INSUFFICIENT else f"Step {n}"
        what = dom.say(m.ws, c.step, c.value)
        lines.append(f"  {label}: {what}")
        lines.append(f"      {c.token}   judge {g:.2f}   backed by {_who(c)}")
        if c.reviews:
            lines.append(f"      reviews: {', '.join(s.replace(':', ' ', 1) for s in c.reviews)}")
        if reasons and judge is not None:
            why = judge.reasons(c.feats, top=3)
            if why:
                lines.append("      why: " + ", ".join(f"{'+' if w >= 0 else '−'}{abs(w):.1f} {f}" for f, w in why))
        rivals = sorted(((m.gates[i + 1], o) for i, o in enumerate(m.cands) if i != k), key=lambda t: -t[0])
        shown = [f"{o.token} {gg:.2f} ({o.props[0].expert}{'+' + str(len(o.props) - 1) if len(o.props) > 1 else ''})"
                 for gg, o in rivals[:alternatives] if gg >= 0.01]
        if shown or m.gates[0] >= 0.01:
            lines.append("      also on the table: " + ", ".join(shown + ([f"none of these {m.gates[0]:.2f}"]
                                                                        if m.gates[0] >= 0.01 else [])))
    other = [f"{fmt(v)} ({p:.2f}, {r} route{'s' if r > 1 else ''})" for v, p, r in res.answers[1:3]]
    routes = res.answers[0][2] if res.answers else 0
    answerable = getattr(task, "answerable", True)
    known = getattr(task, "target", None) is not None or not answerable
    truth = ""
    if known:
        v = dom.verdict(task, res)
        truth = f"  [truth {dom.truth(task)}{': correct' if v == 'right' else ': WRONG' if v == 'wrong' else ''}]"
    if res.answer is None and dom.verifiable:
        lines.append(f"  => abstains: nothing it found passes the problem's own check (closest route shown){truth}"
                     f"   compute {res.cost:.1f}")
    elif res.answer is None:
        best = fmt(res.route.outcome)
        lines.append(f"  => abstains: best answer {best} only reached {res.probability:.2f} (needs {res.threshold:.2f}){truth}")
    else:
        lines.append(f"  => {fmt(res.answer)}   probability {res.probability:.2f}"
                     f" ({routes} route{'s' if routes > 1 else ''} reached it){truth}   compute {res.cost:.1f}")
    if other:
        lines.append("     other answers considered: " + ", ".join(other))
    if res.certified:
        lines.append("     (sure enough to teach the room from this solution)")
    return "\n".join(lines)
