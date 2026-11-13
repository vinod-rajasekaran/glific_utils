import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "org_programme_architecture" / "build_org_map.py"
FIX = ROOT / "tests" / "fixtures"


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
        self.assertTrue(pages[0].endswith("programmes.html"))
        self.assertTrue(pages[1].endswith("graph.html"))
        folder = Path(pages[0]).parent
        self.assertEqual(folder.parent.resolve(), out.resolve())
        for name in ("programmes.html", "programmes.json", "claude_input.json", "graph.html"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertIn("weekly-tips", [u["id"] for u in json.loads((folder / "programmes.json").read_text())["use_cases"]])

    def test_no_sdk_falls_back(self):
        block = tempfile.mkdtemp()
        (Path(block) / "anthropic.py").write_text("raise ImportError('blocked for the test')\n")
        p, out = run("--programmes", PYTHONPATH=block)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("programme page was skipped", p.stderr)
        self.assertIn("anthropic", p.stderr)
        pages = p.stdout.split()
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].endswith("graph.html"))

    def test_env_flag_turns_step_on(self):
        p, _ = run("--reuse-claude", str(FIX), GLIFIC_PROGRAMMES="1")
        self.assertTrue(p.stdout.split()[0].endswith("programmes.html"), p.stderr)

    def test_graph_page_written(self):
        p, _ = run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('class="fgraph"', Path(p.stdout.split()[0]).read_text())


if __name__ == "__main__":
    unittest.main()
