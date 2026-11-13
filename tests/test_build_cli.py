import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "get_system_flow_architecture" / "build_flow_architecture.py"
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
        p, out = run("--usecases", "--reuse-claude", str(FIX))
        self.assertEqual(p.returncode, 0, p.stderr)
        pages = p.stdout.split()
        self.assertTrue(pages[0].endswith("flow_usecases.html"))
        self.assertTrue(pages[1].endswith("flow_architecture.html"))
        folder = Path(pages[0]).parent
        self.assertEqual(folder.parent.resolve(), out.resolve())
        for name in ("flow_usecases.html", "usecases.json", "claude_input.json", "flow_architecture.html"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertIn("weekly-tips", [u["id"] for u in json.loads((folder / "usecases.json").read_text())["use_cases"]])

    def test_no_sdk_falls_back(self):
        block = tempfile.mkdtemp()
        (Path(block) / "anthropic.py").write_text("raise ImportError('blocked for the test')\n")
        p, out = run("--usecases", PYTHONPATH=block)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("use-case page skipped", p.stderr)
        self.assertIn("anthropic", p.stderr)
        pages = p.stdout.split()
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].endswith("flow_architecture.html"))

    def test_env_flag_turns_step_on(self):
        p, _ = run("--reuse-claude", str(FIX), GLIFIC_USECASES="1")
        self.assertTrue(p.stdout.split()[0].endswith("flow_usecases.html"), p.stderr)

    def test_default_layout_graph(self):
        p, _ = run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('class="fgraph"', Path(p.stdout.split()[0]).read_text())


if __name__ == "__main__":
    unittest.main()
