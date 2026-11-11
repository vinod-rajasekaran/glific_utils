#!/usr/bin/env python3
"""Fetch all flows from a Glific instance, including each flow's nodes and edges.

Usage (put the variables in the repo-root .env, see .env.example, or export them):
  export GLIFIC_URL=https://api.yourorg.glific.com   # your Glific API host
  export GLIFIC_PHONE=91XXXXXXXXXX
  export GLIFIC_PASSWORD=secret
  python3 glific_get_flows.py --redact old/flows.json   # blank credentials in an earlier export
  python3 glific_get_flows.py   # writes output/get_system_flow_architecture/<YYYY-MM-DD_HH-MM-SS>/flows.json
"""
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PAGE_SIZE = 100

# Each run writes to its own folder, output/<feature>/<YYYY-MM-DD_HH-MM-SS>/ at the repo root
# (git-ignored), so earlier results are never overwritten.
FEATURE = "get_system_flow_architecture"
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "output" / FEATURE
_run_dir = None


def run_dir():
    """This run's output folder, named by the local start time. Created once, never reused."""
    global _run_dir
    if _run_dir is None:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        candidate, n = OUTPUT_ROOT / stamp, 2
        while candidate.exists():          # two runs in the same second
            candidate, n = OUTPUT_ROOT / f"{stamp}-{n}", n + 1
        candidate.mkdir(parents=True)
        _run_dir = candidate
    return _run_dir


def load_env(path=Path(__file__).resolve().parent.parent / ".env"):
    """Load KEY=VALUE lines from the repo-root .env, if present. Shell variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]  # drop one pair of matching surrounding quotes only
        os.environ.setdefault(key, value)


load_env()

FLOWS_QUERY = """
query flows($filter: FlowFilter, $opts: Opts) {
  flows(filter: $filter, opts: $opts) {
    id
    uuid
    name
    versionNumber
    flowType
    keywords
    lastPublishedAt
    lastChangedAt
    isActive
    tag { id label }
  }
}
"""

# Returns the full flow definition (nodes, actions, exits) as a JSON string
EXPORT_QUERY = """
query exportFlow($id: ID!) {
  exportFlow(id: $id) {
    exportData
    errors { key message }
  }
}
"""


def post(path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(
        os.environ["GLIFIC_URL"].rstrip("/") + path, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def save_json(data, filename, out_dir=None):
    """Write data as JSON into out_dir (default: this run's folder) and return the file path."""
    out_dir = out_dir or run_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(json.dumps(data, indent=2))
    return path


def login():
    body = {"user": {"phone": os.environ["GLIFIC_PHONE"], "password": os.environ["GLIFIC_PASSWORD"]}}
    return post("/api/v1/session", body)["data"]["access_token"]


def get_all_flows(token):
    flows, offset = [], 0
    while True:
        variables = {"filter": {"isActive": True}, "opts": {"order": "ASC", "limit": PAGE_SIZE, "offset": offset}}
        result = post("/api", {"query": FLOWS_QUERY, "variables": variables}, token)
        if result.get("errors"):
            sys.exit(f"GraphQL error: {result['errors']}")
        page = result["data"]["flows"]
        flows.extend(page)
        if len(page) < PAGE_SIZE:
            return flows
        offset += PAGE_SIZE


def find_definition(export, flow_uuid):
    """export_data contains the flow plus any sub-flows it calls; pick the matching one."""
    for item in export.get("flows", []):
        definition = item.get("definition", item)
        if definition.get("uuid") == flow_uuid:
            return definition
    return None


REDACTED = "[redacted]"
# Headers that never carry secrets; every other header value is blanked.
SAFE_HEADERS = {"content-type", "accept"}
# Webhook body fields whose literal values are blanked ("@..." expressions are kept).
SECRET_FIELD = re.compile(
    r'("[^"]*(?:key|token|secret|passw|auth|credential|userid|user_id)[^"]*"\s*:\s*)'
    r'(?:"(?!@|\[redacted\]")(?:[^"\\]|\\.)*"|-?\d[\d.eE+-]*)', re.I)
# Credential-shaped strings anywhere in a definition: JWTs and Bearer tokens.
SECRET_VALUE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?<=Bearer )(?!\[redacted\])[^\s\"'\\]+", re.I)


def _scrub(value):
    """Apply SECRET_VALUE to every string inside value. Returns (new value, count)."""
    if isinstance(value, str):
        return SECRET_VALUE.subn(REDACTED, value)
    if isinstance(value, list):
        out, total = [], 0
        for item in value:
            item, n = _scrub(item)
            out.append(item)
            total += n
        return out, total
    if isinstance(value, dict):
        out, total = {}, 0
        for k, item in value.items():
            out[k], n = _scrub(item)
            total += n
        return out, total
    return value, 0


