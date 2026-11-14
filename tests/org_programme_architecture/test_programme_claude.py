"""The Claude call (with a stand-in client) and the validation of its answer."""
import copy
import json
import unittest
from datetime import date
from types import SimpleNamespace

from tests.org_programme_architecture.helpers import FIX, U, model, facts, raw, programmes_raw, validated, FakeClient, stream_client  # also puts org_programme_architecture on sys.path
from glific_common.org_facts import model as md  # noqa: E402
import programme_claude as uc  # noqa: E402
from glific_common.org_facts import facts as uf  # noqa: E402
import render_org_map as ru  # noqa: E402


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

    def test_other_models_and_fallbacks(self):
        client = FakeClient(raw(), self.good())
        uc.run_programmes(facts(), client=client, model="claude-haiku-5-5")
        self.assertEqual([c["model"] for c in client.calls], ["claude-haiku-5-5"] * 2)   # the repair uses it too
        self.assertNotIn("fallbacks", client.calls[0])   # Haiku has no server-side fallback
        client = FakeClient(self.good())
        uc.run_programmes(facts(), client=client, model="claude-sonnet-5-5")
        self.assertEqual(client.calls[0]["fallbacks"], "default")

    def test_usage_is_recorded(self):
        msg = SimpleNamespace(stop_reason="end_turn", stop_details=None, model="claude-opus-5-5",
                              usage=SimpleNamespace(input_tokens=10, output_tokens=20, cache_read_input_tokens=0,
                                                    cache_creation_input_tokens=5),
                              content=[SimpleNamespace(type="text", text=json.dumps(self.good()))])
        out = uc.call_claude(facts(), client=stream_client(msg))
        self.assertEqual(out["_meta"], {"model": "claude-opus-5-5", "input_tokens": 10, "output_tokens": 20,
                                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5})

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


class ProgrammeValidateTest(unittest.TestCase):
    def setUp(self):
        _, _, self.v, self.p, _ = validated("claude_output_programmes.json")
        self.pr = {x["id"]: x for x in self.v["programmes"]}

    def test_parts_checked(self):
        self.assertEqual(self.pr["healthy-families"]["parts"], ["weekly-tips", "survey"])
        self.assertTrue(any("not-a-use-case" in x for x in self.p))

    def test_part_in_two_programmes_keeps_first(self):
        self.assertEqual(self.pr["tests"]["parts"], ["tests"])
        self.assertTrue(any("survey" in x.lower() and "already" in x for x in self.p))

    def test_empty_programme_dropped(self):
        self.assertNotIn("empty", self.pr)

    def test_programme_statements_validated(self):
        self.assertEqual(len(self.pr["healthy-families"]["story"]), 1)

    def test_old_answer_wraps_each_use_case(self):
        _, _, v, p, _ = validated("claude_output.json")
        self.assertEqual([x["parts"] for x in v["programmes"]], [[u["id"]] for u in v["use_cases"]])
        self.assertFalse(any("programme" in x.lower() for x in p))

    def test_use_case_left_out_gets_own_programme(self):
        raw = json.loads((FIX / "claude_output_programmes.json").read_text())
        raw["programmes"] = raw["programmes"][:1]          # "tests" use case now in no programme
        flows = json.loads((FIX / "flows.json").read_text())
        triggers = json.loads((FIX / "triggers.json").read_text())
        m = md.Model(flows, triggers, md.Settings(today=date(2026, 11, 13)))
        v, p = uc.validate(raw, uf.build_facts(m))
        self.assertIn(["tests"], [x["parts"] for x in v["programmes"]])
        self.assertTrue(any("not in any programme" in x for x in p))

    def test_schema_has_programmes(self):
        self.assertIn("programmes", uc.SCHEMA["properties"])


