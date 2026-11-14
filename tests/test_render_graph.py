"""The sections under the full graph, and checks that span the page modules."""
import unittest
from datetime import date

from tests.helpers import ROOT, load, model  # also puts org_programme_architecture on sys.path
import model as md  # noqa: E402
import sections as sec  # noqa: E402


class DeadCode(unittest.TestCase):
    def test_no_grid_leftovers(self):
        pkg = ROOT / "org_programme_architecture"
        src = "".join(p.read_text() for p in list(pkg.glob("*.py")) + list(pkg.glob("assets/*")))
        for leftover in ("#wires", ".wire{", ".canvas{", 'attrs = "data-static"', "tagged(", "scope_all", "GLIFIC_TAG"):
            self.assertNotIn(leftover, src, leftover)


class SharedTableTest(unittest.TestCase):
    def test_shared_resources_is_a_collapsed_table(self):
        flows, triggers = load()
        m = md.Model(flows, triggers, md.Settings(today=date(2026, 11, 13)))
        m.shared_fields = {"stage": set(list(m.flows)[:3])}     # a field written by three flows
        html = sec.shared_resources(m)
        self.assertIn("stage", html)
        self.assertIn("<details", html)
        self.assertIn("<table", html)
        self.assertNotIn('class="note"', html)

    def test_strip_is_a_table(self):
        flows, triggers = load()
        m = md.Model(flows, triggers, md.Settings(today=date(2026, 11, 13)))
        m.strip = [next(u for u in m.flows if m.name(u) == "Old draft")]   # a flow left off the graph
        html = sec.strip_section(m)
        self.assertIn("Old draft", html)
        self.assertIn("<table", html)
        self.assertNotIn("<article", html)



class RenderPageLeavesModel(unittest.TestCase):
    def test_report_does_not_change_findings(self):
        flows, triggers = load()
        flows[0]["nodes"][0]["actions"].append({"type": "enter_flow", "uuid": "x1", "flow": {"uuid": "gone", "name": "Ghost flow"}})
        m = model(flows, triggers)      # the report adds a finding about the missing flow
        before = list(m.findings)
        first, second = m.report(), m.report()
        self.assertTrue(any("Ghost flow" in f for f in first))
        self.assertEqual(m.findings, before)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
