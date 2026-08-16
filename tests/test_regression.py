"""Phase 2E: regression detection tests.

The central guarantee (spec 2E): the tool must identify useful historical
correction patterns WITHOUT turning ordinary sequential code changes into
fabricated regressions. CORRELATION IS NOT PROOF OF CAUSATION - the
wording contract is tested here too (never \"caused the bug\").

The six mandatory property tests (spec 2E/22) are at the top; the rest
cover the spec's fixture list with structured assertions (classification +
evidence + language), not just exit codes.
"""

from __future__ import annotations

import json as jsonlib
import unittest

from agent_blame.analyzer import analyze
from agent_blame.models import Target
from agent_blame.output import render_json
from agent_blame.repository import discover_repository

from tests.gitfixture import (make_regression_chronology_fixture,
                              make_regression_commit_after_revert_fixture,
                              make_regression_commit_revert_fixture,
                              make_regression_corrective_fixture,
                              make_regression_deterministic_fixture,
                              make_regression_diff_fixture,
                              make_regression_fix_sequence_fixture,
                              make_regression_malicious_fixture,
                              make_regression_moved_then_fixed_fixture,
                              make_regression_multiple_fixes_fixture,
                              make_regression_no_false_positive_fixture,
                              make_regression_revert_sequence_fixture,
                              make_regression_same_symbol_refactor_fixture,
                              make_regression_shallow_fixture,
                              make_regression_trivial_revert_fixture,
                              make_regression_unicode_fixture)


def _analyze(fx, path, line, revision="HEAD"):
    repo = discover_repository(fx.root)
    return analyze(repo, Target(file=path, start_line=line, end_line=line),
                   revision=revision)


def _types(res):
    return [r["type"] for r in res.regressions]


class _Base(unittest.TestCase):
    """Shared lifecycle: build the fixture once, analyze with a helper."""

    fx = None

    def setUp(self):
        self.fx = self.make_fx()

    def tearDown(self):
        if self.fx is not None:
            self.fx.cleanup()
            self.fx = None

    def analyze(self, path, line, revision="HEAD"):
        return _analyze(self.fx, path, line, revision=revision)


# ---------------------------------------------------------------------------
# Mandatory property tests (spec 2E/22)
# ---------------------------------------------------------------------------

class TestProperty1_NoFalseRegression(unittest.TestCase):
    """A -> B with no corrective/revert evidence must NOT become a
    regression."""

    def make_fx(self):
        return make_regression_same_symbol_refactor_fixture()

    def test_no_regression_finding(self):
        fx = self.make_fx()
        try:
            res = _analyze(fx, "app/foo.py", 2)
            self.assertEqual(res.regressions, [],
                             "A plain modification must not become a regression")
        finally:
            fx.cleanup()


class TestProperty2_ExplicitRevertDetected(unittest.TestCase):
    """A -> B -> explicit revert of B must detect EXPLICIT_REVERT."""

    def make_fx(self):
        return make_regression_revert_sequence_fixture()

    def test_explicit_revert_detected(self):
        fx = self.make_fx()
        try:
            # D's line (sleep(delay)) - later commits include the revert C.
            res = _analyze(fx, "app/retry.py", 4)
            self.assertIn("EXPLICIT_REVERT", _types(res))
            revert = next(r for r in res.regressions
                          if r["type"] == "EXPLICIT_REVERT")
            self.assertEqual(revert["reverted_commit"], fx.shas["B"])
            self.assertIn("explicitly reverts", revert["explanation"])
        finally:
            fx.cleanup()


class TestProperty3_MovementPreservesIdentity(unittest.TestCase):
    """A -> move -> B -> fix must preserve logical symbol identity: the
    finding names the ORIGINAL introducer A, not the mover."""

    def make_fx(self):
        return make_regression_moved_then_fixed_fixture()

    def test_fix_after_move_keeps_origin(self):
        fx = self.make_fx()
        try:
            # Line 1 (the def line) is blamed to A through the rename; C
            # (the fix) is a later commit on the moved path.
            res = _analyze(fx, "new.py", 1)
            self.assertTrue(res.regressions,
                            "the fix sequence must still be detected after the move")
            # No regression finding may name the MOVE commit as origin.
            for r in res.regressions:
                self.assertNotEqual(r.get("original_commit"), fx.shas["B"])
        finally:
            fx.cleanup()


