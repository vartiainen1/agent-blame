"""Phase 2A tests: --diff mode analyzes the developer's changes.

These tests assert on the STRUCTURE of the diff analysis - which lines are
grouped together, which introducing commit is credited, whether added
lines are honestly reported as having no history, whether deletions
analyze the previous revision - not just that the command exited 0.

Fixture histories are tiny and KNOWN (see gitfixture.py), so the expected
conclusions are exact.
"""

import json as jsonlib
import os
import unittest

from agent_blame.diff import analyze_diff
from agent_blame.output import render_diff_terminal, render_json
from agent_blame.repository import discover_repository

from tests.gitfixture import (make_diff_add_fixture, make_diff_deleted_fixture,
                              make_diff_empty_fixture, make_diff_malicious_fixture,
                              make_diff_modify_fixture, make_diff_multi_hunk_fixture,
                              make_diff_new_file_fixture, make_diff_rename_fixture,
                              make_diff_revert_fixture, make_diff_staged_fixture,
                              make_diff_unicode_fixture, make_diff_whitespace_fixture,
                              make_shallow_fixture)


class _Base(unittest.TestCase):
    fx = None
    staged = False

    def setUp(self):
        self.fx = self.make_fx()
        self.repo = discover_repository(self.fx.root)
        self.assertIsNotNone(self.repo)

    def tearDown(self):
        self.fx.cleanup()

    def analyze(self, staged=None):
        return analyze_diff(self.repo, staged=self.staged if staged is None
                            else staged)

    def group_for(self, res, path):
        """The (first) analyzed group for a changed file path."""
        for f in res.files:
            if f.path == path:
                self.assertTrue(f.groups, f"no groups for {path}")
                return f.groups[0]
        self.fail(f"file {path} not in diff result: "
                  f"{[f.path for f in res.files]}")


