"""Phase 2C tests: caller/symbol relationships.

The most important success criterion of this phase: when agent-blame says
something calls this code, that statement is trustworthy. These tests
therefore assert exact RELATIONSHIP CLASSIFICATIONS (DIRECT_CALL vs
POSSIBLE_CALL vs TEXTUAL_MATCH) on tiny KNOWN fixture repositories - with
special attention to the false-positive cases (comments, strings,
unrelated identifiers, same-name modules, missing imports).

They also assert evidence integration (live_caller items, weights, risk
reasons) and that caller analysis is revision-aware (historical callers
are NOT found before they existed; callers deleted by a commit are marked
DELETED).
"""

import json as jsonlib
import unittest

from agent_blame.analyzer import analyze
from agent_blame.commit import analyze_commit
from agent_blame.diff import analyze_diff
from agent_blame.models import Target
from agent_blame.output import render_json, render_terminal
from agent_blame.repository import discover_repository

from tests.gitfixture import (GitFixture, make_caller_aliased_fixture,
                              make_caller_ambiguous_fixture,
                              make_caller_attribute_fixture,
                              make_caller_deleted_fixture,
                              make_caller_diff_fixture,
                              make_caller_false_positive_fixture,
                              make_caller_history_fixture,
                              make_caller_large_fixture,
                              make_caller_malicious_fixture,
                              make_caller_method_fixture,
                              make_caller_modify_commit_fixture,
                              make_caller_multiple_fixture,
                              make_caller_nested_fixture,
                              make_caller_none_fixture,
                              make_caller_removed_fixture,
                              make_caller_same_name_fixture,
                              make_caller_simple_fixture,
                              make_caller_unicode_fixture,
                              make_caller_unsupported_fixture)


class _Base(unittest.TestCase):
    fx = None

    def setUp(self):
        self.fx = self.make_fx()
        self.repo = discover_repository(self.fx.root)
        self.assertIsNotNone(self.repo)

    def tearDown(self):
        self.fx.cleanup()

    def why(self, path, line, revision="HEAD"):
        return analyze(self.repo, Target(file=path, start_line=line,
                                         end_line=line), revision=revision)

    def callers(self, res):
        return {c["symbol"]: c for c in res.callers}


class TestSimpleDirectCaller(_Base):
    """1. Simple direct caller: handle_request -> authenticate()."""

    @staticmethod
    def make_fx():
        return make_caller_simple_fixture()

    def test_direct_caller_found(self):
        res = self.why("src/auth.py", 1)
        self.assertEqual(res.symbol["name"], "authenticate")
        c = self.callers(res)["src/server.py:handle_request"]
        self.assertEqual(c["relationship"], "DIRECT_CALL")
        self.assertEqual(c["status"], "LIVE")
        self.assertEqual(c["confidence"], "HIGH")

    def test_live_caller_evidence_and_risk(self):
        res = self.why("src/auth.py", 1)
        kinds = [e["kind"] for e in res.evidence]
        self.assertIn("live_caller", kinds)
        self.assertIn("import_reference", kinds)
        risk_reasons = " ".join(res.risk.reasons)
        self.assertIn("confirmed live caller", risk_reasons)

    def test_no_false_callers_from_definition(self):
        # The def itself and its own file must not appear as a caller.
        res = self.why("src/auth.py", 1)
        self.assertNotIn("src/auth.py:authenticate", self.callers(res))


class TestMultipleCallers(_Base):
    """2. Multiple callers across two files."""

    @staticmethod
    def make_fx():
        return make_caller_multiple_fixture()

    def test_both_callers_found(self):
        res = self.why("src/auth.py", 1)
        callers = self.callers(res)
        self.assertEqual(callers["src/server.py:handle_request"]["relationship"],
                         "DIRECT_CALL")
        self.assertEqual(callers["src/worker.py:run_job"]["relationship"],
                         "DIRECT_CALL")

    def test_evidence_count_matches(self):
        res = self.why("src/auth.py", 1)
        live = [e for e in res.evidence if e["kind"] == "live_caller"]
        self.assertEqual(len(live), 2)


class TestMethodCaller(_Base):
    """3+4. Method target: instance call is POSSIBLE, class call DIRECT."""

    @staticmethod
    def make_fx():
        return make_caller_method_fixture()

    def test_instance_call_is_possible_not_direct(self):
        res = self.why("src/auth.py", 2)
        self.assertEqual(res.symbol["name"], "Auth.check")
        # NOTE: both classifications come from the SAME caller symbol
        # (handle) - inspect the raw list, not the symbol-keyed dict.
        by_rel = {(c["relationship"], c["confidence"]) for c in res.callers}
        self.assertIn(("DIRECT_CALL", "HIGH"), by_rel)   # Auth.check(a)
        self.assertIn(("POSSIBLE_CALL", "LOW"), by_rel)  # a.check()


