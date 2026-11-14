#!/usr/bin/env python3
"""An MCP server for a Glific account: lets an assistant such as Claude read the account's flows,
collections, templates, tags, languages and settings, and (only when switched on) create flows and
collections or start flows.

Based on github.com/vinod-rajasekaran/glific-mcp (Node.js), rewritten in Python on the repo's
shared Glific client. Settings come from the repo-root .env (GLIFIC_URL, GLIFIC_PHONE,
GLIFIC_PASSWORD), the same as every other feature.

The org tools (get_org_overview, get_flow_facts, get_org_facts) pull the whole account once and
return the same cleaned facts the org map sends to Claude; get_org_map returns the programmes from
the latest saved org map (org_map.json).

Privacy and safety:
  - No tool reads or returns contacts, phone numbers or message history.
  - The org tools mask staff names too (found from staff alerts and tickets across the account).
  - Flow definitions come with webhook credentials blanked; message texts, quick replies and
    template bodies have phone numbers, emails, links and secrets masked. IDs are left intact.
  - Tools that change the account or message real people are registered only when
    GLIFIC_MCP_ALLOW_WRITES=1.

Usage:
  .venv/bin/python3 glific_mcp/server.py            # serve over stdio (what MCP clients launch)
  .venv/bin/python3 glific_mcp/server.py --check    # log in, call every read tool once, print a summary
"""
import copy
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repo root, for glific_common

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from glific_common import api  # noqa: E402
from glific_common.flows import export_definition  # noqa: E402
from glific_common.org_facts import fetch, org_map_file  # noqa: E402
from glific_common.org_facts.facts import build_facts  # noqa: E402
from glific_common.org_facts.grouping import group_flows  # noqa: E402
from glific_common.org_facts.model import Model, Settings  # noqa: E402
from glific_common.privacy import mask  # noqa: E402

WRITES_ON = os.environ.get("GLIFIC_MCP_ALLOW_WRITES") == "1"
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
SENDS = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

INSTRUCTIONS = (
    "Tools for one Glific (WhatsApp chatbot) account. Use the list tools to find IDs, then the get tools for detail. "
    "get_flow returns a flow's full definition: nodes with actions (messages, webhooks, field updates, group changes, "
    "starts of other flows) and exits. Message texts are masked for phone numbers, emails and links, and webhook "
    "credentials are blanked, so '[number]', '[email]' and '[redacted]' are placeholders, not real values. "
    "To understand what the bot does, start with get_org_overview (every active flow, how flows group by their links, "
    "flows started by settings), then get_flow_facts for one flow (how it starts, what it leads to, what it touches, "
    "message excerpts). get_org_map returns the programmes from the latest saved org map, if one was built. "
    "The first org tool call pulls the whole account, which can take a minute."
    + ("" if WRITES_ON else " This server is read-only: it cannot create flows or collections, or start flows.")
)

server = MCPServer(name="glific", title="Glific", instructions=INSTRUCTIONS, version="2.1.0")
_session = None
_org = None   # the account's model and facts, pulled on the first org tool call


def session(post=None):
    """The shared logged-in session, created on first use. post replaces the HTTP call (tests)."""
    global _session, _org
    if post is not None:
        _session, _org = api.Session(post=post), None
    if _session is None:
        missing = api.missing_settings()
        if missing:
            raise ToolError(f"Glific is not configured: set {', '.join(missing)} in the repo's .env.")
        _session = api.Session()
    return _session


def query(q, variables=None):
    try:
        return session().query(q, variables)
    except api.GlificError as e:
        raise ToolError(str(e)) from e


def _opts(limit, offset):
    return {"limit": max(1, min(int(limit), 500)), "offset": max(0, int(offset))}


def _masked(value):
    """value with every string masked (for free text: messages, quick replies, template bodies)."""
    if isinstance(value, str):
        return mask(value, set())
    if isinstance(value, list):
        return [_masked(v) for v in value]
    if isinstance(value, dict):
        return {k: _masked(v) for k, v in value.items()}
    return value


