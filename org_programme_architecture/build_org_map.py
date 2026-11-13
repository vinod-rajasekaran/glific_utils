#!/usr/bin/env python3
"""Pull all flows and triggers from Glific and build the graph page and, with --programmes, the programme page.

Each run writes three files to a new folder, output/org_programme_architecture/<YYYY-MM-DD_HH-MM-SS>/:
  flows.json               every active flow with nodes and edges (credentials blanked)
  triggers.json            every trigger, with a readable schedule
  settings.json            the organisation settings that start flows (default, new contact, opt-in, ...)
  org_map.html             the page: the flow graph, or with --programmes the programme page
                           (the full graph is one of its views)

Usage (same env vars as the other scripts; settings can also come from .env):
  python3 build_org_map.py --project "My Bot" --tag "2025 Pilot"
  python3 build_org_map.py --from-json output/org_programme_architecture/2026-11-11_21-43-05 --tag "2025 Pilot"
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
from glific_get_settings import fetch_settings
from glific_get_triggers import fetch_triggers
from render_graph import Model, Settings, render_html
from render_programmes import render_programme_page
from programme_claude import MODEL, PROMPT_PATH, ProgrammeError, run_programmes, validate
from programme_facts import build_facts

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
    p.add_argument("--programmes", action="store_true",
                   default=os.environ.get("GLIFIC_PROGRAMMES", "").lower() in ("1", "true", "yes"),
                   help="also ask Claude to explain the bot as programmes and their parts, on the same page; "
                        "sends cleaned facts and message excerpts to the Anthropic API (needs ANTHROPIC_API_KEY "
                        "and pip install anthropic; env GLIFIC_PROGRAMMES=1)")
    p.add_argument("--reuse-claude", metavar="DIR", type=Path,
                   help="with the programme page: read Claude's answer from DIR/claude_output.json instead of calling the API")
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
        org = {}
        if (args.from_json / "settings.json").is_file():
            org = json.loads((args.from_json / "settings.json").read_text())
            shutil.copy2(args.from_json / "settings.json", out_dir / "settings.json")
        else:
            print("No settings.json in that folder, so flows started by Glific settings show as 'No start found'.", file=sys.stderr)
    else:
        token = login()
        flows = fetch_flows(token)
        triggers = fetch_triggers(token)
        check_inputs(flows, triggers)
        out_dir = run_dir()
        print(f"Saved {save_json(flows, 'flows.json', out_dir)}", file=sys.stderr)
        print(f"Saved {save_json(triggers, 'triggers.json', out_dir)}", file=sys.stderr)
        org = fetch_settings(token)
        print(f"Saved {save_json(org, 'settings.json', out_dir)}", file=sys.stderr)

    settings = Settings(project=args.project, tag=args.tag, tz=args.tz, today=args.date, footer=args.footer,
                        notes=args.notes.read_text() if args.notes else "")
    page, findings = render_html(flows, triggers, settings, out=sys.stderr, org=org)
    print("\nFindings:" if findings else "\nFindings: none", file=sys.stderr)
    for f in findings:
        print(f"  {f}", file=sys.stderr)
    if args.programmes or args.reuse_claude:
        # One page per run: with programmes, the programme page (the full graph is one of its views)
        page = programme_step(args, flows, triggers, out_dir, org, Model(flows, triggers, settings, org=org)) or page
    path = out_dir / HTML_NAME
    path.write_text(page, encoding="utf-8")
    print(f"\nSaved {path}", file=sys.stderr)
    print(path.resolve())  # the only line on stdout, so wrappers can open it


def programme_step(args, flows, triggers, out_dir, org, graph_model):
    """Facts, Claude, validation and the programme page. Returns its HTML, or None when skipped.

    Nothing that goes wrong here may cost the user the graph page, so every error ends the
    step with a one-line reason."""
    try:
        return _programme_step(args, flows, triggers, out_dir, org, graph_model)
    except Exception as e:   # noqa: BLE001 - deliberately broad, see the docstring
        reason = str(e) if isinstance(e, ProgrammeError) else f"{type(e).__name__}: {e}"
        print(f"\nThe programme page was skipped: {reason}. The graph page was written instead.", file=sys.stderr)
        return None


def _programme_step(args, flows, triggers, out_dir, org, graph_model):
    st = Settings(project=args.project, tag=args.tag, tz=args.tz, today=args.date, footer=args.footer,
                  notes=args.notes.read_text() if args.notes else "", scope_all=True)
    m = Model(flows, triggers, st, org=org)
    facts = build_facts(m)
    save_json({"model": MODEL, "system": PROMPT_PATH.read_text(encoding="utf-8"), "facts": facts}, "claude_input.json", out_dir)
    if args.reuse_claude:
        raw = json.loads((args.reuse_claude / "claude_output.json").read_text(encoding="utf-8"))
        save_json(raw, "claude_output.json", out_dir)
        validated, notes = validate(raw, facts)
        print(f"Using Claude's saved answer from {args.reuse_claude}", file=sys.stderr)
    else:
        print(f"Asking Claude ({MODEL}) to read {len(facts['flows'])} flows; this can take a few minutes...", file=sys.stderr)
        raw, validated, notes = run_programmes(facts)
        save_json(raw, "claude_output.json", out_dir)
    if notes:
        print(f"\nValidation dropped {len(notes)} parts of Claude's answer (listed on the page):", file=sys.stderr)
        for n in notes[:10]:
            print(f"  {n}", file=sys.stderr)
    return render_programme_page(m, facts, validated, notes, st, graph_model=graph_model)


if __name__ == "__main__":
    main()
