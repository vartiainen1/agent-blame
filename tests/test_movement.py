"""Phase 2D: code-movement / rename tracking.

The central regression property of this phase (spec 2D/23):

    MOVEMENT must never be reported as INTRODUCTION.

Every fixture has a KNOWN movement chain; tests assert the structured
movement conclusions (type, moved_by, origin, confidence), not exit
codes. The partial-move fixtures are the dangerous ones: git's own
similarity detection misses them, so blame alone would credit the MOVE
commit as the origin.
"""

import json as jsonlib
import unittest

from agent_blame.analyzer import AnalysisMemo, analyze
from agent_blame.commit import analyze_commit
from agent_blame.diff import analyze_diff
from agent_blame.models import Target
from agent_blame.output import render_json, render_terminal
from agent_blame.repository import discover_repository

from tests.gitfixture import (
    make_movement_ambiguous_fixture,
    make_movement_commit_fixture,
    make_movement_copy_fixture,
    make_movement_diff_fixture,
    make_movement_malicious_fixture,
    make_movement_modified_fixture,
    make_movement_multiple_fixture,
    make_movement_partial_fixture,
    make_movement_pure_rename_fixture,
    make_movement_same_name_fixture,
    make_movement_unicode_fixture,
    make_movement_unsupported_fixture,
)


def _why(fx, path, start=1, end=2):
    repo = discover_repository(fx.root)
    return analyze(repo, Target(file=path, start_line=start, end_line=end),
                   memo=AnalysisMemo())


class TestPureRename(unittest.TestCase):
    """Spec 1+2: file rename with/without later modification."""

    def test_movement_attributes(self):
        fx = make_movement_pure_rename_fixture()
        try:
            r = _why(fx, "new.py")
            mv = r.movement
            self.assertIsNotNone(mv)
            self.assertEqual(mv["type"], "RENAME")
            self.assertEqual(mv["source_path"], "old.py")
            self.assertEqual(mv["dest_path"], "new.py")
            self.assertEqual(mv["origin"], fx.shas["A"])
            self.assertEqual(mv["moved_by"], fx.shas["B"])
            self.assertEqual(mv["confidence"], "HIGH")
            self.assertIn("git rename metadata", mv["signals"])
            # The origin fact blames A, never the mover B.
            for f in r.facts:
                self.assertNotEqual(f["commit"], fx.shas["B"],
                                    "the mover must not be the introducing fact")
        finally:
            fx.cleanup()

    def test_code_movement_evidence_present(self):
        fx = make_movement_pure_rename_fixture()
        try:
            r = _why(fx, "new.py")
            kinds = {e["kind"] for e in r.evidence}
            self.assertIn("code_movement", kinds)
            self.assertIn("introduced_by", kinds)
        finally:
            fx.cleanup()


