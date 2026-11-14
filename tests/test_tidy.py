"""Less text on the pages, and every start box in one column."""
import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import render_graph as ra  # noqa: E402
import render_programmes as ru  # noqa: E402
import programme_claude as uc  # noqa: E402
import programme_facts as uf  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def load():
    return json.loads((FIX / "flows.json").read_text()), json.loads((FIX / "triggers.json").read_text())


class StartColumnTest(unittest.TestCase):
    def test_all_start_boxes_share_one_column(self):
        flows, triggers = load()
        m = ra.Model(flows, triggers, ra.Settings(scope_all=True, today=date(2026, 11, 13)))
        svg, _ = ra.graph_svg(m, m.graph_view(set(m.flows)), [])
        xs = {float(x) for x in re.findall(r'data-id="[tkxs]-[^"]+"[^>]*><rect x="([\d.]+)"', svg)}
        self.assertGreaterEqual(len(re.findall(r'data-id="[tkxs]-', svg)), 3)
        self.assertEqual(len(xs), 1, xs)


class SharedTableTest(unittest.TestCase):
    def test_shared_resources_is_a_collapsed_table(self):
        flows, triggers = load()
        m = ra.Model(flows, triggers, ra.Settings(scope_all=True, today=date(2026, 11, 13)))
        m.shared_fields = {"stage": set(list(m.flows)[:3])}     # a field written by three flows
        html = ra.shared_resources(m)
        self.assertIn("stage", html)
        self.assertIn("<details", html)
        self.assertIn("<table", html)
        self.assertNotIn('class="note"', html)

    def test_strip_is_a_table(self):
        flows, triggers = load()
        m = ra.Model(flows, triggers, ra.Settings(tag="Demo", today=date(2026, 11, 13)))
        m.strip = [next(u for u in m.flows if m.name(u) == "Old draft")]   # a flow left off the graph
        html = ra.strip_section(m)
        self.assertIn("Old draft", html)
        self.assertIn("<table", html)
        self.assertNotIn("<article", html)


class CardPillsTest(unittest.TestCase):
    def test_home_cards_keep_few_pills(self):
        flows, triggers = load()
        st = ra.Settings(project="Demo", tag="Demo", scope_all=True, today=date(2026, 11, 13))
        m = ra.Model(flows, triggers, st)
        facts = uf.build_facts(m)
        v, p = uc.validate(json.loads((FIX / "claude_output_programmes.json").read_text()), facts)
        page = ru.render_programme_page(m, facts, v, p, st)
        home = page[page.index('id="home"'):page.index('class="ucview"')]
        for card in re.findall(r'<a class="uccard.*?</a>', home, re.S):
            self.assertLessEqual(card.count('class="pill2'), 5, card[:80])
        self.assertNotIn("Groups:", home)
        self.assertNotIn("without the Demo tag", home)


if __name__ == "__main__":
    unittest.main()
