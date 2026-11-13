import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import render_graph as ra  # noqa: E402
import programme_facts as uf  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def facts():
    flows = json.loads((FIX / "flows.json").read_text())
    triggers = json.loads((FIX / "triggers.json").read_text())
    m = ra.Model(flows, triggers, ra.Settings(scope_all=True, today=date(2026, 11, 13)))
    return uf.build_facts(m)


class CleanTextTest(unittest.TestCase):
    def test_masks_phone_and_email(self):
        out = uf.clean_text("call 9876543210 or +91 98765-43210 or a@b.org", set())
        self.assertNotRegex(out, r"\d{6}")
        self.assertNotIn("a@b.org", out)

    def test_strips_staff_names(self):
        self.assertEqual(uf.clean_text("Ask Asha Rao today", {"Asha Rao"}), "Ask a staff contact today")

    def test_url_to_host(self):
        self.assertEqual(uf.clean_text("see https://docs.google.com/x/y?z=1 now", set()), "see docs.google.com now")

    def test_keeps_expressions(self):
        self.assertEqual(uf.clean_text("Hi @contact.name, week @fields.week_number", set()),
                         "Hi @contact.name, week @fields.week_number")

    def test_cuts_by_characters(self):
        text = "नमस्ते दुनिया " * 200
        out = uf.clean_text(text, set())
        self.assertLessEqual(len(out), 201)
        self.assertTrue(out.endswith("…"))
        out.encode("utf-8").decode("utf-8")

    def test_staff_name_that_names_a_flow_is_kept(self):
        flows = {"a": {"name": "Helpline-support", "nodes": [{"actions": [
            {"type": "send_broadcast", "contacts": [{"name": "Helpline"}, {"name": "Ravi Kumar"}]}]}]}}
        self.assertEqual(uf.staff_names(flows), {"Ravi Kumar"})


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


if __name__ == "__main__":
    unittest.main()
