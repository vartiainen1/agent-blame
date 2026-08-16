"""Tests for target parsing (file:line / file:start-end)."""

import unittest

from agent_blame.target import TargetError, parse_target


class TestParseTarget(unittest.TestCase):

    def test_single_line(self):
        t = parse_target("src/auth/session.py:142")
        self.assertEqual(t.file, "src/auth/session.py")
        self.assertEqual(t.start_line, 142)
        self.assertEqual(t.end_line, 142)

    def test_range(self):
        t = parse_target("src/auth/session.py:130-160")
        self.assertEqual(t.start_line, 130)
        self.assertEqual(t.end_line, 160)

    def test_windows_path_with_drive_letter(self):
        t = parse_target("C:\\repo\\src\\auth.py:142")
        # Last-colon split keeps the drive letter in the path.
        self.assertEqual(t.file, "C:\\repo\\src\\auth.py")
        self.assertEqual(t.start_line, 142)

    def test_path_with_colons(self):
        t = parse_target("src/weird:name/file.py:3")
        self.assertEqual(t.file, "src/weird:name/file.py")
        self.assertEqual(t.start_line, 3)

    def test_no_line_spec(self):
        with self.assertRaises(TargetError):
            parse_target("src/auth.py")

    def test_bad_line_spec(self):
        with self.assertRaises(TargetError):
            parse_target("src/auth.py:abc")

    def test_empty_path(self):
        with self.assertRaises(TargetError):
            parse_target(":142")

    def test_empty_target(self):
        with self.assertRaises(TargetError):
            parse_target("")
        with self.assertRaises(TargetError):
            parse_target("   ")

    def test_zero_line(self):
        with self.assertRaises(TargetError):
            parse_target("src/auth.py:0")

    def test_reversed_range(self):
        with self.assertRaises(TargetError):
            parse_target("src/auth.py:10-5")

    def test_whitespace_tolerance(self):
        t = parse_target("  src/auth.py:5  ")
        self.assertEqual(t.file, "src/auth.py")
        self.assertEqual(t.start_line, 5)


if __name__ == "__main__":
    unittest.main()
