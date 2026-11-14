#!/usr/bin/env bash
# Run the Glific MCP server (glific_mcp/server.py) with the repo's virtual environment.
# MCP clients (Claude Code, Claude Desktop) launch this; it talks MCP over stdin/stdout.
#
# Usage (works from any folder):
#   ./glific_mcp.sh            # serve over stdio
#   ./glific_mcp.sh --check    # log in with .env, call every read tool once, print a summary
# Add to Claude Code:  claude mcp add glific -- /absolute/path/to/glific_utils/glific_mcp.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="python3"
if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  PY="$ROOT/.venv/bin/python3"
fi
exec "$PY" "$ROOT/glific_mcp/server.py" "$@"
