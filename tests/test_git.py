"""Tests for the safe Git abstraction (spec sections 20/21).

The wrapper must never use shell=True, must pass args as a list, must
time out, and must surface failures as clean GitError (no tracebacks).
"""

import subprocess
import unittest

from agent_blame import git
from agent_blame.git import GitError

from tests.gitfixture import make_introduction_fixture


class TestGitWrapper(unittest.TestCase):

    def setUp(self):
        self.fx = make_introduction_fixture()

    def tearDown(self):
        self.fx.cleanup()

    def test_git_output_returns_string(self):
        out = git.git_output(["rev-parse", "HEAD"], cwd=self.fx.root)
        self.assertEqual(len(out.strip()), 40)
        self.assertIsInstance(out, str)

    def test_git_lines_splits(self):
        out = git.git_lines(["log", "--oneline"], cwd=self.fx.root)
        self.assertEqual(len(out), 1)

    def test_failure_raises_git_error(self):
        with self.assertRaises(GitError) as ctx:
            git.git_output(["rev-parse", "NO-SUCH-REF"], cwd=self.fx.root)
        self.assertNotIn("Traceback", str(ctx.exception))

    def test_try_git_output_returns_none_on_failure(self):
        self.assertIsNone(
            git.try_git_output(["rev-parse", "NO-SUCH-REF"], cwd=self.fx.root))

    def test_timeout_raises_clean_error(self):
        # Simulate a hung git command deterministically: monkeypatch
        # subprocess.run to raise TimeoutExpired and assert the wrapper
        # maps it to a clean GitError (no traceback, clear message).
        import subprocess as _sp
        from agent_blame import git as _git
        original = _sp.run

        def _hung(*a, **kw):
            raise _sp.TimeoutExpired(cmd=a[0], timeout=kw.get("timeout", 0))

        _sp.run = _hung
        try:
            with self.assertRaises(GitError) as ctx:
                _git.git_output(["rev-parse", "HEAD"], cwd=self.fx.root, timeout=1)
            self.assertIn("timed out", str(ctx.exception))
        finally:
            _sp.run = original

    def test_no_shell_true_anywhere(self):
        """The wrapper must construct argv lists, never shell strings."""
        import inspect
        src = inspect.getsource(git)
        # Strip the docstring so documentation text can't trip the check.
        body = src.split('"""', 2)[-1]
        self.assertNotIn("shell=True", body)
        self.assertNotIn("shell = True", body)

    def test_args_are_lists(self):
        """run_git must reject a bare string command."""
        with self.assertRaises((TypeError, GitError)):
            git.run_git("rev-parse HEAD", cwd=self.fx.root)


if __name__ == "__main__":
    unittest.main()