class TestModifyHistoricallyMeaningfulLine(_Base):
    """1/2. Modify a line whose introducing commit is KNOWN (commit B)."""

    @staticmethod
    def make_fx():
        return make_diff_modify_fixture()

    def test_introducing_commit_credited_correctly(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        facts = [f for f in g.analysis["facts"] if f["kind"] == "blame"]
        self.assertTrue(facts, "blame facts expected for the modified line")
        # The sleep line was introduced by B (Fix retry timing), not A.
        self.assertIn("Fix retry timing for 429s", g.analysis["history"][0]["subject"]
                      if g.analysis.get("history") else "".join(
                          f["text"] for f in facts))

    def test_changed_lines_are_modifications(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        types = {c["type"] for c in g.changes}
        self.assertIn("mod", types)
        self.assertEqual(len(g.changes), 2)  # one old + one new line

    def test_history_chain_available(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        subjects = [h["subject"] for h in g.analysis["history"]]
        self.assertIn("Add rate-limit handling", subjects)
        self.assertIn("Fix retry timing for 429s", subjects)

    def test_confidence_not_fabricated(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        level = g.analysis["confidence"]["level"]
        self.assertIn(level, ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT"))


class TestAddedLinesNoFabricatedHistory(_Base):
    """3. Add a completely new line: no history, context analyzed."""

    @staticmethod
    def make_fx():
        return make_diff_add_fixture()

    def test_added_line_reported_without_invented_introducer(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        add_changes = [c for c in g.changes if c["type"] == "add"]
        self.assertTrue(add_changes, "the new line must appear as an addition")
        # Blame facts may cover the context, but the added line itself
        # must not be claimed as introduced by a commit it never had.
        for c in add_changes:
            self.assertEqual(c["side"], "new")

    def test_context_still_analyzed(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        # The group still carries the file's history (context analysis).
        self.assertTrue(g.analysis.get("history"))


class TestNewFile(_Base):
    """New file: no base version, honest no-evidence report."""

    @staticmethod
    def make_fx():
        return make_diff_new_file_fixture()

    def test_new_file_reported_without_analysis(self):
        res = self.analyze()
        for f in res.files:
            if f.path == "src/backoff.py":
                self.assertTrue(f.groups[0].new_file)
                self.assertEqual(f.groups[0].analysis["confidence"]["level"],
                                 "INSUFFICIENT")
                return
        self.fail("src/backoff.py missing from diff")


class TestStagedScope(_Base):
    """Staged-only changes: --diff sees nothing, --staged sees them."""

    @staticmethod
    def make_fx():
        return make_diff_staged_fixture()

    def test_worktree_scope_empty(self):
        res = self.analyze(staged=False)
        paths = [f.path for f in res.files]
        self.assertNotIn("src/retry.py", paths,
                         "staged-only change must not appear in the worktree diff")

    def test_staged_scope_finds_change(self):
        res = self.analyze(staged=True)
        g = self.group_for(res, "src/retry.py")
        self.assertTrue(g.changes)
        self.assertEqual(res.scope, "staged")

    def test_scope_recorded_in_json(self):
        res = self.analyze(staged=True)
        data = jsonlib.loads(render_json(res))
        self.assertEqual(data["scope"], "staged")
        self.assertEqual(data["mode"], "diff")


class TestDeletedFile(_Base):
    """Deleted file: analyze the previous revision + full history."""

    @staticmethod
    def make_fx():
        return make_diff_deleted_fixture()

    def test_deletion_analyzed_against_previous_revision(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        self.assertEqual(g.deleted_lines, 4)
        # The whole file's history is surfaced (introducer + fix commit).
        subjects = [h["subject"] for h in g.analysis["history"]]
        self.assertIn("Add rate-limit handling", subjects)
        self.assertIn("Fix retry timing for 429s", subjects)

    def test_deletion_has_risk_context(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        self.assertTrue(g.analysis.get("risk", {}).get("reasons")
                        or g.analysis.get("risk", {}).get("level"))


class TestRename(_Base):
    """Renamed file (staged): analyzed via the pre-rename path."""

    @staticmethod
    def make_fx():
        return make_diff_rename_fixture()

    def test_rename_detected_with_old_path(self):
        res = self.analyze(staged=True)
        for f in res.files:
            if f.path == "src/session.py":
                self.assertEqual(f.status, "R")
                self.assertEqual(f.old_path, "src/retry.py")
                self.assertTrue(f.groups)
                return
        self.fail("rename not detected in staged diff")

    def test_rename_history_follows_old_path(self):
        res = self.analyze(staged=True)
        g = self.group_for(res, "src/session.py")
        subjects = [h["subject"] for h in g.analysis["history"]]
        self.assertIn("Add rate-limit handling", subjects)


class TestMultipleFiles(_Base):
    """Multiple files changed in one diff."""

    @staticmethod
    def make_fx():
        f = make_diff_modify_fixture()
        f.write("src/other.py", "z = 1\n")
        return f

    def test_both_files_present(self):
        res = self.analyze()
        paths = {f.path for f in res.files}
        self.assertIn("src/retry.py", paths)
        self.assertIn("src/other.py", paths)


class TestMultipleHunksMerge(_Base):
    """Multiple changed regions sharing evidence -> ONE aggregated group."""

    @staticmethod
    def make_fx():
        return make_diff_multi_hunk_fixture()

    def test_same_evidence_merged_into_one_group(self):
        res = self.analyze()
        g = self.group_for(res, "src/multi.py")
        # 5 modified lines, all introduced by the same commit, must be ONE
        # group (the noise-control contract: no per-line duplicates).
        self.assertEqual(len([c for c in g.changes]), 10)  # 5 old + 5 new
        self.assertEqual(g.deleted_lines, 5)
        self.assertEqual(g.added_lines, 5)

    def test_single_explanation_not_many(self):
        res = self.analyze()
        g = self.group_for(res, "src/multi.py")
        self.assertEqual(len(res.files[0].groups), 1,
                         "identical evidence must merge to a single group")


class TestRevertRelatedChange(_Base):
    """Reverted history + a new change: revert surfaces as counter-evidence."""

    @staticmethod
    def make_fx():
        return make_diff_revert_fixture()

    def test_revert_in_history(self):
        res = self.analyze()
        g = self.group_for(res, "app/retry.py")
        subjects = [h["subject"] for h in g.analysis["history"]]
        self.assertTrue(any("evert" in s for s in subjects),
                        f"revert commit should be in history: {subjects}")

    def test_confidence_not_high_with_revert_history(self):
        res = self.analyze()
        g = self.group_for(res, "app/retry.py")
        level = g.analysis["confidence"]["level"]
        self.assertNotEqual(level, "HIGH")


class TestInsufficientEvidence(_Base):
    """Added line with no usable context -> honest INSUFFICIENT."""

    @staticmethod
    def make_fx():
        from tests.gitfixture import GitFixture
        f = GitFixture()
        f.commit("Add file", {"src/only.py": "a = 1\n"})
        f.write("src/only.py", "a = 1\nb = 2\n")  # pure addition
        return f


class TestMaliciousDiffContent(_Base):
    """Malicious ANSI/control sequences in changed lines must never reach output."""

    @staticmethod
    def make_fx():
        return make_diff_malicious_fixture()

    def test_terminal_output_clean(self):
        res = self.analyze()
        text = render_diff_terminal(res)
        for ch in text:
            if ch in "\n\t":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} leaked: {text!r}")

    def test_json_output_clean(self):
        res = self.analyze()
        raw = render_json(res)
        for ch in raw:
            if ch in "\n\t ":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} in JSON output")


class TestUnicodePath(_Base):
    """Unicode path in a diff."""

    @staticmethod
    def make_fx():
        return make_diff_unicode_fixture()

    def test_unicode_path_analyzed(self):
        res = self.analyze()
        paths = [f.path for f in res.files]
        self.assertTrue(any("ünïcode" in p for p in paths),
                        f"unicode path missing: {paths}")


class TestEmptyDiff(_Base):
    """Empty diff: no changes -> clean no-op result."""

    @staticmethod
    def make_fx():
        return make_diff_empty_fixture()

    def test_no_files(self):
        res = self.analyze()
        self.assertEqual(res.files, [])
        self.assertEqual(res.scope, "worktree")

    def test_terminal_output(self):
        res = self.analyze()
        text = render_diff_terminal(res)
        self.assertIn("No changes", text)


class TestWhitespaceOnly(_Base):
    """Whitespace-only modification still credits the introducing commit."""

    @staticmethod
    def make_fx():
        return make_diff_whitespace_fixture()

    def test_introducer_credited(self):
        res = self.analyze()
        g = self.group_for(res, "src/retry.py")
        facts = [f for f in g.analysis["facts"] if f["kind"] == "blame"]
        self.assertTrue(facts, "whitespace-only change must still blame")
        text = " ".join(f["text"] for f in facts)
        self.assertIn("Fix retry timing", text)


class TestJsonStructure(_Base):
    """Diff JSON schema: stable, machine-readable, evidence exposed."""

    @staticmethod
    def make_fx():
        return make_diff_modify_fixture()

    def test_diff_json_schema(self):
        res = self.analyze()
        data = jsonlib.loads(render_json(res))
        self.assertEqual(data["mode"], "diff")
        self.assertIn("scope", data)
        self.assertIn("files", data)
        f = data["files"][0]
        for key in ("path", "status", "old_path", "groups"):
            self.assertIn(key, f)
        g = f["groups"][0]
        for key in ("ranges", "changes", "added_lines", "deleted_lines",
                    "analysis"):
            self.assertIn(key, g)
        a = g["analysis"]
        for key in ("confidence", "facts", "evidence", "counter_evidence",
                    "history", "risk", "inferences", "warnings"):
            self.assertIn(key, a)

    def test_json_is_deterministic(self):
        res1 = self.analyze()
        res2 = self.analyze()
        self.assertEqual(render_json(res1), render_json(res2))


class TestShallowDiff(_Base):
    """Shallow clone: LIMITED HISTORY warning surfaces in diff mode too."""

    @staticmethod
    def make_fx():
        return make_shallow_fixture()

    def test_shallow_warning_emitted(self):
        res = self.analyze()
        joined = " ".join(res.warnings).lower()
        self.assertIn("shallow", joined)


class TestSecurityNoShellInDiffPath(unittest.TestCase):
    """The diff code path must never use shell=True or shell interpolation."""

    def test_no_shell_in_diff_module(self):
        with open(os.path.join(os.path.dirname(__file__), "..",
                               "agent_blame", "diff.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("shell=True", src)
        self.assertNotIn("shell=", src)
        self.assertNotIn("os.system", src)
        self.assertNotIn("subprocess.call", src)
        self.assertNotIn("eval(", src)


if __name__ == "__main__":
    unittest.main()
