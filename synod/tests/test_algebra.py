import unittest
from fractions import Fraction

from synod.algebra.lang import ALGEBRA, eliminate, read
from synod.algebra.world import AlgebraScenario, AlgebraWorld
from synod.room.experiment import run_room
from synod.room.experts import Scene
from synod.room.room import RoomConfig, make_room
from synod.room.workspace import Step


class AlgebraDomainTest(unittest.TestCase):
    def test_reads_equations_as_written_and_what_is_asked(self):
        r = read("Given 2x + 3y = 13 and x - y = -1, what is x plus y?")
        self.assertEqual([e.text() for e, _, _ in r.eqs], ["2x + 3y = 13", "x - y = -1"])
        self.assertEqual(r.variables, ["x", "y"])
        self.assertEqual(sorted(r.mentions.values()), ["x", "y"])

    def test_general_moves_make_a_full_derivation(self):
        scene = Scene("Solve 3(x + 4) - 2 = 5x - 6. What is x?", ALGEBRA)
        ws = scene.workspace()
        lines = []
        for st in [Step("expand", ("Q1",)), Step("gather", ("S1",)), Step("divide", ("S2",)), Step("value", ("S3",))]:
            v = ws.run(st)
            lines.append(ALGEBRA.say(ws, st, v))
            ws = ws.apply(st, v)
        self.assertEqual(ws.answer, Fraction(8))
        self.assertIn("3x + 10 = 5x - 6", lines[0])
        self.assertIn("x = 8", lines[2])

    def test_moves_keep_equations_true(self):
        q1, q2 = (e for e, _, _ in read("Given 2x + 3y = 13 and x - y = -1, what is y?").eqs)
        e = eliminate(q1, q2, "x")
        self.assertEqual(e.text(), "5y = 15")  # (x, y) = (2, 3) still satisfies it

    def test_the_room_learns_to_solve_systems_from_answers_alone(self):
        world = AlgebraWorld(AlgebraScenario(n_train=400, n_per_test_split=8, seed=0))
        run = run_room("algebra", seed=0, world=world,
                       build=lambda s: make_room(n_neural=2, seed=s, domain=ALGEBRA, config=RoomConfig(max_steps=10)))
        self.assertGreater(run.summary("seen")["accuracy"], 0.7)
        self.assertGreater(run.summary("forms")["accuracy"], 0.5)  # equation shapes and letters never seen


if __name__ == "__main__":
    unittest.main()
