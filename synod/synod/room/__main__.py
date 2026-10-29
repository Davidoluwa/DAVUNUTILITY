"""The room: a large council that solves maths step by step.

  python -m synod.room train [--seed S] [--domain arith|code|algebra|orchestra]   train a room, save it
  python -m synod.room ask [--domain D] "Suppose 3*n - 4 = 11. What is n times 6?"
  python -m synod.room chat                      ask questions interactively
  python -m synod.room report [--seeds N]        compare with the old council -> results/ROOM_REPORT.md
  python -m synod.room exam                      the 40-question exam, step by step
  python -m synod.room trace                     every exam deliberation -> results/room_viewer.html
  python -m synod.room general [--seeds N]       the same room on code and algebra -> results/GENERAL_REPORT.md
  python -m synod.room orchestra [--seeds N]     one room for every modality -> results/ORCHESTRA_REPORT.md
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time

from ..protocol import Task
from .transcript import render

MODEL = os.path.join("results", "room.pkl")
DOMAINS = ("arith", "code", "algebra", "orchestra")


def model_path(domain: str = "arith") -> str:
    return MODEL if domain == "arith" else os.path.join("results", f"room_{domain}.pkl")


def _setup(domain: str, seed: int):
    """(room, practice world) for a domain."""
    from .room import RoomConfig, make_room
    if domain == "code":
        from ..code.lang import CODE
        from ..code.world import CodeScenario, CodeWorld
        return make_room(seed=seed, domain=CODE), CodeWorld(CodeScenario(seed=seed, n_per_test_split=0))
    if domain == "algebra":
        from ..algebra.lang import ALGEBRA
        from ..algebra.world import AlgebraScenario, AlgebraWorld
        return (make_room(seed=seed, domain=ALGEBRA, config=RoomConfig(max_steps=10)),
                AlgebraWorld(AlgebraScenario(n_train=2000, seed=seed, n_per_test_split=0)))
    if domain == "orchestra":
        from .orchestra import OrchestraWorld, orchestra
        return make_room(seed=seed, domain=orchestra()), OrchestraWorld(seed=seed, per=0)
    from .world import RoomScenario, RoomWorld
    return make_room(seed=seed), RoomWorld(RoomScenario(seed=seed, n_per_test_split=0))


def train(seed: int = 0, verbose: bool = True, domain: str = "arith"):
    room, world = _setup(domain, seed)
    t0 = time.time()
    for k, task in enumerate(world.train_stream(), 1):
        room.handle(task)
        if verbose and k % 1000 == 0:
            print(f"  {k} practice questions ({time.time() - t0:.0f}s)", flush=True)
    room.config.learn = False
    return room


def load(domain: str = "arith"):
    path = model_path(domain)
    if not os.path.exists(path):
        print(f"no trained {domain} room yet; training one (a few minutes)...", file=sys.stderr)
        room = train(verbose=False, domain=domain)
        save(room, domain)
    else:
        from .orchestra import orchestra
        orchestra()  # every domain registered before unpickling
        with open(path, "rb") as fh:
            room = pickle.load(fh)
    room.config.learn = False
    return room


def save(room, domain: str = "arith"):
    path = model_path(domain)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(room, fh)


def ask(room, question: str) -> str:
    task = Task(10 ** 7, (), 1e-6, None, "", False, question=question, split="ask")
    res = room.handle(task)
    out = render(task, res, judge=room.judge)
    if res.route is not None and res.route.trail and res.route.trail[0][0].ws.domain.name == "code" and res.answer is not None:
        from ..code.lang import to_python
        out += "\n\n" + to_python(res.steps, res.route.trail[0][0].ws.reading)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m synod.room")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--domain", choices=DOMAINS, default="arith")
    a = sub.add_parser("ask")
    a.add_argument("question", nargs="+")
    a.add_argument("--domain", choices=DOMAINS, default="arith")
    c = sub.add_parser("chat")
    c.add_argument("--domain", choices=DOMAINS, default="arith")
    rp = sub.add_parser("report")
    rp.add_argument("--seeds", type=int, default=3)
    rp.add_argument("--reuse", action="store_true", help="reuse the last comparison runs (results/room_compare.pkl)")
    sub.add_parser("exam")
    sub.add_parser("trace")
    g = sub.add_parser("general")
    g.add_argument("--seeds", type=int, default=3)
    g.add_argument("--per", type=int, default=100)
    o = sub.add_parser("orchestra")
    o.add_argument("--seeds", type=int, default=3)
    o.add_argument("--per", type=int, default=100)
    args = ap.parse_args(argv)

    if args.cmd == "train":
        room = train(args.seed, domain=args.domain)
        save(room, args.domain)
        print(f"saved to {model_path(args.domain)} ({len(room.experts)} experts)")
    elif args.cmd == "ask":
        print(ask(load(args.domain), " ".join(args.question)))
    elif args.cmd == "chat":
        room = load(args.domain)
        print("Ask a maths question (empty line to quit).")
        while True:
            try:
                q = input("> ").strip()
            except EOFError:
                break
            if not q:
                break
            print(ask(room, q))
    elif args.cmd == "report":
        from .exam import sit_council, sit_room
        from .report import compare, write
        from .trace import build_viewer, export
        seeds = list(range(args.seeds))
        saved = os.path.join("results", "room_compare.pkl")
        if args.reuse and os.path.exists(saved) and os.path.exists(MODEL):
            with open(saved, "rb") as fh:
                table, extras, seeds = pickle.load(fh)
        else:
            table, extras = compare(seeds, keep_room=MODEL)  # the seed-0 room is saved as the model
            with open(saved, "wb") as fh:
                pickle.dump((table, extras, seeds), fh)
        with open(MODEL, "rb") as fh:
            room = pickle.load(fh)
        exam = {**sit_room(room=room), "council v2 (question -> answer)": sit_council()}
        path = os.path.join("results", "ROOM_REPORT.md")
        write(table, extras, seeds, path, exam)
        print(f"report written to {path}; viewer -> {build_viewer(export(room=room))}")
    elif args.cmd == "exam":
        from .exam import sit_room
        for name, (r_, w_, a_) in sit_room(verbose=True).items():
            print(f"{name}: {r_}/40 right, {w_} wrong, {a_} abstained")
    elif args.cmd == "general":
        from .general import compare, write
        seeds = list(range(args.seeds))
        print(f"report written to {write(compare(seeds, per=args.per), seeds)}")
    elif args.cmd == "orchestra":
        from .orchestra import compare as o_compare, write as o_write
        seeds = list(range(args.seeds))
        print(f"report written to {o_write(o_compare(seeds, per=args.per))}")
    elif args.cmd == "trace":
        from .trace import build_viewer, export
        data = export()
        print(f"traced {len(data['cases'])} questions -> {build_viewer(data)}")


if __name__ == "__main__":
    main()