class TestProperty4_UnrelatedSymbolNoRegression(unittest.TestCase):
    """A modifies foo(), B modifies unrelated bar() must NOT become a
    foo() regression."""

    def make_fx(self):
        fx = self.__class__._mk()
        return fx

    @staticmethod
    def _mk():
        from tests.gitfixture import GitFixture
        f = GitFixture()
        a = f.commit("Add foo and bar", {
            "app/mod.py": "def foo():\n    return 1\n\ndef bar():\n    return 2\n",
        })
        b = f.commit("Fix bar", {
            "app/mod.py": "def foo():\n    return 1\n\ndef bar():\n    return 3\n",
        })
        f.shas = {"A": a, "B": b}
        return f

    def test_foo_not_flagged(self):
        fx = self.make_fx()
        try:
            # foo's line (line 2) was not touched by B; B fixed bar only.
            res = _analyze(fx, "app/mod.py", 2)
            self.assertEqual(res.regressions, [],
                             "a fix to an unrelated symbol must not flag foo")
        finally:
            fx.cleanup()


class TestProperty5_DocOnlyNoRegression(unittest.TestCase):
    """A changes implementation, B only changes documentation - must NOT
    become a code regression."""

    def make_fx(self):
        fx = self.__class__._mk()
        return fx

    @staticmethod
    def _mk():
        from tests.gitfixture import GitFixture
        f = GitFixture()
        a = f.commit("Add retry logic", {
            "app/retry.py": "def retry(fn):\n    return fn()\n",
        })
        b = f.commit("Fix documentation typo", {
            "README.md": "# fixed docs\n",
        })
        f.shas = {"A": a, "B": b}
        return f

    def test_doc_only_not_flagged(self):
        fx = self.make_fx()
        try:
            res = _analyze(fx, "app/retry.py", 2)
            self.assertEqual(res.regressions, [],
                             "a documentation-only commit must not become a "
                             "code regression")
        finally:
            fx.cleanup()


class TestProperty6_FixWordAloneNoRegression(unittest.TestCase):
    """The word \"fix\" alone must NOT establish a regression."""

    def make_fx(self):
        return make_regression_no_false_positive_fixture()

    def test_fix_word_without_overlap(self):
        fx = self.make_fx()
        try:
            # B says "Fix naming..." but changes nothing observable (no
            # removal, no tests); C reverts an UNRELATED file. Neither may
            # produce a finding for app/retry.py.
            res = _analyze(fx, "app/retry.py", 3)
            self.assertEqual(res.regressions, [])
        finally:
            fx.cleanup()


# ---------------------------------------------------------------------------
# Classification ladder
# ---------------------------------------------------------------------------

class TestExplicitRevert(_Base):
    """EXPLICIT_REVERT: structured trailer pointing at a file-related
    commit - HIGH when it is the introducer, MEDIUM for file-level."""

    def make_fx(self):
        return make_regression_revert_sequence_fixture()

    def test_explicit_revert_classified(self):
        res = self.analyze("app/retry.py", 4)
        revert = next(r for r in res.regressions
                      if r["type"] == "EXPLICIT_REVERT")
        self.assertEqual(revert["confidence"], "MEDIUM")  # B is not D's introducer
        self.assertEqual(revert["relationship"], "FILE_OVERLAP")
        self.assertEqual(revert["reverted_commit"], self.fx.shas["B"])
        self.assertEqual(revert["fix_commit"], self.fx.shas["C"])
        self.assertIn("explicitly reverts", revert["explanation"])
        self.assertNotIn("caused", revert["explanation"].lower())
        self.assertNotIn("bug", revert["explanation"].lower())

    def test_revert_evidence_replaces_weak_item(self):
        res = self.analyze("app/retry.py", 4)
        kinds = [e["kind"] for e in res.evidence + res.counter_evidence]
        # C's revert must appear ONCE, as the structured kind - never
        # double-counted as both "revert" and "explicit_revert".
        self.assertNotIn("revert", kinds)
        self.assertIn("explicit_revert", kinds)

    def test_revert_flowed_into_confidence_and_risk(self):
        res = self.analyze("app/retry.py", 4)
        joined_risk = " ".join(res.risk.reasons).lower()
        self.assertIn("revert", joined_risk)


