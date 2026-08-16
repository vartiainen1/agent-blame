"""Tests for terminal-output sanitization (spec section 21).

A malicious commit message must not be able to clear the terminal, move
the cursor, spoof output, or execute escape sequences. We assert the
SANITIZED output contains no control characters at all.
"""

import unittest

from agent_blame.output import sanitize


class TestSanitize(unittest.TestCase):

    def _assert_no_controls(self, s: str):
        for ch in s:
            if ch in "\n\t":
                continue
            self.assertGreaterEqual(ord(ch), 0x20, f"control char {ord(ch):#x} leaked")
            self.assertNotIn(ch, "\x1b\x9b\x07")

    def test_plain_text_untouched(self):
        self.assertEqual(sanitize("hello world"), "hello world")

    def test_csi_clear_screen_removed(self):
        evil = "feature \x1b[2J payload"
        out = sanitize(evil)
        self.assertNotIn("\x1b", out)
        self.assertIn("feature", out)
        self.assertIn("payload", out)
        self._assert_no_controls(out)

    def test_csi_cursor_move_removed(self):
        out = sanitize("a\x1b[Hb")
        self.assertNotIn("\x1b", out)
        self.assertIn("a", out)
        self.assertIn("b", out)
        self._assert_no_controls(out)

    def test_csi_color_codes_removed(self):
        out = sanitize("\x1b[31mred\x1b[0m")
        self.assertNotIn("\x1b", out)
        self.assertEqual(out, "red")
        self._assert_no_controls(out)

    def test_osc_sequence_removed(self):
        # OSC (ESC ] 0;title BEL) must be stripped including the BEL.
        out = sanitize("x\x1b]0;EVIL\x07y")
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertIn("x", out)
        self.assertIn("y", out)
        self._assert_no_controls(out)

    def test_osc_with_st_terminator(self):
        out = sanitize("x\x1b]0;EVIL\x1b\\y")
        self.assertNotIn("\x1b", out)
        self._assert_no_controls(out)

    def test_carriage_return_removed(self):
        # \r could spoof/overwrite lines in some terminals.
        out = sanitize("real\rFAKE")
        self.assertNotIn("\r", out)
        self._assert_no_controls(out)

    def test_c0_controls_removed(self):
        out = sanitize("a\x00b\x08c\x0bd")
        self.assertNotIn("\x00", out)
        self.assertNotIn("\x08", out)
        self.assertNotIn("\x0b", out)
        self._assert_no_controls(out)

    def test_newline_and_tab_kept(self):
        out = sanitize("line1\n\tline2")
        self.assertIn("\n", out)
        self.assertIn("\t", out)

    def test_empty_and_none(self):
        self.assertEqual(sanitize(""), "")
        self.assertEqual(sanitize(None), "")

    def test_unicode_kept(self):
        out = sanitize("ünïcode héllo 中文")
        self.assertIn("ünïcode", out)
        self.assertIn("中文", out)

    def test_full_escape_orchestra(self):
        evil = "\x1b[2J\x1b[H\rmalicious\x1b]0;T\x07\x00\x08"
        out = sanitize(evil)
        self._assert_no_controls(out)
        self.assertIn("malicious", out)

    def test_c1_and_del_removed(self):
        # C1 (0x80-0x9f) and DEL (0x7f) are NOT escaped by json.dumps, so
        # sanitize must strip them - a raw CSI byte (0x9b) in printed JSON
        # would be interpreted by a terminal.
        evil = "a\x9bb\x9dc\x7fd"
        out = sanitize(evil)
        self._assert_no_controls(out)
        self.assertEqual(out, "abcd")


class TestJsonSanitization(unittest.TestCase):
    """JSON output must contain no control chars at all (C0 + C1 + DEL)."""

    def _result_with_evil(self):
        from agent_blame.models import (AnalysisResult, Confidence, Risk,
                                        Target)
        r = AnalysisResult(target=Target("evil.py", 1, 1), mode="why")
        r.confidence = Confidence("HIGH", 0.9)
        r.risk = Risk("HIGH", ["\x9b risk\x7f"])
        r.facts = [{"kind": "blame", "line": 1, "commit": "a" * 40,
                    "text": "evil \x1b[2J\x9bc\x7fd payload"}]
        r.history = [{"sha": "a" * 40, "date": "2026-01-01",
                      "subject": "msg \x9b CSI \x7f DEL \x1b[3J",
                      "author": "\x9d"}]
        return r

    def test_json_has_no_control_chars(self):
        import json as jsonlib
        from agent_blame.output import render_json
        out = render_json(self._result_with_evil())
        data = jsonlib.loads(out)  # still valid JSON
        raw = jsonlib.dumps(data)
        for ch in raw:
            if ch in "\n\t":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} in JSON")
        self.assertNotIn("\x1b", raw)
        self.assertNotIn("\x9b", raw)
        self.assertNotIn("\x7f", raw)


