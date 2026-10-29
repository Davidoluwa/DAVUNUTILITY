import unittest

from synod.code.lang import CODE, passes, read, run_python, to_python
from synod.code.world import FAMILIES, CodeScenario, CodeWorld
from synod.room.experts import Scene
from synod.room.experiment import run_room
from synod.room.room import make_room
from synod.room.workspace import Step, program_to_steps


class CodeDomainTest(unittest.TestCase):
    Q = "Keep the 3 largest numbers, biggest first. Examples: [5, 1, 4, 9, 2] -> [9, 5, 4]; [3, 8, 1, 7] -> [8, 7, 3]"

    def test_reads_a_description_and_examples(self):
        r = read(self.Q)
        self.assertEqual(r.inputs, ((5, 1, 4, 9, 2), (3, 8, 1, 7)))
        self.assertEqual(r.outputs, ((9, 5, 4), (8, 7, 3)))
        self.assertEqual([n for n, _, _ in r.nums], [3])
        self.assertEqual(read("Keep the first three numbers. Examples: [1, 2, 3, 4] -> [1, 2, 3]").nums[0][0], 3)

    def test_a_program_runs_on_every_example_at_once_and_prints_as_python(self):
        scene = Scene(self.Q, CODE)
        ws = scene.workspace()
        steps = [Step("sort_desc", ("I1",)), Step("take", ("S1", "N1"))]
        for st in steps:
            ws = ws.apply(st, ws.run(st))
        self.assertTrue(CODE.matches(ws.answer, scene.target))
        src = to_python(steps, scene.reading)
        self.assertEqual(run_python(src, [7, 1, 9, 3, 8]), [9, 8, 7])  # the generated Python runs

    def test_every_kind_of_task_is_solved_by_its_own_program_on_hidden_inputs(self):
        world = CodeWorld(CodeScenario(seed=3))
        for fam in FAMILIES:
            q, checks, prog = world.make(fam, bool(fam.test))
            steps = program_to_steps(prog)
            self.assertTrue(passes(steps, checks), fam.name)
            self.assertTrue(passes(steps, q), fam.name)

    def test_the_room_learns_to_program_from_examples_alone(self):
        world = CodeWorld(CodeScenario(n_train=300, n_per_test_split=10, seed=0))
        run = run_room("code", seed=0, world=world, build=lambda s: make_room(n_neural=2, seed=s, domain=CODE))
        self.assertGreater(run.summary("seen")["accuracy"], 0.7)
        self.assertGreater(run.summary("compose")["accuracy"], 0.5)


if __name__ == "__main__":
    unittest.main()
