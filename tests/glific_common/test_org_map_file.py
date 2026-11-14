"""Finding and reading the latest org_map.json."""
import json
import tempfile
import unittest
from pathlib import Path

from glific_common.org_facts import org_map_file as omf


class LatestTest(unittest.TestCase):
    def test_latest_run_with_a_map(self):
        root = Path(tempfile.mkdtemp())
        for name, has_map in (("2026-11-01_10-00-00", True), ("2026-11-02_10-00-00", True), ("2026-11-03_10-00-00", False)):
            (root / name).mkdir()
            if has_map:
                (root / name / omf.FILENAME).write_text(json.dumps({"run": name}))
        path, data = omf.latest(root)
        self.assertEqual(path.parent.name, "2026-11-02_10-00-00")   # the newest folder has no map yet
        self.assertEqual(data["run"], "2026-11-02_10-00-00")

    def test_claude_map_wins_over_a_later_one_without_claude(self):
        root = Path(tempfile.mkdtemp())
        for name, source in (("2026-11-01_10-00-00", "structure"), ("2026-11-02_10-00-00", "claude"), ("2026-11-03_10-00-00", "structure")):
            (root / name).mkdir()
            (root / name / omf.FILENAME).write_text(json.dumps({"run": name, "source": source}))
        self.assertEqual(omf.latest(root)[1]["run"], "2026-11-02_10-00-00")
        (root / "2026-11-02_10-00-00" / omf.FILENAME).unlink()
        self.assertEqual(omf.latest(root)[1]["run"], "2026-11-03_10-00-00")

    def test_none_yet(self):
        self.assertEqual(omf.latest(Path(tempfile.mkdtemp()) / "missing"), (None, None))


if __name__ == "__main__":
    unittest.main()
