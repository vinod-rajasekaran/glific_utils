"""The command line, run as a subprocess on the made-up org."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.org_programme_architecture.helpers import ROOT, FIX, SETTINGS  # also puts org_programme_architecture on sys.path
from glific_common import privacy as pv  # noqa: E402


BUILD = ROOT / "org_programme_architecture" / "build_org_map.py"


def run(*args, **env):
    out = tempfile.mkdtemp()
    e = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
    e.update({"GLIFIC_OUTPUT_ROOT": out, "GLIFIC_NO_DOTENV": "1"}, **env)
    p = subprocess.run([sys.executable, str(BUILD), "--from-json", str(FIX), "--date", "2026-11-13", *args],
                       capture_output=True, text=True, env=e, cwd=ROOT)
    return p, Path(out)


class BuildCliTest(unittest.TestCase):
    def test_reuse_claude_writes_page(self):
        p, out = run("--reuse-claude", str(FIX))
        self.assertEqual(p.returncode, 0, p.stderr)
        pages = p.stdout.split()
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].endswith("org_map.html"))
        folder = Path(pages[0]).parent
        self.assertEqual(folder.parent.resolve(), out.resolve())
        names = sorted(x.name for x in folder.iterdir())
        self.assertEqual(names, ["claude_input.json", "claude_output.json", "flows.json", "org_map.html", "org_map.json", "triggers.json"])
        page = Path(pages[0]).read_text()
        self.assertIn('id="uc-weekly-tips"', page)
        self.assertIn('id="uc--graph"', page)

    def test_no_sdk_falls_back(self):
        block = tempfile.mkdtemp()
        (Path(block) / "anthropic.py").write_text("raise ImportError('blocked for the test')\n")
        p, out = run(PYTHONPATH=block)          # Claude is the default, but the package is missing
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Claude was not used", p.stderr)
        self.assertIn("anthropic", p.stderr)
        pages = p.stdout.split()
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].endswith("org_map.html"))
        page = Path(pages[0]).read_text()
        self.assertIn('class="fgraph"', page)
        self.assertIn("Built without Claude", page)
        self.assertIn("anthropic", page)

    def test_page_written_without_claude(self):
        p, _ = run("--no-claude")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('class="fgraph"', Path(p.stdout.split()[0]).read_text())


class ClaudeStepNeverLosesPage(unittest.TestCase):
    def test_clean_text_survives_odd_urls(self):
        out = pv.clean_text("see https://[your-link] and https://user:pw@host.org/x?token=1", set())
        self.assertNotIn("pw@", out)
        self.assertNotIn("token", out)

    def test_bad_saved_answer_falls_back_to_groups(self):
        bad = tempfile.mkdtemp()
        (Path(bad) / "claude_output.json").write_text(json.dumps({"use_cases": [{"name": "x", "flows": 5}]}))
        out = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        env.update(GLIFIC_OUTPUT_ROOT=out, GLIFIC_NO_DOTENV="1")
        p = subprocess.run([sys.executable, str(ROOT / "org_programme_architecture" / "build_org_map.py"),
                            "--from-json", str(FIX), "--reuse-claude", bad], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Claude was not used", p.stderr)
        self.assertIn("Built without Claude", Path(p.stdout.split()[0]).read_text())
        self.assertTrue(p.stdout.split()[0].endswith("org_map.html"))


class SettingsCliTest(unittest.TestCase):
    def test_from_json_reads_settings(self):
        src = Path(tempfile.mkdtemp())
        for n in ("flows.json", "triggers.json"):
            shutil.copy(FIX / n, src / n)
        (src / "settings.json").write_text(json.dumps(SETTINGS))
        out = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        env.update(GLIFIC_OUTPUT_ROOT=out, GLIFIC_NO_DOTENV="1")
        p = subprocess.run([sys.executable, str(ROOT / "org_programme_architecture" / "build_org_map.py"),
                            "--from-json", str(src), "--date", "2026-11-13", "--no-claude"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        page = Path(p.stdout.split()[0])
        self.assertTrue((page.parent / "settings.json").is_file())
        self.assertIn("Glific setting", page.read_text())


class OrgNameTest(unittest.TestCase):
    def run_with_settings(self, *args, org_name="Healthy Families Trust", **env):
        src = Path(tempfile.mkdtemp())
        for n in ("flows.json", "triggers.json"):
            shutil.copy(FIX / n, src / n)
        (src / "settings.json").write_text(json.dumps({"name": org_name, "outOfOffice": {}}))
        out = tempfile.mkdtemp()
        e = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        e.update({"GLIFIC_OUTPUT_ROOT": out, "GLIFIC_NO_DOTENV": "1"}, **env)
        p = subprocess.run([sys.executable, str(BUILD), "--from-json", str(src), "--date", "2026-11-13", "--no-claude", *args],
                           capture_output=True, text=True, env=e, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stderr)
        return Path(p.stdout.split()[0]).read_text()

    def test_org_name_from_settings(self):
        self.assertIn("<title>Healthy Families Trust org map</title>", self.run_with_settings())

    def test_project_flag_wins(self):
        self.assertIn("<title>Pilot review org map</title>", self.run_with_settings("--project", "Pilot review"))


if __name__ == "__main__":
    unittest.main()


class OrgMapJsonTest(unittest.TestCase):
    """Every run also saves org_map.json, which the MCP server reads."""
    def saved(self, *args):
        p, _ = run(*args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads((Path(p.stdout.split()[0]).parent / "org_map.json").read_text())

    def test_without_claude(self):
        d = self.saved("--no-claude")
        self.assertEqual(d["source"], "structure")
        self.assertIn("--no-claude", d["reason"])
        self.assertTrue(d["answer"]["use_cases"])
        self.assertEqual(d["flow_names"]["00000000-0000-4000-8000-000000000004"], "Ask AI")

    def test_with_claude(self):
        d = self.saved("--reuse-claude", str(FIX))
        self.assertEqual(d["source"], "claude")
        self.assertTrue(d["answer"]["org_summary"]["text"])
        self.assertTrue(d["dropped"], "the fixture answer has faults that validation drops")

    def test_names_are_masked(self):
        flows = json.loads((FIX / "flows.json").read_text())
        flows[0]["name"] = "Call 9876543210"
        src = Path(tempfile.mkdtemp())
        (src / "flows.json").write_text(json.dumps(flows))
        shutil.copy(FIX / "triggers.json", src / "triggers.json")
        e = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        e.update(GLIFIC_OUTPUT_ROOT=tempfile.mkdtemp(), GLIFIC_NO_DOTENV="1")
        p = subprocess.run([sys.executable, str(BUILD), "--from-json", str(src), "--no-claude"],
                           capture_output=True, text=True, env=e, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("9876543210", (Path(p.stdout.split()[0]).parent / "org_map.json").read_text())


class ModelOptionTest(unittest.TestCase):
    def test_model_is_recorded_in_claude_input(self):
        p, _ = run("--reuse-claude", str(FIX), "--model", "claude-sonnet-5-5")
        self.assertEqual(p.returncode, 0, p.stderr)
        sent = json.loads((Path(p.stdout.split()[0]).parent / "claude_input.json").read_text())
        self.assertEqual(sent["model"], "claude-sonnet-5-5")

    def test_default_is_opus(self):
        p, _ = run("--reuse-claude", str(FIX))
        sent = json.loads((Path(p.stdout.split()[0]).parent / "claude_input.json").read_text())
        self.assertEqual(sent["model"], "claude-opus-5-5")

    def test_unknown_model_is_refused(self):
        p, _ = run("--model", "gpt-4", "--no-claude")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("invalid choice", p.stderr)
