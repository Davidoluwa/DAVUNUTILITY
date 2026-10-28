import unittest

import numpy as np

from synod.nodes.inducer import GRAMMAR, InducerNode, fit_template
from synod.protocol import Record, TaskView

BY_NAME = {t.name: t for t in GRAMMAR}


def view(history, tol=0.5, i=0):
    return TaskView(i, tuple(float(v) for v in history), tol)


class FitTest(unittest.TestCase):
    def test_exact_laws(self):
        cases = {
            "recurrence-2": ([2, 3, 5, 8, 13, 21, 34, 55], 89),
            "geometric": ([3, 6, 12, 24, 48, 96, 192, 384], 768),
            "quadratic": ([k * k - 2 * k + 5 for k in range(8)], 8 * 8 - 16 + 5),
            "interleaved": ([1, 10, 4, 13, 7, 16, 10, 19], 13),
        }
        for name, (hist, nxt) in cases.items():
            f = fit_template(BY_NAME[name], np.array(hist, dtype=float))
            self.assertTrue(f.exact, name)
            self.assertAlmostEqual(f.prediction, nxt, places=6, msg=name)

    def test_snapped_coefficients_are_readable(self):
        f = fit_template(BY_NAME["recurrence-2"], np.array([2, 3, 5, 8, 13, 21, 34, 55], dtype=float))
        self.assertEqual(f.template.describe(f.coef), "x[n] = x[n-1] + x[n-2]")

    def test_noise_gives_graded_not_exact_fit(self):
        rng = np.random.default_rng(0)
        hist = np.array([2.0 + 1.5 * k for k in range(8)]) + rng.normal(0, 0.5, 8)
        f = fit_template(BY_NAME["line"], hist)
        self.assertFalse(f.exact)
        self.assertGreater(f.sd, 0.0)
        self.assertLess(abs(f.prediction - (2.0 + 1.5 * 8)), 2.0)


class InducerNodeTest(unittest.TestCase):
    def test_solves_and_explains(self):
        node = InducerNode(seed=0)
        p = node.solve(view([1, 1, 2, 3, 5, 8, 13, 21]))
        self.assertAlmostEqual(p.value, 34)
        self.assertIn("x[n-1] + x[n-2]", p.rationale)
        self.assertEqual(p.evidence[0], "exact")

    def test_invents_concepts_and_gets_cheaper(self):
        node = InducerNode(seed=0)
        seqs = [[a, b] for a, b in [(1, 2), (3, 1), (2, 7), (5, 4), (1, 9), (4, 4)]]
        costs = []
        for i, s in enumerate(seqs):
            while len(s) < 9:
                s.append(s[-1] + s[-2])
            v = view(s[:8], i=i)
            p = node.solve(v)
            costs.append(p.cost)
            rec = Record(v, proposals=[p], label=float(s[8]))
            node.observe(rec)
        self.assertTrue(any("x[n-1] + x[n-2]" in rule for rule, _ in node.describe_knowledge()))
        self.assertLess(costs[-1], costs[0])

    def test_critic_reports_signals_not_vetoes(self):
        from synod.nodes.critic import CriticNode
        from synod.protocol import Proposal
        v = view([3, 6, 12, 24, 48, 96, 192, 384])
        verdict = CriticNode(seed=0).critique(v, Proposal("other", "neural", 300.0, 0.8, 0.0, "guess"))
        self.assertTrue(verdict.evidence)
        self.assertTrue(any(":broken:" in s for s in verdict.evidence))
        # untrained: no constraint is trusted yet, so it takes no side
        self.assertIsNone(verdict.endorses)

    def test_bias_fault_and_clear(self):
        node = InducerNode(seed=0)
        v = view([1, 2, 3, 4, 5, 6, 7, 8])
        node.fault("bias")
        self.assertAlmostEqual(node.solve(v).value, 10)
        node.clear_fault()
        node._scratch.clear()
        self.assertAlmostEqual(node.solve(v).value, 9)


if __name__ == "__main__":
    unittest.main()
