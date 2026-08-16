"""Performance regression tests (Phase 2A spec: \"add a regression/performance
test if necessary\").

These do NOT assert wall-clock time (flaky on CI). They assert the
STRUCTURAL property that prevents the N+1 explosion: git is invoked a
bounded number of times per run, independent of the number of changed
lines / commits in the file's history. The batched implementations
(metadata via one `git log --format`, per-commit counts via one
`git log --numstat`) make this deterministic.

The exact bound (<= 40 for a 4-file diff over a ~10-commit history) is
generous enough to absorb platform differences while still failing loudly
if someone reintroduces a per-line or per-commit subprocess loop.
"""

import sys
import unittest

from agent_blame import git as gitmod
from agent_blame.diff import analyze_diff
from agent_blame.repository import discover_repository

from tests.gitfixture import (make_diff_modify_fixture, make_diff_multi_hunk_fixture)


class _CountingGit:
    """Wraps git.subprocess.run to count invocations of git only."""

    def __init__(self):
        self.count = 0
        self._orig = gitmod.subprocess.run

    def install(self):
        gitmod.subprocess.run = self._counting
        return self

    def restore(self):
        gitmod.subprocess.run = self._orig

    def _counting(self, args, **kwargs):
        if args and args[0] == "git":
            self.count += 1
        return self._orig(args, **kwargs)


class TestDiffGitCallBound(unittest.TestCase):

    def tearDown(self):
        # Never leave the monkeypatch installed across tests.
        pass

    def _run_bounded(self, fx, bound):
        counter = _CountingGit()
        counter.install()
        try:
            repo = discover_repository(fx.root)
            self.assertIsNotNone(repo)
            res = analyze_diff(repo)
        finally:
            counter.restore()
        self.assertLessEqual(
            counter.count, bound,
            f"{counter.count} git calls exceeds the {bound} budget - an "
            f"N+1 (per-line/per-commit subprocess loop) has likely "
            f"regressed")
        return res

    def test_modify_fixture_bounded(self):
        fx = make_diff_modify_fixture()
        try:
            res = self._run_bounded(fx, bound=25)
            self.assertTrue(res.files)
        finally:
            fx.cleanup()

    def test_multi_hunk_bounded(self):
        # 5 changed lines in one file: analysis must NOT scale with lines.
        fx = make_diff_multi_hunk_fixture()
        try:
            res = self._run_bounded(fx, bound=25)
            self.assertTrue(res.files)
        finally:
            fx.cleanup()


class TestCommitGitCallBound(unittest.TestCase):
    """--commit mode must stay bounded too (no per-file/per-line loops).

    Analyzing a 2-file commit (one with 5 changed hunks) over a tiny
    history must stay under a small git-call budget; the batched metadata,
    numstat and after-scan calls keep it deterministic.
    """

    def test_commit_analysis_bounded(self):
        from agent_blame.commit import analyze_commit
        from tests.gitfixture import make_commit_multi_fixture
        fx = make_commit_multi_fixture()
        try:
            counter = _CountingGit()
            counter.install()
            try:
                repo = discover_repository(fx.root)
                self.assertIsNotNone(repo)
                res = analyze_commit(repo, fx.shas["B"])
            finally:
                counter.restore()
            self.assertEqual(len(res.changes), 2)
            self.assertLessEqual(
                counter.count, 35,
                f"{counter.count} git calls exceeds the commit-mode budget "
                f"- an N+1 (per-hunk subprocess loop) has likely regressed")
        finally:
            fx.cleanup()


class TestCallerGitCallBound(unittest.TestCase):
    """Caller analysis must not multiply git calls with repository size.

    A ~120-file repository is analyzed with exactly TWO extra git calls
    (ls-tree + one cat-file batch) for the whole-repo source index; the
    per-target pipeline adds its usual bounded calls. If a per-file git
    call were introduced, this bound would fail loudly.
    """

    def test_large_repo_bounded(self):
        from agent_blame.analyzer import analyze
        from agent_blame.models import Target
        from tests.gitfixture import make_caller_large_fixture
        fx = make_caller_large_fixture(n_files=120)
        try:
            counter = _CountingGit()
            counter.install()
            try:
                repo = discover_repository(fx.root)
                self.assertIsNotNone(repo)
                res = analyze(repo, Target(file="src/auth.py", start_line=1,
                                           end_line=1))
            finally:
                counter.restore()
            # The caller must be found despite the large repo.
            self.assertTrue(any("use_auth.py" in c["symbol"]
                                for c in res.callers))
            self.assertLessEqual(
                counter.count, 25,
                f"{counter.count} git calls for a 120-file repo - the "
                f"repo scan must stay at 2 calls (ls-tree + cat-file batch)")
        finally:
            fx.cleanup()

    def test_index_fetched_once_per_revision(self):
        """Two analyses in one run share the source index (no re-scan)."""
        from agent_blame.analyzer import AnalysisMemo, analyze
        from agent_blame.models import Target
        from tests.gitfixture import make_caller_simple_fixture
        fx = make_caller_simple_fixture()
        try:
            repo = discover_repository(fx.root)
            memo = AnalysisMemo()
            counter = _CountingGit()
            counter.install()
            try:
                analyze(repo, Target(file="src/auth.py", start_line=1, end_line=1),
                        memo=memo)
                first = counter.count
                analyze(repo, Target(file="src/server.py", start_line=3, end_line=3),
                        memo=memo)
                second = counter.count
            finally:
                counter.restore()
            # The second analysis must not re-run ls-tree / cat-file.
            self.assertLess(second - first, 8,
                            f"second analysis made {second - first} git calls; "
                            f"the source index should be reused")
        finally:
            fx.cleanup()


class TestMemoReuse(unittest.TestCase):
    """Shared AnalysisMemo must prevent duplicate file-history fetches."""

    def test_two_targets_share_commits(self):
        from agent_blame.analyzer import AnalysisMemo, analyze
        from agent_blame.models import Target
        fx = make_diff_multi_hunk_fixture()
        try:
            repo = discover_repository(fx.root)
            memo = AnalysisMemo()
            counter = _CountingGit()
            counter.install()
            try:
                # Two different targets in the SAME file: the file's commit
                # list must be fetched once, not once per target.
                analyze(repo, Target(file="src/multi.py", start_line=1, end_line=1),
                        memo=memo)
                first = counter.count
                analyze(repo, Target(file="src/multi.py", start_line=5, end_line=5),
                        memo=memo)
                second = counter.count
            finally:
                counter.restore()
            # The second analysis must not re-run the file's git log
            # (metadata batch) - only cheap per-target blame/numstat.
            self.assertLess(second - first, 8,
                            f"second analysis made {second - first} git calls; "
                            f"shared memo should make it near-free")
        finally:
            fx.cleanup()


if __name__ == "__main__":
    unittest.main()
