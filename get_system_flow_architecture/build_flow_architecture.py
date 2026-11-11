#!/usr/bin/env python3
"""Pull all flows and triggers from Glific and build an HTML flow map (spec: PROMPT_SPEC.md).

Each run writes three files to a new folder, output/get_system_flow_architecture/<YYYY-MM-DD_HH-MM-SS>/:
  flows.json               every active flow with nodes and edges (credentials blanked)
  triggers.json            every trigger, with a readable schedule
  flow_architecture.html   the flow map

Usage (same env vars as the other scripts; settings can also come from .env):
  python3 build_flow_architecture.py --project "My Bot" --tag "2025 Pilot"
  python3 build_flow_architecture.py --from-json output/get_system_flow_architecture/2026-11-11_21-43-05 --tag "2025 Pilot"
      # re-render from JSON saved earlier, without calling the API. The result goes to a new
      # run folder with copies of the JSON; the source folder is not touched.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

from glific_get_flows import fetch_flows, login, run_dir, save_json
from glific_get_triggers import fetch_triggers
from render_architecture import Settings, render_html

HTML_NAME = "flow_architecture.html"


def check_inputs(flows, triggers, paths=()):
    """Stop on unusable input, per the spec's input checks."""
    if len(paths) == 2:
        h = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]
        print(f"sha256 flows.json {h[0][:16]}  triggers.json {h[1][:16]}", file=sys.stderr)
        if h[0] == h[1]:
            sys.exit("flows.json and triggers.json are identical. Export both files again.")
    if not isinstance(flows, list) or not isinstance(triggers, list):
        sys.exit("flows.json and triggers.json must each hold a JSON list.")
    if flows and not any(f.get("nodes") for f in flows):
        sys.exit("flows.json holds only flow metadata and no nodes, so links cannot be derived from it.\n"
                 "Export the full flow definitions (glific_get_flows.py does this), ideally filtered by the tag.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-json", metavar="DIR", type=Path, help="folder with flows.json and triggers.json; re-renders the HTML only")
    p.add_argument("--project", default=os.environ.get("GLIFIC_PROJECT", "Glific chatbot"), help="project name for the page title")
    p.add_argument("--tag", default=os.environ.get("GLIFIC_TAG", ""), help="flow tag to start from, e.g. '2025 Pilot' (default: start from triggers and keywords)")
    p.add_argument("--tz", default=os.environ.get("GLIFIC_TZ", "Asia/Kolkata"), help="display timezone: 'IST, UTC+5:30' or an IANA name")
    p.add_argument("--date", type=date.fromisoformat, default=None,
                   help="the snapshot date, YYYY-MM-DD: decides which triggers have ended "
                        "(default: today, or the date the --from-json folder name starts with)")
    p.add_argument("--footer", default="", help="one sentence for the footer")
    p.add_argument("--notes", type=Path, help="text file with context notes (see README)")
    args = p.parse_args()

    if args.date is None:
        try:
            args.date = date.fromisoformat(args.from_json.name[:10]) if args.from_json else date.today()
        except ValueError:
            args.date = date.today()

    if args.from_json:
        paths = (args.from_json / "flows.json", args.from_json / "triggers.json")
        missing = [str(x) for x in paths if not x.is_file()]
        if missing:
            sys.exit(f"Not found: {', '.join(missing)}. --from-json needs a folder holding flows.json and triggers.json.")
        flows, triggers = (json.loads(x.read_text()) for x in paths)
        check_inputs(flows, triggers, paths)
        out_dir = run_dir()
        for x in paths:   # keep each run folder complete; the source folder stays as it was
            shutil.copy2(x, out_dir / x.name)
        print(f"Copied {args.from_json}/{{flows,triggers}}.json to {out_dir}", file=sys.stderr)
    else:
        token = login()
        flows = fetch_flows(token)
        triggers = fetch_triggers(token)
        check_inputs(flows, triggers)
        out_dir = run_dir()
        print(f"Saved {save_json(flows, 'flows.json', out_dir)}", file=sys.stderr)
        print(f"Saved {save_json(triggers, 'triggers.json', out_dir)}", file=sys.stderr)

    settings = Settings(project=args.project, tag=args.tag, tz=args.tz, today=args.date, footer=args.footer,
                        notes=args.notes.read_text() if args.notes else "")
    page, findings = render_html(flows, triggers, settings, out=sys.stderr)
    path = out_dir / HTML_NAME
    path.write_text(page, encoding="utf-8")
    print("\nFindings:" if findings else "\nFindings: none", file=sys.stderr)
    for f in findings:
        print(f"  {f}", file=sys.stderr)
    print(f"\nSaved {path}", file=sys.stderr)
    print(path.resolve())  # the only line on stdout, so wrappers can open the page


if __name__ == "__main__":
    main()
