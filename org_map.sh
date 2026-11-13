#!/usr/bin/env bash
# Map a Glific org in one step: fetch flows, triggers and settings, build graph.html and,
# with --programmes, programmes.html. Opens the pages it wrote.
# Output: a new folder per run, output/org_programme_architecture/<YYYY-MM-DD_HH-MM-SS>/. Nothing is overwritten.
#
# Usage (works from any folder; relative paths are read from where you run it):
#   ./org_map.sh --project "My Bot" --tag "2025 Pilot"                  # live pull from Glific (uses .env)
#   ./org_map.sh --project "My Bot" --tag "2025 Pilot" --programmes     # also ask Claude for the programme page
#   ./org_map.sh --from-json output/org_programme_architecture/<run> --tag "2025 Pilot"
#   ./org_map.sh --help                                                 # all options
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD="$ROOT/org_programme_architecture/build_org_map.py"
# Use the repo's virtual environment when there is one (it holds the anthropic package for --programmes)
PY="python3"
if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
fi

for arg in "$@"; do
  if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
    exec "$PY" "$BUILD" --help
  fi
done

# The build prints each page it wrote on its own stdout line; progress goes to stderr.
pages="$("$PY" "$BUILD" "$@")"

while IFS= read -r page; do
  if [[ -f "$page" ]] && command -v open >/dev/null; then
    open "$page"
  fi
done <<< "$pages"
exit 0