class TestAliasedImport(_Base):
    """6. Aliased import: auth_fn() resolves to the target symbol."""

    @staticmethod
    def make_fx():
        return make_caller_aliased_fixture()

    def test_alias_call_is_direct(self):
        res = self.why("src/auth.py", 1)
        c = self.callers(res)["src/a1.py:go"]
        self.assertEqual(c["relationship"], "DIRECT_CALL")
        self.assertEqual(c["confidence"], "HIGH")


class TestAttributeCall(_Base):
    """7. Attribute call: auth.authenticate() via module import."""

    @staticmethod
    def make_fx():
        return make_caller_attribute_fixture()

    def test_attribute_call_classified(self):
        res = self.why("src/auth.py", 1)
        c = self.callers(res)["src/a2.py:go"]
        self.assertEqual(c["relationship"], "ATTRIBUTE_CALL")
        self.assertEqual(c["confidence"], "MEDIUM")


class TestNestedFunction(_Base):
    """8. Nested function: outer() is the caller of inner()."""

    @staticmethod
    def make_fx():
        return make_caller_nested_fixture()

    def test_nested_caller_found(self):
        res = self.why("src/nest.py", 2)
        self.assertEqual(res.symbol["name"], "outer.inner")
        c = self.callers(res)["src/nest.py:outer"]
        self.assertEqual(c["relationship"], "DIRECT_CALL")


class TestDeletedCaller(_Base):
    """9. Commit deleting the caller file marks it DELETED."""

    @staticmethod
    def make_fx():
        return make_caller_deleted_fixture()

    def test_caller_status_deleted(self):
        res = analyze_commit(self.repo, self.fx.shas["C"])
        found = False
        for ch in res.changes:
            for g in ch.groups:
                for c in g.analysis.get("callers", []):
                    if c["symbol"].endswith("handle_request"):
                        self.assertEqual(c["status"], "DELETED")
                        self.assertEqual(c["relationship"], "DIRECT_CALL")
                        found = True
        self.assertTrue(found, "deleted caller not found in commit analysis")


class TestCallerIntroducedLater(_Base):
    """10. Caller introduced later: absent at the earlier revision."""

    @staticmethod
    def make_fx():
        return make_caller_history_fixture()

    def test_no_caller_before_it_existed(self):
        res = self.why("src/auth.py", 1, revision=self.fx.shas["A"])
        # The symbol exists at A, but no caller existed yet - empty list,
        # not a fabricated caller.
        self.assertEqual(res.symbol["name"], "authenticate")
        self.assertEqual(res.callers, [])

    def test_caller_at_head(self):
        res = self.why("src/auth.py", 1)
        self.assertIn("src/server.py:handle_request", self.callers(res))


class TestCallerRemovedLater(_Base):
    """11. Caller removed later: at HEAD the caller is gone."""

    @staticmethod
    def make_fx():
        return make_caller_removed_fixture()

    def test_caller_present_at_intermediate_commit(self):
        res = self.why("src/auth.py", 1, revision=self.fx.shas["B"])
        self.assertIn("src/server.py:handle_request", self.callers(res))

    def test_no_caller_at_head(self):
        res = self.why("src/auth.py", 1)
        callers = self.callers(res)
        self.assertNotIn("src/server.py:handle_request", callers,
                         "the removed call must not be claimed at HEAD")


class TestNoCaller(_Base):
    """12. No callers: honest no-confirmed-callers report."""

    @staticmethod
    def make_fx():
        return make_caller_none_fixture()

    def test_no_confirmed_callers(self):
        res = self.why("src/auth.py", 1)
        self.assertEqual(res.callers, [])
        self.assertIn("No confirmed callers found.", render_terminal(res))


class TestAmbiguousCaller(_Base):
    """13. Bare call with no import: POSSIBLE, never DIRECT."""

    @staticmethod
    def make_fx():
        return make_caller_ambiguous_fixture()

    def test_possible_not_direct(self):
        res = self.why("src/auth.py", 1)
        c = self.callers(res)["src/worker.py:run"]
        self.assertEqual(c["relationship"], "POSSIBLE_CALL")
        self.assertEqual(c["confidence"], "LOW")
        live = [e for e in res.evidence if e["kind"] == "live_caller"]
        self.assertEqual(live, [], "possible callers must not count as "
                                  "confirmed live callers")


