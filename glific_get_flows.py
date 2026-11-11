#!/usr/bin/env python3
"""Fetch all flows from a Glific instance, including each flow's nodes and edges.

Usage:
  export GLIFIC_URL=https://api.yourorg.tides.coloredcow.com   # your Glific API host
  export GLIFIC_PHONE=91XXXXXXXXXX
  export GLIFIC_PASSWORD=secret
  python3 glific_get_flows.py > flows.json
"""
import json
import os
import sys
import urllib.request
from collections import Counter

BASE = os.environ["GLIFIC_URL"].rstrip("/")
PAGE_SIZE = 100

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
        BASE + path, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


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
    # Edges: each node exit points to a destination node (None = flow ends there)
    edges = [
        {"from": node["uuid"], "exit": ex["uuid"], "to": ex.get("destination_uuid")}
        for node in nodes
        for ex in node.get("exits", [])
    ]
    return definition, nodes, edges


if __name__ == "__main__":
    token = login()
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
    print(json.dumps(all_flows, indent=2))
    print(f"Fetched {len(all_flows)} flows", file=sys.stderr)