class TestLikelyRegressionFix(_Base):
    """LIKELY_REGRESSION_FIX: fix language + (introducer reference OR
    corrective shape AND tests)."""

    def make_fx(self):
        return make_regression_fix_sequence_fixture()

    def test_likely_classified(self):
        # Line 2 (the def line) is unchanged across A/B - it stays blamed
        # to A, so B appears in the later history as the fix candidate.
        res = self.analyze("app/retry.py", 2)
        self.assertTrue(res.regressions)
        best = res.regressions[0]
        self.assertEqual(best["type"], "LIKELY_REGRESSION_FIX")
        self.assertEqual(best["confidence"], "MEDIUM")
        self.assertEqual(best["fix_commit"], self.fx.shas["B"])
        self.assertEqual(best["original_commit"], self.fx.shas["A"])
        self.assertIn("corrected", best["explanation"])
        self.assertNotIn("caused", best["explanation"].lower())

    def test_evidence_emitted(self):
        res = self.analyze("app/retry.py", 2)
        kinds = [e["kind"] for e in res.evidence]
        self.assertIn("regression_fix", kinds)


class TestPossibleRegressionFix(_Base):
    """POSSIBLE_REGRESSION_FIX: fix language + one weak signal."""

    def make_fx(self):
        return make_regression_multiple_fixes_fixture()

    def test_possible_classified(self):
        # Line 2 (the def line) is blamed to A; B and C are both later.
        # C (fix + tests + symbol overlap) -> LIKELY; B (fix + overlap,
        # no tests) -> POSSIBLE.
        res = self.analyze("app/retry.py", 2)
        types = _types(res)
        self.assertIn("POSSIBLE_REGRESSION_FIX", types)
        self.assertIn("LIKELY_REGRESSION_FIX", types)
        # Deterministic ordering: strongest type first.
        self.assertEqual(res.regressions[0]["type"], "LIKELY_REGRESSION_FIX")

    def test_low_confidence(self):
        res = self.analyze("app/retry.py", 2)
        poss = [r for r in res.regressions
                if r["type"] == "POSSIBLE_REGRESSION_FIX"]
        self.assertTrue(poss)
        self.assertEqual(poss[0]["confidence"], "LOW")
        self.assertIn("possible", poss[0]["explanation"].lower())


class TestCorrectiveChange(_Base):
    """CORRECTIVE_CHANGE: \"Revert ...\" subject without a trailer."""

    def make_fx(self):
        return make_regression_corrective_fixture()

    def test_corrective_change_classified(self):
        # Line 3 (sleep(delay)) is blamed to C; B ("Revert retry changes",
        # no trailer) is a later commit -> CORRECTIVE_CHANGE.
        res = self.analyze("app/retry.py", 3)
        self.assertIn("CORRECTIVE_CHANGE", _types(res))
        cc = next(r for r in res.regressions
                  if r["type"] == "CORRECTIVE_CHANGE")
        self.assertEqual(cc["confidence"], "LOW")
        self.assertIn("no structured revert reference", cc["explanation"])


class TestRevertOfUnrelatedFile(_Base):
    """A revert of an unrelated file must produce nothing for the target."""

    def make_fx(self):
        return make_regression_no_false_positive_fixture()

    def test_unrelated_revert_ignored(self):
        res = self.analyze("app/retry.py", 3)
        self.assertEqual(res.regressions, [])


class TestSameSymbolRefactorNotRegression(_Base):
    """Spec 2E/14: same symbol changed again by an unrelated refactor is
    counter-evidence territory, never a constructed regression."""

    def make_fx(self):
        return make_regression_same_symbol_refactor_fixture()

    def test_refactor_not_flagged(self):
        res = self.analyze("app/foo.py", 2)
        self.assertEqual(res.regressions, [])