def redact_url(url):
    """Blank user:pass@ credentials and query-string values in a webhook URL.

    Returns (new url, count). A URL that cannot be parsed (e.g. a malformed
    password containing '/' or a bad port) is left unchanged rather than crashing
    the export. IPv6 hosts keep their brackets.
    """
    if "@" not in url.split("?")[0] and "?" not in url:
        return url, 0
    try:
        parts = urlsplit(url)
        username, password, port = parts.username, parts.password, parts.port
    except ValueError:
        return url, 0  # malformed URL; leave it as-is
    count = 0
    if "://" in url and (password or (username and username != "redacted")):
        host = parts.hostname or ""
        if ":" in host:          # IPv6 literal; urlsplit strips the brackets
            host = f"[{host}]"
        host += f":{port}" if port else ""
        parts = parts._replace(netloc=f"redacted@{host}")
        count += 1
    if parts.query:
        original = parse_qsl(parts.query, keep_blank_values=True)
        query = [(k, v if v.startswith("@") else REDACTED) for k, v in original]
        parts = parts._replace(query=urlencode(query, safe="@[]"))
        count += sum(1 for (_, old), (_, new) in zip(original, query) if old != new)
    return urlunsplit(parts), count


def redact_nodes(nodes):
    """Blank webhook credentials in place before anything is saved. Returns the count."""
    count = 0
    for node in nodes:
        for action in node.get("actions") or []:
            if action.get("type") != "call_webhook":
                continue
            headers = action.get("headers")
            if isinstance(headers, dict):
                for name in headers:
                    if name.lower() not in SAFE_HEADERS and headers[name] != REDACTED:
                        headers[name] = REDACTED
                        count += 1
            url = action.get("url")
            if isinstance(url, str):
                action["url"], n = redact_url(url)
                count += n
            body = action.get("body")
            if isinstance(body, str):
                action["body"], n = SECRET_FIELD.subn(lambda m: f'{m.group(1)}"{REDACTED}"', body)
                count += n
    # Safety net for tokens anywhere else in the definition, string by string
    cleaned, n = _scrub(nodes)
    if n:
        nodes[:] = cleaned
    return count + n


def get_graph(flow, token):
    result = post("/api", {"query": EXPORT_QUERY, "variables": {"id": flow["id"]}}, token)
    payload = (result.get("data") or {}).get("exportFlow") or {}
    if result.get("errors") or payload.get("errors"):
        print(f"Export failed for {flow['name']}: {result.get('errors') or payload['errors']}", file=sys.stderr)
        return None, [], []

    export = payload.get("exportData") or payload.get("export_data") or {}
    if isinstance(export, str):
        export = json.loads(export)
    definition = find_definition(export, flow["uuid"]) or {}

    nodes = definition.get("nodes", [])
    redacted = redact_nodes(nodes)
    if redacted:
        print(f"  {flow['name']}: blanked {redacted} credential value(s)", file=sys.stderr)
    # Edges: each node exit points to a destination node (None = flow ends there)
    edges = [
        {"from": node["uuid"], "exit": ex["uuid"], "to": ex.get("destination_uuid")}
        for node in nodes
        for ex in node.get("exits", [])
    ]
    return definition, nodes, edges


def fetch_flows(token):
    """Fetch every active flow with its nodes, edges and editor layout."""
    active_flows = get_all_flows(token)

    # Show every tag seen so you can check nothing relevant was dropped
    tag_counts = Counter(((f.get("tag") or {}).get("label") or "<untagged>") for f in active_flows)
    print("Active flows by tag:", file=sys.stderr)
    for label, n in tag_counts.most_common():
        print(f"  {label}: {n}", file=sys.stderr)

    all_flows = active_flows  # every active flow; the flow map narrows by tag later
    print(f"Pulling all {len(all_flows)} active flows\n", file=sys.stderr)

    for flow in all_flows:
        definition, flow["nodes"], flow["edges"] = get_graph(flow, token)
        flow["ui"] = (definition or {}).get("_ui")  # node positions from the editor
        print(f"{flow['name']}: {len(flow['nodes'])} nodes, {len(flow['edges'])} edges", file=sys.stderr)
    return all_flows


def redact_file(path):
    """Blank credentials in a flows.json saved earlier, rewriting it in place."""
    flows = json.loads(Path(path).read_text())
    total = sum(redact_nodes(f.get("nodes") or []) for f in flows)
    Path(path).write_text(json.dumps(flows, indent=2))
    print(f"Blanked {total} credential value(s) in {path}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--redact":
        redact_file(sys.argv[2])  # python3 glific_get_flows.py --redact path/to/flows.json
        sys.exit()
    flows = fetch_flows(login())
    path = save_json(flows, "flows.json")
    print(f"Fetched {len(flows)} flows -> {path}", file=sys.stderr)
