"""Phase 2B tests: --commit mode analyzes a specific commit.

These tests assert on the STRUCTURE and CHRONOLOGY of the commit analysis
- which commit is credited with introducing the PREVIOUS behavior, that
the analyzed commit itself never appears as its own origin, revert
relationships, root/merge/deleted/renamed/binary handling, and JSON
schema - not just that the command exited 0.

Fixture histories are tiny and KNOWN (see gitfixture.py), and record the
exact shas in `fx.shas`, so the expected conclusions are exact.
"""

import json as jsonlib
import unittest

from agent_blame.commit import analyze_commit
from agent_blame.output import render_commit_terminal, render_json
from agent_blame.repository import discover_repository

from tests.gitfixture import (GitFixture, make_commit_add_fixture,
                              make_commit_binary_fixture,
                              make_commit_delete_fixture,
                              make_commit_evolution_fixture,
                              make_commit_malicious_fixture,
                              make_commit_multi_fixture,
                              make_commit_rename_fixture,
                              make_commit_reverted_later_fixture,
                              make_commit_revert_fixture,
                              make_commit_root_fixture,
                              make_commit_unicode_fixture, make_merge_fixture,
                              make_shallow_fixture)


class _Base(unittest.TestCase):
    fx = None

    def setUp(self):
        self.fx = self.make_fx()
        self.repo = discover_repository(self.fx.root)
        self.assertIsNotNone(self.repo)

    def tearDown(self):
        self.fx.cleanup()

    def analyze(self, rev):
        return analyze_commit(self.repo, rev)

    def change_for(self, res, path):
        """The CommitChange entry for a changed file path."""
        for c in res.changes:
            if c.path == path:
                return c
        self.fail(f"file {path} not in commit result: "
                  f"{[c.path for c in res.changes]}")

    def blame_facts(self, group):
        return [f for f in group.analysis["facts"] if f["kind"] == "blame"]

    def blame_commits(self, group):
        return {f.get("commit") for f in self.blame_facts(group)}


class TestSimpleCommit(_Base):
    """2/3. A normal commit modifying code with a known introducer."""

    @staticmethod
    def make_fx():
        return make_commit_evolution_fixture()

    def test_commit_metadata(self):
        res = self.analyze(self.fx.shas["B"])
        self.assertEqual(res.commit["sha"], self.fx.shas["B"])
        self.assertEqual(res.commit["subject"], "Fix retry timing for 429s")
        self.assertEqual(res.commit["parents"], [self.fx.shas["A"]])
        self.assertEqual(res.parent, self.fx.shas["A"])
        self.assertFalse(res.commit["is_merge"])
        self.assertFalse(res.commit["is_root"])

    def test_introducer_of_previous_behavior_is_A_not_B(self):
        # Chronology (spec section 6/21): B changes line 3; blaming against
        # B's parent must credit A ("Add rate-limit handling"), never B.
        res = self.analyze(self.fx.shas["B"])
        g = self.change_for(res, "src/retry.py").groups[0]
        commits = self.blame_commits(g)
        self.assertIn(self.fx.shas["A"], commits)
        self.assertNotIn(self.fx.shas["B"], commits,
                         "the analyzed commit must not be credited as the "
                         "origin of the behavior it changes")
        text = " ".join(f["text"] for f in self.blame_facts(g))
        self.assertIn("Add rate-limit handling", text)

    def test_history_chain_stops_before_target(self):
        res = self.analyze(self.fx.shas["B"])
        g = self.change_for(res, "src/retry.py").groups[0]
        subjects = [h["subject"] for h in g.analysis["history"]]
        self.assertIn("Add rate-limit handling", subjects)
        self.assertNotIn("Fix retry timing for 429s", subjects,
                         "the analyzed commit must not appear in the "
                         "before-state history chain")

    def test_changed_lines_present(self):
        res = self.analyze(self.fx.shas["B"])
        g = self.change_for(res, "src/retry.py").groups[0]
        self.assertTrue(g.changes)
        types = {c["type"] for c in g.changes}
        self.assertIn("mod", types)