# ---------------------------------------------------------------------------
# Integration + edge cases
# ---------------------------------------------------------------------------

class TestCommitSelfRevert(_Base):
    """--commit: analyzing a revert commit classifies EXPLICIT_REVERT."""

    def make_fx(self):
        return make_regression_commit_revert_fixture()

    def test_self_revert_classified(self):
        from agent_blame.commit import analyze_commit
        repo = discover_repository(self.fx.root)
        res = analyze_commit(repo, self.fx.shas["C"])
        self.assertEqual(res.commit["revert_of"], self.fx.shas["B"])
        self.assertTrue(res.changes)
        c = res.changes[0]
        self.assertTrue(c.regressions, "the revert change must carry the finding")
        r = c.regressions[0]
        self.assertEqual(r["type"], "EXPLICIT_REVERT")
        self.assertEqual(r["confidence"], "HIGH")
        self.assertEqual(r["relationship"], "DIRECT_RANGE_OVERLAP")
        self.assertEqual(r["reverted_commit"], self.fx.shas["B"])
        self.assertIn("explicitly reverts", r["explanation"])


class TestCommitAfterRevert(_Base):
    """--commit: the after-scan classifies a later revert of the analyzed
    commit as EXPLICIT_REVERT."""

    def make_fx(self):
        return make_regression_commit_after_revert_fixture()

    def test_after_scan_classified(self):
        from agent_blame.commit import analyze_commit
        repo = discover_repository(self.fx.root)
        res = analyze_commit(repo, self.fx.shas["C"])
        c = next(ch for ch in res.changes if ch.path == "app/retry.py")
        after = c.after.get("regressions", [])
        self.assertTrue(after, "D reverts C - the after-scan must say so")
        self.assertEqual(after[0]["type"], "EXPLICIT_REVERT")
        self.assertEqual(after[0]["reverted_commit"], self.fx.shas["C"])
        self.assertEqual(after[0]["confidence"], "HIGH")


class TestDiffIntegration(_Base):
    """--diff: the changed line's history contains a fix+revert sequence;
    the diff analysis must surface the regression finding."""

    def make_fx(self):
        return make_regression_diff_fixture()

    def test_diff_surfaces_regression(self):
        from agent_blame.diff import analyze_diff
        repo = discover_repository(self.fx.root)
        res = analyze_diff(repo)
        self.assertTrue(res.files)
        g = res.files[0].groups[0]
        regressions = g.analysis.get("regressions", [])
        self.assertTrue(regressions,
                        "diff analysis must surface the historical regression")
        self.assertIn("LIKELY_REGRESSION_FIX",
                      [r["type"] for r in regressions])


class TestMovementAssisted(_Base):
    """Property 3 detail: the fix finding after a move names the ORIGINAL
    introducer, and never the move commit."""

    def make_fx(self):
        return make_regression_moved_then_fixed_fixture()

    def test_origin_not_the_move(self):
        res = self.analyze("new.py", 1)
        self.assertTrue(res.regressions)
        for r in res.regressions:
            self.assertNotEqual(r.get("original_commit"), self.fx.shas["B"])
            self.assertNotEqual(r.get("fix_commit"), self.fx.shas["B"])


class TestUnicodePath(_Base):
    """18. Unicode paths must work through the whole pipeline."""

    def make_fx(self):
        return make_regression_unicode_fixture()

    def test_unicode_path_regression(self):
        res = self.analyze("src/ünïcode/retry.py", 2)
        self.assertTrue(res.regressions)
        self.assertIn("LIKELY_REGRESSION_FIX", _types(res))


class TestMaliciousMessage(_Base):
    """19. Malicious commit message with fix words + ANSI escapes: must
    not crash, must not be misclassified by the escape junk, and terminal
    output must stay sanitized."""

    def make_fx(self):
        return make_regression_malicious_fixture()

    def test_no_crash_and_no_false_regression(self):
        res = self.analyze("app/retry.py", 3)
        # The evil message contains "fix" but no overlap signals (no
        # removal, no tests): it must NOT establish a regression.
        self.assertEqual(res.regressions, [])
        from agent_blame.output import render_terminal
        out = render_terminal(res)
        self.assertNotIn("\x1b[", out)


