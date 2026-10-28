import unittest
from fractions import Fraction

from synod.maths.mathlang import read
from synod.protocol import Task
from synod.room.experts import Scene, open_context
import pickle

from synod.room import procedures
from synod.room.experts import NeuralExpert
from synod.room.room import make_room, verdict
from synod.room.transcript import render
from synod.room.workspace import (PROCS, UNKNOWABLE, Step, Workspace, canonical_program, program_to_steps, say,
                                  steps_to_program)
from synod.room.world import FAMILIES, INCOMPLETE_TEST, INCOMPLETE_TRAIN, RoomScenario, RoomWorld


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


class ReadingTest(unittest.TestCase):
    def test_numbers_written_as_words(self):
        r = read("Ali has three pens and twenty-five pencils. Each one costs two hundred cents.")
        self.assertEqual(r.nums, [3, 25, 200])
        self.assertEqual(r.texts[("N", 1)], "twenty-five")
        self.assertIn("one", r.skeleton)  # a lone "one" stays a word

    def test_a_vague_quantity_is_an_unknown_number(self):
        ws = Workspace(read("Rosa has 9 crayons and gets a few boxes of 11 crayons. How many crayons does Rosa have?"))
        self.assertIs(ws.fact("N2").value, UNKNOWABLE)
        self.assertEqual(ws.fact("N2").text, "a few")
        s1 = ws.run(Step("mul", ("N2", "N3")))
        self.assertIs(s1, UNKNOWABLE)  # anything built from it is unknown too
        self.assertIs(ws.apply(Step("mul", ("N2", "N3")), s1).run(Step("add", ("N1", "S1"))), UNKNOWABLE)

    def test_not_enough_information_is_its_own_outcome(self):
        answerable = Task(1, (), 1e-6, 5.0, "", False, question="?")
        missing = Task(2, (), 1e-6, None, "", False, question="?", answerable=False)
        self.assertEqual(verdict(missing, UNKNOWABLE), "right")
        self.assertEqual(verdict(missing, 5), "wrong")
        self.assertEqual(verdict(answerable, UNKNOWABLE), "wrong")
        self.assertEqual(verdict(answerable, None), "abstain")


class WorldTest(unittest.TestCase):
    def test_asides_and_missing_numbers(self):
        world = RoomWorld(RoomScenario(n_train=0, n_per_test_split=30, seed=2))
        tests = world.test_tasks(0)
        distract = [t for t in tests if t.split == "distract"]
        missing = [t for t in tests if t.split == "missing"]
        self.assertTrue(all(t.answerable and t.target is not None for t in distract))
        self.assertTrue(all(not t.answerable and t.target is None for t in missing))
        self.assertTrue(all(t.family in INCOMPLETE_TEST for t in missing))
        self.assertFalse(INCOMPLETE_TRAIN & INCOMPLETE_TEST)
        # the hidden reference skips the aside: running it gives the answer
        for t in distract:
            ws = Workspace(read(t.question))
            for step in program_to_steps(t.solution):
                ws = ws.apply(step, ws.run(step))
            self.assertAlmostEqual(float(ws.answer), t.target)

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
        late = [verdict(t, r.answer) == "right" for t, r in zip(tasks[-200:], self.rows[-200:])]
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


class ProcedureTest(unittest.TestCase):
    PCT = ["mul(N1,N2)", "div(S1,K100)", "add(N1,S2)"]  # b increased by p percent

    def test_recurring_pieces_are_found_and_abstracted(self):
        prog = procedures.tree([Step.parse(t) for t in self.PCT])
        bodies = {b for b, _ in procedures.fragments(prog)}
        self.assertIn(("div", ("mul", ("$", 0), ("$", 1)), ("K", 100)), bodies)  # "percent of", constant kept
        self.assertIn(("add", ("$", 0), ("div", ("mul", ("$", 0), ("$", 1)), ("K", 100))), bodies)  # same fact, same parameter

    def test_a_procedure_runs_rewrites_and_reads_back_as_its_operations(self):
        pct = procedures.make(("div", ("mul", ("$", 0), ("$", 1)), ("K", 100)), (("num",), ("num",)))
        from synod.room.workspace import register
        register(pct)
        scene = Scene("What is 200 increased by 15 percent?")
        path = procedures.replay_path(scene, tuple(self.PCT), [pct])
        self.assertEqual([s.token for _, s in path], [f"{pct.name}(N1,N2)", "add(N1,S1)", "answer"])
        self.assertEqual(path[-1][0].answer, Fraction(230))
        # method comparisons see through it
        self.assertEqual(steps_to_program([s for _, s in path]), steps_to_program([Step.parse(t) for t in self.PCT]))
        self.assertIn("invented", say(path[0][0], path[0][1]))

    def test_adopting_a_procedure_gives_it_an_expert_and_a_word(self):
        room = make_room(n_neural=2, seed=0)
        n = len(room.experts)
        proc = procedures.make(("div", ("mul", ("$", 0), ("$", 1)), ("K", 100)), (("num",), ("num",)))
        room.adopt(proc)
        self.assertEqual(len(room.experts), n + 1)
        self.assertIn(proc.name, room.full.by_name)
        neural = [e for e in room.full.experts if isinstance(e, NeuralExpert)]
        self.assertTrue(all(proc.name in e.tokens and e.net.W2.shape[1] == len(e.tokens) for e in neural))
        PROCS.pop(proc.name, None)
        again = pickle.loads(pickle.dumps(room))  # loading a room re-registers what it invented
        self.assertIn(proc.name, PROCS)
        self.assertEqual(len(again.procedures), 1)


if __name__ == "__main__":
    unittest.main()
