#!/usr/bin/env bash
# Build the Glific flow map in one step: fetch flows, fetch triggers, render HTML.
# Output: a new folder per run, output/get_system_flow_architecture/<YYYY-MM-DD_HH-MM-SS>/
#         holding flows.json, triggers.json and flow_architecture.html. Nothing is overwritten.
#
# Usage (works from any folder; relative paths are read from where you run it):
#   ./flow_map.sh --project "My Bot" --tag "2025 Pilot"        # live pull from Glific (uses .env)
#   ./flow_map.sh --from-json output/get_system_flow_architecture/2026-11-11_21-43-05 --tag "2025 Pilot"
#   ./flow_map.sh --help                                       # all options
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD="$ROOT/get_system_flow_architecture/build_flow_architecture.py"

for arg in "$@"; do
  if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
    exec python3 "$BUILD" --help
  fi
done

# The build prints the page it wrote as its only stdout line; progress goes to stderr.
page="$(python3 "$BUILD" "$@")"

if [[ -f "$page" ]] && command -v open >/dev/null; then
  open "$page"
fi
exit 0
