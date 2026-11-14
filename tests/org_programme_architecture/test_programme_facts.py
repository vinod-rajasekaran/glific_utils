"""The facts sent to Claude: shape, IDs, excerpts and masked names."""
import json
import unittest
from datetime import date

from tests.org_programme_architecture.helpers import SETTINGS, load, model, facts, by_name  # also puts org_programme_architecture on sys.path
from glific_common.org_facts import model as md  # noqa: E402
import programme_claude as uc  # noqa: E402
from glific_common.org_facts import facts as uf  # noqa: E402


class FactsTest(unittest.TestCase):
    def test_facts_shape(self):
        f = facts()
        self.assertEqual(len(f["flows"]), 8)
        ids = [e["id"] for fl in f["flows"] for e in fl["excerpts"]]
        self.assertEqual(len(ids), len(set(ids)))
        save = next(fl for fl in f["flows"] if fl["name"] == "Survey save")
        sticky = [e for e in save["excerpts"] if e["kind"] == "sticky"]
        self.assertTrue(sticky)
        self.assertNotRegex(sticky[0]["text"], r"\d{8}")
        self.assertNotIn("Asha", json.dumps(f, ensure_ascii=False))

    def test_starts_and_leads(self):
        f = facts()
        by = {fl["name"]: fl for fl in f["flows"]}
        self.assertEqual({s["kind"] for s in by["Weekly tip"]["starts_from"]}, {"trigger"})
        self.assertEqual(by["Old draft"]["starts_from"][0]["kind"], "none")
        self.assertIn(by["Profile"]["id"], [l["ref"] for l in by["Welcome"]["leads_to"] if l["kind"] == "flow"])
        self.assertIn("group:Members", [l["ref"] for l in by["Profile"]["leads_to"] if l["kind"] == "group"])

    def test_ids_resolve(self):
        f = facts()
        known = {fl["id"] for fl in f["flows"]} | {g["id"] for g in f["groups"]} | {t["id"] for t in f["triggers"]}
        for e in f["edges"]:
            self.assertIn(e["from"], known)
            self.assertIn(e["to"], known)
        self.assertEqual(f["hosts"], ["api.example.org"])

    def test_facts_json_has_no_secrets(self):
        text = json.dumps(facts(), ensure_ascii=False)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("[redacted]", text)
        self.assertNotIn("abc123", text)
        self.assertNotIn("lead@example.org", text)


class SizeBudget(unittest.TestCase):
    def test_excerpts_capped_with_stickies_first(self):
        flow = {"nodes": [{"actions": [{"type": "send_msg", "text": f"message {i}"} for i in range(30)]}],
                "ui": {"stickies": {"s": {"title": "Note", "body": "what this flow is for"}}}}
        ex = uf._excerpts(flow, "u", set())
        self.assertLessEqual(len(ex), uf.MAX_EXCERPTS)
        self.assertEqual(ex[0]["kind"], "sticky")

    def test_output_budget(self):
        self.assertEqual(uc.MAX_TOKENS, 128000)


class MissingGroups(unittest.TestCase):
    def test_groups_from_routers_and_inactive_triggers(self):
        names = {g["name"] for g in uf.build_facts(model(project="Demo"))["groups"]}
        self.assertIn("Staff", names)
        self.assertIn("Old cohort", names)


class BadWebhookUrl(unittest.TestCase):
    def test_build_facts_survives_bad_url(self):
        flows, triggers = load()
        flows[3]["nodes"][1]["actions"][0]["url"] = "https://[bad-host/path"
        m = md.Model(flows, triggers, md.Settings(today=date(2026, 11, 13)))
        uf.build_facts(m)


class InteractiveText(unittest.TestCase):
    def test_scalar_text_does_not_crash(self):
        for text in ("5", "[1,2]", "null"):
            uf._interactive_text({"name": "Menu", "text": text})

    def test_list_body_kept(self):
        out = uf._interactive_text({"name": "Menu", "text": json.dumps({"type": "list", "body": "Pick a topic", "items": []})})
        self.assertIn("Pick a topic", out)


class FactsUseMaskedNames(unittest.TestCase):
    def test_keywords_and_router_groups_masked(self):
        flows, triggers = load()
        w = by_name(flows, "Welcome")
        w["keywords"] = ["hi", "call9876500111", "9876500112"]
        w["nodes"][0]["router"]["cases"][0]["arguments"] = ["g9", "Staff 9876500113"]
        text = json.dumps(uf.build_facts(model(flows, triggers)), ensure_ascii=False)
        for seed in ("9876500112", "9876500113"):
            self.assertNotIn(seed, text, seed)

    def test_facts_reuse_model_staff(self):
        m = model()
        m.staff = {"Welcome"}                 # a staff name the export does not contain
        f = uf.build_facts(m)
        self.assertNotIn("Welcome to the Healthy", json.dumps(f))


class SettingsFactsTest(unittest.TestCase):
    def test_facts_setting_start(self):
        f = uf.build_facts(model(org=SETTINGS))
        old = next(x for x in f["flows"] if x["name"] == "Old draft")
        self.assertEqual([s["kind"] for s in old["starts_from"]], ["setting"])
        self.assertIn("default flow", old["starts_from"][0]["text"].lower())


if __name__ == "__main__":
    unittest.main()
