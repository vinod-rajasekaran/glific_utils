"""Programmes: use cases grouped into the few things the bot does, each with its parts."""
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "get_system_flow_architecture"))

import render_architecture as ra  # noqa: E402
import render_usecases as ru  # noqa: E402
import usecase_claude as uc  # noqa: E402
import usecase_facts as uf  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
U = lambda n: f"00000000-0000-4000-8000-{n:012d}"  # noqa: E731


def setup(name):
    flows = json.loads((FIX / "flows.json").read_text())
    triggers = json.loads((FIX / "triggers.json").read_text())
    st = ra.Settings(project="Demo", layout="graph", scope_all=True, today=date(2026, 11, 13))
    m = ra.Model(flows, triggers, st)
    facts = uf.build_facts(m)
    v, p = uc.validate(json.loads((FIX / name).read_text()), facts)
    return m, facts, v, p, st


class ValidateTest(unittest.TestCase):
    def setUp(self):
        _, _, self.v, self.p, _ = setup("claude_output_programmes.json")
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
        _, _, v, p, _ = setup("claude_output.json")
        self.assertEqual([x["parts"] for x in v["programmes"]], [[u["id"]] for u in v["use_cases"]])
        self.assertFalse(any("programme" in x.lower() for x in p))

    def test_use_case_left_out_gets_own_programme(self):
        raw = json.loads((FIX / "claude_output_programmes.json").read_text())
        raw["programmes"] = raw["programmes"][:1]          # "tests" use case now in no programme
        flows = json.loads((FIX / "flows.json").read_text())
        triggers = json.loads((FIX / "triggers.json").read_text())
        m = ra.Model(flows, triggers, ra.Settings(layout="graph", scope_all=True, today=date(2026, 11, 13)))
        v, p = uc.validate(raw, uf.build_facts(m))
        self.assertIn(["tests"], [x["parts"] for x in v["programmes"]])
        self.assertTrue(any("not in any programme" in x for x in p))

    def test_schema_has_programmes(self):
        self.assertIn("programmes", uc.SCHEMA["properties"])


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m, facts, v, p, st = setup("claude_output_programmes.json")
        cls.page = ru.render_usecase_page(m, facts, v, p, st)
        i = cls.page.index('id="home"')
        cls.home = cls.page[i:cls.page.index("</section>", i)]

    def test_home_lists_programmes_with_parts(self):
        self.assertEqual(self.home.count('href="#uc-healthy-families"'), 1)
        self.assertEqual(self.home.count('href="#uc-tests"'), 1)
        self.assertNotIn('href="#uc-weekly-tips"', self.home)
        self.assertIn("Weekly pregnancy tips", self.home)
        self.assertIn("Survey", self.home)

    def test_one_view_and_graph_per_programme(self):
        self.assertIn('id="uc-healthy-families"', self.page)
        self.assertIn('id="healthy-families-graph"', self.page)
        self.assertNotIn('id="weekly-tips-graph"', self.page)

    def test_boxes_marked_by_part(self):
        view = self.page[self.page.index('id="uc-healthy-families"'):]
        view = view[:view.index("</section>")]
        self.assertIn('class="pstripe p1"', view)
        self.assertIn('class="pstripe p2"', view)

    def test_pane_has_part_sections(self):
        view = self.page[self.page.index('id="uc-healthy-families"'):]
        self.assertIn('class="part"', view)
        self.assertIn("Weekly pregnancy tips", view[:view.index("</section>")])


if __name__ == "__main__":
    unittest.main()


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
        m = ra.Model(flows, triggers, ra.Settings(layout="graph", scope_all=True, today=date(2026, 11, 13)))
        v, _ = uc.validate(raw, uf.build_facts(m))
        tips = next(u for u in v["use_cases"] if u["id"] == "weekly-tips")
        self.assertEqual((len(tips["story"]), len(tips["how_it_works"]), len(tips["watch"])), (3, 1, 1))
        prog = next(p for p in v["programmes"] if p["id"] == "healthy-families")
        self.assertEqual((len(prog["story"]), len(prog["watch"])), (1, 1))