TEXT_FIELDS = ("text", "quick_replies", "body")


def _mask_definition(definition):
    """Mask the free text in a flow definition's actions and sticky notes; leave IDs and structure."""
    for node in definition.get("nodes") or []:
        for action in node.get("actions") or []:
            for k in TEXT_FIELDS:
                if k in action:
                    action[k] = _masked(action[k])
    ui = definition.get("_ui")
    if isinstance(ui, dict) and isinstance(ui.get("stickies"), dict):
        ui["stickies"] = _masked(ui["stickies"])
    return definition


def _checked(payload, key):
    """The object under key in a create/start mutation, raising the mutation's own errors."""
    if payload.get("errors"):
        raise ToolError(f"Glific refused: {payload['errors']}")
    return payload.get(key) if key else payload


# ── Read tools ───────────────────────────────────────────────────────────────

@server.tool(annotations=READ)
def list_flows(limit: int = 20, offset: int = 0, name_filter: str = "", active_only: bool = False) -> list[dict[str, Any]]:
    """List flows: id, uuid, name, keywords, whether active, tag and last change. name_filter matches part of the name."""
    flt = {"name": name_filter} if name_filter else {}
    if active_only:
        flt["isActive"] = True
    data = query("""query flows($filter: FlowFilter, $opts: Opts) {
      flows(filter: $filter, opts: $opts) { id uuid name keywords isActive lastChangedAt tag { label } } }""",
                 {"filter": flt, "opts": _opts(limit, offset)})
    return data["flows"]


@server.tool(annotations=READ)
def get_flow(id: str, include_definition: bool = True) -> dict[str, Any]:
    """Get one flow by ID: its details and, by default, its full definition (nodes, actions and exits),
    with webhook credentials blanked and message text masked."""
    data = query("""query flow($id: ID!) { flow(id: $id) {
      flow { id uuid name keywords ignoreKeywords isActive versionNumber lastPublishedAt lastChangedAt tag { label } }
      errors { key message } } }""", {"id": id})
    flow = _checked(data["flow"] or {}, "flow")
    if not flow:
        raise ToolError(f"No flow with ID {id}.")
    if include_definition:
        try:
            s = session()
            definition, _ = s.call(lambda token: export_definition(flow["id"], flow["uuid"], token, post=s.post))
        except api.GlificError as e:
            raise ToolError(f"Could not export flow {id}: {e}") from e
        flow["definition"] = _mask_definition(definition)
    return flow


@server.tool(annotations=READ)
def list_collections(limit: int = 20, offset: int = 0, label_filter: str = "") -> list[dict[str, Any]]:
    """List collections (contact groups): id, label, description, number of contacts and whether restricted."""
    data = query("""query groups($filter: GroupFilter, $opts: Opts) {
      groups(filter: $filter, opts: $opts) { id label description contactsCount isRestricted } }""",
                 {"filter": {"label": label_filter} if label_filter else {}, "opts": _opts(limit, offset)})
    return data["groups"]


@server.tool(annotations=READ)
def get_collection(id: str) -> dict[str, Any]:
    """Get one collection by ID, with its number of contacts."""
    data = query("""query group($id: ID!) { group(id: $id) {
      group { id label description contactsCount isRestricted } errors { key message } } }""", {"id": id})
    group = _checked(data["group"] or {}, "group")
    if not group:
        raise ToolError(f"No collection with ID {id}.")
    return group


@server.tool(annotations=READ)
def list_templates(limit: int = 20, offset: int = 0, label_filter: str = "",
                   status: Literal["", "APPROVED", "PENDING", "REJECTED"] = "") -> list[dict[str, Any]]:
    """List message templates (HSMs and session templates): label, body (masked), type, status, category, language."""
    flt = {k: v for k, v in (("label", label_filter), ("status", status)) if v}
    data = query("""query sessionTemplates($filter: SessionTemplateFilter, $opts: Opts) {
      sessionTemplates(filter: $filter, opts: $opts) { id label body type status isHsm category language { label } } }""",
                 {"filter": flt, "opts": _opts(limit, offset)})
    return [{**t, "body": _masked(t.get("body"))} for t in data["sessionTemplates"]]


