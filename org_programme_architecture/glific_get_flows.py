#!/usr/bin/env python3
"""Fetch all flows from a Glific instance, including each flow's nodes and edges.

Usage (put the variables in the repo-root .env, see .env.example, or export them):
  export GLIFIC_URL=https://api.yourorg.glific.com   # your Glific API host
  export GLIFIC_PHONE=91XXXXXXXXXX
  export GLIFIC_PASSWORD=secret
  python3 glific_get_flows.py --redact old/flows.json   # blank credentials in an earlier export
  python3 glific_get_flows.py   # writes output/org_programme_architecture/<YYYY-MM-DD_HH-MM-SS>/flows.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repo root, for glific_common

from glific_common import output  # noqa: E402
from glific_common.api import GlificError, login  # noqa: E402,F401  (login is used by the other scripts)
from glific_common.org_facts import fetch  # noqa: E402
from glific_common.redact import _scrub, redact_nodes  # noqa: E402

FEATURE = "org_programme_architecture"


def run_dir():
    """This run's output folder, output/org_programme_architecture/<YYYY-MM-DD_HH-MM-SS>/."""
    return output.run_dir(FEATURE)


def save_json(data, filename, out_dir=None):
    """Write data as JSON into out_dir (default: this run's folder) and return the file path."""
    return output.save_json(data, filename, out_dir or run_dir())


def fetch_flows(token):
    """Every active flow with its nodes, edges and editor layout; exits if the list cannot be read."""
    try:
        return fetch.fetch_flows(token)
    except GlificError as e:
        sys.exit(str(e))


def redact_file(path):
    """Blank credentials in a flows.json saved earlier, rewriting it in place."""
    flows = json.loads(Path(path).read_text())
    total = 0
    for f in flows:
        total += redact_nodes(f.get("nodes") or [])
        if isinstance(f.get("ui"), dict):
            f["ui"], n = _scrub(f["ui"])
            total += n
    Path(path).write_text(json.dumps(flows, indent=2))
    print(f"Blanked {total} credential value(s) in {path}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--redact":
        redact_file(sys.argv[2])  # python3 glific_get_flows.py --redact path/to/flows.json
        sys.exit()
    flows = fetch_flows(login())
    path = save_json(flows, "flows.json")
    print(f"Fetched {len(flows)} flows -> {path}", file=sys.stderr)
