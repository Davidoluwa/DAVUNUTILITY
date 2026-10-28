import unittest
from fractions import Fraction

from synod.maths.mathlang import read
from synod.protocol import Task
from synod.room.experts import Scene, open_context
from synod.room.room import make_room
from synod.room.transcript import render
from synod.room.workspace import Step, Workspace, canonical_program, program_to_steps, say, steps_to_program
from synod.room.world import FAMILIES, RoomScenario, RoomWorld


class WorkspaceTest(unittest.TestCase):
    def test_programs_become_steps_and_back(self):
        prog = ("div", ("sub", ("add", ("N", 0), ("mul", ("N", 1), ("N", 2))), ("N", 3)), ("N", 4))
        steps = program_to_steps(prog)
        self.assertEqual([s.token for s in steps], ["mul(N2,N3)", "add(N1,S1)", "sub(S2,N4)", "div(S3,N5)"])
        self.assertEqual(steps_to_program(steps), canonical_program(prog))

    def test_steps_run_exactly_and_read_as_a_worked_solution(self):
        ws = Workspace(read("Suppose 3*n - 4 = 11. What is n times 6?"))
        lines = []
        for step in program_to_steps(("mul", ("solve", ("Q", 0)), ("N", 0))):
            v = ws.run(step)
            lines.append(say(ws, step, v))
            ws = ws.apply(step, v)
        self.assertEqual(ws.answer, Fraction(30))
        self.assertEqual(lines, ["solve 3*n - 4 = 11 for n: n = 5", "6 × 5 = 30"])

    def test_results_are_grounded_where_the_question_talks_about_them(self):
        scene = Scene("Suppose 7*t - 29 = 3*t - 49. Is t a prime number?")
        ws = scene.workspace()
        ws = ws.apply(Step("solve", ("Q1",)), ws.run(Step("solve", ("Q1",))))
        self.assertIn("oW:prime", open_context(scene, ws))

    def test_commutative_steps_have_one_spelling(self):
        ws = Workspace(read("What is 3 plus 4?"))
        self.assertEqual(ws.bindings("add"), [("N1", "N2")])
        self.assertEqual(len(ws.bindings("sub")), 2)


class WorldTest(unittest.TestCase):
    def test_every_family_grounds_and_runs(self):
        world = RoomWorld(RoomScenario(seed=3))
        for fam in FAMILIES:
            for held in (False, True):
                q, ans, prog = world.make(fam, held)
                self.assertIsNotNone(ans, fam.name)
                self.assertGreaterEqual(len(program_to_steps(prog)), 1)

    def test_the_method_is_hidden_from_the_room(self):
        task = next(RoomWorld(RoomScenario(n_train=1)).train_stream())
        self.assertTrue(task.solution)
        self.assertFalse(hasattr(task.view(), "solution"))


class RoomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.room = make_room(n_neural=2, seed=0)
        cls.world = RoomWorld(RoomScenario(n_train=600, seed=0))
        cls.rows = [cls.room.handle(t) for t in cls.world.train_stream()]

    def test_it_learns_from_answers_alone(self):
        tasks = list(RoomWorld(RoomScenario(n_train=600, seed=0)).train_stream())
        late = [r.answer is not None and t.is_correct(float(r.answer)) for t, r in zip(tasks[-200:], self.rows[-200:])]
        self.assertGreater(sum(late) / len(late), 0.4)

    def test_a_worked_solution_with_its_deliberation(self):
        task = Task(1, (), 1e-6, 31.0, "add", False, question="What is 14 plus 17?", split="test")
        self.room.config.learn = False
        try:
            res = self.room.handle(task)
        finally:
            self.room.config.learn = True
        text = render(task, res, judge=self.room.judge)
        self.assertIn("Step 1:", text)
        self.assertIn("backed by", text)

    def test_cross_fitting_keeps_a_wording_away_from_one_sparring_bench(self):
        room = make_room(n_neural=1, seed=0, crossfit=True)
        scene = Scene("What is 14 plus 17?")
        self.assertIsNot(room.outsider(scene), room.folds[room.fold(scene)])
        self.assertEqual(len(room.benches), 3)
        self.assertEqual(len(self.room.benches), 1)


if __name__ == "__main__":
    unittest.main()