@server.tool(annotations=READ)
def list_tags(limit: int = 50, offset: int = 0, label_filter: str = "") -> list[dict[str, Any]]:
    """List tags used to label contacts, messages and flows."""
    data = query("""query tags($filter: TagFilter, $opts: Opts) {
      tags(filter: $filter, opts: $opts) { id label description colorCode } }""",
                 {"filter": {"label": label_filter} if label_filter else {}, "opts": _opts(limit, offset)})
    return data["tags"]


@server.tool(annotations=READ)
def get_organization_info() -> dict[str, Any]:
    """The organisation's name and status, and the flows its settings start: the default flow (any message that
    matches no keyword), the new-contact, opt-in, out-of-office and regex flows."""
    data = query("""query organization { organization { organization {
      id name isActive
      newcontactFlowId optinFlowId
      outOfOffice { enabled startTime endTime flowId defaultFlowId }
      regxFlow { flowId regx } } } }""")
    return data["organization"]["organization"]


@server.tool(annotations=READ)
def list_languages() -> list[dict[str, Any]]:
    """List the languages configured in the account."""
    return query("""query languages($opts: Opts) { languages(opts: $opts) { id label locale isActive } }""",
                 {"opts": {"limit": 100, "offset": 0}})["languages"]


# ── Org tools: the cleaned facts the org map is built from ──────────────────

def org(refresh=False):
    """{"model", "facts", "pulled"} for the whole account, pulled once and kept for this process."""
    global _org
    if _org is None or refresh:
        s = session()
        try:
            flows, triggers, settings = s.call(lambda token: fetch.fetch_all(token, post=s.post))
        except api.GlificError as e:
            raise ToolError(f"Could not read the account: {e}") from e
        name = mask(str(settings.get("name") or "")).strip() or "Glific chatbot"
        m = Model(flows, triggers, Settings(project=name), org=settings)
        _org = {"model": m, "facts": build_facts(m), "pulled": datetime.now().isoformat(timespec="seconds")}
    return _org


def org_map_root():
    """Where the org map writes its runs (GLIFIC_OUTPUT_ROOT replaces it, as for the org map)."""
    return Path(os.environ.get("GLIFIC_OUTPUT_ROOT") or api.ROOT / "output" / "org_programme_architecture")


def _named(m, entries):
    """starts_from / leads_to entries with the name of the flow each one refers to."""
    return [{**e, "flow": m.name(e["ref"])} if e.get("ref") in m.flows else e for e in entries]


def _find_flow(facts, flow):
    """The fact for a flow given its id (uuid) or its name: exact, else the one name containing it."""
    by_id = {f["id"]: f for f in facts["flows"]}
    if flow in by_id:
        return by_id[flow]
    q = flow.strip().casefold()
    exact = [f for f in facts["flows"] if f["name"].casefold() == q]
    found = exact or [f for f in facts["flows"] if q and q in f["name"].casefold()]
    if len(found) == 1:
        return found[0]
    if not found:
        raise ToolError(f"No active flow named {flow!r}. get_org_overview lists every active flow.")
    raise ToolError(f"{len(found)} flows match {flow!r}: " + "; ".join(f["name"] for f in found[:15])
                    + ". Give the full name or the id.")


