"""Observability: record everything the council does on a question.

Nothing here changes behaviour. For each question it captures how the notation
was read, what every node privately computed (on a throwaway copy, so the real
deliberation is untouched), whom the learned router asked and why, what the
reviewers reported, and how the learned judge weighed the candidates, with its
strongest reasons in plain words. The result is plain JSON for the viewer.
"""
from __future__ import annotations

import copy
import json
import math
import os

import numpy as np

from ..protocol import Task
from .exam import EXAM, freeze, train_curriculum_only
from .mathlang import context, features, read
from .nodes import featurize, feature_strings
from .programs import describe, run


def _f(v):
    if v is None:
        return None
    v = float(v)
    if v != v or math.isinf(v):
        return None
    return round(v, 6)


def _poly_text(p):
    if p is None:
        return ""
    var = p.var or "x"
    terms = []
    for k in sorted(p.c, reverse=True):
        c = p.c[k]
        cs = str(c) if c.denominator != 1 else str(c.numerator)
        terms.append(f"{cs}" if k == 0 else f"{cs}·{var}" + (f"^{k}" if k > 1 else ""))
    return " + ".join(terms).replace("+ -", "− ") or "0"


def reading_of(r):
    return {
        "skeleton": list(r.skeleton),
        "slots": r.slots,
        "numbers": [_f(v) for v in r.nums],
        "lists": [[_f(v) for v in lst] for lst in r.lists],
        "equations": [_poly_text(q) + " = 0" for q in r.eqs],
        "functions": [f"{n}({p.var or 'x'}) = {_poly_text(p)}" for n, p in r.fdefs],
        "calls": [f"{n}({_f(v):g})" for n, v in r.calls],
        "expressions": [_poly_text(p) for p in r.exprs],
    }


# ---------------------------------------------------------------- inner views
def parser_view(node, view, r):
    sc = node.scratch(view)
    ev, spent, _ = node.glance(view)
    plan = sc.get("plan")
    table, strength = node.cues(r) if node.lex_total else ({}, {})
    cues = []
    for w, s in sorted(strength.items(), key=lambda kv: -kv[1])[:6]:
        top = node._top_prim(w, table)
        cues.append({"word": w, "means": top, "strength": round(s, 2)})
    similar = [{"wording": " ".join(sk), "similarity": round(sim, 2),
                "program": describe(node.ranked(sk, r)[0][3]) if node.ranked(sk, r) else None}
               for sim, sk in node.similar(r)]
    known = node.memory.get(r.skeleton)
    return {
        "evidence": list(ev),
        "mode": ev[0] if ev else None,
        "known_wording": bool(known),
        "program": describe(plan[1]) if plan else None,
        "value": _f(plan[2]) if plan else None,
        "why": plan[3] if plan else "no plan",
        "similar": similar,
        "cues": cues,
        "compute": round(spent, 2),
    }


def reader_view(node, view, r):
    if not node.programs:
        return {"top": [], "novel": None}
    idx = featurize(r)
    probs = []
    for net in node.nets:
        _, z = net.forward(idx)
        p = np.exp(z - z.max())
        probs.append(p / p.sum())
    mean = np.mean(probs, axis=0)
    top = []
    for k in np.argsort(-mean)[:6]:
        prog = node.programs[int(k)]
        v = run(prog, r)
        top.append({"program": describe(prog), "p": round(float(mean[k]), 3),
                    "value": _f(v), "runs": v is not None})
        if len(top) >= 4:
            break
    votes = []
    for p in probs:
        live = [int(k) for k in np.argsort(-p)[:12] if run(node.programs[int(k)], r) is not None]
        votes.append(describe(node.programs[live[0]]) if live else None)
    pred = node.predict(view)
    structure = node.structure(r)
    return {
        "top": top,
        "votes": votes,
        "agree": bool(pred[3]) if pred else None,
        "novel": bool(pred[4]) if pred else None,
        "important_words": list(structure[1:]),
        "chosen": describe(pred[0]) if pred else None,
        "chosen_value": _f(pred[1]) if pred else None,
    }


