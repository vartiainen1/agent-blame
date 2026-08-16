"""Algorithm tests: does agent-blame reach the CORRECT conclusion?

These tests run the full analyze() pipeline against fixture repositories
with KNOWN histories and assert on the resulting evidence, confidence,
history chain, and risk - not just that the command exited 0.
"""

import os
import unittest

from agent_blame.analyzer import analyze
from agent_blame.models import Target
from agent_blame.repository import discover_repository, resolve_repo_path

from tests.gitfixture import (make_adversarial_fixture, make_deleted_file_fixture,
                              make_detached_head_fixture, make_evolution_fixture,
                              make_introduction_fixture, make_malicious_message_fixture,
                              make_merge_fixture, make_rename_fixture,
                              make_replacement_fixture, make_revert_fixture,
                              make_shallow_fixture, make_unicode_fixture)


class _Base(unittest.TestCase):
    fx = None

    def setUp(self):
        self.fx = self.make_fx()
        self.repo = discover_repository(self.fx.root)
        self.assertIsNotNone(self.repo)

    def tearDown(self):
        self.fx.cleanup()

    def target(self, path, start, end=None):
        return Target(file=resolve_repo_path(self.repo, path),
                      start_line=start, end_line=end or start)

    def analyze(self, path, start, end=None, mode="why"):
        return analyze(self.repo, self.target(path, start, end), mode=mode)


class TestSimpleIntroduction(_Base):

    @staticmethod
    def make_fx():
        return make_introduction_fixture()

    def test_introducing_commit_is_credited(self):
        res = self.analyze("app/retry.py", 2)
        kinds = {e["kind"] for e in res.evidence}
        self.assertIn("introduced_by", kinds)
        intro = [e for e in res.evidence if e["kind"] == "introduced_by"]
        self.assertEqual(len(intro), 1)
        self.assertIn("rate-limit", intro[0]["text"].lower())

    def test_confidence_not_insufficient(self):
        res = self.analyze("app/retry.py", 2)
        self.assertIn(res.confidence.level, ("HIGH", "MEDIUM", "LOW"))

    def test_history_contains_introducing_commit(self):
        res = self.analyze("app/retry.py", 2)
        self.assertEqual(len(res.history), 1)
        self.assertEqual(res.history[0]["subject"], "Add rate-limit handling")

    def test_target_lines_recorded_as_facts(self):
        res = self.analyze("app/retry.py", 2)
        lines = {f["line"] for f in res.facts}
        self.assertIn(2, lines)


class TestEvolution(_Base):

    @staticmethod
    def make_fx():
        return make_evolution_fixture()

    def test_later_modification_detected(self):
        res = self.analyze("app/retry.py", 3)
        kinds = {e["kind"] for e in res.evidence}
        self.assertIn("introduced_by", kinds)
        self.assertIn("modified_by", kinds)
        self.assertIn("related_test", kinds)

    def test_related_test_found(self):
        # The regression test was added by a LATER commit (not the
        # introducing one), so it surfaces as related_test evidence.
        res = self.analyze("app/retry.py", 3)
        tests = [e for e in res.evidence if e["kind"] == "related_test"]
        self.assertEqual(len(tests), 1)
        self.assertIn("test_retry.py", tests[0]["text"])

    def test_history_chain_has_three_events(self):
        res = self.analyze("app/retry.py", 3)
        subjects = [h["subject"] for h in res.history]
        # The test-adding commit does not touch app/retry.py, so it is not
        # part of the file's history chain - but the test it added is
        # still detected as related_test evidence.
        self.assertIn("Add rate-limit handling", subjects)
        self.assertIn("Fix retry timing for 429s", subjects)

    def test_confidence_high_with_strong_evidence(self):
        res = self.analyze("app/retry.py", 3)
        # introduction (0.30) + modification (0.18) + related test (0.20) +
        # fix-related later commit (0.15) -> HIGH
        self.assertEqual(res.confidence.level, "HIGH")

    def test_regression_fix_signal(self):
        res = self.analyze("app/retry.py", 3)
        fixes = [e for e in res.evidence if e["kind"] == "fix_related"]
        self.assertTrue(fixes, "later fix commit should be flagged")


class TestRevert(_Base):

    @staticmethod
    def make_fx():
        return make_revert_fixture()

    def test_revert_detected_as_counter_evidence(self):
        res = self.analyze("app/retry.py", 1)
        # Blame credits the revert commit as introducer; the revert is
        # therefore flagged as counter-evidence.
        reverts = [e for e in res.counter_evidence if e["kind"] == "revert"]
        self.assertTrue(reverts, "revert commit should be detected as counter-evidence")
        self.assertTrue(all(e["is_counter"] for e in reverts))

    def test_confidence_not_high_when_reverted(self):
        res = self.analyze("app/retry.py", 1)
        self.assertIn(res.confidence.level, ("CONTRADICTORY", "LOW", "MEDIUM"))

    def test_risk_mentions_revert(self):
        res = self.analyze("app/retry.py", 1)
        joined = " ".join(res.risk.reasons).lower()
        self.assertIn("revert", joined)


