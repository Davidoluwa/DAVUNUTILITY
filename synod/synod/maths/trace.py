"""Observability: record everything the council does on a question.

Nothing here changes behaviour. For each question it captures how the notation
was read, what every node privately computed (on a throwaway copy, so the real
deliberation is untouched), the auction, every review and belief change, and
the final weighing of candidates. The result is plain JSON for the viewer.
"""
from __future__ import annotations

import copy
import json
import math
import os

import numpy as np

from ..council import Council
from ..protocol import Task
from .exam import EXAM, freeze, train_curriculum_only
from .mathlang import context, read
from .nodes import featurize, feature_strings, numeric_features  # noqa: F401  (numeric_features kept for parity)
from .programs import describe, matches, primitives, run


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
            checks.append({"check": c, "reliability": round(rel, 3), "trusted": rel >= node.veto_at})
    return {"checks": checks}


INNER = {"parser": parser_view, "reader": reader_view, "estimator": estimator_view, "checker": checker_view}


# ---------------------------------------------------------------- one question
def trace(council, question, answer=None, qid=0):
    r = read(question)
    tol = 1e-6 * max(1.0, abs(answer)) if answer is not None else 1e-6
    task = Task(qid, (), tol, None if answer is None else float(answer), "", False,
                question=question, context=context(r), split="exam")
    view = task.view(0.0)

    # Private views, computed on a throwaway copy so the real run is untouched.
    shadow = copy.deepcopy(council)
    inner = {n.name: INNER[n.name](n, view, r) for n in shadow.nodes if n.name in INNER}

    live = copy.deepcopy(council)
    order = [n.name for n in sorted(live.nodes, key=lambda n: n.estimate_glance_cost()) if n.solves]
    weighings = []
    original = Council.reconcile

    def spy(cands, tolerance):
        post = original(cands, tolerance)
        weighings.append([{"node": c["prop"].node, "value": _f(c["prop"].value),
                           "belief_before": round(c["belief"], 3), "belief_after": round(post[id(c)], 3)}
                          for c in cands])
        return post

    Council.reconcile = staticmethod(spy)
    try:
        rec = live.handle(task)
    finally:
        Council.reconcile = staticmethod(original)

    turns = {d.node: {"node": d.node, "action": "declined", "reason": d.reason, "compute": round(d.spent, 2)}
             for d in rec.declined}
    for b in rec.bids:
        turns[b.node] = {"node": b.node, "action": "bid", "p_mean": round(b.p_mean, 3), "p_bid": round(b.p_success, 3),
                         "council_reading": round(live.belief_in(b.node, b.p_mean), 3),
                         "evidence": list(b.evidence), "compute": round(b.spent, 2), "needs": round(b.cost, 2)}
    auction = [turns[n] for n in order if n in turns]

    steps = []
    for p in rec.proposals:
        steps.append({"type": "proposal", "node": p.node, "kind": p.kind, "value": _f(p.value),
                      "confidence": round(p.confidence, 3), "rationale": p.rationale, "evidence": list(p.evidence),
                      "program": describe(p.program) if p.program is not None else None,
                      "compute": round(p.cost, 2)})
        for rv in rec.reviews:
            if rv.proposal is not p:
                continue
            v = rv.verdict
            steps.append({
                "type": "review", "lead": p.node, "reviewer": rv.reviewer,
                "verdict": "abstain" if v.endorses is None else ("endorse" if v.endorses else "reject"),
                "rationale": v.rationale, "evidence": list(v.evidence),
                "belief_before": round(rv.belief_before, 3), "belief_after": round(rv.belief_after, 3),
                "counter": None if v.counter is None else {"node": v.counter.node, "value": _f(v.counter.value),
                                                           "confidence": round(v.counter.confidence, 3),
                                                           "rationale": v.counter.rationale},
                "compute": round(rv.cost, 2)})
    if not rec.proposals:
        steps.append({"type": "silence"})

    final = rec.final
    verdict = None
    if answer is not None:
        verdict = "abstain" if final is None else ("right" if task.is_correct(final.value) else "wrong")
    return {
        "id": qid, "question": question, "answer": _f(answer) if answer is not None else None,
        "reading": reading_of(r), "context": list(view.context), "inner": inner,
        "auction": auction, "steps": steps,
        "weighing": weighings[-1] if weighings else [],
        "threshold": round(live.objective.deliver_threshold(view.pressure), 3),
        "final": None if final is None else {"node": final.node, "value": _f(final.value),
                                             "belief": round(rec.final_belief, 3)},
        "verdict": verdict, "compute": round(rec.cost, 2),
    }


def knowledge(council):
    by = council.by_name
    parser, reader = by["parser"], by["reader"]
    return {
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
