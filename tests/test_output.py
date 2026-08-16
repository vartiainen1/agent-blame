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


if __name__ == "__main__":
    unittest.main()
