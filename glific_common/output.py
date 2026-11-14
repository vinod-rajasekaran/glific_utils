"""Run folders and JSON output.

Every run of a feature writes to its own folder, output/<feature>/<YYYY-MM-DD_HH-MM-SS>/ at the
repo root (git-ignored), so earlier results are never overwritten. GLIFIC_OUTPUT_ROOT replaces
output/<feature> (the tests use it to stay out of output/).
"""
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_run_dirs = {}


def run_dir(feature):
    """This run's output folder for a feature, named by the local start time. Created once per
    process, never reused across runs."""
    if feature not in _run_dirs:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        root = Path(os.environ.get("GLIFIC_OUTPUT_ROOT") or ROOT / "output" / feature)
        candidate, n = root / stamp, 2
        while candidate.exists():          # two runs in the same second
            candidate, n = root / f"{stamp}-{n}", n + 1
        candidate.mkdir(parents=True)
        _run_dirs[feature] = candidate
    return _run_dirs[feature]


def save_json(data, filename, out_dir):
    """Write data as JSON into out_dir and return the file path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(json.dumps(data, indent=2))
    return path
