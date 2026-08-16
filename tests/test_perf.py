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