class CompactSchemaTest(unittest.TestCase):
    def test_schema_has_two_statement_lists(self):
        self.assertLessEqual(json.dumps(uc.SCHEMA).count('"refs"'), 4)   # 2 statement lists, each names refs twice

    def test_statements_with_sections_are_split(self):
        raw = json.loads((FIX / "claude_output_programmes.json").read_text())
        for u in raw["use_cases"]:
            u["statements"] = ([dict(s, section="story") for s in u.pop("story")] +
                               [dict(s, section="how_it_works") for s in u.pop("how_it_works")] +
                               [dict(s, section="watch") for s in u.pop("watch")])
        for p in raw["programmes"]:
            p["statements"] = [dict(s, section="story") for s in p.pop("story")] + [dict(s, section="watch") for s in p.pop("watch")]
        flows = json.loads((FIX / "flows.json").read_text())
        triggers = json.loads((FIX / "triggers.json").read_text())
        m = md.Model(flows, triggers, md.Settings(today=date(2026, 11, 13)))
        v, _ = uc.validate(raw, uf.build_facts(m))
        tips = next(u for u in v["use_cases"] if u["id"] == "weekly-tips")
        self.assertEqual((len(tips["story"]), len(tips["how_it_works"]), len(tips["watch"])), (3, 1, 1))
        prog = next(p for p in v["programmes"] if p["id"] == "healthy-families")
        self.assertEqual((len(prog["story"]), len(prog["watch"])), (1, 1))


class RepairFailureKeepsFirstAnswer(unittest.TestCase):
    def test_failed_repair_keeps_first_answer(self):
        client = FakeClient(raw(), RuntimeError("network down"))
        got_raw, validated, notes = uc.run_programmes(facts(), client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("weekly-tips", [u["id"] for u in validated["use_cases"]])
        self.assertTrue(any("999999999999" in n for n in notes))
        self.assertTrue(any("repair" in n.lower() for n in notes))


class InventedEvidenceReported(unittest.TestCase):
    def test_unknown_evidence_on_purpose_and_summary_is_reported(self):
        r = raw()
        r["flows"][0]["evidence"].append("msg:invented:9")
        r["org_summary"]["evidence"].append("sticky:invented:1")
        _, problems = uc.validate(r, facts())
        self.assertTrue(any("msg:invented:9" in p for p in problems))
        self.assertTrue(any("sticky:invented:1" in p for p in problems))


class FallbackTextBlocks(unittest.TestCase):
    def test_text_blocks_are_joined(self):
        good = json.dumps({"use_cases": []})
        msg = SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[
            SimpleNamespace(type="text", text=good[:7]), SimpleNamespace(type="fallback"), SimpleNamespace(type="text", text=good[7:])])

        class Ctx:
            def __enter__(self):
                return SimpleNamespace(get_final_message=lambda: msg)

            def __exit__(self, *a):
                return False
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Ctx())))
        self.assertEqual(uc.call_claude(facts(), client), {"use_cases": []})


class SlugMapping(unittest.TestCase):
    def test_parts_follow_slugged_use_case_ids(self):
        r = programmes_raw()
        r["use_cases"][0]["id"] = "Weekly_Tips"
        r["programmes"][0]["parts"] = ["Weekly_Tips", "survey"]
        v, problems = uc.validate(r, facts())
        first = next(p for p in v["programmes"] if p["name"] == "Healthy families programme")
        self.assertEqual(first["parts"], ["weekly-tips", "survey"])
        self.assertFalse(any("Weekly_Tips" in p for p in problems))


