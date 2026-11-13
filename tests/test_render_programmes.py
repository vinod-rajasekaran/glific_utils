import json
import re
import shutil
import subprocess
import sys
import tempfile
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
U = lambda n: f"00000000-0000-4000-8000-{n:012d}"  # noqa: E731


def render():
    flows = json.loads((FIX / "flows.json").read_text())
    triggers = json.loads((FIX / "triggers.json").read_text())
    st = ra.Settings(project="Demo bot", scope_all=True, today=date(2026, 11, 13))
    m = ra.Model(flows, triggers, st)
    facts = uf.build_facts(m)
    validated, problems = uc.validate(json.loads((FIX / "claude_output.json").read_text()), facts)
    return ru.render_programme_page(m, facts, validated, problems, st), validated


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page, cls.uc = render()
        i = cls.page.index('id="home"')
        cls.home = cls.page[i:cls.page.index("</section>", i)]

    def test_lists_use_cases(self):
        for u in self.uc["use_cases"]:
            self.assertEqual(self.home.count(f'href="#uc-{u["id"]}"'), 1)
            self.assertIn(f'id="uc-{u["id"]}"', self.page)
        self.assertNotIn("Ghost", self.home)

    def test_escapes_claude_text(self):
        self.assertNotIn("<script>alert", self.page)
        self.assertIn("&lt;script&gt;alert", self.page)

    def test_page_checks(self):
        bal = ra._Balance()
        bal.feed(self.page)
        self.assertEqual((bal.errors, bal.stack), ([], []))
        self.assertNotIn("—", self.page)
        node = shutil.which("node")
        if node:
            js = "\n".join(re.findall(r"<script>(.*?)</script>", self.page, re.S))
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
                fh.write(js)
            self.assertEqual(subprocess.run([node, "--check", fh.name], capture_output=True).returncode, 0)

    def test_no_pii(self):
        self.assertNotIn("Asha", self.page)
        self.assertNotRegex(self.page, r"(?<![\d-])\d{10}(?![\d-])")
        self.assertNotIn("docs.google.com/", self.page)
        self.assertNotIn("lead@example.org", self.page)

    def test_dropped_listed(self):
        i = self.page.index("Dropped by validation")
        self.assertIn("999999999999", self.page[i:])

    def test_not_placed_listed(self):
        i = self.page.index("Not placed")
        self.assertIn("Old draft", self.page[i:i + 2000])

    def test_one_graph_per_use_case(self):
        for u in self.uc["use_cases"]:
            self.assertIn(f'id="{u["id"]}-graph"', self.page)

    def test_tests_neighbour_left_out(self):
        # Ask AI copy (tests) reads a field Profile sets: not drawn, but warned about from the export
        view = self.page[self.page.index('id="uc-weekly-tips"'):]
        view = view[:view.index("</section>")]
        self.assertNotIn(f'data-id="weekly-tips-f-{U(5)}"', view)
        self.assertNotIn(f'data-id="weekly-tips-k-{U(5)}"', view)
        self.assertIn("From the export", view)
        self.assertIn("Ask AI copy", view)
        self.assertIn("stage", view)

    def test_evidence_shown_with_statement(self):
        self.assertIn("Welcome to the Healthy Families service", self.page)
        self.assertIn('class="conf c-clear"', self.page)


if __name__ == "__main__":
    unittest.main()