class TestCallerStatusMarkers(unittest.TestCase):
    """Phase 4: caller status markers must not mislead.

    MODIFIED callers exist at the analyzed revision (their file is part
    of the analyzed change) - they render with '~', never with the dead
    marker. DELETED is the only status rendered as dead (x).
    """

    def _render(self, status):
        from agent_blame.output import _render_callers
        out = []
        callers = [{"symbol": f"src/app.py:caller", "path": "src/app.py",
                    "name": "caller", "line": 5, "call_sites": 1,
                    "relationship": "DIRECT_CALL", "status": status,
                    "confidence": "HIGH",
                    "text": "confirmed live caller: src/app.py:caller"}]
        _render_callers(out, callers, False, indent="  ")
        return "\n".join(out)

    def test_live_marker(self):
        self.assertIn("✓ src/app.py:caller  DIRECT_CALL  LIVE",
                      self._render("LIVE"))

    def test_modified_marker_not_dead(self):
        line = self._render("MODIFIED")
        self.assertIn("~ src/app.py:caller  DIRECT_CALL  MODIFIED", line)
        self.assertNotIn("✗", line)

    def test_deleted_marker(self):
        self.assertIn("✗ src/app.py:caller  DIRECT_CALL  DELETED",
                      self._render("DELETED"))


class TestEvidenceNoiseControl(unittest.TestCase):
    """Phase 4 output-quality: the WHY/HISTORY/RISK renderer honors the
    same noise-control contract as diff/commit.

    - dozens of per-commit `modified_by` bullets collapse into ONE
      aggregated line (rich/console.py produced 199 near-identical lines);
    - caller evidence kinds are not listed twice (once in Evidence, once
      in Callers);
    - WHY/RISK cap the Historical chain with a pointer to --history while
      HISTORY mode keeps the full timeline.
    """

    def _result(self, n_later=40, mode="why", symbol=None):
        from agent_blame.models import (AnalysisResult, Confidence, Risk,
                                        Target)
        r = AnalysisResult(target=Target("src/app.py", 10, 10), mode=mode)
        r.confidence = Confidence("MEDIUM", 0.5)
        r.risk = Risk("MEDIUM", [])
        r.facts = [{"kind": "blame", "line": 10, "commit": "a" * 40,
                    "text": "line 10 introduced by aaaaaaaa: init"}]
        r.evidence = [{"kind": "introduced_by", "commit": "a" * 40,
                       "text": "lines 10-10 introduced by aaaaaaaa: init",
                       "weight": 0.3, "is_counter": False}]
        for i in range(n_later):
            sha = f"{i:08x}"
            r.evidence.append({"kind": "modified_by", "commit": sha,
                               "text": f"later commit {sha} modified the file: chg {i}",
                               "weight": 0.18, "is_counter": False})
        if symbol is not None:
            r.symbol = {"name": symbol, "path": "src/app.py",
                        "qualified": "src/app.py:func", "kind": "function"}
            r.callers = [{"symbol": "src/app.py:caller", "path": "src/app.py",
                          "name": "caller", "line": 5, "call_sites": 1,
                          "relationship": "DIRECT_CALL", "status": "LIVE",
                          "confidence": "HIGH",
                          "text": "confirmed live caller: src/app.py:caller"}]
            r.evidence.append({"kind": "live_caller", "commit": "",
                               "text": "confirmed live caller: src/app.py:caller",
                               "weight": 0.2, "is_counter": False})
        r.history = [{"sha": f"{i:08x}" * 5, "date": f"2026-01-{i:02d}",
                      "subject": f"commit {i}", "author": "x"}
                     for i in range(1, n_later + 2)]
        return r

    def test_modified_by_collapses_to_one_line(self):
        from agent_blame.output import render_terminal
        text = render_terminal(self._result(n_later=40))
        self.assertEqual(text.count("later commit "), 1,
                         "40 per-commit bullets must collapse to one")
        self.assertIn("40 later commits modified this file", text)

    def test_caller_evidence_not_duplicated(self):
        from agent_blame.output import render_terminal
        text = render_terminal(self._result(symbol="func"))
        # The caller appears exactly once: in the Callers section.
        self.assertEqual(text.count("src/app.py:caller"), 1)
        self.assertIn("Callers", text)

    def test_caller_evidence_kept_when_no_symbol(self):
        from agent_blame.output import render_terminal
        r = self._result(symbol=None)
        r.evidence.append({"kind": "live_caller", "commit": "",
                           "text": "confirmed live caller: other.py:caller",
                           "weight": 0.2, "is_counter": False})
        text = render_terminal(r)
        # No symbol -> no Callers section; the caller fact stays in Evidence.
        self.assertIn("confirmed live caller: other.py:caller", text)

    def test_chain_capped_in_why_capped_full_in_history(self):
        from agent_blame.output import render_terminal
        n_history = 41  # range(1, n_later + 2) with n_later=40
        why = render_terminal(self._result(n_later=40, mode="why"))
        self.assertIn(
            f"... {n_history - 25} more commit(s) in the full lineage", why)
        hist = render_terminal(self._result(n_later=40, mode="history"))
        self.assertNotIn("more commit(s) in the full lineage", hist)
        # chain lines are "  <sha>  <date>  commit N" (two spaces before the
        # subject); the evidence line "e.g. later commit ..." has one.
        self.assertEqual(hist.count("  commit "), n_history)  # full timeline


if __name__ == "__main__":
    unittest.main()