class TestAfterScan(_Base):
    """7. Later commits surface as after-state evidence, chronologically
    separate from the before-state analysis. Analyzes B in a history where
    C (a fix) and D (a revert) both touch the same file afterwards."""

    @staticmethod
    def make_fx():
        return make_commit_reverted_later_fixture()

    def test_later_commits_listed_in_after(self):
        res = self.analyze(self.fx.shas["B"])
        c = self.change_for(res, "app/retry.py")
        self.assertTrue(c.after)
        subjects = [lc["subject"] for lc in c.after["later_commits"]]
        self.assertIn("Fix timeout to 10", subjects)
        self.assertTrue(any("evert" in s for s in subjects))
        self.assertEqual(c.after["count"], 2)
        self.assertEqual(c.after["reverts"], 1)
        self.assertEqual(c.after["fixes"], 1)

    def test_after_never_mixed_into_before_evidence(self):
        res = self.analyze(self.fx.shas["B"])
        c = self.change_for(res, "app/retry.py")
        g = c.groups[0]
        evidence_shas = {e.get("commit") for e in g.analysis["evidence"]}
        history_shas = {h["sha"] for h in g.analysis["history"]}
        after_shas = {lc["sha"] for lc in c.after["later_commits"]}
        self.assertTrue(after_shas)
        for sha in evidence_shas | history_shas:
            self.assertNotIn(sha, after_shas,
                             "after-state commits must not leak into the "
                             "before-state analysis")


class TestAddedFile(_Base):
    """4. Commit adding a new file: NEW FILE, no fabricated history."""

    @staticmethod
    def make_fx():
        return make_commit_add_fixture()

    def test_new_file_reported_honestly(self):
        res = self.analyze(self.fx.shas["B"])
        c = self.change_for(res, "tests/test_mod.py")
        self.assertEqual(c.status, "A")
        g = c.groups[0]
        self.assertTrue(g.new_file)
        self.assertEqual(g.analysis["confidence"]["level"], "INSUFFICIENT")
        self.assertFalse(self.blame_facts(g),
                         "a new file has no previous lines to blame")


class TestDeletedFile(_Base):
    """5. Commit deleting a file: analyzed against the baseline revision."""

    @staticmethod
    def make_fx():
        return make_commit_delete_fixture()

    def test_deletion_analyzed_against_baseline(self):
        res = self.analyze(self.fx.shas["B"])
        c = self.change_for(res, "src/parser.py")
        self.assertEqual(c.status, "D")
        g = c.groups[0]
        self.assertTrue(self.blame_facts(g))
        text = " ".join(f["text"] for f in self.blame_facts(g))
        self.assertIn("Add parser", text)


class TestRenameCommit(_Base):
    """6. Rename commit: history follows the pre-rename path."""

    @staticmethod
    def make_fx():
        return make_commit_rename_fixture()

    def test_rename_reported_with_old_path(self):
        res = self.analyze(self.fx.shas["C"])
        c = self.change_for(res, "src/security/session.py")
        self.assertEqual(c.status, "R")
        self.assertEqual(c.old_path, "src/auth.py")

    def test_history_follows_old_path(self):
        res = self.analyze(self.fx.shas["C"])
        g = self.change_for(res, "src/security/session.py").groups[0]
        subjects = [h["subject"] for h in g.analysis["history"]]
        self.assertIn("Add auth module", subjects)
        self.assertIn("Fix auth bug", subjects)


class TestRootCommit(_Base):
    """14. Root commit: no parent, reported without a baseline."""

    @staticmethod
    def make_fx():
        return make_commit_root_fixture()

    def test_root_detected(self):
        res = self.analyze(self.fx.shas["A"])
        self.assertTrue(res.commit["is_root"])
        self.assertIsNone(res.parent)
        self.assertEqual(res.commit["parents"], [])
        joined = " ".join(res.warnings)
        self.assertIn("root commit", joined)

    def test_all_files_new(self):
        res = self.analyze(self.fx.shas["A"])
        self.assertEqual(len(res.changes), 2)
        for c in res.changes:
            self.assertEqual(c.status, "A")
            self.assertTrue(c.groups[0].new_file)
            self.assertEqual(c.groups[0].analysis["confidence"]["level"],
                             "INSUFFICIENT")


class TestMergeCommit(_Base):
    """13. Merge commit: first-parent baseline, documented warning."""

    @staticmethod
    def make_fx():
        return make_merge_fixture()

    def test_merge_handled_with_first_parent(self):
        res = self.analyze(self.fx.head)
        self.assertTrue(res.commit["is_merge"])
        self.assertEqual(len(res.commit["parents"]), 2)
        self.assertEqual(res.parent, res.commit["parents"][0])
        joined = " ".join(res.warnings)
        self.assertIn("merge commit", joined)
        self.assertIn("first parent", joined)