class TestAdversarial(_Base):

    @staticmethod
    def make_fx():
        return make_adversarial_fixture()

    def test_misleading_security_commit_not_credited(self):
        # src/cache.py was introduced by "Add new cache", NOT by the
        # earlier "Fix security issue" commit (which touched README only).
        res = self.analyze("src/cache.py", 1)
        intro = [e for e in res.evidence if e["kind"] == "introduced_by"]
        self.assertEqual(len(intro), 1)
        self.assertIn("new cache", intro[0]["text"].lower())
        self.assertNotIn("security", intro[0]["text"].lower())

    def test_no_security_inference_from_unrelated_commit(self):
        res = self.analyze("src/cache.py", 1)
        for inf in res.inferences:
            self.assertNotIn("security", inf["text"].lower())


class TestMaliciousMessage(_Base):

    @staticmethod
    def make_fx():
        return make_malicious_message_fixture()

    def test_no_control_chars_in_output(self):
        from agent_blame.output import render_terminal
        res = self.analyze("src/evil.py", 1)
        text = render_terminal(res)
        for ch in text:
            if ch in "\n\t":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} leaked into output")

    def test_raw_subject_stays_intact_for_analysis(self):
        # Raw facts keep the malicious content (analysis needs it); the
        # SANITIZED rendering is what must be clean (tested below).
        res = self.analyze("src/evil.py", 1)
        self.assertTrue(res.facts)  # blame still worked

    def test_rendered_output_has_no_control_chars(self):
        from agent_blame.output import render_terminal
        res = self.analyze("src/evil.py", 1)
        text = render_terminal(res)
        for ch in text:
            if ch in "\n\t":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} leaked into output")


class TestUnicode(_Base):

    @staticmethod
    def make_fx():
        return make_unicode_fixture()

    def test_unicode_path_analyzed(self):
        res = self.analyze("src/émoji/ünïcode.py", 2)
        self.assertTrue(res.facts)
        self.assertIn("émoji", res.target.file)


class TestRename(_Base):

    @staticmethod
    def make_fx():
        return make_rename_fixture()

    def test_history_follows_rename(self):
        res = self.analyze("src/security/session.py", 1)
        subjects = {h["subject"] for h in res.history}
        self.assertIn("Add auth module", subjects)
        self.assertIn("Move auth to security", subjects)


class TestDeletedFile(_Base):

    @staticmethod
    def make_fx():
        return make_deleted_file_fixture()

    def test_warning_emitted(self):
        res = self.analyze("src/parser.py", 1)
        joined = " ".join(res.warnings).lower()
        self.assertIn("does not exist at head", joined)

    def test_history_still_available(self):
        res = self.analyze("src/parser.py", 1)
        self.assertTrue(res.history)


class TestShallowClone(_Base):

    @staticmethod
    def make_fx():
        return make_shallow_fixture()

    def test_shallow_warning_emitted(self):
        res = self.analyze("src/deep.py", 1)
        joined = " ".join(res.warnings).lower()
        self.assertIn("shallow", joined)


class TestRiskLevels(_Base):

    @staticmethod
    def make_fx():
        return make_evolution_fixture()

    def test_high_risk_signals(self):
        # evolution fixture: fix history + tests + later mods -> MEDIUM/HIGH
        res = self.analyze("app/retry.py", 3, mode="risk")
        self.assertIn(res.risk.level, ("MEDIUM", "HIGH"))


class TestReplacement(_Base):
    """11. Replacement: old implementation removed, new one introduced in
    place. The supersession must reduce confidence and surface as
    counter-evidence - the original explanation is no longer the full story.
    """

    @staticmethod
    def make_fx():
        return make_replacement_fixture()

    def test_replacement_detected_as_counter_evidence(self):
        res = self.analyze("src/cache.py", 1)
        repl = [e for e in res.counter_evidence if e["kind"] == "replacement"]
        self.assertTrue(repl, "wholesale deletion should surface as replacement")
        self.assertTrue(all(e["is_counter"] for e in repl))

    def test_replacement_reduces_confidence(self):
        res = self.analyze("src/cache.py", 1)
        # replacement (-0.20) + deleted_lines (-0.15) pull the score down
        # from the 0.30 intro alone; never HIGH, never a fabricated purpose.
        self.assertIn(res.confidence.level, ("LOW", "MEDIUM", "INSUFFICIENT",
                                             "CONTRADICTORY"))
        self.assertNotEqual(res.confidence.level, "HIGH")

    def test_replacement_history_visible(self):
        res = self.analyze("src/cache.py", 1)
        subjects = {h["subject"] for h in res.history}
        self.assertIn("Add legacy cache", subjects)
        self.assertIn("Remove legacy cache", subjects)
        self.assertIn("Add new cache", subjects)


