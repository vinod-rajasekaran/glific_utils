"""Tests for the final-review findings (one test per finding, named after it)."""
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "get_system_flow_architecture"))

import render_architecture as ra  # noqa: E402
import render_usecases as ru  # noqa: E402
import usecase_claude as uc  # noqa: E402
import usecase_facts as uf  # noqa: E402
from tests.test_usecase_claude import FakeClient, U, facts, raw  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def model():
    flows = json.loads((FIX / "flows.json").read_text())
    triggers = json.loads((FIX / "triggers.json").read_text())
    return ra.Model(flows, triggers, ra.Settings(project="Demo", layout="graph", scope_all=True, today=date(2026, 11, 13)))


class C1NoFalseNoStart(unittest.TestCase):
    def test_neighbour_started_elsewhere_has_no_no_start_box(self):
        m = model()
        m.graph_view({U(3), U(2)})       # Weekly tip and Profile; Welcome (which starts Profile) is off the graph
        self.assertNotIn(U(2), m.no_start)


class I1StepNeverLosesGraphPage(unittest.TestCase):
    def test_clean_text_survives_odd_urls(self):
        out = uf.clean_text("see https://[your-link] and https://user:pw@host.org/x?token=1", set())
        self.assertNotIn("pw@", out)
        self.assertNotIn("token", out)

    def test_unexpected_error_still_prints_graph_page(self):
        bad = tempfile.mkdtemp()
        (Path(bad) / "claude_output.json").write_text(json.dumps({"use_cases": [{"name": "x", "flows": 5}]}))
        out = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        env.update(GLIFIC_OUTPUT_ROOT=out, GLIFIC_NO_DOTENV="1")
        p = subprocess.run([sys.executable, str(ROOT / "get_system_flow_architecture" / "build_flow_architecture.py"),
                            "--from-json", str(FIX), "--reuse-claude", bad], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("was skipped", p.stderr)
        self.assertTrue(p.stdout.split()[0].endswith("flow_architecture.html"))


class I2RepairFailureKeepsFirstAnswer(unittest.TestCase):
    def test_failed_repair_keeps_first_answer(self):
        client = FakeClient(raw(), RuntimeError("network down"))
        got_raw, validated, notes = uc.run_usecases(facts(), client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("weekly-tips", [u["id"] for u in validated["use_cases"]])
        self.assertTrue(any("999999999999" in n for n in notes))
        self.assertTrue(any("repair" in n.lower() for n in notes))


class I3Privacy(unittest.TestCase):
    def test_staff_name_needs_word_boundaries(self):
        self.assertEqual(uf.clean_text("The Program quality", {"Ram"}), "The Program quality")

    def test_staff_first_name_alone_is_masked(self):
        self.assertNotIn("Priya", uf.clean_text("Call Priya today", {"Priya Sharma"}))

    def test_flow_name_exemption_is_whole_words(self):
        flows = {"a": {"name": "Sanitation drive", "nodes": [{"actions": [{"type": "send_broadcast", "contacts": [{"name": "Anita"}]}]}]}}
        self.assertEqual(uf.staff_names(flows), {"Anita"})

    def test_phones_with_dots_and_brackets(self):
        out = uf.clean_text("call 98765.43210 or (022) 2345 6789", set())
        self.assertNotRegex(out, r"\d{4}")

    def test_schemeless_links_lose_path(self):
        self.assertNotIn("token", uf.clean_text("go to www.example.org/reset?token=abcDEF123 now", set()))

    def test_iso_dates_kept(self):
        self.assertIn("2025-11-13", uf.clean_text("starts on 2025-11-13", set()))


class I4InventedEvidenceReported(unittest.TestCase):
    def test_unknown_evidence_on_purpose_and_summary_is_reported(self):
        r = raw()
        r["flows"][0]["evidence"].append("msg:invented:9")
        r["org_summary"]["evidence"].append("sticky:invented:1")
        _, problems = uc.validate(r, facts())
        self.assertTrue(any("msg:invented:9" in p for p in problems))
        self.assertTrue(any("sticky:invented:1" in p for p in problems))


class I5ClaudeTextLabelled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = model()
        f = uf.build_facts(m)
        v, p = uc.validate(raw(), f)
        cls.page = ru.render_usecase_page(m, f, v, p, m.st)
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


class I6DevanagariCut(unittest.TestCase):
    def test_cut_does_not_split_a_cluster(self):
        text = "स्वास्थ्य जानकारी " * 30
        for limit in range(190, 200):
            out = uf.clean_text(text, set(), limit)
            body = out.rstrip("…").rstrip()
            last = body[-1]
            self.assertFalse(unicodedata.category(last).startswith("M") and last == "्", (limit, out[-6:]))
            self.assertNotEqual(last, "्")
            if len(body) < len(text):
                nxt = text[len(body)]
                self.assertFalse(unicodedata.category(nxt).startswith("M"), (limit, out[-6:]))


class I7SizeBudget(unittest.TestCase):
    def test_excerpts_capped_with_stickies_first(self):
        flow = {"nodes": [{"actions": [{"type": "send_msg", "text": f"message {i}"} for i in range(30)]}],
                "ui": {"stickies": {"s": {"title": "Note", "body": "what this flow is for"}}}}
        ex = uf._excerpts(flow, "u", set())
        self.assertLessEqual(len(ex), uf.MAX_EXCERPTS)
        self.assertEqual(ex[0]["kind"], "sticky")

    def test_output_budget(self):
        self.assertEqual(uc.MAX_TOKENS, 128000)


class M1FallbackTextBlocks(unittest.TestCase):
    def test_text_blocks_are_joined(self):
        good = json.dumps({"use_cases": []})
        msg = SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[
            SimpleNamespace(type="text", text=good[:7]), SimpleNamespace(type="fallback"), SimpleNamespace(type="text", text=good[7:])])

        class Ctx:
            def __enter__(self):
                return SimpleNamespace(get_final_message=lambda: msg)

            def __exit__(self, *a):
                return False
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Ctx())))
        self.assertEqual(uc.call_claude(facts(), client), {"use_cases": []})


class MissingGroups(unittest.TestCase):
    def test_groups_from_routers_and_inactive_triggers(self):
        names = {g["name"] for g in uf.build_facts(model())["groups"]}
        self.assertIn("Staff", names)
        self.assertIn("Old cohort", names)


if __name__ == "__main__":
    unittest.main()