def estimator_view(node, view, r):
    if len(node.buffer) < 150:
        return {"ready": False}
    y = node.guess(view)
    sd = max(math.sqrt(node.resid.get(view.context, 1.0)), 0.15)
    feats = feature_strings(r)
    unfamiliar = sum(f not in node.familiar for f in feats) / max(len(feats), 1)
    about = math.copysign(10 ** abs(y) - 1, y)
    lo = math.copysign(10 ** max(abs(y) - 2.5 * sd - 0.1, 0) - 1, y)
    hi = math.copysign(10 ** (abs(y) + 2.5 * sd + 0.1) - 1, y)
    return {"ready": True, "about": round(about, 3), "range": sorted([round(lo, 3), round(hi, 3)]),
            "unfamiliar": round(unfamiliar, 2), "has_feel": unfamiliar <= 0.15}


def checker_view(node, view, r):
    checks = []
    for c in node.CHECKS:
        if node._applies(c, r):
            rel = node.reliability.mean((c,) + view.context + (r.skeleton,))
            checks.append({"check": c, "reliability": round(rel, 3), "trusted": rel >= node.trusted_at})
    return {"checks": checks}


INNER = {"parser": parser_view, "reader": reader_view, "estimator": estimator_view, "checker": checker_view}


# ---------------------------------------------------------------- the judge's features, in words
def _tok(t):
    if t.startswith("w:"):
        return f"the word '{t[2:]}'"
    if t.startswith("ctx:"):
        return f"shape {t[4:]}"
    return t


def _signal(tag):
    parts = tag.split(":")
    if len(parts) == 3:
        return f"{parts[0]} {parts[1]} ({parts[2]})"
    if len(parts) == 2:
        return f"{parts[0]} {parts[1]}"
    return {"endorse": "it's fine", "reject": "something's off", "abstain": "can't judge"}.get(tag, tag)


def readable(feature):
    """The judge's (and router's) learned features, in plain words."""
    p = feature.split("|")
    k = p[0]
    try:
        if k == "null":
            return "baseline caution"
        if k == "b":
            return f"{p[1]}'s overall record"
        if k == "cl":
            return f"{p[1]}'s self-confidence"
        if k == "cb":
            lo = int(p[2]) * 10
            return f"{p[1]} saying it's {lo}-{lo + 9}% sure"
        if k == "nc":
            return f"{p[2]} different answer{'s' if p[2] != '1' else ''} on the table"
        if k == "e":
            return f"{p[1]}'s evidence: {p[2].replace('/', ' · ')}"
        if k == "x":
            return (f"caution on questions with {_tok(p[2])}" if p[1] == "null"
                    else f"{p[1]} on questions with {_tok(p[2])}")
        if k == "ex":
            return f"{p[1]} ({p[2].replace('/', ' · ')}) on questions with {_tok(p[3])}"
        if k in ("with", "vs"):
            rel = "agrees" if k == "with" else "disagrees"
            return f"{p[2]} {rel}" + (f" ({p[3].replace('/', ' · ')})" if len(p) > 3 else "")
        if k == "ag":
            return {"0": "nobody else agrees", "1": "one other member agrees"}.get(p[2], f"{p[2]} others agree")
        if k == "v":
            return f"{p[2]} on {p[1]}'s answer: {_signal(p[3])}"
        if k == "has":
            return f"caution when {p[2]} offers {p[3].replace('/', ' · ')}"
    except (IndexError, ValueError):
        pass
    return feature


def _reasons(pairs):
    return [{"feature": f, "text": readable(f), "weight": round(w, 2)} for f, w in pairs]


