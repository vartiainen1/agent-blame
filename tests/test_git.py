"""Tests for the safe Git abstraction (spec sections 20/21).

The wrapper must never use shell=True, must pass args as a list, must
time out, and must surface failures as clean GitError (no tracebacks).

Phase 3 additions: the batched name-status parser and the SHA-integrity
property of commit_files_batch (batch results must be byte-identical to
the per-sha `git show` path - commit identifiers must never be corrupted
through batched parsing).
"""

import subprocess
import unittest

from agent_blame import git
from agent_blame.analyzer import AnalysisMemo
from agent_blame.git import GitError
from agent_blame.history import (commit_files, commit_files_batch,
                                 _parse_batched_name_status)

from tests.gitfixture import (make_commit_multi_fixture,
                              make_introduction_fixture)


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


class TestBatchedNameStatusParser(unittest.TestCase):
    """Phase 3: the `git log --no-walk --name-status -z --stdin` layout.

    Byte layout per commit: `<40-hex sha>\0\nM\0<path>\0` ... with the
    NEXT sha following the last path directly (no separator). The parser
    must never mistake a path for a record header (SHA-integrity).
    """

    def _stream_simple(self, records):
        """Emit git's exact `log --no-walk --name-status -z --stdin` layout
        (verified against `od -c` on a real repo):

            <sha>\x00\x00\n<status>\x00<path>\x00[<oldpath>\x00 for R/C]

        with the NEXT sha following the last path directly. The two NULs
        are the %x00 format token plus the -z record separator; the '\n'
        is git's header newline that lands on the first status token.
        """
        parts = []
        for sha, entries in records:
            parts.append(sha.encode() + b"\x00\x00\n")
            for status, path, old in entries:
                parts.append(status.encode() + b"\x00")
                # For R/C, git emits the OLD path FIRST, then the new one:
                # `R100\0old.py\0new.py\0` (verified with od -c).
                if status[0] in ("R", "C") and old:
                    parts.append(old.encode() + b"\x00")
                parts.append(path.encode() + b"\x00")
        return b"".join(parts)

    def test_single_commit_single_file(self):
        sha = "a" * 40
        raw = self._stream_simple([(sha, [("M", "app/retry.py", None)])])
        out = _parse_batched_name_status(raw)
        self.assertEqual(out, {sha: ["app/retry.py"]})

    def test_multiple_files_and_commits_adjacent(self):
        s1, s2 = "b" * 40, "c" * 40
        raw = self._stream_simple([
            (s1, [("M", "a.py", None), ("A", "b.py", None)]),
            (s2, [("M", "c.py", None)]),
        ])
        out = _parse_batched_name_status(raw)
        self.assertEqual(out, {s1: ["a.py", "b.py"], s2: ["c.py"]})

    def test_rename_records(self):
        sha = "d" * 40
        raw = self._stream_simple([
            (sha, [("R100", "new.py", "old.py"), ("M", "keep.py", None)]),
        ])
        out = _parse_batched_name_status(raw)
        self.assertEqual(out, {sha: ["new.py", "keep.py"]})

    def test_sha_looking_path_not_mistaken_for_header(self):
        # A path that is itself 40 hex chars must be consumed as a path,
        # not treated as the next record's sha.
        sha = "e" * 40
        hex_path = "f" * 40 + ".py"
        raw = self._stream_simple([(sha, [("A", hex_path, None)])])
        out = _parse_batched_name_status(raw)
        self.assertEqual(out, {sha: [hex_path]})

    def test_malformed_stream_skips_without_crash(self):
        out = _parse_batched_name_status(b"not a sha at all\x00junk")
        self.assertEqual(out, {})
        out2 = _parse_batched_name_status(b"")
        self.assertEqual(out2, {})


class TestBatchShaIntegrity(unittest.TestCase):
    """Phase 3: commit_files_batch must return EXACTLY what the per-sha
    `git show --name-status` path returns, for every non-merge commit in
    a real fixture. A corrupted sha would silently break origin tracking.
    """

    def test_batch_matches_per_sha_on_real_fixture(self):
        fx = make_commit_multi_fixture()
        try:
            from agent_blame.repository import discover_repository
            repo = discover_repository(fx.root)
            shas = [fx.shas[k] for k in sorted(fx.shas)]
            memo = AnalysisMemo()
            commit_files_batch(repo, memo, shas)
            for sha in shas:
                batched = memo._commit_files.get(sha)
                self.assertIsNotNone(batched, f"batch missed {sha[:8]}")
                self.assertEqual(batched, commit_files(repo, sha),
                                 f"batch corrupted files for {sha[:8]}")
        finally:
            fx.cleanup()


if __name__ == "__main__":
    unittest.main()