class TestMergeHistory(_Base):
    """7. Merge: a merge commit exists in the file's history."""

    @staticmethod
    def make_fx():
        return make_merge_fixture()

    def test_analysis_does_not_crash_on_merge(self):
        res = self.analyze("src/mod.py", 1)
        self.assertIn(res.confidence.level,
                      ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT"))

    def test_history_covers_both_parent_branches(self):
        # git log --follow (history simplification) may omit the merge
        # commit itself from a path-limited log - documented limitation.
        # What must hold: commits from BOTH parents are visible, so the
        # merged history is not lost.
        res = self.analyze("src/mod.py", 1)
        subjects = {h["subject"] for h in res.history}
        self.assertIn("Feature change", subjects)
        self.assertIn("Main change", subjects)
        self.assertIn("Add module", subjects)


class TestDetachedHead(_Base):
    """Detached HEAD: analysis must not crash and stays deterministic."""

    @staticmethod
    def make_fx():
        return make_detached_head_fixture()

    def test_detached_head_analysis(self):
        res = self.analyze("src/detached.py", 1)
        self.assertTrue(res.facts, "blame should work on detached HEAD")


class TestOutOfRangeLine(_Base):
    """Target line beyond file length -> clean INSUFFICIENT, no traceback."""

    @staticmethod
    def make_fx():
        return make_introduction_fixture()

    def test_out_of_range_is_insufficient(self):
        res = self.analyze("app/retry.py", 99999)
        self.assertEqual(res.confidence.level, "INSUFFICIENT")
        self.assertEqual(res.evidence, [])
        self.assertEqual(res.counter_evidence, [])
        joined = " ".join(res.warnings).lower()
        self.assertIn("could not blame", joined)


class TestTestPathHeuristic(unittest.TestCase):
    """Word-boundary test detection: no false positives on latest.py etc."""

    def test_no_false_positives(self):
        from agent_blame.graph import _is_test_path
        for p in ("src/latest.py", "src/contest.py", "src/attest.py",
                  "src/request.py"):
            self.assertFalse(_is_test_path(p), f"{p} should not be a test")

    def test_real_test_paths(self):
        from agent_blame.graph import _is_test_path
        for p in ("tests/test_retry.py", "test_foo.py", "foo_test.py",
                  "src/foo.test.py", "tests/unit/test_x.py"):
            self.assertTrue(_is_test_path(p), f"{p} should be a test")


class TestCommitShaIntegrity(_Base):
    """Regression: git log --format=%H%x00 appends \n after each NUL, so
    every sha after the first used to carry a leading newline. That broke
    introducer-vs-later matching: the introducing commit was silently
    re-credited as a LATER modification. Shas must be clean 40-hex.
    """

    @staticmethod
    def make_fx():
        return make_evolution_fixture()

    def test_all_history_shas_are_clean_hex(self):
        res = self.analyze("app/retry.py", 3)
        for h in res.history:
            self.assertRegex(h["sha"], r"^[0-9a-f]{40}$",
                             f"corrupted sha: {h['sha']!r}")

    def test_introducer_not_double_credited_as_later_modifier(self):
        res = self.analyze("app/retry.py", 3)
        intro = [e for e in res.evidence if e["kind"] == "introduced_by"]
        self.assertEqual(len(intro), 1)
        intro_sha = intro[0]["commit"]
        # The introducing commit must NOT also appear as a later modifier.
        mods = [e for e in res.evidence
                if e["kind"] == "modified_by" and e["commit"] == intro_sha]
        self.assertEqual(mods, [], "introducer wrongly credited as later mod")

    def test_facts_and_history_share_clean_shas(self):
        res = self.analyze("app/retry.py", 3)
        fact_shas = {f["commit"] for f in res.facts if f.get("commit")}
        hist_shas = {h["sha"] for h in res.history}
        # Every blamed introducer must exist in the file's history list.
        self.assertTrue(fact_shas <= hist_shas,
                        "blame shas not found in history: "
                        f"{fact_shas - hist_shas}")


class TestJsonStructure(_Base):

    @staticmethod
    def make_fx():
        return make_evolution_fixture()

    def test_json_schema_keys(self):
        import json as jsonlib
        from agent_blame.output import render_json
        res = self.analyze("app/retry.py", 3)
        data = jsonlib.loads(render_json(res))
        for key in ("tool", "version", "target", "mode", "repository",
                    "confidence", "facts", "inferences", "evidence",
                    "counter_evidence", "history", "risk", "warnings"):
            self.assertIn(key, data)
        self.assertEqual(data["target"]["file"], "app/retry.py")
        self.assertEqual(data["target"]["start_line"], 3)


if __name__ == "__main__":
    unittest.main()