class TestChronologyOldRevert(_Base):
    """Phase 3 bug (requests/models.py): an OLD revert that predates the
    line's introducing commit must NOT be cited against the current code.

    Before the fix, `later` held every file commit except introducers, so
    a 2019 revert was reported as EXPLICIT_REVERT of a 2026 introducer and
    several such items zeroed confidence to CONTRADICTORY on healthy
    long-lived code. The fix: `later` is strictly newer than the newest
    introducing commit.
    """

    def make_fx(self):
        return make_regression_chronology_fixture()

    def test_pre_introducer_revert_not_a_regression(self):
        res = self.analyze("app/retry.py", 3)
        self.assertEqual(res.regressions, [],
                         "pre-introducer revert must not become a regression")
        kinds = {e["kind"] for e in res.evidence}
        self.assertNotIn("explicit_revert", kinds)
        self.assertNotEqual(res.confidence.level, "CONTRADICTORY",
                            "old reverts must not zero confidence")

    def test_introducer_is_the_rewrite_not_the_old_revert(self):
        res = self.analyze("app/retry.py", 3)
        intro = next(e for e in res.evidence if e["kind"] == "introduced_by")
        self.assertEqual(intro["commit"], self.fx.shas["C"])


class TestTrivialRevertSubject(_Base):
    """Phase 3 noise gate: a "revert copyright year" 1/1 docstring edit
    (no symbol overlap, no net removal) must NOT produce CORRECTIVE_CHANGE
    - the flask/__init__.py reproduction (2018 copyright revert cited
    against dispatch_request/version line)."""

    def make_fx(self):
        return make_regression_trivial_revert_fixture()

    def test_trivial_revert_not_flagged(self):
        # Target the retry symbol (line 3 = sleep) - B's revert subject
        # touched only the docstring line, not the symbol.
        res = self.analyze("app/retry.py", 4)
        self.assertEqual(res.regressions, [],
                         "trivial 1/1 revert-subject edit must not be "
                         "correction evidence")

    def test_symbol_resolved_check(self):
        # The target resolves to the retry symbol; verify the finding is
        # absent regardless of which symbol-anchored line we choose.
        res = self.analyze("app/retry.py", 5)
        self.assertEqual(res.regressions, [])


class TestShallowHistory(_Base):
    """16. Shallow: regression detection must not invent findings from
    missing history."""

    def make_fx(self):
        return make_regression_shallow_fixture()

    def test_shallow_no_fabrication(self):
        res = self.analyze("app/retry.py", 3)
        self.assertEqual(res.regressions, [])
        joined = " ".join(res.warnings).lower()
        self.assertIn("shallow", joined)


class TestJsonSchema(_Base):
    """JSON: regressions is a structured, additive field."""

    def make_fx(self):
        return make_regression_revert_sequence_fixture()

    def test_json_regressions(self):
        res = self.analyze("app/retry.py", 4)
        data = jsonlib.loads(render_json(res))
        self.assertIn("regressions", data)
        self.assertTrue(data["regressions"])
        r = data["regressions"][0]
        for key in ("type", "confidence", "relationship", "original_commit",
                    "fix_commit", "reverted_commit", "target_path",
                    "target_symbol", "signals", "explanation"):
            self.assertIn(key, r)
        # JSON must be free of terminal control characters.
        raw = render_json(res)
        self.assertNotIn("\x1b", raw)


class TestDeterministic(_Base):
    """28. Deterministic repeated execution."""

    def make_fx(self):
        return make_regression_deterministic_fixture()

    def test_deterministic(self):
        res1 = self.analyze("app/retry.py", 4)
        res2 = self.analyze("app/retry.py", 4)
        self.assertEqual(render_json(res1), render_json(res2))
        self.assertEqual(res1.regressions, res2.regressions)


if __name__ == "__main__":
    unittest.main()