@server.tool(annotations=READ)
def get_org_overview(refresh: bool = False) -> dict[str, Any]:
    """What the bot is made of: every active flow (id, name, tag, keywords), the flows started by the
    organisation's settings, the flows grouped by their links (flows that start each other, hand over
    data or fill a group a schedule sends to), counts, and warnings. Pulls the whole account on the first
    call (refresh=True pulls it again). Start here, then use get_flow_facts."""
    o = org(refresh)
    m, f = o["model"], o["facts"]
    path, saved = org_map_file.latest(org_map_root())
    return {
        "organisation": m.st.project,
        "pulled_at": o["pulled"],
        "counts": {"active_flows": len(f["flows"]), "triggers": len(f["triggers"]),
                   "active_triggers": sum(1 for t in f["triggers"] if t.get("active")),
                   "groups": len(f["groups"]), "outside_hosts": len(f["hosts"])},
        "started_by_settings": [{"flow": m.name(u), "id": u, "settings": [short for short, _ in v]}
                                for u, v in sorted(m.setting_starts.items(), key=lambda kv: m.name_key(kv[0]))],
        "groups_by_links": [{"name": name, "flows": [m.name(u) for u in us]} for name, us in group_flows(m)],
        "warnings": f["findings"],
        "flows": [{"id": x["id"], "name": x["name"], "tag": x["tag"], "keywords": x["keywords"]} for x in f["flows"]],
        "saved_org_map": {"built": saved.get("built"), "source": saved.get("source")} if saved else None,
    }


@server.tool(annotations=READ)
def get_flow_facts(flow: str) -> dict[str, Any]:
    """Everything known about one active flow, by name (or part of it) or id: how it starts (keywords,
    schedules, other flows, settings, groups), what it leads to, what it touches (groups, fields, outside
    services, sheets), its routes, and excerpts of its messages and notes (masked). Includes what the saved
    org map says it is for, when there is one."""
    o = org()
    m = o["model"]
    fact = copy.deepcopy(_find_flow(o["facts"], flow))
    fact["starts_from"] = _named(m, fact.get("starts_from") or [])
    fact["leads_to"] = _named(m, fact.get("leads_to") or [])
    _, saved = org_map_file.latest(org_map_root())
    if saved:
        answer = saved.get("answer") or {}
        reading = next((x for x in answer.get("flows") or [] if x.get("id") == fact["id"]), None)
        if reading:
            part = next((u for u in answer.get("use_cases") or [] if u.get("id") == reading.get("use_case")), {})
            fact["org_map"] = {"purpose": reading.get("purpose", ""), "role": reading.get("role", ""),
                               "part": part.get("name", ""), "confidence": reading.get("confidence", ""),
                               "source": saved.get("source"), "built": saved.get("built")}
    return fact


@server.tool(annotations=READ)
def get_org_facts(include_excerpts: bool = False) -> dict[str, Any]:
    """The whole account's cleaned facts, as the org map sends them to Claude: every flow (how it starts,
    what it leads to, what it touches, routes), groups, triggers, links between flows, outside hosts and
    warnings. Message excerpts are left out unless include_excerpts=True (that roughly doubles the size;
    get_flow_facts gives one flow's excerpts)."""
    f = org()["facts"]
    if include_excerpts:
        return f
    return {**f, "flows": [{k: v for k, v in x.items() if k != "excerpts"} | {"excerpt_count": len(x.get("excerpts") or [])}
                           for x in f["flows"]]}


def _statements(items, names):
    return [{"text": s.get("text", ""), "confidence": s.get("confidence", ""),
             "about": [names[r] for r in s.get("refs") or [] if r in names]} for s in items or []]


