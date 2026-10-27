import unittest
from fractions import Fraction

from synod.maths.experiment import run_maths
from synod.maths.mathlang import Poly, parse_poly, read
from synod.maths.nodes import ParserNode
from synod.maths.programs import describe, explain, run
from synod.maths.world import MathScenario
from synod.protocol import Record, TaskView


class ReadingTest(unittest.TestCase):
    def test_notation_becomes_typed_slots(self):
        r = read("Solve 3*x + 7 = 22 for x.")
        self.assertEqual(r.slots, "Q1")
        self.assertEqual(r.skeleton, ("solve", "<eq>", "for", "<var>"))
        self.assertEqual(r.eqs[0].c, {1: Fraction(3), 0: Fraction(-15)})

    def test_functions_lists_and_words(self):
        r = read("Let f(x) = 2*x^2 - 3*x + 1. What is f(4)?")
        self.assertEqual(r.slots, "F1C1")
        self.assertEqual(r.calls, [("f", Fraction(4))])
        r = read("What is the mean of -3, 4, 11 and 20?")
        self.assertEqual(r.lists, [[Fraction(-3), Fraction(4), Fraction(11), Fraction(20)]])
        r = read("Is 7 a prime number?")  # 'a' is a word here, not a variable
        self.assertEqual(r.skeleton, ("is", "#", "a", "prime", "number"))

    def test_implicit_multiplication_and_two_variables(self):
        self.assertEqual(parse_poly(["2", "x", "-", "4"]).c, {1: 2, 0: -4})
        self.assertIsNone(parse_poly(["x", "+", "y"]))

    def test_poly_calculus(self):
        p = Poly({2: Fraction(3), 1: Fraction(2)}, "t")
        self.assertEqual(p.at(2), 16)
        self.assertEqual(p.derivative().at(2), 14)


class ProgramTest(unittest.TestCase):
    def check(self, question, answer, expected):
        progs = explain(read(question), answer)
        self.assertTrue(progs, question)
        self.assertEqual(describe(progs[0]), expected, question)

    def test_search_finds_the_meaning(self):
        self.check("Subtract 5 from 12.", 7, "(n2 - n1)")
        self.check("How many minutes are there in 3.5 hours?", 210, "(n1 * 60)")
        self.check("Is 97 a prime number?", 1, "is_prime(n1)")
        self.check("Let g(y) = 5y + 1. What is the derivative of g at y = 3?", 5, "f'(solve(equation))")
        self.check("What is the greatest common divisor of 84 and 126, multiplied by 3?", 126, "(gcd(n1, n2) * n3)")

    def test_execution_is_exact_and_safe(self):
        r = read("What is 2 to the power of 20?")
        self.assertEqual(run(("pow", ("N", 0), ("N", 1)), r), 2 ** 20)
        self.assertIsNone(run(("pow", ("N", 0), ("N", 1)), read("What is 99 to the power of 60?")))
        self.assertEqual(run(("is_prime", ("N", 0)), read("Is -7 prime?")), 0)


class ParserLearningTest(unittest.TestCase):
    def teach(self, node, i, question, answer):
        view = TaskView(i, (), 1e-6, question=question)
        rec = Record(view, label=float(answer))
        note = node.explain(rec)
        if note:
            rec.notes[node.name] = note
        node.observe(rec)

    def test_learns_a_wording_from_two_examples(self):
        node = ParserNode(seed=0)
        self.teach(node, 1, "What is the remainder when 47 is divided by 5?", 2)
        self.teach(node, 2, "What is the remainder when 100 is divided by 7?", 2)
        view = TaskView(3, (), 1e-6, question="What is the remainder when 1000 is divided by 7?")
        node.glance(view)
        self.assertAlmostEqual(node.solve(view).value, 6)

    def test_no_idea_means_no_bid(self):
        node = ParserNode(seed=0)
        self.teach(node, 1, "What is 3 plus 4?", 7)
        self.assertIsNone(node.analogize(read("What is the capital of France?")))


class EndToEndTest(unittest.TestCase):
    def test_short_curriculum(self):
        sc = MathScenario(n_train=900, n_per_test_split=25, seed=1)
        r = run_maths("synod", seed=1, scenario=sc)
        self.assertGreater(r.summary("seen")["accuracy"], 0.85)
        self.assertGreater(r.summary("big")["accuracy"], 0.85)
        self.assertLess(r.summary("seen")["wrong"], 0.05)

    def test_teacher_budget_is_respected(self):
        sc = MathScenario(n_train=600, n_per_test_split=20, seed=2)
        r = run_maths("synod", seed=2, scenario=sc, help_budget=5)
        asked = sum(x["asked"] for x in r.rows)
        self.assertGreater(asked, 0)
        self.assertLessEqual(asked, 5)


if __name__ == "__main__":
    unittest.main()


class ExamKeyTest(unittest.TestCase):
    def test_answer_key_is_right_and_unseen(self):
        """Recompute every exam answer with plain Python, independent of Synod."""
        import math
        from statistics import mean, median

        from synod.maths.exam import EXAM, leaked

        def isprime(n):
            return n > 1 and all(n % d for d in range(2, int(n ** 0.5) + 1))

        key = [348 + 279, 900 - 456, 64 * 25, 144 / 12, 12 * (7 + 8) - 30, 523 % 9, 250 % 7, math.gcd(252, 198),
               math.gcd(91, 65), 45, int(isprime(391)), int(isprime(211)), 3 ** 7, 45 ** 2, math.isqrt(2209),
               (23 + 12) / 7, (-7 - 9) / (4 - 2), -15 / 3, 3 * 9 - 2 * 3 + 4, 2 * 8 - 2, 3 * 16 - 10 * 4 + 2,
               12 * (-2) + 3, 41, 192, 13, mean([12, 18, 25, 33, 37]), median([7, 3, 19, 11, 5]),
               max([14, -3, 27, 8, 19]), max(-12, -15), int(45 > 54), 2.5 * 60, 7 * 100, 63 / 7, 23 + 15, 48 / 6,
               7 * 9, (22 + 3) / 5 + 10, (14 / 2) * 3, (2 * 3 + 5) + 4, 12 - 5]
        self.assertEqual(len(EXAM), 40)
        for (_, _, q, a), k in zip(EXAM, key):
            self.assertAlmostEqual(a, k, msg=q)
        self.assertEqual(leaked(0), [])
