# Glific MCP server

An [MCP](https://modelcontextprotocol.io) server that lets an assistant such as Claude read a Glific account: its flows (with full definitions), collections, message templates, tags, languages and organisation settings. It can also create flows and collections and start flows, but only when you switch that on.

> **Moved here from [`vinod-rajasekaran/glific-mcp`](https://github.com/vinod-rajasekaran/glific-mcp).** That repo held a Node.js version. This is a Python rewrite based on it, with the same tools, built on the repo's shared Glific client ([`glific_common/`](../glific_common/)). The old repo is no longer maintained.

| File | What it does |
|---|---|
| [`server.py`](server.py) | The server: its tools, masking of what it returns, and `--check` |
| [`../glific_mcp.sh`](../glific_mcp.sh) | Runs the server with the repo's `.venv`; this is what MCP clients launch |

## Setup

1. Follow the [main README's setup](../README.md#setup): `.venv` with `pip install -e ".[mcp]"`, and `GLIFIC_URL`, `GLIFIC_PHONE` and `GLIFIC_PASSWORD` in `.env`. The server reads the same `.env` as the org map, wherever it is started from.
2. Check it against your account:

   ```bash
   ./glific_mcp.sh --check
   ```

   This logs in, calls every read tool once and prints counts (flows, collections, templates, tags, languages) and the organisation's name. It changes nothing.
3. Connect it to a client:

   **Claude Code**
   ```bash
   claude mcp add glific -- /absolute/path/to/glific_utils/glific_mcp.sh
   ```

   **Claude Desktop** (`claude_desktop_config.json`)
   ```json
   {
     "mcpServers": {
       "glific": { "command": "/absolute/path/to/glific_utils/glific_mcp.sh" }
     }
   }
   ```

   Credentials stay in `.env`; nothing needs to go in the client's config.

## Tools

**Read tools** (always on, marked read-only):

| Tool | Returns |
|---|---|
| `list_flows` | Flows: id, uuid, name, keywords, active, tag, last change. Filters: `name_filter`, `active_only`; paging: `limit`, `offset` |
| `get_flow` | One flow's details and its full definition: nodes, actions (messages, webhooks, field updates, group changes, flow starts) and exits |
| `list_collections`, `get_collection` | Collections (contact groups) with their number of contacts |
| `list_templates` | Message templates: label, body, type, status, category, language. Filters: `label_filter`, `status` |
| `list_tags` | Tags |
| `get_organization_info` | The organisation's name and status, and the flows its settings start (default, new contact, opt-in, out-of-office, regex) |
| `list_languages` | Languages configured in the account |

**Write tools** (off unless `GLIFIC_MCP_ALLOW_WRITES=1` is set in `.env` or the client's environment):

| Tool | What it does |
|---|---|
| `create_flow` | Creates an empty flow with keywords |
| `create_collection` | Creates an empty collection |
| `start_flow_for_contact` | Starts a flow for one contact, by internal ID. **Sends WhatsApp messages to a real person** |
| `start_flow_for_collection` | Starts a flow for every contact in a collection. **Sends WhatsApp messages to real people** |

The two start tools are marked destructive, so clients that ask before such actions will ask you first.

## Privacy

Everything a tool returns goes to the assistant's model provider, so the server limits what it returns:

- **No contact data.** No tool reads or returns contacts, phone numbers or message history. The Node version had already removed those tools; its README still listed them.
- **Credentials blanked.** Flow definitions pass through `glific_common/redact.py` (webhook headers, keys in URLs and bodies, JWTs and Bearer tokens become `[redacted]`), as in the org map's export.
- **Free text masked.** Message texts, quick replies, sticky notes and template bodies pass through `glific_common/privacy.py`: phone numbers become `[number]`, emails `[email]`, links their host, and secrets `[redacted]`. IDs and structure are left intact so the assistant can follow them. Staff names are not recognised here (the org map finds them from staff alerts and tickets; this server does not read whole accounts).
- Names of flows, collections, tags and templates are returned as they are in Glific.

## Differences from the Node version

- Python, on the shared client: one `.env` for every feature. Settings changed from `GLIFIC_API_URL` (ending in `/api`) to `GLIFIC_URL` (the host), the same as the org map.
- `get_flow` now returns the flow's definition (the Node version said it did, but returned only name, keywords and dates).
- `list_flows` also returns uuid and tag, and can list only active flows; `get_organization_info` also returns the flows started by settings.
- Write tools are off by default.
- The login token is cached and renewed when Glific rejects it, instead of assumed to last 23 hours.
- Debug logging that printed the raw login reply (which holds the access token) is gone.

## Tests

`python3 -m unittest discover -s tests/glific_mcp -t .` from the repo root (with `.venv/bin/python3`, which has the `mcp` package). The tests call the server through an in-process MCP client against a fake Glific: read-only by default, write tools only when switched on, masking and redaction of flow definitions and templates, Glific errors, an expired token, and missing settings.