class RepairOnlyWhenItMatters(unittest.TestCase):
    def good(self):
        return CallTest.good(CallTest())

    def test_cosmetic_problem_does_not_repair(self):
        out = self.good()
        out["flows"] = [f for f in out["flows"] if f["id"] != U(8)]     # one flow without a purpose
        client = FakeClient(out)
        _, _, notes = uc.run_programmes(facts(), client=client)
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(any("no purpose" in n for n in notes))

    def test_worse_repair_keeps_first_answer(self):
        first = raw()
        worse = raw()
        worse["use_cases"] = worse["use_cases"][:1] + [{"id": "x", "name": "X", "summary": "", "kind": "journey", "flows": ["nope"],
                                                         "story": [], "how_it_works": [], "watch": [], "confidence": "guess"}]
        client = FakeClient(first, worse)
        _, validated, notes = uc.run_programmes(facts(), client=client)
        self.assertIn("survey", [u["id"] for u in validated["use_cases"]])
        self.assertTrue(any("first answer" in n for n in notes))


class DuplicateFlowInUseCase(unittest.TestCase):
    def test_repeat_inside_one_use_case_dropped(self):
        r = raw()
        r["use_cases"][0]["flows"] = [U(1), U(1), U(3)]
        v, problems = uc.validate(r, facts())
        tips = next(u for u in v["use_cases"] if u["id"] == "weekly-tips")
        self.assertEqual(tips["flows"], [U(1), U(3)])
        self.assertTrue(any("twice" in p for p in problems))


class StatementChecks(unittest.TestCase):
    def test_bad_or_missing_confidence_becomes_guess(self):
        r = raw()
        r["use_cases"][0]["story"][0]["confidence"] = "reading From-the-export"
        del r["use_cases"][0]["story"][1]["confidence"]
        v, _ = uc.validate(r, facts())
        story = next(u for u in v["use_cases"] if u["id"] == "weekly-tips")["story"]
        self.assertEqual([s["confidence"] for s in story[:2]], ["guess", "guess"])


class SaveAnswersOnFailure(unittest.TestCase):
    def test_raw_answer_attached_to_error(self):
        with self.assertRaises(uc.ProgrammeError) as cm:
            uc.run_programmes(facts(), client=FakeClient({"use_cases": []}, {"use_cases": []}))
        self.assertEqual(cm.exception.raw, {"use_cases": []})


class ModelNamedFromAnswer(unittest.TestCase):
    def test_model_recorded(self):
        out = raw()
        msg = SimpleNamespace(stop_reason="end_turn", stop_details=None, model="claude-opus-4-8",
                              content=[SimpleNamespace(type="text", text=json.dumps(out))])

        class Ctx:
            def __enter__(self):
                return SimpleNamespace(get_final_message=lambda: msg)

            def __exit__(self, *a):
                return False
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Ctx())))
        got = uc.call_claude(facts(), client)
        self.assertEqual(got["_meta"]["model"], "claude-opus-4-8")
        m = model()
        f = uf.build_facts(m)
        v, p = uc.validate(got, f)
        self.assertIn("claude-opus-4-8", ru.render_org_map(m, f, v, p))


class FactsCached(unittest.TestCase):
    def test_facts_block_has_cache_control(self):
        client = FakeClient(raw())
        uc.call_claude(facts(), client)
        content = client.calls[0]["messages"][0]["content"]
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})


class EvidenceTypes(unittest.TestCase):
    def test_string_evidence_is_not_read_letter_by_letter(self):
        r = raw()
        r["flows"][0]["evidence"] = f"msg:{U(1)}:1"
        r["org_summary"]["evidence"] = "sticky:x:1"
        v, problems = uc.validate(r, facts())
        self.assertEqual(next(f for f in v["flows"] if f["id"] == U(1))["evidence"], [])
        self.assertEqual(v["org_summary"]["evidence"], [])
        self.assertFalse(any("IDs m, s" in p or "IDs s, t" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()


class NumericIds(unittest.TestCase):
    def test_numeric_use_case_ids_in_parts(self):
        r = programmes_raw()
        r["use_cases"][0]["id"], r["use_cases"][1]["id"] = 1, 2
        r["programmes"][0]["parts"] = [1, 2]
        v, problems = uc.validate(r, facts())
        first = next(p for p in v["programmes"] if p["name"] == "Healthy families programme")
        self.assertEqual(len(first["parts"]), 2)
