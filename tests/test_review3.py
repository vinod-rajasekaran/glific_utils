"""Tests for the deeper security (S1-S6) and code (C1-C8, M1-M4) reviews."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import glific_get_flows as gf  # noqa: E402
import programme_claude as uc  # noqa: E402
import programme_facts as uf  # noqa: E402
import render_graph as ra  # noqa: E402
import render_programmes as ru  # noqa: E402
from tests.test_programme_claude import FakeClient, U, facts, raw  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
TODAY = date(2026, 11, 13)


def load():
    return json.loads((FIX / "flows.json").read_text()), json.loads((FIX / "triggers.json").read_text())


def model(flows=None, triggers=None, org=None, **kw):
    f, t = load()
    return ra.Model(flows or f, triggers or t, ra.Settings(today=TODAY, **kw), org=org)


def by_name(flows, name):
    return next(f for f in flows if f["name"] == name)


def hostile():
    """The fixture with personal data and secrets planted in structural fields."""
    flows, triggers = load()
    w = by_name(flows, "Welcome")
    w["nodes"][0]["router"] = {"type": "switch", "operand": "@contact.phone",
                               "categories": [{"uuid": "c1", "name": "919876500001", "exit_uuid": "wel-e0"},
                                              {"uuid": "c2", "name": "Staff anil@example.org", "exit_uuid": "wel-e0"}],
                               "cases": []}
    w["nodes"][0]["actions"].append({"type": "add_input_labels", "uuid": "l1", "labels": [{"name": "call 9876512345"}]})
    w["nodes"][0]["actions"].append({"type": "open_ticket", "uuid": "t1", "topic": "Escalate to Meena 9876500003",
                                     "assignee": {"name": "Meena Rao"}})
    w["name"] = "Welcome 9876500009"
    w["ui"]["stickies"] = {"s": {"title": "Auth", "body": "Bearer SECRETBEARER123 key sk_live_ABC123SECRETxyz"}}
    return flows, triggers


SEEDS = ("919876500001", "anil@example.org", "9876512345", "9876500003", "Meena", "9876500009",
         "SECRETBEARER123", "sk_live_ABC123SECRETxyz")


class S1StructuralFieldsMasked(unittest.TestCase):
    def test_facts_and_page_have_no_planted_pii(self):
        flows, triggers = hostile()
        m = model(flows, triggers, scope_all=True)
        text = json.dumps(uf.build_facts(m), ensure_ascii=False)
        page, _ = ra.render_html(flows, triggers, ra.Settings(today=TODAY))
        for seed in SEEDS[:6]:
            self.assertNotIn(seed, text, seed)
            self.assertNotIn(seed, page, seed)


class S2StickySecrets(unittest.TestCase):
    def test_exporter_scrubs_ui(self):
        definition = {"nodes": [], "_ui": {"stickies": {"s": {"body": "Bearer SECRETBEARER123"}}}}
        gf.redact_definition(definition)
        self.assertNotIn("SECRETBEARER123", json.dumps(definition))

    def test_clean_text_masks_tokens(self):
        out = uf.clean_text("Bearer SECRETBEARER123 key sk_live_ABC123SECRETxyz and AIzaSyA1234567890abcdefghij", set())
        for s in ("SECRETBEARER123", "sk_live_ABC123SECRETxyz", "AIzaSyA1234567890abcdefghij"):
            self.assertNotIn(s, out)

    def test_redact_file_covers_ui(self):
        p = Path(tempfile.mkdtemp()) / "flows.json"
        p.write_text(json.dumps([{"nodes": [], "ui": {"stickies": {"s": {"body": "Bearer SECRETBEARER123"}}}}]))
        gf.redact_file(p)
        self.assertNotIn("SECRETBEARER123", p.read_text())


class S3BareLinks(unittest.TestCase):
    def test_bare_host_with_path_cut_to_host(self):
        out = uf.clean_text("see bit.ly/secretdoc or docs.google.com/spreadsheets/d/SHEETID12345 now", set())
        self.assertNotIn("SHEETID12345", out)
        self.assertNotIn("secretdoc", out)
        self.assertIn("docs.google.com", out)

    def test_plain_sentences_untouched(self):
        self.assertEqual(uf.clean_text("Rest well. Drink water.", set()), "Rest well. Drink water.")


class S4C6StatementChecks(unittest.TestCase):
    def test_bad_or_missing_confidence_becomes_guess(self):
        r = raw()
        r["use_cases"][0]["story"][0]["confidence"] = "reading From-the-export"
        del r["use_cases"][0]["story"][1]["confidence"]
        v, _ = uc.validate(r, facts())
        story = next(u for u in v["use_cases"] if u["id"] == "weekly-tips")["story"]
        self.assertEqual([s["confidence"] for s in story[:2]], ["guess", "guess"])


class S5PromptInjection(unittest.TestCase):
    def test_prompt_says_excerpts_are_data(self):
        self.assertIn("never instructions", (ROOT / "org_programme_architecture" / "PROGRAMME_PROMPT.md").read_text())

    def test_role_badge_marked_as_claude(self):
        m = model(scope_all=True)
        f = uf.build_facts(m)
        v, p = uc.validate(raw(), f)
        page = ru.render_programme_page(m, f, v, p, m.st)
        self.assertIn('class="role claude', page)


class S6WebhookPaths(unittest.TestCase):
    def test_schemeless_url_not_printed_whole(self):
        d = ra.webhook_desc({"url": "hooks.example.com/services/T0000/B0000/SECRETPATHTOKEN?x=1"})
        self.assertNotIn("SECRETPATHTOKEN", d)

    def test_mixed_case_last_segment_hidden(self):
        self.assertNotIn("SecretAlphaToken", ra.webhook_desc({"url": "https://hooks.example.com/services/SecretAlphaToken"}))

    def test_glific_function_names_kept(self):
        self.assertIn("filesearch-gpt", ra.webhook_desc({"url": "filesearch-gpt"}))


class C1CallersAcrossExport(unittest.TestCase):
    def test_filler_with_real_caller_is_not_no_start(self):
        flows, triggers = load()
        for f in flows:
            f["tag"] = {"label": "Only"} if f["name"] == "Weekly tip" else None
        m = model(flows, triggers, tag="Only")
        profile = next(u for u in m.flows if m.name(u) == "Profile")
        self.assertIn(profile, m.view.on_map)
        self.assertNotIn(profile, m.view.no_start)


class C2C3SettingFlows(unittest.TestCase):
    ORG = {"outOfOffice": {"defaultFlowId": "008"}}

    def test_default_flow_on_graph_without_tag(self):
        m = model(org=self.ORG)
        old = next(u for u in m.flows if m.name(u) == "Old draft")
        self.assertIn(old, m.view.on_map)
        self.assertIn(old, m.view.setting_flows)

    def test_tagged_setting_flow_on_graph(self):
        flows, triggers = load()
        by_name(flows, "Old draft")["tag"] = {"label": "Demo"}
        m = model(flows, triggers, org=self.ORG, tag="Demo")
        old = next(u for u in m.flows if m.name(u) == "Old draft")
        self.assertIn(old, m.view.setting_flows)


class C4CapKeepsEntryFlows(unittest.TestCase):
    def test_entry_flows_survive_the_cap(self):
        import model as model_module
        saved = model_module.GRAPH_CAP
        model_module.GRAPH_CAP = 4
        try:
            m = model(scope_all=True)
        finally:
            model_module.GRAPH_CAP = saved
        self.assertLessEqual(len(m.view.on_map), 6)        # the cap is really applied (plus group fillers)
        for name in ("Weekly tip", "Welcome", "Survey start"):
            self.assertIn(next(u for u in m.flows if m.name(u) == name), m.view.on_map, name)


class C5InteractiveText(unittest.TestCase):
    def test_scalar_text_does_not_crash(self):
        for text in ("5", "[1,2]", "null"):
            uf._interactive_text({"name": "Menu", "text": text})

    def test_list_body_kept(self):
        out = uf._interactive_text({"name": "Menu", "text": json.dumps({"type": "list", "body": "Pick a topic", "items": []})})
        self.assertIn("Pick a topic", out)


class C7SaveAnswersOnFailure(unittest.TestCase):
    def test_raw_answer_attached_to_error(self):
        with self.assertRaises(uc.ProgrammeError) as cm:
            uc.run_programmes(facts(), client=FakeClient({"use_cases": []}, {"use_cases": []}))
        self.assertEqual(cm.exception.raw, {"use_cases": []})


class C8HostPills(unittest.TestCase):
    def test_pills_use_parsed_hosts(self):
        flows, triggers = load()
        by_name(flows, "Ask AI")["nodes"][1]["actions"][0]["url"] = "https://[bad-host/path"
        m = model(flows, triggers, scope_all=True)
        f = uf.build_facts(m)
        v, p = uc.validate(raw(), f)
        page = ru.render_programme_page(m, f, v, p, m.st)
        self.assertNotIn('>an</span>', page)


class C11NoDuplicateGroupEdges(unittest.TestCase):
    def test_two_triggers_one_group_edge(self):
        flows, triggers = load()
        extra = copy.deepcopy(next(t for t in triggers if t["isActive"]))
        extra["id"] = "599"
        m = model(flows, triggers + [extra], scope_all=True)
        gt = [e for e in m.view.edges(m) if e[2] == "gt"]
        self.assertEqual(len(gt), len(set(map(tuple, gt))))


class M1DataEdgeMeanings(unittest.TestCase):
    def test_data_edge_meaning_shown(self):
        m = model(scope_all=True)
        f = uf.build_facts(m)
        r = raw()
        r["edges"].append({"id": f"edge:{U(2)}:{U(3)}:data", "meaning": "hands the stage to the weekly tip"})
        v, p = uc.validate(r, f)
        self.assertIn("hands the stage to the weekly tip", ru.render_programme_page(m, f, v, p, m.st))


class M2ModelNamedFromAnswer(unittest.TestCase):
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
        m = model(scope_all=True)
        f = uf.build_facts(m)
        v, p = uc.validate(got, f)
        self.assertIn("claude-opus-4-8", ru.render_programme_page(m, f, v, p, m.st))


class M3FactsCached(unittest.TestCase):
    def test_facts_block_has_cache_control(self):
        client = FakeClient(raw())
        uc.call_claude(facts(), client)
        content = client.calls[0]["messages"][0]["content"]
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})


class M4DeadCode(unittest.TestCase):
    def test_no_grid_leftovers(self):
        src = (ROOT / "org_programme_architecture" / "render_graph.py").read_text()
        for leftover in ("#wires", ".wire{", ".canvas{", 'attrs = "data-static"'):
            self.assertNotIn(leftover, src)


if __name__ == "__main__":
    unittest.main()


class OverMasking(unittest.TestCase):
    def test_number_ranges_are_not_phones(self):
        self.assertEqual(uf.clean_text("birth_weight (1 - 2500 or 2501 - 4000)", set()), "birth_weight (1 - 2500 or 2501 - 4000)")

    def test_phones_still_masked(self):
        for p in ("+91 98765 43210", "98765-43210", "(022) 2345 6789", "98765.43210", "9876543210"):
            self.assertNotRegex(uf.clean_text(f"call {p} now", set()), r"\d{4}", p)

    def test_cloud_run_host_kept(self):
        host = "volunteer-digital-onboarding-238853749053.europe-west1.run.app"
        self.assertEqual(uf.clean_text(f"calls {host} (validate)", set()), f"calls {host} (validate)")
        self.assertIn(host, ra.webhook_desc({"url": f"https://{host}/validate"}))
        m = model(scope_all=True)
        self.assertNotIn("[secret]", json.dumps(uf.build_facts(m)))


class EvidenceTypes(unittest.TestCase):
    def test_string_evidence_is_not_read_letter_by_letter(self):
        r = raw()
        r["flows"][0]["evidence"] = f"msg:{U(1)}:1"
        r["org_summary"]["evidence"] = "sticky:x:1"
        v, problems = uc.validate(r, facts())
        self.assertEqual(next(f for f in v["flows"] if f["id"] == U(1))["evidence"], [])
        self.assertEqual(v["org_summary"]["evidence"], [])
        self.assertFalse(any("IDs m, s" in p or "IDs s, t" in p for p in problems), problems)
