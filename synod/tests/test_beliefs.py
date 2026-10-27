import unittest

import numpy as np

from synod.beliefs import ClaimCalibrator, Competence, DriftMonitor, claim_bin
from synod.objective import Objective


class CompetenceTest(unittest.TestCase):
    def test_unseen_key_returns_prior(self):
        c = Competence(prior_mean=0.3)
        self.assertAlmostEqual(c.mean(("a", "b")), 0.3)

    def test_children_inherit_then_specialise(self):
        c = Competence(prior_mean=0.5, strength=4, decay=1.0)
        for _ in range(40):
            c.update(("x", "seen"), 1.0)
        # A sibling we never saw borrows the parent's (high) success rate...
        self.assertGreater(c.mean(("x", "unseen")), 0.8)
        # ...but specialises once it has its own evidence.
        for _ in range(40):
            c.update(("x", "unseen"), 0.0)
        self.assertLess(c.mean(("x", "unseen")), 0.2)
        self.assertGreater(c.mean(("x", "seen")), 0.8)

    def test_humble_keeps_mean_drops_certainty(self):
        c = Competence(decay=1.0)
        for _ in range(50):
            c.update(("k",), 1.0)
        before = c.mean(("k",))
        c.humble(0.1)
        self.assertLess(c.count(("k",)), 6)
        self.assertGreater(c.mean(("k",)), 0.5)
        self.assertLess(c.mean(("k",)), before)


class ClaimCalibratorTest(unittest.TestCase):
    def test_face_value_without_evidence(self):
        self.assertAlmostEqual(ClaimCalibrator().adjust("peer", 0.9), 0.9)

    def test_confident_failures_are_discounted_fast(self):
        cal = ClaimCalibrator()
        for _ in range(5):
            cal.update("liar", 0.97, correct=False)
        self.assertLess(cal.adjust("liar", 0.97), 0.5)
        self.assertLess(cal.trust("liar"), 0.4)
        self.assertAlmostEqual(cal.adjust("someone-else", 0.97), 0.97)

    def test_calibrated_peer_keeps_trust(self):
        cal, rng = ClaimCalibrator(), np.random.default_rng(0)
        for _ in range(300):
            cal.update("honest", 0.7, correct=bool(rng.random() < 0.7))
        self.assertGreater(cal.trust("honest"), 0.8)

    def test_bins(self):
        self.assertEqual(claim_bin(0.0), 0)
        self.assertEqual(claim_bin(0.999), claim_bin(1.0))


class DriftMonitorTest(unittest.TestCase):
    def test_broken_node_alarms_quickly(self):
        d = DriftMonitor()
        fired = [d.update(0.95, correct=False) for _ in range(5)]
        self.assertTrue(any(fired))
        self.assertLessEqual(fired.index(True), 4)

    def test_calibrated_node_rarely_alarms(self):
        d, rng = DriftMonitor(), np.random.default_rng(1)
        alarms = sum(d.update(0.9, correct=bool(rng.random() < 0.9)) for _ in range(500))
        self.assertLessEqual(alarms, 2)


class ObjectiveTest(unittest.TestCase):
    def test_threshold_rises_under_pressure(self):
        o = Objective()
        self.assertAlmostEqual(o.deliver_threshold(0.0), 0.5)
        self.assertGreater(o.deliver_threshold(1.0), 0.6)
        self.assertEqual(o.decision_value(0.3), 0.0)  # abstaining beats a likely miss


if __name__ == "__main__":
    unittest.main()
