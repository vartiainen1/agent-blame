"""Tests for target parsing: the Phase 6C forms (bare file, file:function,
bare sha) plus the original file:line / file:start-end contract."""

import unittest

from agent_blame.target import (TargetError, classify_target, is_sha_like,
                                parse_target)


class TestClassifyTarget(unittest.TestCase):
    """Pure classification of the four supported target forms."""

    def test_file_line(self):
        cs = classify_target("src/auth/session.py:142")
        self.assertEqual(cs.kind, "file_line")
        self.assertEqual(cs.path, "src/auth/session.py")
        self.assertEqual((cs.start_line, cs.end_line), (142, 142))

    def test_file_range(self):
        cs = classify_target("src/auth/session.py:130-160")
        self.assertEqual(cs.kind, "file_line")
        self.assertEqual((cs.start_line, cs.end_line), (130, 160))

    def test_file_function(self):
        cs = classify_target("app/retry.py:retry")
        self.assertEqual(cs.kind, "file_function")
        self.assertEqual(cs.path, "app/retry.py")
        self.assertEqual(cs.line_part, "retry")

    def test_file_function_qualified_name(self):
        cs = classify_target("app/retry.py:Server.handle")
        self.assertEqual(cs.kind, "file_function")
        self.assertEqual(cs.line_part, "Server.handle")

    def test_file_function_dunder(self):
        cs = classify_target("app/retry.py:__init__")
        self.assertEqual(cs.kind, "file_function")
        self.assertEqual(cs.line_part, "__init__")

    def test_bare_file(self):
        cs = classify_target("src/auth.py")
        self.assertEqual(cs.kind, "bare_file")
        self.assertEqual(cs.path, "src/auth.py")

    def test_bare_sha(self):
        cs = classify_target("fd13816d")
        self.assertEqual(cs.kind, "sha")
        self.assertEqual(cs.path, "fd13816d")

    def test_sha_uppercase(self):
        self.assertEqual(classify_target("DEADBEEF").kind, "sha")

    def test_sha_min_and_max_length(self):
        self.assertEqual(classify_target("abcd").kind, "sha")
        full = "a" * 40
        self.assertEqual(classify_target(full).kind, "sha")

    def test_sha_like_shape_only(self):
        # Shape decides sha-vs-file, but the REPO decides validity: these
        # are never sha-shaped, so they can never be hijacked as commits.
        self.assertFalse(is_sha_like("dead/beef"))
        self.assertFalse(is_sha_like("deadbeef.py"))
        self.assertFalse(is_sha_like("src/auth.py"))
        self.assertFalse(is_sha_like("abc"))          # too short for git
        self.assertFalse(is_sha_like("deadbeefg"))    # non-hex char
        self.assertTrue(is_sha_like("deadbeef"))

    def test_empty_path_colon(self):
        with self.assertRaises(TargetError):
            classify_target(":142")

    def test_bad_function_charset(self):
        # A name is a Python identifier (plus dots for qualified names);
        # anything else is a malformed target, never a function guess.
        with self.assertRaises(TargetError):
            classify_target("app/retry.py:foo-bar")
        with self.assertRaises(TargetError):
            classify_target("app/retry.py:1-")
        with self.assertRaises(TargetError):
            classify_target("app/retry.py:123abc")

    def test_zero_and_reversed_ranges_still_rejected(self):
        with self.assertRaises(TargetError):
            classify_target("src/auth.py:0")
        with self.assertRaises(TargetError):
            classify_target("src/auth.py:10-5")

    def test_empty_target(self):
        with self.assertRaises(TargetError):
            classify_target("")
        with self.assertRaises(TargetError):
            classify_target("   ")

    def test_windows_drive_letter_kept_in_path(self):
        cs = classify_target("C:\\repo\\src\\auth.py:142")
        self.assertEqual(cs.kind, "file_line")
        self.assertEqual(cs.path, "C:\\repo\\src\\auth.py")
        self.assertEqual(cs.start_line, 142)

    def test_path_with_colons(self):
        cs = classify_target("src/weird:name/file.py:3")
        self.assertEqual(cs.kind, "file_line")
        self.assertEqual(cs.path, "src/weird:name/file.py")
        self.assertEqual(cs.start_line, 3)


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

    def test_function_form_still_rejected_here(self):
        # parse_target keeps its original contract: only numeric forms.
        with self.assertRaises(TargetError):
            parse_target("src/auth.py:abc")

    def test_sha_form_still_rejected_here(self):
        with self.assertRaises(TargetError):
            parse_target("fd13816d")


class TestIsShaLike(unittest.TestCase):

    def test_valid_shas(self):
        for s in ("deadbeef", "fd13816d", "ABCDEF12", "a" * 40, "abcd"):
            self.assertTrue(is_sha_like(s), s)

    def test_non_shas(self):
        for s in ("abc", "deadbeefg", "dead/beef", "deadbeef.py",
                  "src/auth.py", "HEAD", "dead-beef", ""):
            self.assertFalse(is_sha_like(s), s)


if __name__ == "__main__":
    unittest.main()