@server.tool(annotations=READ)
def get_org_map(programme: str = "") -> dict[str, Any]:
    """The programmes from the latest saved org map built by ./org_map.sh (the newest built with Claude, else the newest grouped by links):
    the organisation summary and each programme with its parts and flows. Give programme (its name or id) for
    its story, how each part works, what to watch, and each flow's purpose."""
    path, saved = org_map_file.latest(org_map_root())
    if not saved:
        raise ToolError("No org map has been saved yet. Run ./org_map.sh (or ./org_map.sh --no-claude) in glific_utils first.")
    a, names = saved.get("answer") or {}, saved.get("flow_names") or {}
    parts = {u["id"]: u for u in a.get("use_cases") or []}
    head = {"built": saved.get("built"), "run": path.parent.name, "organisation": saved.get("project"),
            "source": "Claude" if saved.get("source") == "claude" else "grouped by links, without Claude",
            "reason": saved.get("reason") or None}
    if not programme:
        return {**head,
                "summary": (a.get("org_summary") or {}).get("text", ""),
                "programmes": [{"id": p["id"], "name": p["name"], "summary": p.get("summary", ""), "kind": p.get("kind", ""),
                                "parts": [{"id": pid, "name": parts[pid]["name"], "summary": parts[pid].get("summary", ""),
                                           "flows": [names.get(u, u) for u in parts[pid].get("flows") or []]}
                                          for pid in p.get("parts") or [] if pid in parts]}
                               for p in a.get("programmes") or []],
                "not_placed": [names.get(u, u) for u in a.get("not_placed") or []],
                "outside_systems": [{"host": s.get("host"), "name": s.get("name")} for s in a.get("systems") or []],
                "dropped_by_validation": len(saved.get("dropped") or [])}
    q = programme.strip().casefold()
    p = next((p for p in a.get("programmes") or [] if q in (p["id"].casefold(), p["name"].casefold())), None)
    if not p:
        raise ToolError(f"No programme {programme!r}. Programmes: " + "; ".join(x["name"] for x in a.get("programmes") or []))
    readings = {x["id"]: x for x in a.get("flows") or []}

    def part(u):
        return {"name": u["name"], "summary": u.get("summary", ""), "kind": u.get("kind", ""),
                "story": _statements(u.get("story"), names), "how_it_works": _statements(u.get("how_it_works"), names),
                "watch": _statements(u.get("watch"), names),
                "flows": [{"name": names.get(x, x), "id": x, "purpose": readings.get(x, {}).get("purpose", ""),
                           "role": readings.get(x, {}).get("role", "")} for x in u.get("flows") or []]}
    return {**head, "name": p["name"], "summary": p.get("summary", ""), "kind": p.get("kind", ""),
            "confidence": p.get("confidence", ""), "story": _statements(p.get("story"), names),
            "watch": _statements(p.get("watch"), names),
            "parts": [part(parts[pid]) for pid in p.get("parts") or [] if pid in parts]}


# ── Tools that change the account (only with GLIFIC_MCP_ALLOW_WRITES=1) ─────

def create_flow(name: str, keywords: list[str], description: str = "", ignore_keywords: bool = False) -> dict[str, Any]:
    """Create a new, empty flow with these keywords. It changes the live account."""
    data = query("""mutation createFlow($input: FlowInput!) {
      createFlow(input: $input) { flow { id uuid name keywords } errors { key message } } }""",
                 {"input": {"name": name, "keywords": keywords, "description": description, "ignoreKeywords": ignore_keywords}})
    return _checked(data["createFlow"], "flow")


def create_collection(label: str, description: str = "") -> dict[str, Any]:
    """Create a new, empty collection. It changes the live account."""
    data = query("""mutation createGroup($input: GroupInput!) {
      createGroup(input: $input) { group { id label description } errors { key message } } }""",
                 {"input": {"label": label, "description": description}})
    return _checked(data["createGroup"], "group")


def start_flow_for_contact(flow_id: str, contact_id: str) -> dict[str, Any]:
    """Start a flow for one contact by internal ID. It sends WhatsApp messages to a real person."""
    data = query("""mutation startContactFlow($flowId: ID!, $contactId: ID!) {
      startContactFlow(flowId: $flowId, contactId: $contactId) { success errors { key message } } }""",
                 {"flowId": flow_id, "contactId": contact_id})
    return _checked(data["startContactFlow"], None)


def start_flow_for_collection(flow_id: str, group_id: str) -> dict[str, Any]:
    """Start a flow for every contact in a collection. It sends WhatsApp messages to real people."""
    data = query("""mutation startGroupFlow($flowId: ID!, $groupId: ID!) {
      startGroupFlow(flowId: $flowId, groupId: $groupId) { success errors { key message } } }""",
                 {"flowId": flow_id, "groupId": group_id})
    return _checked(data["startGroupFlow"], None)


