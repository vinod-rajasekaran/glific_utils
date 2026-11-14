#!/usr/bin/env python3
"""Map a Glific org: pull every active flow, trigger and the flow settings, and build one page.

By default Claude reads cleaned facts about the flows and groups them into programmes with
stories (needs ANTHROPIC_API_KEY and pip install anthropic). With --no-claude, or when Claude
cannot be used, the flows are grouped by their links instead and nothing leaves the machine.

Each run writes to a new folder, output/org_programme_architecture/<YYYY-MM-DD_HH-MM-SS>/:
  flows.json               every active flow with nodes and edges (credentials blanked)
  triggers.json            every trigger, with a readable schedule
  settings.json            the organisation's name and the settings that start flows
  claude_input.json        what was sent to Claude (when Claude is used)
  claude_output.json       Claude's answer (when Claude is used)
  org_map.html             the page

Usage (settings come from .env):
  python3 build_org_map.py                       # live pull from Glific, with Claude
  python3 build_org_map.py --no-claude           # live pull, grouped by links, nothing sent to Claude
  python3 build_org_map.py --from-json output/org_programme_architecture/<run>
      # rebuild from a run saved earlier, without calling Glific; add --reuse-claude <run> to
      # reuse that run's Claude answer instead of asking again
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repo root, for glific_common

from glific_common.privacy import mask  # noqa: E402
from glific_get_flows import fetch_flows, login, run_dir, save_json  # noqa: E402
from glific_get_settings import fetch_settings
from glific_get_triggers import fetch_triggers
from glific_common.org_facts.model import Model, Settings
from glific_common.org_facts.grouping import group_answer
from render_org_map import render_org_map
from programme_claude import MODEL, PROMPT_PATH, ProgrammeError, run_programmes, validate
from glific_common.org_facts.facts import build_facts

HTML_NAME = "org_map.html"


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
                 "Export the full flow definitions (glific_get_flows.py does this).")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-json", metavar="DIR", type=Path, help="folder with flows.json and triggers.json; re-renders the HTML only")
    p.add_argument("--project", default=None,
                   help="name for the page titles (default: the organisation's name from Glific, else 'Glific chatbot')")
    p.add_argument("--tz", default=os.environ.get("GLIFIC_TZ", "Asia/Kolkata"), help="display timezone: 'IST, UTC+5:30' or an IANA name")
    p.add_argument("--date", type=date.fromisoformat, default=None,
                   help="the snapshot date, YYYY-MM-DD: decides which triggers have ended "
                        "(default: today, or the date the --from-json folder name starts with)")
    p.add_argument("--no-claude", action="store_true",
                   help="do not send anything to Claude: group the flows by their links instead of into programmes")
    p.add_argument("--reuse-claude", metavar="DIR", type=Path,
                   help="read Claude's answer from DIR/claude_output.json instead of calling the API")
    p.add_argument("--footer", default="", help="one sentence for the footer")
    p.add_argument("--notes", type=Path, help="text file with context notes (see README)")
    args = p.parse_args()

    if args.date is None:
        try:
            args.date = date.fromisoformat(args.from_json.name[:10]) if args.from_json else date.today()
        except ValueError:
            args.date = date.today()
    return args


def main():
    args = parse_args()
    flows, triggers, org, out_dir = load_saved(args.from_json) if args.from_json else fetch_live()
    m = Model(flows, triggers, settings_from(args, org), org=org)
    findings = m.report()
    print("\nFindings:" if findings else "\nFindings: none", file=sys.stderr)
    for f in findings:
        print(f"  {f}", file=sys.stderr)
    facts = build_facts(m)
    answer, dropped = claude_answer(args, facts, out_dir) if not args.no_claude else (None, [])
    if answer is None:
        reason = "it was run with --no-claude" if args.no_claude else getattr(args, "claude_skipped", "Claude could not be used")
        answer = group_answer(m, reason)
    path = out_dir / HTML_NAME
    path.write_text(render_org_map(m, facts, answer, dropped), encoding="utf-8")
    print(f"\nSaved {path} ({'programmes from Claude' if answer.get('source') != 'structure' else 'groups by links, no Claude'})",
          file=sys.stderr)
    print(path.resolve())  # the only line on stdout, so wrappers can open it


def project_name(args, org):
    """--project if given; otherwise the organisation's name from settings.json."""
    return args.project or mask(str((org or {}).get("name") or "")).strip() or "Glific chatbot"


