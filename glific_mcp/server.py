#!/usr/bin/env python3
"""An MCP server for a Glific account: lets an assistant such as Claude read the account's flows,
collections, templates, tags, languages and settings, and (only when switched on) create flows and
collections or start flows.

Based on github.com/vinod-rajasekaran/glific-mcp (Node.js), rewritten in Python on the repo's
shared Glific client. Settings come from the repo-root .env (GLIFIC_URL, GLIFIC_PHONE,
GLIFIC_PASSWORD), the same as every other feature.

Privacy and safety:
  - No tool reads or returns contacts, phone numbers or message history.
  - Flow definitions come with webhook credentials blanked; message texts, quick replies and
    template bodies have phone numbers, emails, links and secrets masked. IDs are left intact.
  - Tools that change the account or message real people are registered only when
    GLIFIC_MCP_ALLOW_WRITES=1.

Usage:
  .venv/bin/python3 glific_mcp/server.py            # serve over stdio (what MCP clients launch)
  .venv/bin/python3 glific_mcp/server.py --check    # log in, call every read tool once, print a summary
"""
import os
import sys
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repo root, for glific_common

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from glific_common import api  # noqa: E402
from glific_common.flows import export_definition  # noqa: E402
from glific_common.privacy import mask  # noqa: E402

WRITES_ON = os.environ.get("GLIFIC_MCP_ALLOW_WRITES") == "1"
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
SENDS = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

INSTRUCTIONS = (
    "Tools for one Glific (WhatsApp chatbot) account. Use the list tools to find IDs, then the get tools for detail. "
    "get_flow returns a flow's full definition: nodes with actions (messages, webhooks, field updates, group changes, "
    "starts of other flows) and exits. Message texts are masked for phone numbers, emails and links, and webhook "
    "credentials are blanked, so '[number]', '[email]' and '[redacted]' are placeholders, not real values."
    + ("" if WRITES_ON else " This server is read-only: it cannot create flows or collections, or start flows.")
)

server = MCPServer(name="glific", title="Glific", instructions=INSTRUCTIONS, version="2.0.0")
_session = None


def session(post=None):
    """The shared logged-in session, created on first use. post replaces the HTTP call (tests)."""
    global _session
    if post is not None:
        _session = api.Session(post=post)
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
    print("OK: the .env settings work and every read tool answered." + ("" if WRITES_ON else " Write tools are off."))


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        import asyncio
        asyncio.run(check())
    else:
        server.run()
