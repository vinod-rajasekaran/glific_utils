#!/usr/bin/env bash
# Build the Glific flow map in one step: fetch flows, fetch triggers, render HTML.
# Output: output/get_system_flow_architecture/<YYYY-MM-DD>/{flows.json,triggers.json,flow_architecture.html}
#
# Usage:
#   ./flow_map.sh --project "My Bot" --tag "2025 Pilot"        # live pull from Glific (uses .env)
#   ./flow_map.sh --from-json output/get_system_flow_architecture/2026-11-03 --tag "2025 Pilot"
#   ./flow_map.sh --help                                       # all options
set -euo pipefail
cd "$(dirname "$0")"
python3 get_system_flow_architecture/build_flow_architecture.py "$@"

# Open the newest page on macOS, unless --help was asked for
if [[ " $* " != *" --help "* && " $* " != *" -h "* ]] && command -v open >/dev/null; then
  page=$(ls -t output/get_system_flow_architecture/*/flow_architecture.html 2>/dev/null | head -1)
  [[ -n "$page" ]] && open "$page"
fi