WRITE_TOOLS = [(create_flow, WRITE), (create_collection, WRITE),
               (start_flow_for_contact, SENDS), (start_flow_for_collection, SENDS)]
if WRITES_ON:
    for fn, ann in WRITE_TOOLS:
        server.tool(annotations=ann)(fn)


# ── --check: validate the settings against the real account ──────────────────

async def check():
    """Log in with the .env settings, call every read tool once through an MCP client, and print
    what came back: counts and the organisation's name only."""
    import json
    from mcp import Client

    missing = api.missing_settings()
    if missing:
        sys.exit(f"Not configured: set {', '.join(missing)} in .env")
    async with Client(server) as client:
        tools = await client.list_tools()
        print(f"{len(tools.tools)} tools: {', '.join(t.name for t in tools.tools)}")

        async def call(name, args=None):
            r = await client.call_tool(name, args or {})
            if r.is_error:
                raise SystemExit(f"{name} failed: {r.content[0].text if r.content else r}")
            s = r.structured_content
            return s.get("result", s) if isinstance(s, dict) else s

        org = await call("get_organization_info")
        print(f"Organisation: {org['name']} (active: {org['isActive']})")
        settings = {k: v for k, v in {"default flow": (org.get("outOfOffice") or {}).get("defaultFlowId"),
                                      "new contact flow": org.get("newcontactFlowId"), "opt-in flow": org.get("optinFlowId")}.items() if v}
        print("Flows started by settings: " + (", ".join(f"{k} {v}" for k, v in settings.items()) or "none"))
        flows = await call("list_flows", {"limit": 500, "active_only": True})
        print(f"Active flows: {len(flows)}")
        for name, args in (("list_collections", {"limit": 500}), ("list_templates", {"limit": 500}),
                           ("list_tags", {"limit": 500}), ("list_languages", None)):
            print(f"{name}: {len(await call(name, args))}")
        if flows:
            f = await call("get_flow", {"id": flows[0]["id"]})
            text = json.dumps(f.get("definition") or {})
            print(f"get_flow {f['name']!r}: {len((f.get('definition') or {}).get('nodes') or [])} nodes; "
                  f"placeholders in it: {text.count('[redacted]')} [redacted], {text.count('[number]')} [number], "
                  f"{text.count('[email]')} [email]")
        import time
        start = time.monotonic()
        o = await call("get_org_overview")
        print(f"get_org_overview: {o['counts']['active_flows']} flows, {len(o['groups_by_links'])} groups by links, "
              f"{len(o['started_by_settings'])} started by settings; pulled in {time.monotonic() - start:.0f}s; "
              f"{len(json.dumps(o)):,} characters")
        if o["flows"]:
            f = await call("get_flow_facts", {"flow": o["flows"][0]["id"]})
            print(f"get_flow_facts {f['name']!r}: {len(f.get('excerpts') or [])} excerpts; {len(json.dumps(f)):,} characters")
        for args in ({}, {"include_excerpts": True}):
            print(f"get_org_facts {args or ''}: {len(json.dumps(await call('get_org_facts', args))):,} characters")
        r = await client.call_tool("get_org_map", {})
        if r.is_error:
            print("get_org_map: no saved org map yet (run ./org_map.sh)")
        else:
            m = r.structured_content
            print(f"get_org_map: run {m['run']} ({m['source']}), {len(m['programmes'])} programmes; {len(json.dumps(m)):,} characters")
            if m["programmes"]:
                d = await call("get_org_map", {"programme": m["programmes"][0]["id"]})
                print(f"get_org_map {d['name']!r}: {len(d['parts'])} parts; {len(json.dumps(d)):,} characters")
    print("OK: the .env settings work and every read tool answered." + ("" if WRITES_ON else " Write tools are off."))


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        import asyncio
        asyncio.run(check())
    else:
        server.run()
