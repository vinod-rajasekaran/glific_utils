import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import render_graph as ra  # noqa: E402
import programme_claude as uc  # noqa: E402
import programme_facts as uf  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
U = lambda n: f"00000000-0000-4000-8000-{n:012d}"  # noqa: E731


def facts():
    flows = json.loads((FIX / "flows.json").read_text())
    triggers = json.loads((FIX / "triggers.json").read_text())
    return uf.build_facts(ra.Model(flows, triggers, ra.Settings(scope_all=True, today=date(2026, 11, 13))))


def raw():
    return json.loads((FIX / "claude_output.json").read_text())


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns the queued outputs in order and records each request."""

    def __init__(self, *outputs, stop_reason="end_turn"):
        self.outputs, self.calls, self.stop_reason = list(outputs), [], stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append(kw)
        nxt = self.outputs.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        text = json.dumps(nxt)
        msg = SimpleNamespace(stop_reason=self.stop_reason, stop_details=None,
                              content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)])

        class Ctx:
            def __enter__(self_):
                return SimpleNamespace(get_final_message=lambda: msg)

            def __exit__(self_, *a):
                return False
        return Ctx()


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.out, self.problems = uc.validate(raw(), facts())
        self.ucs = {u["id"]: u for u in self.out["use_cases"]}

    def test_unknown_ids_dropped(self):
        self.assertNotIn("00000000-0000-4000-8000-999999999999", self.ucs["weekly-tips"]["flows"])
        self.assertNotIn("Survey save", [f["id"] for f in self.out["flows"]])
        self.assertEqual([e["id"] for e in self.out["edges"]], [f"edge:{U(1)}:{U(2)}:start"])
        self.assertTrue(any("999999999999" in p for p in self.problems))

    def test_unsupported_clear_statement_dropped(self):
        texts = [s["text"] for s in self.ucs["weekly-tips"]["story"]]
        self.assertNotIn("This statement cites nothing that exists.", texts)
        self.assertEqual(len(texts), 3)

    def test_double_assignment_keeps_first(self):
        self.assertIn(U(2), self.ucs["weekly-tips"]["flows"])
        self.assertNotIn(U(2), self.ucs["survey"]["flows"])

    def test_missing_flow_not_placed(self):
        self.assertEqual(self.out["not_placed"], [U(8)])
        old = next(f for f in self.out["flows"] if f["id"] == U(8))
        self.assertEqual(old["role"], "unknown")

    def test_empty_use_case_dropped(self):
        self.assertNotIn("ghost", self.ucs)
        self.assertTrue(any("Ghost" in p for p in self.problems))

    def test_unknown_system_dropped(self):
        self.assertEqual([s["host"] for s in self.out["systems"]], ["api.example.org"])

    def test_flow_use_case_follows_membership(self):
        by = {f["id"]: f for f in self.out["flows"]}
        self.assertEqual(by[U(2)]["use_case"], "weekly-tips")


class CallTest(unittest.TestCase):
    def good(self):
        out = raw()
        out["use_cases"] = [u for u in out["use_cases"] if u["id"] != "ghost"]
        out["use_cases"][0]["flows"] = [U(1), U(2), U(3), U(4)]
        out["use_cases"][0]["story"] = out["use_cases"][0]["story"][:3]
        out["use_cases"][1]["flows"] = [U(6), U(7)]
        out["use_cases"].insert(2, {"id": "drafts", "name": "Drafts", "summary": "Old.", "kind": "tests", "flows": [U(8)],
                                    "story": [], "how_it_works": [], "watch": [], "confidence": "guess"})
        out["flows"] = [f for f in out["flows"] if f["id"] != "Survey save"] + [
            {"id": U(8), "purpose": "Old draft.", "role": "leftover", "use_case": "drafts", "evidence": [f"msg:{U(8)}:1"], "confidence": "likely"}]
        out["edges"] = out["edges"][:1]
        out["systems"] = out["systems"][:1]
        return out

    def test_good_output_has_no_problems(self):
        _, problems = uc.validate(self.good(), facts())
        self.assertEqual(problems, [])

    def test_request_shape(self):
        client = FakeClient(self.good())
        uc.run_programmes(facts(), client=client)
        kw = client.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(kw["output_config"]["effort"], "high")
        self.assertEqual(kw["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(len(client.calls), 1)

    def test_repair_called_once(self):
        client = FakeClient(raw(), self.good())
        _, validated, notes = uc.run_programmes(facts(), client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("999999999999", client.calls[1]["messages"][-1]["content"])
        self.assertEqual(notes, [])
        self.assertIn("drafts", [u["id"] for u in validated["use_cases"]])

    def test_second_failure_degrades(self):
        client = FakeClient(raw(), raw())
        _, validated, notes = uc.run_programmes(facts(), client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(notes)
        self.assertIn("weekly-tips", [u["id"] for u in validated["use_cases"]])

    def test_unusable_raises(self):
        with self.assertRaises(uc.ProgrammeError):
            uc.run_programmes(facts(), client=FakeClient({}, {}))

    def test_refusal_raises(self):
        with self.assertRaises(uc.ProgrammeError):
            uc.run_programmes(facts(), client=FakeClient(self.good(), stop_reason="refusal"))

    def test_schema_is_strict(self):
        def walk(node):
            if node.get("type") == "object":
                self.assertFalse(node.get("additionalProperties", True))
                self.assertEqual(set(node["required"]), set(node["properties"]))
                for v in node["properties"].values():
                    walk(v)
            elif node.get("type") == "array":
                walk(node["items"])
        walk(copy.deepcopy(uc.SCHEMA))


if __name__ == "__main__":
    unittest.main()