class TestSameNameTwoModules(_Base):
    """14+17. Same symbol name in two modules: only the matching module's
    usage may be credited."""

    @staticmethod
    def make_fx():
        return make_caller_same_name_fixture()

    def test_mod_a_gets_the_caller(self):
        res = self.why("src/mod_a.py", 1)
        c = self.callers(res)["src/use_a.py:go"]
        self.assertEqual(c["relationship"], "DIRECT_CALL")

    def test_mod_b_does_not_get_the_caller(self):
        res = self.why("src/mod_b.py", 1)
        self.assertNotIn("src/use_a.py:go", self.callers(res),
                         "use_a imports from mod_a - it must NOT be "
                         "attributed as a caller of mod_b")
        live = [e for e in res.evidence if e["kind"] == "live_caller"]
        self.assertEqual(live, [])


class TestFalsePositives(_Base):
    """15. Comments, strings and authenticate_other are NOT callers."""

    @staticmethod
    def make_fx():
        return make_caller_false_positive_fixture()

    def test_no_resolved_caller_from_tricks(self):
        res = self.why("src/auth.py", 1)
        callers = self.callers(res)
        for key in list(callers):
            self.assertNotIn("tricks", key,
                             f"false positive caller: {key}")
        self.assertNotIn("authenticate_other", [c["name"] for c in res.callers])

    def test_textual_match_reported_transparently(self):
        res = self.why("src/auth.py", 1)
        textual = [c for c in res.callers if c["relationship"] == "TEXTUAL_MATCH"]
        self.assertEqual(len(textual), 1)
        self.assertEqual(textual[0]["call_sites"], 1)  # tricks.py only

    def test_textual_match_has_zero_evidence_weight(self):
        res = self.why("src/auth.py", 1)
        kinds = [e["kind"] for e in res.evidence]
        self.assertNotIn("textual_match", kinds)
        # Only the introduction evidence - no caller inflation.
        self.assertEqual(kinds, ["introduced_by"])


class TestUnicodePath(_Base):
    """16. Unicode path in caller discovery."""

    @staticmethod
    def make_fx():
        return make_caller_unicode_fixture()

    def test_unicode_caller_found(self):
        res = self.why("src/auth.py", 1)
        key = "src/ünïcode/handler.py:go"
        self.assertIn(key, self.callers(res))


class TestUnsupportedLanguage(_Base):
    """17. Unsupported language: honest absence, no crash."""

    @staticmethod
    def make_fx():
        return make_caller_unsupported_fixture()

    def test_no_symbol_analysis(self):
        res = self.why("src/app.js", 1)
        self.assertIsNone(res.symbol)
        self.assertEqual(res.callers, [])
        self.assertNotIn("Callers", render_terminal(res))


class TestHistoricalRevision(_Base):
    """18. Historical revision: callers resolved at the analyzed revision."""

    @staticmethod
    def make_fx():
        return make_caller_history_fixture()

    def test_before_and_after(self):
        before = self.why("src/auth.py", 1, revision=self.fx.shas["A"])
        self.assertEqual(before.callers, [])
        after = self.why("src/auth.py", 1, revision=self.fx.shas["B"])
        self.assertIn("src/server.py:handle_request", self.callers(after))


class TestDiffIntegration(_Base):
    """19. --diff: modifying authenticate() surfaces its callers."""

    @staticmethod
    def make_fx():
        return make_caller_diff_fixture()

    def test_diff_group_has_callers(self):
        res = analyze_diff(self.repo)
        for f in res.files:
            if f.path == "src/auth.py":
                g = f.groups[0]
                a = g.analysis
                self.assertIsNotNone(a.get("symbol"))
                self.assertIn("src/server.py:handle_request",
                              {c["symbol"] for c in a["callers"]})
                return
        self.fail("src/auth.py missing from diff")


class TestCommitIntegration(_Base):
    """20. --commit: modifying authenticate() shows its before-state callers."""

    @staticmethod
    def make_fx():
        return make_caller_modify_commit_fixture()

    def test_commit_group_has_live_callers(self):
        res = analyze_commit(self.repo, self.fx.shas["C"])
        for ch in res.changes:
            if ch.path == "src/auth.py":
                g = ch.groups[0]
                a = g.analysis
                self.assertEqual(a["symbol"]["name"], "authenticate")
                self.assertIn("src/server.py:handle_request",
                              {c["symbol"] for c in a["callers"]})
                return
        self.fail("src/auth.py missing from commit analysis")


