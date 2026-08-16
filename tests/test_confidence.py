"""Regression tests for confidence scoring (review fixes).

Covers the rules that were corrected during the code review:
  - counter-evidence must ALWAYS reduce the score (not be hidden by a
    large pile of supporting items)
  - any revert in history caps the level at MEDIUM
  - a direct revert of the introducer is CONTRADICTORY
  - net-negative evidence (replacement) is CONTRADICTORY
  - no evidence -> INSUFFICIENT (never fabricated)
"""

import unittest

from agent_blame.confidence import compute_confidence
from agent_blame.models import EvidenceItem


def ev(kind, weight, commit=None, counter=False):
    return EvidenceItem(kind=kind, commit=commit, weight=weight,
                        is_counter=counter)


def support():
    """A healthy pile of supporting evidence (score would be HIGH)."""
    return [
        ev("introduced_by", 0.30, commit="A"),
        ev("same_commit_test", 0.20, commit="A"),
        ev("modified_by", 0.18, commit="B"),
        ev("fix_related", 0.15, commit="B"),
    ]


class TestCounterEvidenceAlwaysReduces(unittest.TestCase):

    def test_counter_lowers_score(self):
        base = compute_confidence(support())
        self.assertEqual(base.level, "HIGH")
        reduced = compute_confidence([*support(),
                                      ev("deleted_lines", -0.15, counter=True)])
        self.assertLess(reduced.score, base.score)
        # 0.83 support capped at 1.0 would hide -0.15; the fix subtracts
        # from the cap, so the score must be strictly lower.
        self.assertAlmostEqual(reduced.score, 0.68, places=2)

    def test_lots_of_support_cannot_hide_counter(self):
        big = [
            *support(),
            ev("modified_by", 0.18, commit="C"),
            ev("fix_related", 0.15, commit="C"),
            ev("modified_by", 0.18, commit="D"),
            ev("fix_related", 0.15, commit="D"),
        ]
        with_counter = compute_confidence([*big,
                                           ev("deleted_lines", -0.15, counter=True)])
        self.assertLess(with_counter.score, 1.0,
                        "counter-evidence must remain visible even with "
                        "support >> 1.0")


class TestRevertCapsAtMedium(unittest.TestCase):

    def test_revert_in_history_never_high(self):
        items = [*support(), ev("revert", -0.25, commit="E", counter=True)]
        c = compute_confidence(items)
        self.assertEqual(c.level, "MEDIUM")
        self.assertNotEqual(c.level, "HIGH")

    def test_revert_of_introducer_is_contradictory(self):
        items = [*support(), ev("revert", -0.25, commit="A", counter=True)]
        c = compute_confidence(items)
        self.assertEqual(c.level, "CONTRADICTORY")


class TestNetNegative(unittest.TestCase):

    def test_replacement_dominates_is_contradictory(self):
        items = [
            ev("introduced_by", 0.30, commit="A"),
            ev("replacement", -0.20, commit="B", counter=True),
            ev("deleted_lines", -0.15, counter=True),
            ev("revert", -0.25, commit="C", counter=True),
        ]
        c = compute_confidence(items)
        self.assertEqual(c.level, "CONTRADICTORY")


class TestInsufficient(unittest.TestCase):

    def test_no_evidence_is_insufficient(self):
        c = compute_confidence([])
        self.assertEqual(c.level, "INSUFFICIENT")
        self.assertEqual(c.score, 0.0)

    def test_weak_evidence_is_insufficient(self):
        c = compute_confidence([ev("temporal", 0.03)])
        self.assertEqual(c.level, "INSUFFICIENT")


class TestDeterminism(unittest.TestCase):

    def test_same_evidence_same_result(self):
        items = [*support(), ev("deleted_lines", -0.15, counter=True)]
        a = compute_confidence(items)
        b = compute_confidence(list(reversed(items)))
        self.assertEqual(a.level, b.level)
        self.assertAlmostEqual(a.score, b.score, places=6)


if __name__ == "__main__":
    unittest.main()
