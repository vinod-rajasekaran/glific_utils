#!/usr/bin/env python3
"""Fetch all flows from a Glific instance, including each flow's nodes and edges.

Usage (put the variables in the repo-root .env, see .env.example, or export them):
  export GLIFIC_URL=https://api.yourorg.tides.coloredcow.com   # your Glific API host
  export GLIFIC_PHONE=91XXXXXXXXXX
  export GLIFIC_PASSWORD=secret
  python3 glific_get_flows.py --redact old/flows.json   # blank credentials in an earlier export
  python3 glific_get_flows.py   # writes output/get_system_flow_architecture/<YYYY-MM-DD>/flows.json
"""
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PAGE_SIZE = 100

# Results go to output/<feature>/<today's date>/ at the repo root (git-ignored).
# Re-running on the same day overwrites that day's files.
FEATURE = "get_system_flow_architecture"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / FEATURE / date.today().isoformat()


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

# Keep flows whose tag label contains one of these (case-insensitive).
# Untagged flows and tags containing "test" are dropped.
INCLUDE_TAGS = ("pilot", "central", "common")
EXCLUDE_TAGS = ("test",)

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


def save_json(data, filename):
    """Write data as JSON into OUTPUT_DIR and return the file path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
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


def wanted(flow):
    label = ((flow.get("tag") or {}).get("label") or "").lower()
    if not label or any(t in label for t in EXCLUDE_TAGS):
        return False
    return any(t in label for t in INCLUDE_TAGS)


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
SECRET_FIELD = re.compile(r'("[^"]*(?:key|token|secret|passw|auth|credential|userid|user_id)[^"]*"\s*:\s*)"(?!@|\[redacted\]")[^"]*"', re.I)
# Credential-shaped strings anywhere in a definition: JWTs and Bearer tokens.
SECRET_VALUE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?<=Bearer )[^\s\"']+", re.I)


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
            if isinstance(url, str) and "?" in url:
                parts = urlsplit(url)
                query = [(k, v if v.startswith("@") else REDACTED) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
                action["url"] = urlunsplit(parts._replace(query=urlencode(query, safe="@[]")))
                count += sum(1 for _, v in query if v == REDACTED)
            body = action.get("body")
            if isinstance(body, str):
                action["body"], n = SECRET_FIELD.subn(lambda m: f'{m.group(1)}"{REDACTED}"', body)
                count += n
    # Safety net for tokens anywhere else in the definition
    text, n = SECRET_VALUE.subn(REDACTED, json.dumps(nodes))
    if n:
        nodes[:] = json.loads(text)
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

    # To filter by tag again, use: [f for f in active_flows if wanted(f)]
    all_flows = active_flows
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
