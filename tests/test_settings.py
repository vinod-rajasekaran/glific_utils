"""Flows started by Glific's organisation settings (default, new contact, opt-in, out of office, regex)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import glific_get_settings as gs  # noqa: E402
import render_graph as ra  # noqa: E402
import programme_facts as uf  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
U = lambda n: f"00000000-0000-4000-8000-{n:012d}"  # noqa: E731
# Old draft (id "008") is the default flow; Welcome (id "001") the new-contact flow
SETTINGS = {"newcontactFlowId": "001", "optinFlowId": None,
            "outOfOffice": {"enabled": False, "flowId": None, "defaultFlowId": "008"},
            "regxFlow": {"flowId": None, "regx": None}}


def model(org=SETTINGS, **kw):
    flows = json.loads((FIX / "flows.json").read_text())
    triggers = json.loads((FIX / "triggers.json").read_text())
    st = ra.Settings(today=date(2026, 11, 13), **kw)
    return ra.Model(flows, triggers, st, org=org)


class FetchTest(unittest.TestCase):
    def test_fetch_settings_reads_organization(self):
        calls = []

        def fake_post(path, payload, token=None):
            calls.append(payload["query"])
            return {"data": {"organization": {"organization": dict(SETTINGS, name="Demo org")}}}
        got = gs.fetch_settings("tok", post=fake_post)
        self.assertEqual(got["outOfOffice"]["defaultFlowId"], "008")
        self.assertNotIn("email", calls[0])

    def test_fetch_settings_survives_errors(self):
        got = gs.fetch_settings("tok", post=lambda *a, **k: {"errors": [{"message": "unauthorized"}]})
        self.assertEqual(got, {})


class ModelTest(unittest.TestCase):
    def test_setting_starts_mapped_by_flow_id(self):
        m = model(scope_all=True)
        self.assertIn("default flow", m.setting_starts[U(8)][0][1].lower())
        self.assertIn("new contact", m.setting_starts[U(1)][0][1].lower())

    def test_setting_flow_is_not_no_start(self):
        m = model(scope_all=True)
        m.graph_view({U(8)})
        self.assertNotIn(U(8), m.no_start)
        self.assertIn([f"s-{U(8)}", f"f-{U(8)}", "s"], m.edges())

    def test_graph_page_shows_setting_box(self):
        flows = json.loads((FIX / "flows.json").read_text())
        triggers = json.loads((FIX / "triggers.json").read_text())
        page, _ = ra.render_html(flows, triggers, ra.Settings(today=date(2026, 11, 13)), org=SETTINGS)
        self.assertIn("Glific setting", page)
        self.assertNotIn("No start found for Old draft", page)

    def test_without_settings_nothing_changes(self):
        m = model(org=None, scope_all=True)
        self.assertEqual(m.setting_starts, {})


class FactsTest(unittest.TestCase):
    def test_facts_setting_start(self):
        f = uf.build_facts(model(scope_all=True))
        old = next(x for x in f["flows"] if x["name"] == "Old draft")
        self.assertEqual([s["kind"] for s in old["starts_from"]], ["setting"])
        self.assertIn("default flow", old["starts_from"][0]["text"].lower())


class CliTest(unittest.TestCase):
    def test_from_json_reads_settings(self):
        src = Path(tempfile.mkdtemp())
        for n in ("flows.json", "triggers.json"):
            shutil.copy(FIX / n, src / n)
        (src / "settings.json").write_text(json.dumps(SETTINGS))
        out = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        env.update(GLIFIC_OUTPUT_ROOT=out, GLIFIC_NO_DOTENV="1")
        p = subprocess.run([sys.executable, str(ROOT / "org_programme_architecture" / "build_org_map.py"),
                            "--from-json", str(src), "--date", "2026-11-13"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        page = Path(p.stdout.split()[0])
        self.assertTrue((page.parent / "settings.json").is_file())
        self.assertIn("Glific setting", page.read_text())


if __name__ == "__main__":
    unittest.main()
