"""The command line, run as a subprocess on the made-up org."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, FIX, SETTINGS  # also puts org_programme_architecture on sys.path
import privacy as pv  # noqa: E402


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
        p, out = run("--programmes", "--reuse-claude", str(FIX))
        self.assertEqual(p.returncode, 0, p.stderr)
        pages = p.stdout.split()
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].endswith("org_map.html"))
        folder = Path(pages[0]).parent
        self.assertEqual(folder.parent.resolve(), out.resolve())
        names = sorted(x.name for x in folder.iterdir())
        self.assertEqual(names, ["claude_input.json", "claude_output.json", "flows.json", "org_map.html", "triggers.json"])
        page = Path(pages[0]).read_text()
        self.assertIn('id="uc-weekly-tips"', page)
        self.assertIn('id="uc--graph"', page)

    def test_no_sdk_falls_back(self):
        block = tempfile.mkdtemp()
        (Path(block) / "anthropic.py").write_text("raise ImportError('blocked for the test')\n")
        p, out = run("--programmes", PYTHONPATH=block)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("programme page was skipped", p.stderr)
        self.assertIn("anthropic", p.stderr)
        pages = p.stdout.split()
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].endswith("org_map.html"))
        page = Path(pages[0]).read_text()
        self.assertIn('class="fgraph"', page)
        self.assertNotIn('id="home"', page)

    def test_env_flag_turns_step_on(self):
        p, _ = run("--reuse-claude", str(FIX), GLIFIC_PROGRAMMES="1")
        self.assertIn('id="home"', Path(p.stdout.split()[0]).read_text(), p.stderr)

    def test_graph_page_written(self):
        p, _ = run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('class="fgraph"', Path(p.stdout.split()[0]).read_text())


class StepNeverLosesGraphPage(unittest.TestCase):
    def test_clean_text_survives_odd_urls(self):
        out = pv.clean_text("see https://[your-link] and https://user:pw@host.org/x?token=1", set())
        self.assertNotIn("pw@", out)
        self.assertNotIn("token", out)

    def test_unexpected_error_still_prints_graph_page(self):
        bad = tempfile.mkdtemp()
        (Path(bad) / "claude_output.json").write_text(json.dumps({"use_cases": [{"name": "x", "flows": 5}]}))
        out = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        env.update(GLIFIC_OUTPUT_ROOT=out, GLIFIC_NO_DOTENV="1")
        p = subprocess.run([sys.executable, str(ROOT / "org_programme_architecture" / "build_org_map.py"),
                            "--from-json", str(FIX), "--reuse-claude", bad], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("was skipped", p.stderr)
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
                            "--from-json", str(src), "--date", "2026-11-13"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        page = Path(p.stdout.split()[0])
        self.assertTrue((page.parent / "settings.json").is_file())
        self.assertIn("Glific setting", page.read_text())


if __name__ == "__main__":
    unittest.main()


class OrgNameTest(unittest.TestCase):
    def run_with_settings(self, *args, org_name="Healthy Families Trust", **env):
        src = Path(tempfile.mkdtemp())
        for n in ("flows.json", "triggers.json"):
            shutil.copy(FIX / n, src / n)
        (src / "settings.json").write_text(json.dumps({"name": org_name, "outOfOffice": {}}))
        out = tempfile.mkdtemp()
        e = {k: v for k, v in os.environ.items() if not k.startswith(("GLIFIC_", "ANTHROPIC_"))}
        e.update({"GLIFIC_OUTPUT_ROOT": out, "GLIFIC_NO_DOTENV": "1"}, **env)
        p = subprocess.run([sys.executable, str(BUILD), "--from-json", str(src), "--date", "2026-11-13", *args],
                           capture_output=True, text=True, env=e, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stderr)
        return Path(p.stdout.split()[0]).read_text()

    def test_org_name_from_settings(self):
        self.assertIn("<title>Healthy Families Trust flow map</title>", self.run_with_settings())

    def test_project_flag_wins(self):
        self.assertIn("<title>Pilot review flow map</title>", self.run_with_settings("--project", "Pilot review"))