class TestPartialMove(unittest.TestCase):
    """Spec 3 + the MANDATORY spec 2D/23 property: git misses this move,
    blame credits the mover B - the tool must correct it to A."""

    def test_introduction_never_the_mover(self):
        fx = make_movement_partial_fixture()
        try:
            r = _why(fx, "new.py")
            self.assertIsNotNone(r.movement, "partial move must be detected")
            mv = r.movement
            self.assertEqual(mv["type"], "CODE_MOVEMENT")
            self.assertEqual(mv["moved_by"], fx.shas["B"])
            self.assertEqual(mv["origin"], fx.shas["A"])
            self.assertEqual(mv["origin_path"], "old.py")
            self.assertEqual(mv["confidence"], "HIGH")
            # The movement section is the correction; the raw blame fact
            # stays a raw git fact, but the tool's CONCLUSION (movement)
            # must point at A, and no fact may claim B introduced it as
            # the analyzed conclusion.
            self.assertIn("code_movement", {e["kind"] for e in r.evidence})
        finally:
            fx.cleanup()

    def test_control_genuine_introduction(self):
        # A brand-new symbol with no prior existence must NOT be a move.
        import tempfile, os, subprocess
        d = tempfile.mkdtemp()
        def g(*args):
            return subprocess.run(["git", "-C", d, *args], check=True,
                                  capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t")
        g("config", "user.name", "T")
        with open(os.path.join(d, "new.py"), "w") as fh:
            fh.write("def brand_new():\n    return 42\n")
        g("add", "new.py"); g("commit", "-qm", "N: brand new code")
        try:
            repo = discover_repository(d)
            r = analyze(repo, Target(file="new.py", start_line=1, end_line=2),
                        memo=AnalysisMemo())
            self.assertIsNone(r.movement)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_modified_move_is_possible_not_fabricated(self):
        # Standalone WHY is CONSERVATIVE: find_origin only overrides a
        # confident blame with a CONFIRMED move (strong similarity + clear
        # margin). A moved-and-modified symbol (one value changed) is
        # below the confirmed threshold, so standalone WHY stays silent
        # rather than speculate - the POSSIBLE classification belongs to
        # the boundary analysis (--commit), where both trees are known.
        fx = make_movement_modified_fixture()
        try:
            r = _why(fx, "new.py")
            self.assertIsNone(r.movement)
            # Boundary analysis (commit mode) classifies it as POSSIBLE.
            repo = discover_repository(fx.root)
            res = analyze_commit(repo, fx.shas["B"], memo=AnalysisMemo())
            by_path = {c.path: c for c in res.changes}
            ch = by_path.get("new.py")
            self.assertIsNotNone(ch)
            self.assertEqual(ch.movement["type"], "POSSIBLE_MOVEMENT")
            self.assertEqual(ch.movement["origin"], fx.shas["A"])
        finally:
            fx.cleanup()


class TestMultipleMoves(unittest.TestCase):
    """Spec 10: the chain must trace through BOTH moves back to A."""

    def test_chain_traces_to_origin(self):
        fx = make_movement_multiple_fixture()
        try:
            r = _why(fx, "new.py")
            mv = r.movement
            self.assertIsNotNone(mv)
            self.assertEqual(mv["origin"], fx.shas["A"])
            self.assertEqual(mv["origin_path"], "old.py")
            self.assertEqual(mv["moved_by"], fx.shas["C"])
            # The immediate source of the last move, plus the full chain.
            self.assertEqual(mv["source_path"], "middle.py")
            chain = mv["chain"]
            self.assertEqual(len(chain), 2)
            self.assertEqual(chain[0]["commit"], fx.shas["C"])
            self.assertEqual(chain[1]["commit"], fx.shas["B"])
            self.assertEqual(chain[1]["old_path"], "old.py")
        finally:
            fx.cleanup()


class TestCopyNeverMove(unittest.TestCase):
    """Spec 9/13: a copy (source still exists) must never be 'moved'."""

    def test_copy_classified_as_copy(self):
        fx = make_movement_copy_fixture()
        try:
            r = _why(fx, "new.py")
            # The standalone path has no boundary, so no movement dict is
            # built for copies there (the source still exists - blame
            # correctly credits B). The classification is exercised at the
            # boundary level below.
            from agent_blame.symbols import match_moved_symbols
            repo = discover_repository(fx.root)
            memo = AnalysisMemo()
            before = memo.py_sources_limited(repo, fx.shas["A"],
                                             ["old.py", "new.py"])
            after = memo.py_sources_limited(repo, fx.shas["B"],
                                            ["old.py", "new.py"])
            moves = match_moved_symbols(repo, memo, before, after, {})
            self.assertTrue(moves)
            self.assertEqual(moves[0]["type"], "COPY")
            self.assertNotEqual(moves[0]["type"], "CODE_MOVEMENT")
        finally:
            fx.cleanup()


class TestAmbiguity(unittest.TestCase):
    """Spec 15/17: two identical same-name origins -> AMBIGUOUS, never a
    confident claim of one origin."""

    def test_ambiguous_origin(self):
        fx = make_movement_ambiguous_fixture()
        try:
            from agent_blame.symbols import match_moved_symbols
            repo = discover_repository(fx.root)
            memo = AnalysisMemo()
            before = memo.py_sources_limited(repo, fx.shas["A"],
                                             ["mod_a.py", "mod_b.py", "new.py"])
            after = memo.py_sources_limited(repo, fx.shas["B"],
                                            ["mod_a.py", "mod_b.py", "new.py"])
            moves = match_moved_symbols(repo, memo, before, after, {})
            self.assertTrue(moves)
            self.assertEqual(moves[0]["type"], "POSSIBLE_MOVEMENT")
            self.assertEqual(moves[0]["confidence"], "AMBIGUOUS")
        finally:
            fx.cleanup()

    def test_same_name_picks_structurally_identical_origin(self):
        fx = make_movement_same_name_fixture()
        try:
            from agent_blame.symbols import match_moved_symbols
            repo = discover_repository(fx.root)
            memo = AnalysisMemo()
            before = memo.py_sources_limited(repo, fx.shas["A"],
                                             ["mod_a.py", "old.py", "new.py"])
            after = memo.py_sources_limited(repo, fx.shas["B"],
                                            ["mod_a.py", "old.py", "new.py"])
            moves = match_moved_symbols(repo, memo, before, after, {})
            self.assertTrue(moves)
            self.assertEqual(moves[0]["source_path"], "old.py")
            self.assertNotEqual(moves[0]["source_path"], "mod_a.py")
        finally:
            fx.cleanup()


class TestUnsupportedAndUnicode(unittest.TestCase):
    def test_unsupported_language_no_symbol_claim(self):
        # A git-detected FILE rename is language-agnostic metadata and is
        # reported (type RENAME) - but no SYMBOL-level claim is made for
        # an unsupported language (source_symbol stays None, no fabricated
        # "moved function" story from regex guessing).
        fx = make_movement_unsupported_fixture()
        try:
            r = _why(fx, "new.js", start=1, end=1)
            mv = r.movement
            self.assertIsNotNone(mv)
            self.assertEqual(mv["type"], "RENAME")
            self.assertIsNone(mv["source_symbol"])
            self.assertEqual(mv["origin"], fx.shas["A"])
        finally:
            fx.cleanup()

    def test_unicode_paths(self):
        fx = make_movement_unicode_fixture()
        try:
            r = _why(fx, "src/émoji/new.py")
            mv = r.movement
            self.assertIsNotNone(mv)
            self.assertEqual(mv["type"], "RENAME")
            self.assertEqual(mv["origin"], fx.shas["A"])
            self.assertEqual(mv["moved_by"], fx.shas["B"])
        finally:
            fx.cleanup()


class TestMaliciousContent(unittest.TestCase):
    def test_no_crash_and_sanitized(self):
        fx = make_movement_malicious_fixture()
        try:
            r = _why(fx, "new.py")
            self.assertIsNotNone(r.movement)
            text = render_terminal(r)
            self.assertNotIn("\x1b[", text)          # ANSI stripped
            self.assertNotIn("\x07", text)           # BEL stripped
            data = jsonlib.loads(render_json(r))
            # The 1:1 content move is git-DETECTED (R100) - either
            # classification is a move, never an introduction.
            self.assertIn(data["movement"]["type"],
                          ("RENAME", "CODE_MOVEMENT"))
            self.assertEqual(data["movement"]["origin"], fx.shas["A"])
        finally:
            fx.cleanup()


class TestDiffIntegration(unittest.TestCase):
    """Spec 20: worktree rename (untracked new path + deleted old path)."""

    def test_worktree_rename_traces_origin(self):
        fx = make_movement_diff_fixture()
        try:
            repo = discover_repository(fx.root)
            res = analyze_diff(repo, memo=AnalysisMemo())
            by_path = {f.path: f for f in res.files}
            self.assertIn("new.py", by_path)
            self.assertEqual(by_path["new.py"].status, "?")
            mv = by_path["new.py"].movement
            self.assertIsNotNone(mv, "worktree rename must carry movement")
            self.assertEqual(mv["type"], "CODE_MOVEMENT")
            self.assertEqual(mv["source_path"], "old.py")
            self.assertEqual(mv["origin"], fx.shas["A"])
        finally:
            fx.cleanup()


class TestCommitIntegration(unittest.TestCase):
    """Spec 21: the partial-move commit itself - added ranges of the moved
    symbol must be analyzed against the SOURCE at the baseline."""

    def test_commit_movement_and_origin(self):
        fx = make_movement_commit_fixture()
        try:
            repo = discover_repository(fx.root)
            res = analyze_commit(repo, fx.shas["B"], memo=AnalysisMemo())
            by_path = {c.path: c for c in res.changes}
            self.assertIn("new.py", by_path)
            ch = by_path["new.py"]
            self.assertIsNotNone(ch.movement)
            self.assertEqual(ch.movement["type"], "CODE_MOVEMENT")
            self.assertEqual(ch.movement["moved_by"], fx.shas["B"])
            self.assertEqual(ch.movement["origin"], fx.shas["A"])
            # The added-range group must carry the movement and blame the
            # SOURCE (origin A), never report "no previous version".
            groups = [g for g in ch.groups if g.analysis.get("movement")]
            self.assertTrue(groups, "moved-symbol group must exist")
            g = groups[0]
            self.assertEqual(g.analysis["movement"]["origin"], fx.shas["A"])
            blame_facts = [f for f in g.analysis.get("facts", [])
                           if f["kind"] == "blame"]
            self.assertTrue(blame_facts)
            for f in blame_facts:
                self.assertEqual(f["commit"], fx.shas["A"],
                                 "origin analysis must blame A, not the mover")
            # JSON stays consistent with the structured result.
            data = jsonlib.loads(render_json(res))
            ch_json = next(c for c in data["changes"] if c["path"] == "new.py")
            self.assertEqual(ch_json["movement"]["origin"], fx.shas["A"])
        finally:
            fx.cleanup()


class TestJsonShape(unittest.TestCase):
    def test_movement_in_json_deterministic(self):
        fx = make_movement_partial_fixture()
        try:
            r = _why(fx, "new.py")
            d1 = jsonlib.loads(render_json(r))
            d2 = jsonlib.loads(render_json(r))
            self.assertEqual(d1, d2)
            mv = d1["movement"]
            for key in ("type", "source_path", "source_symbol", "dest_path",
                        "dest_symbol", "moved_by", "origin", "origin_path",
                        "confidence", "signals"):
                self.assertIn(key, mv)
            self.assertFalse(any(k.startswith("_") for k in mv.keys()),
                             "private fields must not leak into JSON")
        finally:
            fx.cleanup()

    def test_movement_in_risk_reasons_not_level(self):
        # Movement is CONTEXT: it may appear in risk reasons, but it must
        # not by itself drive the level (spec 2D/25: "moved = high risk"
        # is forbidden).
        fx = make_movement_partial_fixture()
        try:
            r = _why(fx, "new.py")
            self.assertIn("code_movement", {e["kind"] for e in r.evidence})
            self.assertTrue(any("moved here by" in reason
                                for reason in r.risk.reasons))
            # No revert / fix / test / caller signals exist here, so the
            # level cannot be HIGH from movement alone.
            self.assertNotEqual(r.risk.level, "HIGH")
        finally:
            fx.cleanup()


if __name__ == "__main__":
    unittest.main()
