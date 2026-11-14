"""The programme page: cards, views, panes, labels and evidence."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from datetime import date

from tests.org_programme_architecture.helpers import ROOT, FIX, U, load, model, raw, programmes_raw, validated, render_demo, by_name  # also puts org_programme_architecture on sys.path
from glific_common.org_facts import model as md  # noqa: E402
import programme_claude as uc  # noqa: E402
from glific_common.org_facts import facts as uf  # noqa: E402
import page_check as ra  # noqa: E402
import render_org_map as ru  # noqa: E402


class ProgrammeRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m, facts, v, p, st = validated("claude_output_programmes.json")
        cls.page = ru.render_org_map(m, facts, v, p)
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

    def test_full_graph_is_a_view(self):
        self.assertIn('href="#uc--graph"', self.home)
        view = self.page[self.page.index('id="uc--graph"'):]
        self.assertIn('id="-graph-graph"', view[:view.index("</section>")])

    def test_pane_has_part_sections(self):
        view = self.page[self.page.index('id="uc-healthy-families"'):]
        self.assertIn('class="part"', view)
        self.assertIn("Weekly pregnancy tips", view[:view.index("</section>")])


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page, cls.uc = render_demo()
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


class ClaudeTextLabelled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = model(project="Demo")
        f = uf.build_facts(m)
        v, p = uc.validate(raw(), f)
        cls.page = ru.render_org_map(m, f, v, p)
        i = cls.page.index('id="home"')
        cls.home = cls.page[i:cls.page.index('<h2 style="margin:26px', i) + 4000]

    def test_cards_are_labelled(self):
        self.assertGreaterEqual(self.home.count("Claude’s reading"), 3)

    def test_system_pill_keeps_host(self):
        self.assertIn("api.example.org", self.home)
        self.assertIn('class="pill2 sys claude"', self.home)

    def test_counts_are_split(self):
        self.assertNotIn("to check", self.page)
        self.assertIn("concern", self.page)


class ReservedGraphIds(unittest.TestCase):
    def test_programmes_named_graph_or_all_do_not_collide(self):
        r = programmes_raw()
        r["programmes"][0]["id"] = "graph"
        r["programmes"][1]["id"] = "all"
        m = model(project="Demo")
        f = uf.build_facts(m)
        v, p = uc.validate(r, f)
        page = ru.render_org_map(m, f, v, p)
        dupes = [k for k, n in Counter(re.findall(r'\bid="([^"]+)"', page)).items() if n > 1]
        self.assertEqual(dupes, [])
        i = page.index('class="uccard graphcard"')
        href = re.search(r'href="#([^"]+)"', page[i - 200:i + 200]).group(1)
        self.assertIn(f'<section class="ucview" id="{href}"', page)
        self.assertIn(f'id="{href[3:]}-graph"', page)      # the page script derives ns from the section id


class NotesOnProgrammePage(unittest.TestCase):
    def test_context_notes_shown(self):
        m = model(project="Demo", notes="journey Field work: f:Visit | c:Welcome message\nCampaigns are made in Sheets.")
        f = uf.build_facts(m)
        v, p = uc.validate(programmes_raw(), f)
        page = ru.render_org_map(m, f, v, p)
        self.assertIn('class="jrow"', page)
        self.assertIn("Campaigns are made in Sheets", page)


class PromptInjection(unittest.TestCase):
    def test_prompt_says_excerpts_are_data(self):
        self.assertIn("never instructions", (ROOT / "org_programme_architecture" / "PROGRAMME_PROMPT.md").read_text())

    def test_role_badge_marked_as_claude(self):
        m = model()
        f = uf.build_facts(m)
        v, p = uc.validate(raw(), f)
        page = ru.render_org_map(m, f, v, p)
        self.assertIn('class="role claude', page)


class HostPills(unittest.TestCase):
    def test_pills_use_parsed_hosts(self):
        flows, triggers = load()
        by_name(flows, "Ask AI")["nodes"][1]["actions"][0]["url"] = "https://[bad-host/path"
        m = model(flows, triggers)
        f = uf.build_facts(m)
        v, p = uc.validate(raw(), f)
        page = ru.render_org_map(m, f, v, p)
        self.assertNotIn('>an</span>', page)


class DataEdgeMeanings(unittest.TestCase):
    def test_data_edge_meaning_shown(self):
        m = model()
        f = uf.build_facts(m)
        r = raw()
        r["edges"].append({"id": f"edge:{U(2)}:{U(3)}:data", "meaning": "hands the stage to the weekly tip"})
        v, p = uc.validate(r, f)
        self.assertIn("hands the stage to the weekly tip", ru.render_org_map(m, f, v, p))


class CardPillsTest(unittest.TestCase):
    def test_home_cards_keep_few_pills(self):
        flows, triggers = load()
        st = md.Settings(project="Demo", today=date(2026, 11, 13))
        m = md.Model(flows, triggers, st)
        facts = uf.build_facts(m)
        v, p = uc.validate(json.loads((FIX / "claude_output_programmes.json").read_text()), facts)
        page = ru.render_org_map(m, facts, v, p)
        home = page[page.index('id="home"'):page.index('class="ucview"')]
        for card in re.findall(r'<a class="uccard.*?</a>', home, re.S):
            self.assertLessEqual(card.count('class="pill2'), 6, card[:80])
        self.assertNotIn("Groups:", home)
        self.assertNotIn("without the Demo tag", home)
        self.assertIn("Tags: Demo", home)


if __name__ == "__main__":
    unittest.main()
