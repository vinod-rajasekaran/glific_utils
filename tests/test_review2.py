"""Tests for the second code review (one class per finding)."""
import json
import os
import re
import sys
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import glific_get_flows as gf  # noqa: E402
import programme_claude as uc  # noqa: E402
import programme_facts as uf  # noqa: E402
import render_graph as ra  # noqa: E402
import render_programmes as ru  # noqa: E402
from tests.test_programme_claude import FakeClient, U, facts, raw  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def load():
    return json.loads((FIX / "flows.json").read_text()), json.loads((FIX / "triggers.json").read_text())


def model(**kw):
    flows, triggers = load()
    return ra.Model(flows, triggers, ra.Settings(scope_all=True, today=date(2026, 11, 13), **kw))


def programmes_raw():
    return json.loads((FIX / "claude_output_programmes.json").read_text())


class F1SlugMapping(unittest.TestCase):
    def test_parts_follow_slugged_use_case_ids(self):
        r = programmes_raw()
        r["use_cases"][0]["id"] = "Weekly_Tips"
        r["programmes"][0]["parts"] = ["Weekly_Tips", "survey"]
        v, problems = uc.validate(r, facts())
        first = next(p for p in v["programmes"] if p["name"] == "Healthy families programme")
        self.assertEqual(first["parts"], ["weekly-tips", "survey"])
        self.assertFalse(any("Weekly_Tips" in p for p in problems))


class F2RepairOnlyWhenItMatters(unittest.TestCase):
    def good(self):
        from tests.test_programme_claude import CallTest
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


class F3EmptyEnvValues(unittest.TestCase):
    def test_empty_values_are_not_exported(self):
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("ZZ_TEST_EMPTY=\nZZ_TEST_SET=1\n")
        os.environ.pop("ZZ_TEST_EMPTY", None)
        os.environ.pop("ZZ_TEST_SET", None)
        saved = os.environ.pop("GLIFIC_NO_DOTENV", None)
        try:
            gf.load_env(path)
        finally:
            if saved is not None:
                os.environ["GLIFIC_NO_DOTENV"] = saved
        self.assertNotIn("ZZ_TEST_EMPTY", os.environ)
        self.assertEqual(os.environ.pop("ZZ_TEST_SET"), "1")

    def test_env_example_has_no_empty_key_line(self):
        self.assertNotRegex((ROOT / ".env.example").read_text(), r"(?m)^ANTHROPIC_API_KEY=\s*$")


class F4ReservedGraphIds(unittest.TestCase):
    def test_programmes_named_graph_or_all_do_not_collide(self):
        r = programmes_raw()
        r["programmes"][0]["id"] = "graph"
        r["programmes"][1]["id"] = "all"
        m = model(project="Demo")
        f = uf.build_facts(m)
        v, p = uc.validate(r, f)
        flows, triggers = load()
        gm = ra.Model(flows, triggers, ra.Settings(project="Demo", tag="Demo", today=date(2026, 11, 13)))
        page = ru.render_programme_page(m, f, v, p, m.st, graph_model=gm)
        dupes = [k for k, n in Counter(re.findall(r'\bid="([^"]+)"', page)).items() if n > 1]
        self.assertEqual(dupes, [])
        i = page.index('class="uccard graphcard"')
        href = re.search(r'href="#([^"]+)"', page[i - 200:i + 200]).group(1)
        self.assertIn(f'<section class="ucview" id="{href}"', page)
        self.assertIn(f'id="{href[3:]}-graph"', page)      # the page script derives ns from the section id


class F5BadWebhookUrl(unittest.TestCase):
    def test_build_facts_survives_bad_url(self):
        flows, triggers = load()
        flows[3]["nodes"][1]["actions"][0]["url"] = "https://[bad-host/path"
        m = ra.Model(flows, triggers, ra.Settings(scope_all=True, today=date(2026, 11, 13)))
        uf.build_facts(m)


class F6NotesOnProgrammePage(unittest.TestCase):
    def test_context_notes_shown(self):
        m = model(project="Demo", notes="journey Field work: f:Visit | c:Welcome message\nCampaigns are made in Sheets.")
        f = uf.build_facts(m)
        v, p = uc.validate(programmes_raw(), f)
        page = ru.render_programme_page(m, f, v, p, m.st)
        self.assertIn('class="jrow"', page)
        self.assertIn("Campaigns are made in Sheets", page)


class F7DuplicateFlowInUseCase(unittest.TestCase):
    def test_repeat_inside_one_use_case_dropped(self):
        r = raw()
        r["use_cases"][0]["flows"] = [U(1), U(1), U(3)]
        v, problems = uc.validate(r, facts())
        tips = next(u for u in v["use_cases"] if u["id"] == "weekly-tips")
        self.assertEqual(tips["flows"], [U(1), U(3)])
        self.assertTrue(any("twice" in p for p in problems))


class F8OnlyStartedByHiddenFlow(unittest.TestCase):
    def test_flow_started_only_by_hidden_flow_gets_a_box(self):
        m = model()
        save, start = U(7), U(6)                     # Survey start enters Survey save
        m.graph_view({save}, ignore_callers={start})
        self.assertIn(save, m.no_start)
        svg, _ = ra.graph_svg(m, m.edges(), [])
        self.assertIn("Only test flows start it", svg)


if __name__ == "__main__":
    unittest.main()
