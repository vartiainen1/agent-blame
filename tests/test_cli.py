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


class TestCliRegression(unittest.TestCase):
    """Phase 2E: regression findings must appear in terminal + JSON with
    careful (never causal) wording."""

    def setUp(self):
        from tests.gitfixture import make_regression_revert_sequence_fixture
        self.fx = make_regression_revert_sequence_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_terminal_shows_regression_evidence(self):
        proc = _run_cli(["app/retry.py:4"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("Historical regression evidence", out)
        self.assertIn("EXPLICIT_REVERT", out)
        self.assertIn("explicitly reverts", out)
        # NEVER causal language.
        self.assertNotIn("caused the bug", out.lower())
        self.assertNotIn("is buggy", out.lower())

    def test_json_regressions_block(self):
        proc = _run_cli(["app/retry.py:4", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertIn("regressions", data)
        self.assertTrue(data["regressions"])
        r = data["regressions"][0]
        self.assertIn("type", r)
        self.assertIn("confidence", r)
        self.assertIn("explanation", r)

    def test_commit_terminal_shows_self_revert(self):
        from tests.gitfixture import make_regression_commit_revert_fixture
        fx = make_regression_commit_revert_fixture()
        try:
            proc = _run_cli(["--commit", fx.shas["C"]], fx.root)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = proc.stdout
            self.assertIn("Historical regression evidence", out)
            self.assertIn("EXPLICIT_REVERT", out)
            self.assertIn("explicitly reverts", out)
        finally:
            fx.cleanup()


class TestCliDiscoverability(unittest.TestCase):
    """Phase 6B: the first-run surface must let an unfamiliar user build a
    valid invocation from --help alone. Deterministic text assertions on the
    help and error paths (not exit codes only)."""

    def setUp(self):
        self.fx = make_introduction_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_help_has_quick_start_examples(self):
        proc = _run_cli(["--help"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        # Quick start section with the three primary modes.
        self.assertIn("Quick start", out)
        self.assertIn("agent-blame src/auth/session.py:142", out)
        self.assertIn("why does this line exist?", out)
        self.assertIn("agent-blame --diff", out)
        self.assertIn("what history explains my current changes?", out)
        self.assertIn("agent-blame --commit", out)
        self.assertIn("why does the code this commit changed exist?", out)

    def test_help_differentiates_from_git_blame(self):
        proc = _run_cli(["--help"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not a prettier `git blame`", proc.stdout)
        self.assertIn("WHY, not just WHO", proc.stdout)

    def test_help_target_is_question_first(self):
        proc = _run_cli(["--help"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = " ".join(proc.stdout.split())  # argparse wraps long lines
        self.assertIn("WHY: <file>:<line>", out)
        self.assertIn("how did this code evolve?", out)
        self.assertIn("what should I know before changing/removing it?", out)
        self.assertIn("your current working-tree changes", out)

    def test_no_target_prints_help_with_quick_start(self):
        proc = _run_cli([], self.cwd)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stdout.lower())
        self.assertIn("Quick start", proc.stdout)

    def test_bare_file_offers_blameable_lines(self):
        # Phase 6C 15: the bare-file case (Phase 6A class-C failure) is now
        # an AFFORDANCE, not an error - the CLI resolves it to the file's
        # blame-able lines so the next step (`agent-blame file.py:LINE`) is
        # one keystroke away.
        proc = _run_cli(["app/retry.py"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        out = proc.stdout
        self.assertIn("needs a line number", out)
        self.assertIn("app/retry.py", out)
        self.assertIn("Symbols in app/retry.py", out)
        self.assertIn("function retry", out)
        self.assertIn("agent-blame app/retry.py:1", out)

class TestCliTargetResolution(unittest.TestCase):
    """Phase 6C 15: the target-resolution entry points (bare file,
    file:function, bare sha) via the real CLI - output values, not just
    exit codes."""

    def setUp(self):
        self.fx = make_evolution_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_bare_file_python_symbol_table(self):
        proc = _run_cli(["app/retry.py"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("needs a line number", out)
        self.assertIn("2  function retry", out)
        self.assertIn("agent-blame app/retry.py:1", out)

    def test_bare_file_non_python_line_count(self):
        self.fx.commit("Add a doc", {"docs/notes.txt": "one\ntwo\nthree\n"})
        proc = _run_cli(["docs/notes.txt"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("3 line(s)", proc.stdout)
        self.assertIn("agent-blame docs/notes.txt:1", proc.stdout)

    def test_bare_file_missing_clean_error(self):
        proc = _run_cli(["nope.py"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("neither a file", proc.stderr)
        self.assertIn("nor a resolvable commit", proc.stderr)

    def test_file_function_resolves_to_def_line(self):
        # app/retry.py: `def retry` is line 2 - resolution must land there
        # and SAY SO (the explicit "resolved to line N" contract).
        proc = _run_cli(["app/retry.py:retry"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("WHY DOES THIS CODE EXIST?", out)
        self.assertIn("resolved 'retry' to line 2", out)
        self.assertIn("app/retry.py:2", out)

    def test_file_function_json_target_and_warning(self):
        proc = _run_cli(["app/retry.py:retry", "--json"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = jsonlib.loads(proc.stdout)
        self.assertEqual(data["target"]["file"], "app/retry.py")
        self.assertEqual(data["target"]["start_line"], 2)
        self.assertTrue(any("resolved 'retry' to line 2" in w
                            for w in data["warnings"]))

    def test_file_function_in_history_and_risk_modes(self):
        for flag in ("--history", "--risk"):
            proc = _run_cli([flag, "app/retry.py:retry"], self.cwd)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("resolved 'retry' to line 2", proc.stdout)
        self.assertIn("HISTORY", _run_cli(["--history", "app/retry.py:retry"],
                                           self.cwd).stdout)
        self.assertIn("CHANGE / REMOVAL ANALYSIS",
                      _run_cli(["--risk", "app/retry.py:retry"],
                               self.cwd).stdout)

    def test_file_function_nonexistent_function(self):
        proc = _run_cli(["app/retry.py:missing_fn"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("no function 'missing_fn'", proc.stderr)
        self.assertIn("retry", proc.stderr)  # lists the available symbols

    def test_file_function_ambiguous_names(self):
        from tests.gitfixture import GitFixture
        fx = GitFixture()
        try:
            fx.commit("Add ambiguous symbols", {
                "app/x.py": (
                    "def retry(fn):\n"
                    "    return fn()\n"
                    "\n"
                    "class Server:\n"
                    "    def retry(self):\n"
                    "        return 1\n"
                ),
            })
            proc = _run_cli(["app/x.py:retry"], fx.root)
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("ambiguous", proc.stderr)
            self.assertIn("Server.retry", proc.stderr)
            # The qualified name disambiguates deterministically.
            proc = _run_cli(["app/x.py:Server.retry"], fx.root)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("resolved 'Server.retry' to line 5", proc.stdout)
        finally:
            fx.cleanup()

    def test_file_function_non_python_rejected(self):
        self.fx.commit("Add a config", {"cfg.yaml": "key: value\n"})
        proc = _run_cli(["cfg.yaml:key"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("only supported for Python files", proc.stderr)
        self.assertIn("cfg.yaml:<line>", proc.stderr)

    def test_file_function_missing_file(self):
        proc = _run_cli(["nope.py:retry"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("does not exist at HEAD", proc.stderr)

    def test_malformed_target_clean_error(self):
        for bad in ("app/retry.py:1-", "app/retry.py:foo-bar", "app/retry.py:123abc"):
            proc = _run_cli([bad], self.cwd)
            self.assertEqual(proc.returncode, 2, bad)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("error", proc.stderr.lower())


class TestCliBareSha(unittest.TestCase):
    """Phase 6C 15: `agent-blame <sha>` is the --commit entry point."""

    def setUp(self):
        self.fx = make_commit_evolution_fixture()
        self.cwd = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def test_bare_sha_runs_commit_mode(self):
        proc = _run_cli([self.fx.shas["B"]], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("COMMIT ANALYSIS", out)
        self.assertIn("Fix retry timing for 429s", out)
        self.assertIn("Baseline", out)

    def test_bare_sha_abbrev(self):
        proc = _run_cli([self.fx.shas["B"][:10]], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("COMMIT ANALYSIS", proc.stdout)

    def test_bare_sha_json_identical_to_commit_flag(self):
        bare = _run_cli([self.fx.shas["B"], "--json"], self.cwd)
        flag = _run_cli(["--commit", self.fx.shas["B"], "--json"], self.cwd)
        self.assertEqual(bare.returncode, 0, bare.stderr)
        self.assertEqual(flag.returncode, 0, flag.stderr)
        self.assertEqual(jsonlib.loads(bare.stdout),
                         jsonlib.loads(flag.stdout))

    def test_bare_sha_rejects_mode_flags(self):
        for flag in ("--history", "--risk"):
            proc = _run_cli([flag, self.fx.shas["B"]], self.cwd)
            self.assertEqual(proc.returncode, 2, flag)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("COMMIT mode", proc.stderr)

    def test_sha_shaped_not_a_commit_falls_back_to_file(self):
        # A hex-looking string that is neither a commit nor a file: the
        # sha verification fails and the file interpretation reports it
        # honestly instead of crashing or guessing.
        proc = _run_cli(["deadbeef"], self.cwd)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("neither a file", proc.stderr)

    def test_file_named_like_a_sha_is_not_hijacked(self):
        # A real file whose NAME looks like a sha must still work as a
        # bare-file target once the sha check fails to resolve it.
        self.fx.commit("Add a hex-named file", {"deadbeef": "x\ny\n"})
        proc = _run_cli(["deadbeef"], self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("needs a line number", proc.stdout)
        self.assertIn("2 line(s)", proc.stdout)


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
