import os
import subprocess
import sys
import unittest

from synod.council import Council, CouncilConfig
from synod.experiment import make_nodes, run
from synod.learner import SparseLogLinear, sigmoid
from synod.node import Node
from synod.protocol import NEURAL, Proposal, Task, TaskView
from synod.world import Event, Scenario, World


class Stub(Node):
    """A solver with a fixed rule and a fixed claim about itself."""

    def __init__(self, name, offset, confidence, cost=1.0):
        super().__init__(name)
        self.offset, self.claim, self.price = offset, confidence, cost

    def solve(self, view):
        return Proposal(self.name, NEURAL, view.history[0] + self.offset, self.claim, self.price, "stub", ("s",))


def task(i, labeled=True):
    return Task(i, (float(i),), 0.5, float(i), "f", labeled, context=("c",))


def council(explore=1.0, **kw):
    # honest is always right but modest; liar is always wrong and sure of itself
    nodes = [Stub("honest", 0.0, 0.6), Stub("liar", 5.0, 0.99)]
    return Council(nodes, config=CouncilConfig(explore=explore, healing=False, **kw))


class LearnerTest(unittest.TestCase):
    def test_learns_a_logistic_rule_and_explains_it(self):
        m = SparseLogLinear(lr=0.5)
        for _ in range(300):
            for good in (True, False):
                f = {"bias": 1.0, "good" if good else "bad": 1.0}
                m.step(f, sigmoid(m.score(f)) - float(good))
        self.assertGreater(sigmoid(m.score({"bias": 1.0, "good": 1.0})), 0.9)
        self.assertLess(sigmoid(m.score({"bias": 1.0, "bad": 1.0})), 0.1)
        self.assertEqual(m.reasons({"bias": 1.0, "good": 1.0}, top=1)[0][0], "good")


class CouncilLearningTest(unittest.TestCase):
    def test_judge_learns_whom_to_trust_over_what_they_claim(self):
        c = council()
        for i in range(300):
            c.handle(task(i))
        rec = c.handle(task(1000, labeled=False))
        self.assertEqual(rec.final.node, "honest")
        self.assertGreater(rec.final_belief, 0.9)
        self.assertGreater(c.route_prob(c.by_name["honest"], rec.view), 0.9)
        self.assertLess(c.route_prob(c.by_name["liar"], rec.view), 0.1)

    def test_router_stops_asking_a_member_not_worth_its_compute(self):
        c = council(explore=0.0)
        for i in range(300):
            c.handle(task(i))
        rec = c.handle(task(1000, labeled=False))
        self.assertEqual([p.node for p in rec.proposals], ["honest"])
        self.assertEqual([d.node for d in rec.declined], ["liar"])

    def test_agreeing_members_pool_their_weight(self):
        props = [Proposal(n, NEURAL, v, 0.5, 0.0, "") for n, v in (("a", 10.0), ("b", 10.3), ("c", 20.0))]
        self.assertEqual(Council.clusters(props, tol=0.5), [[0, 1], [2]])

    def test_answers_it_asked_for_do_not_train_the_router_or_judge(self):
        c = council()
        for i in range(50):
            c.handle(task(i))
        c.teacher, c.config.help_budget = (lambda t: t.target), 5
        judge, router = dict(c.judge.w), dict(c.router.w)
        recs = [c.handle(task(100 + i, labeled=False)) for i in range(5)]
        self.assertEqual(c.help_used, 5)
        self.assertTrue(all(r.label_source == "asked" for r in recs))
        self.assertEqual(c.judge.w, judge)
        self.assertEqual(c.router.w, router)

    def test_frozen_council_stays_as_trained(self):
        c = council()
        for i in range(50):
            c.handle(task(i))
        c.config.learn = False
        judge = dict(c.judge.w)
        for i in range(20):
            c.handle(task(100 + i))
        self.assertEqual(c.judge.w, judge)

    def test_council_abstains_when_nobody_can_help(self):
        c = Council([n for n in make_nodes(0) if n.name == "critic"])
        rec = c.handle(next(World(0).stream())[1])
        self.assertIsNone(rec.final)


class WorldTest(unittest.TestCase):
    def test_nodes_cannot_see_the_answer(self):
        task = next(World(0).stream())[1]
        v = task.view()
        self.assertIsInstance(v, TaskView)
        self.assertFalse(hasattr(v, "target") or hasattr(v, "family"))


class EndToEndTest(unittest.TestCase):
    def test_short_run_learns_something(self):
        r = run("synod", seed=3, scenario=Scenario(n_tasks=400, events=[]))
        late = r.summary(250, 400)
        self.assertGreater(late["accuracy"], 0.6)
        self.assertGreater(late["utility"], 0.4)

    def test_runs_are_reproducible_across_processes(self):
        code = ("from synod.experiment import run; from synod.world import Scenario; "
                "print(run('synod', seed=2, scenario=Scenario(n_tasks=250, events=[])).summary())")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        outs = {subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                               env={**os.environ, "PYTHONHASHSEED": h}).stdout for h in ("0", "1")}
        self.assertEqual(len(outs), 1, outs)
        self.assertIn("utility", outs.pop())

    def test_broken_symbolic_node_quarantines_itself_and_returns(self):
        sc = Scenario(n_tasks=700, events=[Event(300, "fault", "inducer", "bug"),
                                           Event(450, "clear_fault", "inducer", "fix")])
        r = run("synod", seed=1, scenario=sc)
        inducer = next(n for n in r.nodes if n.name == "inducer")
        log = " | ".join(m for _, m in inducer.journal)
        self.assertIn("quarantined itself", log)
        self.assertIn("back in service", log)
        self.assertEqual(inducer.status, "healthy")


if __name__ == "__main__":
    unittest.main()