def settings_from(args, org):
    return Settings(project=project_name(args, org), tz=args.tz, today=args.date, footer=args.footer,
                    notes=args.notes.read_text() if args.notes else "")


def load_saved(folder):
    """flows.json, triggers.json and (if there) settings.json from an earlier run, copied into a
    new run folder so it is complete; the source folder stays as it was."""
    paths = (folder / "flows.json", folder / "triggers.json")
    missing = [str(x) for x in paths if not x.is_file()]
    if missing:
        sys.exit(f"Not found: {', '.join(missing)}. --from-json needs a folder holding flows.json and triggers.json.")
    flows, triggers = (json.loads(x.read_text()) for x in paths)
    check_inputs(flows, triggers, paths)
    out_dir = run_dir()
    for x in paths:
        shutil.copy2(x, out_dir / x.name)
    print(f"Copied {folder}/{{flows,triggers}}.json to {out_dir}", file=sys.stderr)
    org = {}
    if (folder / "settings.json").is_file():
        org = json.loads((folder / "settings.json").read_text())
        shutil.copy2(folder / "settings.json", out_dir / "settings.json")
    else:
        print("No settings.json in that folder, so flows started by Glific settings show as 'No start found'.", file=sys.stderr)
    return flows, triggers, org, out_dir


def fetch_live():
    """Log in to Glific and save flows, triggers and settings to a new run folder."""
    token = login()
    flows = fetch_flows(token)
    triggers = fetch_triggers(token)
    check_inputs(flows, triggers)
    out_dir = run_dir()
    print(f"Saved {save_json(flows, 'flows.json', out_dir)}", file=sys.stderr)
    print(f"Saved {save_json(triggers, 'triggers.json', out_dir)}", file=sys.stderr)
    org = fetch_settings(token)
    print(f"Saved {save_json(org, 'settings.json', out_dir)}", file=sys.stderr)
    return flows, triggers, org, out_dir


def claude_answer(args, facts, out_dir):
    """Claude's validated answer and what validation dropped, or (None, []) when Claude cannot
    be used; args.claude_skipped then says why. Nothing that goes wrong here may cost the page."""
    try:
        return _claude_answer(args, facts, out_dir)
    except Exception as e:   # noqa: BLE001 - deliberately broad, see the docstring
        reason = str(e) if isinstance(e, ProgrammeError) else f"{type(e).__name__}: {e}"
        args.claude_skipped = f"Claude could not be used ({reason})"
        print(f"\nClaude was not used: {reason}. The flows are grouped by their links instead.", file=sys.stderr)
        return None, []


def _claude_answer(args, facts, out_dir):
    save_json({"model": MODEL, "system": PROMPT_PATH.read_text(encoding="utf-8"), "facts": facts}, "claude_input.json", out_dir)
    if args.reuse_claude:
        raw = json.loads((args.reuse_claude / "claude_output.json").read_text(encoding="utf-8"))
        save_json(raw, "claude_output.json", out_dir)
        validated, notes = validate(raw, facts)
        print(f"Using Claude's saved answer from {args.reuse_claude}", file=sys.stderr)
    else:
        print(f"Sending cleaned facts about {len(facts['flows'])} flows to Claude ({MODEL}); this can take a few minutes. "
              "Use --no-claude to keep everything on this machine.", file=sys.stderr)
        try:
            raw, validated, notes = run_programmes(facts)
        except ProgrammeError as e:
            if getattr(e, "raw", None) is not None:   # keep the paid-for answer to inspect or reuse
                save_json(e.raw, "claude_output.json", out_dir)
            raise
        save_json(raw, "claude_output.json", out_dir)
    if notes:
        print(f"\nValidation dropped {len(notes)} parts of Claude's answer (listed on the page):", file=sys.stderr)
        for n in notes[:10]:
            print(f"  {n}", file=sys.stderr)
    return validated, notes

if __name__ == "__main__":
    main()