class TestMaliciousSource(_Base):
    """21. Malicious source content: output stays clean."""

    @staticmethod
    def make_fx():
        return make_caller_malicious_fixture()

    def _assert_clean(self, text):
        for ch in text:
            if ch in "\n\t ":
                continue
            self.assertGreaterEqual(ord(ch), 0x20,
                                    f"control char {ord(ch):#x} leaked")

    def test_terminal_clean(self):
        res = self.why("src/auth.py", 1)
        self.assertIn("src/caller.py:go", self.callers(res))
        self._assert_clean(render_terminal(res))

    def test_json_clean_and_valid(self):
        res = self.why("src/auth.py", 1)
        raw = render_json(res)
        self._assert_clean(raw)
        data = jsonlib.loads(raw)
        self.assertEqual(data["mode"], "why")
        self.assertIn("callers", data)
        self.assertEqual(data["callers"][0]["relationship"], "DIRECT_CALL")


class TestJsonSchema(_Base):
    """Caller JSON schema: structured, machine-readable, additive."""

    @staticmethod
    def make_fx():
        return make_caller_simple_fixture()

    def test_callers_schema(self):
        res = self.why("src/auth.py", 1)
        data = jsonlib.loads(render_json(res))
        self.assertIsNotNone(data["symbol"])
        self.assertEqual(data["symbol"]["name"], "authenticate")
        c = data["callers"][0]
        for key in ("symbol", "path", "name", "line", "call_sites",
                    "relationship", "status", "confidence", "text"):
            self.assertIn(key, c)

    def test_no_callers_has_null_symbol(self):
        res = self.why("src/app.js", 1) if False else None
        # unsupported-language case via dedicated fixture
        fx = make_caller_unsupported_fixture()
        try:
            repo = discover_repository(fx.root)
            r = analyze(repo, Target(file="src/app.js", start_line=1, end_line=1))
            data = jsonlib.loads(render_json(r))
            self.assertIsNone(data["symbol"])
            self.assertEqual(data["callers"], [])
        finally:
            fx.cleanup()

    def test_json_deterministic(self):
        res1 = self.why("src/auth.py", 1)
        res2 = self.why("src/auth.py", 1)
        self.assertEqual(render_json(res1), render_json(res2))


class TestRiskIntegration(_Base):
    """Risk reasons reflect live callers without absolute claims."""

    @staticmethod
    def make_fx():
        return make_caller_multiple_fixture()

    def test_risk_counts_callers(self):
        res = self.why("src/auth.py", 1)
        reasons = " ".join(res.risk.reasons)
        self.assertIn("2 confirmed live caller(s)", reasons)
        self.assertNotIn("unsafe", reasons)
        self.assertNotIn("safe to delete", reasons)


class TestTestFileCallerWeaker(_Base):
    """A caller in a test file is real but weaker evidence."""

    @staticmethod
    def make_fx():
        f = GitFixture()
        f.commit("Add auth + test", {
            "src/auth.py": "def authenticate():\n    return True\n",
            "tests/test_auth.py": (
                "from auth import authenticate\n"
                "\n"
                "def test_auth():\n"
                "    authenticate()\n"
            ),
        })
        return f

    def test_test_caller_weight_lower(self):
        res = self.why("src/auth.py", 1)
        live = [e for e in res.evidence if e["kind"] == "live_caller"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["weight"], 0.10,
                         "test-file callers carry a weaker weight")


class TestSecurityNoExecInSymbols(unittest.TestCase):
    """The symbol analysis must parse, never execute, source."""

    def test_no_exec_eval_shell_in_symbols(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..",
                            "agent_blame", "symbols.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("shell=True", src)
        self.assertNotIn("shell=", src)
        self.assertNotIn("os.system", src)
        self.assertNotIn("subprocess.call", src)
        # ast.parse is allowed; exec/eval of source is not.
        self.assertNotIn("exec(", src)
        self.assertNotIn("eval(", src)
        self.assertNotIn("__import__(", src)
        self.assertIn("ast.parse", src)


class TestNoTracebackOnMalformedSource(_Base):
    """Malformed Python source must be skipped, never crash."""

    @staticmethod
    def make_fx():
        f = GitFixture()
        f.commit("Add broken + valid", {
            "src/auth.py": "def authenticate():\n    return True\n",
            "src/broken.py": "def broken(:\n    this is not python !!!\n",
            "src/caller.py": (
                "from auth import authenticate\n"
                "\n"
                "def go():\n"
                "    authenticate()\n"
            ),
        })
        return f

    def test_malformed_file_skipped(self):
        res = self.why("src/auth.py", 1)
        self.assertIn("src/caller.py:go", self.callers(res))


if __name__ == "__main__":
    unittest.main()