class TestRevertChronology(_Base):
    """Spec section 21: analyzing C (revert of B) must not confuse the
    history before C with the changes C introduces."""

    @staticmethod
    def make_fx():
        return make_commit_revert_fixture()

    def test_revert_of_detected(self):
        res = self.analyze(self.fx.shas["C"])
        self.assertEqual(res.commit["revert_of"], self.fx.shas["B"])

    def test_previous_behavior_attributed_to_reverted_commit(self):
        res = self.analyze(self.fx.shas["C"])
        g = self.change_for(res, "app/retry.py").groups[0]
        commits = self.blame_commits(g)
        self.assertIn(self.fx.shas["B"], commits,
                      "C reverts B's change; B must be the attributed origin")
        self.assertNotIn(self.fx.shas["C"], commits,
                         "C must never be credited with introducing the "
                         "behavior it reverts")

    def test_target_not_in_before_state_anywhere(self):
        res = self.analyze(self.fx.shas["C"])
        g = self.change_for(res, "app/retry.py").groups[0]
        a = g.analysis
        subjects = [h["subject"] for h in a["history"]]
        self.assertNotIn('Revert "Add timeout to retry"', subjects)
        for e in a["evidence"] + a["counter_evidence"]:
            self.assertNotEqual(e.get("commit"), self.fx.shas["C"])


class TestRevertedLater(_Base):
    """19. Contradictory evidence: the analyzed change was later reverted."""

    @staticmethod
    def make_fx():
        return make_commit_reverted_later_fixture()

    def test_later_revert_surfaces_in_after(self):
        res = self.analyze(self.fx.shas["C"])
        c = self.change_for(res, "app/retry.py")
        self.assertEqual(c.after["reverts"], 1)
        later_shas = {lc["sha"] for lc in c.after["later_commits"]}
        self.assertIn(self.fx.shas["D"], later_shas)

    def test_target_still_not_self_credited(self):
        res = self.analyze(self.fx.shas["C"])
        g = self.change_for(res, "app/retry.py").groups[0]
        self.assertNotIn(self.fx.shas["C"], self.blame_commits(g))


class TestMultipleFiles(_Base):
    """8/9. A commit changing several files + multiple hunks."""

    @staticmethod
    def make_fx():
        return make_commit_multi_fixture()

    def test_both_files_present(self):
        res = self.analyze(self.fx.shas["B"])
        paths = {c.path for c in res.changes}
        self.assertIn("src/multi.py", paths)
        self.assertIn("src/other.py", paths)

    def test_multiple_hunks_merged_into_one_group(self):
        res = self.analyze(self.fx.shas["B"])
        c = self.change_for(res, "src/multi.py")
        # 5 modified lines, all introduced by the same commit -> ONE group
        # (the noise-control contract: no per-line duplicate explanations).
        self.assertEqual(len(c.groups), 1)
        g = c.groups[0]
        self.assertEqual(len(g.changes), 10)  # 5 old + 5 new
        self.assertEqual(g.added_lines, 5)
        self.assertEqual(g.deleted_lines, 5)

    def test_each_change_has_analysis(self):
        res = self.analyze(self.fx.shas["B"])
        for c in res.changes:
            self.assertTrue(c.groups, f"no groups for {c.path}")
            self.assertTrue(c.groups[0].analysis.get("confidence"))


class TestShallowCommit(_Base):
    """12. Shallow repository: LIMITED HISTORY warning, no crash."""

    @staticmethod
    def make_fx():
        return make_shallow_fixture()

    def test_shallow_warning_emitted(self):
        res = self.analyze(self.fx.head)
        joined = " ".join(res.warnings).lower()
        self.assertIn("shallow", joined)


class TestBinaryCommit(_Base):
    """15. Binary file: reported, content never parsed."""

    @staticmethod
    def make_fx():
        return make_commit_binary_fixture()

    def test_binary_reported_not_parsed(self):
        res = self.analyze(self.fx.shas["B"])
        c = self.change_for(res, "src/data.bin")
        self.assertEqual(c.status, "A")
        joined = " ".join(res.warnings).lower()
        self.assertIn("binary", joined)


class TestUnicodeCommit(_Base):
    """16. Unicode path in a commit."""

    @staticmethod
    def make_fx():
        return make_commit_unicode_fixture()

    def test_unicode_path_analyzed(self):
        res = self.analyze(self.fx.shas["B"])
        c = self.change_for(res, "src/ünïcode/mod.py")
        self.assertEqual(c.status, "M")
        self.assertTrue(c.groups[0].analysis.get("confidence"))


