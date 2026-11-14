"""Pulling what the facts are read from: every active flow with its definition (credentials
blanked), every trigger, and the organisation settings that start flows.

Errors raise GlificError (never exit), and progress goes to stderr only: the MCP server uses this,
and its stdout is the protocol channel."""
import sys
from collections import Counter

from glific_common.api import GlificError, paged, post as glific_post
from glific_common.flows import export_definition, list_flows
from .schedules import WEEKDAYS as FULL_WEEKDAYS

TRIGGERS_QUERY = """
query triggers($filter: TriggerFilter, $opts: Opts) {
  triggers(filter: $filter, opts: $opts) {
    id
    name
    isActive
    isRepeating
    frequency
    days
    hours
    startAt
    nextTriggerAt
    endDate
    groupType
    groups
    waGroups
    flow { id uuid name isActive tag { label } }
  }
}
"""

# Only the organisation's name, flow IDs and switches: no emails, phone numbers or keys
SETTINGS_QUERY = """
query organization {
  organization {
    organization {
      name
      newcontactFlowId
      optinFlowId
      outOfOffice { enabled flowId defaultFlowId }
      regxFlow { flowId regx }
    }
    errors { key message }
  }
}
"""

WEEKDAYS = {k: v[:3] for k, v in FULL_WEEKDAYS.items()}


def log(*parts):
    print(*parts, file=sys.stderr)


def graph(flow, token, post=glific_post):
    """(definition, nodes, edges) of one flow; a failed export is logged and gives ({}, [], [])."""
    try:
        definition, redacted = export_definition(flow["id"], flow["uuid"], token, post=post)
    except GlificError as e:
        log(f"Export failed for {flow['name']}: {e}")
        return {}, [], []
    nodes = definition.get("nodes", [])
    if redacted:
        log(f"  {flow['name']}: blanked {redacted} credential value(s)")
    # Edges: each node exit points to a destination node (None = flow ends there)
    edges = [{"from": node["uuid"], "exit": ex["uuid"], "to": ex.get("destination_uuid")}
             for node in nodes for ex in node.get("exits", [])]
    return definition, nodes, edges


def fetch_flows(token, post=glific_post):
    """Every active flow with its nodes, edges and editor layout. Raises GlificError when the flow
    list cannot be read."""
    flows = list_flows(token, filter={"isActive": True}, post=post)
    tags = Counter(((f.get("tag") or {}).get("label") or "<untagged>") for f in flows)
    log("Active flows by tag:")   # every tag seen, so you can check nothing relevant was dropped
    for label, n in tags.most_common():
        log(f"  {label}: {n}")
    log(f"Pulling all {len(flows)} active flows\n")
    for flow in flows:
        definition, flow["nodes"], flow["edges"] = graph(flow, token, post)
        flow["ui"] = definition.get("_ui")   # node positions from the editor
        log(f"{flow['name']}: {len(flow['nodes'])} nodes, {len(flow['edges'])} edges")
    return flows


def describe(t):
    """Human-readable schedule, e.g. 'weekly on Mon, Thu from 2025-06-01T04:30:00Z'."""
    freq = (t.get("frequency") or "none") if t.get("isRepeating") else "once"
    days, hours = t.get("days") or [], t.get("hours") or []
    if freq == "weekly" and days:
        freq += " on " + ", ".join(WEEKDAYS.get(d, str(d)) for d in days)
    elif freq == "monthly" and days:
        freq += " on day(s) " + ", ".join(map(str, days))
    elif freq == "hourly" and hours:
        freq += " at hour(s) " + ", ".join(map(str, hours)) + " UTC"
    when = f"{freq} from {t.get('startAt')}"
    if t.get("endDate"):
        when += f" until {t['endDate']}"
    return when


def fetch_triggers(token, post=glific_post):
    """Every trigger, active and inactive, each with a readable `schedule`. Raises GlificError."""
    triggers = paged(TRIGGERS_QUERY, "triggers", token, post=post)
    for t in triggers:
        t["schedule"] = describe(t)
        flow = (t.get("flow") or {}).get("name") or "<no flow>"
        status = "ACTIVE  " if t.get("isActive") else "inactive"
        log(f"{status} {t['name']} -> {flow} | {t['schedule']} | groups: {t.get('groups')}")
    return triggers


def fetch_settings(token, post=glific_post):
    """The organisation's flow settings, or {} (with a warning) when they cannot be read."""
    try:
        result = post("/api", {"query": SETTINGS_QUERY}, token)
    except Exception as e:   # noqa: BLE001 - settings are optional; the facts work without them
        log(f"Warning: could not read the organisation settings ({type(e).__name__}); "
            "flows started by Glific settings will show as 'No start found'.")
        return {}
    org = ((result.get("data") or {}).get("organization") or {}).get("organization")
    if result.get("errors") or not org:
        log("Warning: the organisation settings were not returned; "
            "flows started by Glific settings will show as 'No start found'.")
        return {}
    return org


def fetch_all(token, post=glific_post):
    """(flows, triggers, settings) for the whole account."""
    return fetch_flows(token, post), fetch_triggers(token, post), fetch_settings(token, post)
