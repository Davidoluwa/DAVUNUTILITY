import unittest

from synod.council import Council
from synod.experiment import make_nodes, run
from synod.protocol import Proposal, TaskView
from synod.world import Event, Scenario, World


def cand(value, belief):
    return {"prop": Proposal("n", "neural", value, belief, 0.0, ""), "belief": belief}


class ReconcileTest(unittest.TestCase):
    def test_conflicting_answers_cast_doubt_on_each_other(self):
        a, b = cand(10.0, 0.9), cand(20.0, 0.9)
        post = Council.reconcile([a, b], tolerance=0.5)
        self.assertAlmostEqual(post[id(a)], 0.5, places=6)
        self.assertAlmostEqual(post[id(a)], post[id(b)])

    def test_compatible_answers_do_not_conflict(self):
        a, b = cand(10.0, 0.9), cand(10.6, 0.7)
        post = Council.reconcile([a, b], tolerance=0.5)
        self.assertAlmostEqual(post[id(a)], 0.9)

    def test_track_record_breaks_ties(self):
        a, b = cand(10.0, 0.95), cand(20.0, 0.3)
        post = Council.reconcile([a, b], tolerance=0.5)
        self.assertGreater(post[id(a)], 0.7)
        self.assertGreater(post[id(a)], post[id(b)])

    def test_beliefs_that_fit_together_are_left_alone(self):
        a, b = cand(10.0, 0.6), cand(20.0, 0.2)
        post = Council.reconcile([a, b], tolerance=0.5)
        self.assertAlmostEqual(post[id(a)], 0.6)


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

    def test_council_abstains_when_nobody_can_help(self):
        council = Council([n for n in make_nodes(0) if n.name == "critic"])
        rec = council.handle(next(World(0).stream())[1])
        self.assertIsNone(rec.final)

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
