"""CLI integration tests.

These run the real CLI as a subprocess and verify OUTPUT VALUES, not just
exit codes (workspace rule 8 / spec section 25). Error paths are verified
with --exit N + --forbid Traceback (stderr is not visible to stdout
inspection).
"""

import json as jsonlib
import os
import subprocess
import sys
import unittest

from tests.gitfixture import (make_caller_simple_fixture,
                              make_commit_evolution_fixture,
                              make_commit_malicious_fixture,
                              make_diff_modify_fixture, make_evolution_fixture,
                              make_introduction_fixture,
                              make_malicious_message_fixture,
                              make_movement_partial_fixture,
                              make_movement_pure_rename_fixture)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_cli(args, cwd):
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = PROJECT_ROOT + (os.pathsep + existing if existing else "")
    proc = subprocess.run(
        [sys.executable, "-m", "agent_blame", *args],
        cwd=cwd, capture_output=True, text=True, env=env,
    )
    return proc


class TestCliWhy(unittest.TestCase):

    def setUp(self):
        self.fx = make_evolution_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_why_mode_output_values(self):
        proc = _run_cli(["app/retry.py:3"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("WHY DOES THIS CODE EXIST?", proc.stdout)
        self.assertIn("Add rate-limit handling", proc.stdout)
        self.assertIn("Confidence", proc.stdout)

    def test_json_mode_output_values(self):
        proc = _run_cli(["app/retry.py:3", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["target"]["file"], "app/retry.py")
        self.assertEqual(data["target"]["start_line"], 3)
        self.assertIn("mode", data)
        self.assertEqual(data["mode"], "why")

    def test_history_mode(self):
        proc = _run_cli(["--history", "app/retry.py:3"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("HISTORY", proc.stdout)
        self.assertIn("Fix retry timing for 429s", proc.stdout)

    def test_risk_mode(self):
        proc = _run_cli(["--risk", "app/retry.py:3"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("CHANGE / REMOVAL ANALYSIS", proc.stdout)
        self.assertIn("Historical removal risk", proc.stdout)

    def test_range_target(self):
        proc = _run_cli(["app/retry.py:1-3", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["target"]["start_line"], 1)
        self.assertEqual(data["target"]["end_line"], 3)


class TestCliErrors(unittest.TestCase):

    def setUp(self):
        self.fx = make_introduction_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_bad_target_exit_2_no_traceback(self):
        proc = _run_cli(["app/retry.py:abc"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("error", proc.stderr.lower())

    def test_no_target_prints_help(self):
        proc = _run_cli([], self.cwd)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stdout.lower())

    def test_not_a_repository(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_cli(["x.py:1"], tmp)
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("not inside a git repository", proc.stderr)

    def test_missing_file_warns_but_exits_0(self):
        proc = _run_cli(["nope.py:1"], self.cwd)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("does not exist at HEAD", proc.stdout)

    def test_out_of_range_line_exits_0_no_traceback(self):
        proc = _run_cli(["app/retry.py:99999"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("could not blame", proc.stdout)
        self.assertIn("INSUFFICIENT", proc.stdout)

    def test_out_of_range_json_is_valid(self):
        proc = _run_cli(["app/retry.py:99999", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["confidence"]["level"], "INSUFFICIENT")
        self.assertEqual(data["evidence"], [])

    def test_dotfile_target(self):
        # .gitignore: the dot must survive path normalization.
        with open(os.path.join(self.cwd, ".gitignore"), "w") as fh:
            fh.write("__pycache__\n")
        proc = _run_cli([".gitignore:1"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(".gitignore", proc.stdout)

    def test_json_is_valid_even_for_missing_file(self):
        proc = _run_cli(["nope.py:1", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["target"]["file"], "nope.py")


class TestCliDiff(unittest.TestCase):
    """--diff mode via the real CLI (output values, not just exit codes)."""

    def setUp(self):
        self.fx = make_diff_modify_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_diff_terminal_output_values(self):
        proc = _run_cli(["--diff"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DIFF ANALYSIS", proc.stdout)
        self.assertIn("src/retry.py", proc.stdout)
        self.assertIn("Historical change risk", proc.stdout)

    def test_diff_json_output_values(self):
        proc = _run_cli(["--diff", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["mode"], "diff")
        self.assertEqual(data["scope"], "worktree")
        self.assertTrue(data["files"])
        self.assertIn("analysis", data["files"][0]["groups"][0])

    def test_diff_no_repo_clean_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_cli(["--diff"], tmp)
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("not inside a git repository", proc.stderr)

    def test_diff_conflicts_with_history(self):
        proc = _run_cli(["--diff", "--history", "src/retry.py:3"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("--diff", proc.stderr)


class TestCliCallers(unittest.TestCase):
    """Caller relationships surface through the real CLI (WHY + JSON)."""

    def setUp(self):
        self.fx = make_caller_simple_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_why_output_shows_callers(self):
        proc = _run_cli(["src/auth.py:1"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Callers", proc.stdout)
        self.assertIn("handle_request", proc.stdout)
        self.assertIn("DIRECT_CALL", proc.stdout)
        self.assertIn("LIVE", proc.stdout)

    def test_risk_output_shows_callers(self):
        proc = _run_cli(["--risk", "src/auth.py:1"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Callers", proc.stdout)
        self.assertIn("confirmed live caller", proc.stdout)

    def test_json_has_callers_and_symbol(self):
        proc = _run_cli(["src/auth.py:1", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["symbol"]["name"], "authenticate")
        self.assertTrue(data["callers"])
        self.assertEqual(data["callers"][0]["relationship"], "DIRECT_CALL")


class TestCliCommit(unittest.TestCase):
    """--commit mode via the real CLI (output values, revision forms,
    error handling - not just exit codes)."""

    def setUp(self):
        self.fx = make_commit_evolution_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_commit_terminal_output_values(self):
        proc = _run_cli(["--commit", self.fx.shas["B"]], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("COMMIT ANALYSIS", proc.stdout)
        self.assertIn("Fix retry timing for 429s", proc.stdout)
        self.assertIn("Baseline", proc.stdout)
        self.assertIn("Historical change risk", proc.stdout)

    def test_commit_json_output_values(self):
        proc = _run_cli(["--commit", self.fx.shas["B"], "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["mode"], "commit")
        self.assertEqual(data["commit"]["sha"], self.fx.shas["B"])
        self.assertEqual(data["commit"]["parents"], [self.fx.shas["A"]])
        self.assertTrue(data["changes"])
        self.assertIn("analysis", data["changes"][0]["groups"][0])

    def test_revision_forms(self):
        # full sha, abbrev, HEAD, HEAD~1 all resolve.
        self.assertEqual(_run_cli(["--commit", self.fx.shas["B"]], self.cwd).returncode, 0)
        self.assertEqual(_run_cli(["--commit", self.fx.shas["B"][:10]], self.cwd).returncode, 0)
        self.assertEqual(_run_cli(["--commit", "HEAD"], self.cwd).returncode, 0)
        self.assertEqual(_run_cli(["--commit", "HEAD~1"], self.cwd).returncode, 0)
        self.assertEqual(_run_cli(["--commit", "HEAD~2"], self.cwd).returncode, 0)

    def test_invalid_revision_clean_error(self):
        proc = _run_cli(["--commit", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("could not resolve commit", proc.stderr)

    def test_dash_revision_rejected(self):
        proc = _run_cli(["--commit=-x"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("-", proc.stderr)

    def test_commit_conflicts_with_target(self):
        proc = _run_cli(["--commit", "HEAD", "src/retry.py:3"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("--commit", proc.stderr)

    def test_commit_conflicts_with_diff(self):
        proc = _run_cli(["--commit", "HEAD", "--diff"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_commit_no_repo_clean_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_cli(["--commit", "HEAD"], tmp)
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("not inside a git repository", proc.stderr)


class TestCliCommitSecurity(unittest.TestCase):
    """Malicious commit message must not leak control chars via --commit."""

    def setUp(self):
        self.fx = make_commit_malicious_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_terminal_output_clean(self):
        proc = _run_cli(["--commit", self.fx.shas["B"]], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for ch in proc.stdout:
            if ch in "\n\t":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} in CLI output")

    def test_json_output_clean(self):
        proc = _run_cli(["--commit", self.fx.shas["B"], "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        raw = jsonlib.dumps(data)
        for ch in raw:
            self.assertNotIn(ch, "\x1b\x07\x00")


class TestCliMovement(unittest.TestCase):
    """Phase 2D: the CLI must present a MOVE as a move, never as the
    original introduction - the mandatory spec 2D/23 property, end to end."""

    def setUp(self):
        self.fx = make_movement_partial_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_terminal_shows_move_and_origin(self):
        proc = _run_cli(["new.py:1"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("Movement", out)
        self.assertIn("CODE_MOVEMENT", out)
        self.assertIn("Moved here by", out)
        self.assertIn("Originally introduced by", out)
        self.assertIn("not the mover", out)
        # The ORIGIN commit's subject appears as the attributed evidence.
        self.assertIn("Add foo and bar in old.py", out)

    def test_json_movement_block(self):
        proc = _run_cli(["new.py:1", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        mv = data.get("movement")
        self.assertIsNotNone(mv)
        self.assertEqual(mv["type"], "CODE_MOVEMENT")
        self.assertEqual(mv["origin"], self.fx.shas["A"])
        self.assertEqual(mv["moved_by"], self.fx.shas["B"])
        # The introducing EVIDENCE must point at the origin, not the mover.
        intro = [e for e in data["evidence"] if e["kind"] == "introduced_by"]
        self.assertTrue(intro)
        self.assertTrue(all(e["commit"] == self.fx.shas["A"] for e in intro),
                        "introducing evidence must be re-attributed to the origin")


class TestCliSecurity(unittest.TestCase):
    """Malicious commit message must not leak control chars via the CLI."""

    def setUp(self):
        self.fx = make_malicious_message_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_terminal_output_clean(self):
        proc = _run_cli(["src/evil.py:1"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for ch in proc.stdout:
            if ch in "\n\t":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} in CLI output")

    def test_json_output_clean(self):
        proc = _run_cli(["src/evil.py:1", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        raw = jsonlib.dumps(data)
        for ch in raw:
            self.assertNotIn(ch, "\x1b\x07\x00")


if __name__ == "__main__":
    unittest.main()