class TestMaliciousMessage(_Base):
    """18. Malicious commit message: no control chars in any output."""

    @staticmethod
    def make_fx():
        return make_commit_malicious_fixture()

    def _assert_clean(self, text):
        for ch in text:
            if ch in "\n\t ":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} leaked: {text!r}")

    def test_terminal_output_clean(self):
        res = self.analyze(self.fx.shas["B"])
        self._assert_clean(render_commit_terminal(res))

    def test_json_output_clean_and_valid(self):
        res = self.analyze(self.fx.shas["B"])
        raw = render_json(res)
        self._assert_clean(raw)
        data = jsonlib.loads(raw)
        # The OSC payload ("EVIL") is stripped entirely with its escape
        # sequence; the surrounding text survives sanitized.
        self.assertIn("oops", data["commit"]["subject"])
        self.assertIn("payload", data["commit"]["subject"])
        self.assertNotIn("\x1b", data["commit"]["subject"])


class TestInsufficientEvidence(_Base):
    """20. Added lines with no previous version: honest INSUFFICIENT."""

    @staticmethod
    def make_fx():
        f = GitFixture()
        a = f.commit("Add empty module", {"src/empty.py": ""})
        b = f.commit("Fill module", {"src/empty.py": "x = 1\n"})
        f.shas = {"A": a, "B": b}
        return f

    def test_pure_addition_insufficient(self):
        res = self.analyze(self.fx.shas["B"])
        g = self.change_for(res, "src/empty.py").groups[0]
        self.assertEqual(g.analysis["confidence"]["level"], "INSUFFICIENT")
        self.assertFalse(self.blame_facts(g),
                         "added lines have no previous lines to blame")


class TestSecurityNoShellInCommitPath(unittest.TestCase):
    """The --commit code path must never use shell=True or interpolation.

    Scans every module the commit mode touches for the dangerous patterns
    (diff.py is covered by its own test in test_diff.py).
    """

    def test_no_shell_in_commit_modules(self):
        import os
        base = os.path.join(os.path.dirname(__file__), "..", "agent_blame")
        for name in ("commit.py", "history.py", "analyzer.py", "cli.py",
                     "models.py", "output.py", "graph.py", "evidence.py"):
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn("shell=True", src, name)
            self.assertNotIn("shell=", src, name)
            self.assertNotIn("os.system", src, name)
            self.assertNotIn("subprocess.call", src, name)
            self.assertNotIn("eval(", src, name)


class TestJsonStructure(_Base):
    """16. Commit JSON schema: stable, machine-readable, structured."""

    @staticmethod
    def make_fx():
        return make_commit_evolution_fixture()

    def test_commit_json_schema(self):
        res = self.analyze(self.fx.shas["B"])
        data = jsonlib.loads(render_json(res))
        self.assertEqual(data["mode"], "commit")
        self.assertEqual(data["commit"]["sha"], self.fx.shas["B"])
        for key in ("sha", "short", "parents", "author", "date", "subject",
                    "body", "is_merge", "is_root", "revert_of"):
            self.assertIn(key, data["commit"])
        self.assertIn("parent", data)
        self.assertIn("warnings", data)
        c = data["changes"][0]
        for key in ("path", "status", "old_path", "groups", "after"):
            self.assertIn(key, c)
        g = c["groups"][0]
        for key in ("ranges", "changes", "added_lines", "deleted_lines",
                    "new_file", "analysis"):
            self.assertIn(key, g)
        a = g["analysis"]
        for key in ("confidence", "facts", "evidence", "counter_evidence",
                    "history", "risk", "inferences", "warnings"):
            self.assertIn(key, a)

    def test_json_is_deterministic(self):
        res1 = self.analyze(self.fx.shas["B"])
        res2 = self.analyze(self.fx.shas["B"])
        self.assertEqual(render_json(res1), render_json(res2))

    def test_diff_schema_unchanged(self):
        # The existing --diff JSON must not have drifted (spec: don't break
        # existing consumers). The ONLY addition is the nullable
        # `movement` field (Phase 2D) - every pre-existing key is intact.
        from agent_blame.diff import analyze_diff
        from tests.gitfixture import make_diff_modify_fixture
        fx = make_diff_modify_fixture()
        try:
            repo = discover_repository(fx.root)
            res = analyze_diff(repo)
            data = jsonlib.loads(render_json(res))
            f = data["files"][0]
            self.assertEqual(set(f.keys()),
                             {"path", "status", "old_path", "groups",
                              "movement"})
        finally:
            fx.cleanup()


if __name__ == "__main__":
    unittest.main()
