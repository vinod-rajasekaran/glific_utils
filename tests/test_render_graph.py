"""The graph page and the sections under it."""
import unittest
from datetime import date

from tests.helpers import ROOT, load  # also puts org_programme_architecture on sys.path
import model as md  # noqa: E402
import sections as sec  # noqa: E402


class DeadCode(unittest.TestCase):
    def test_no_grid_leftovers(self):
        src = (ROOT / "org_programme_architecture" / "render_graph.py").read_text()
        for leftover in ("#wires", ".wire{", ".canvas{", 'attrs = "data-static"'):
            self.assertNotIn(leftover, src)


class SharedTableTest(unittest.TestCase):
    def test_shared_resources_is_a_collapsed_table(self):
        flows, triggers = load()
        m = md.Model(flows, triggers, md.Settings(scope_all=True, today=date(2026, 11, 13)))
        m.shared_fields = {"stage": set(list(m.flows)[:3])}     # a field written by three flows
        html = sec.shared_resources(m)
        self.assertIn("stage", html)
        self.assertIn("<details", html)
        self.assertIn("<table", html)
        self.assertNotIn('class="note"', html)

    def test_strip_is_a_table(self):
        flows, triggers = load()
        m = md.Model(flows, triggers, md.Settings(tag="Demo", today=date(2026, 11, 13)))
        m.strip = [next(u for u in m.flows if m.name(u) == "Old draft")]   # a flow left off the graph
        html = sec.strip_section(m)
        self.assertIn("Old draft", html)
        self.assertIn("<table", html)
        self.assertNotIn("<article", html)


if __name__ == "__main__":
    unittest.main()