# ---------------------------------------------------------------- one question
def trace(council, question, answer=None, qid=0):
    r = read(question)
    tol = 1e-6 * max(1.0, abs(answer)) if answer is not None else 1e-6
    task = Task(qid, (), tol, None if answer is None else float(answer), "", False,
                question=question, context=context(r), split="exam", features=features(r))
    view = task.view(0.0)

    # Private views, computed on a throwaway copy so the real run is untouched.
    shadow = copy.deepcopy(council)
    inner = {n.name: INNER[n.name](n, view, r) for n in shadow.nodes if n.name in INNER}

    live = copy.deepcopy(council)
    rec = live.handle(task)
    note = rec.notes.get("council", {})
    declined = {d.node: d.reason for d in rec.declined}
    cand = {c["node"]: c for c in note.get("candidates", [])}

    solvers = []
    for name, p in note.get("routed", {}).items():  # in the order the router considered them
        prop = next((q for q in rec.proposals if q.node == name), None)
        entry = {"node": name, "kind": live.by_name[name].kind, "p": round(p, 3), "asked": prop is not None}
        if prop is None:
            entry["reason"] = declined.get(name, "")
        else:
            c = cand.get(name)
            entry.update({
                "value": _f(prop.value), "confidence": round(prop.confidence, 3), "rationale": prop.rationale,
                "evidence": [str(e) for e in prop.evidence], "compute": round(prop.cost, 2),
                "program": describe(prop.program) if prop.program is not None else None,
                "gate": round(c["gate"], 3) if c else None, "reasons": _reasons(c["reasons"]) if c else []})
        solvers.append(entry)

    reviewers = []
    for n in live.nodes:
        if n.solves:
            continue
        mine = [x for x in rec.reviews if x.reviewer == n.name]
        if mine:
            reviewers.append({"node": n.name, "kind": n.kind, "asked": True, "compute": round(sum(x.cost for x in mine), 2),
                              "signals": [{"on": _f(x.proposal.value), "by": x.proposal.node,
                                           "rationale": x.verdict.rationale, "evidence": list(x.verdict.evidence)}
                                          for x in mine]})
        else:
            reviewers.append({"node": n.name, "kind": n.kind, "asked": False,
                              "reason": declined.get(n.name, "nothing to review")})

    final = rec.final
    verdict = None
    if answer is not None:
        verdict = "abstain" if final is None else ("right" if task.is_correct(final.value) else "wrong")
    return {
        "id": qid, "question": question, "answer": _f(answer) if answer is not None else None,
        "reading": reading_of(r), "context": list(view.context), "inner": inner,
        "solvers": solvers, "reviewers": reviewers,
        "judge": {"groups": [{"value": _f(g["value"]), "p": round(g["p"], 3), "nodes": g["nodes"]}
                             for g in note.get("groups", [])],
                  "none": round(note.get("none", 1.0), 3), "none_reasons": _reasons(note.get("none_reasons", []))},
        "threshold": round(note.get("threshold", live.objective.deliver_threshold(0.0)), 3),
        "final": None if final is None else {"node": final.node, "value": _f(final.value),
                                             "belief": round(rec.final_belief, 3)},
        "verdict": verdict, "compute": round(rec.cost, 2),
    }


def knowledge(council):
    by = council.by_name
    parser, reader = by["parser"], by["reader"]
    # The judge's strongest learned trust rules (features that don't depend on the question).
    general = [(f, w) for f, w in council.judge.w.items() if f.split("|")[0] in ("b", "cb", "e", "v", "ag", "nc", "null", "with", "vs")]
    general.sort(key=lambda fw: -fw[1])
    return {
        "judge": {"features": len(council.judge.w), "trusts": _reasons(general[:8]), "doubts": _reasons(general[::-1][:8])},
        "parser": {"wordings": len(parser.memory), "meanings": parser.meanings(3)},
        "reader": {"programs": len(reader.programs), "structures": len(reader.structures)},
        "estimator": {"examples": len(by["estimator"].buffer)},
        "checker": {"checks": list(by["checker"].CHECKS)},
    }


def export(path=os.path.join("results", "council_trace.json"), seed=0):
    council = freeze(train_curriculum_only("synod", seed))
    cases = []
    for i, (topic, phrasing, q, ans) in enumerate(EXAM, 1):
        t = trace(council, q, ans, qid=i)
        t["topic"], t["phrasing"] = topic, phrasing
        cases.append(t)
    data = {"seed": seed, "cases": cases, "knowledge": knowledge(council)}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=1)
    return data


def build_viewer(data, out=os.path.join("results", "council_viewer.html")):
    """Embed the traces into the single-file viewer page."""
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "viewer.html")) as fh:
        page = fh.read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    with open(out, "w") as fh:
        fh.write(page.replace("__DATA__", blob))
    return out
