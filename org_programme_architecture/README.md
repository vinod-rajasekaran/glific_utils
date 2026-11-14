# Org Programme Architecture

Pulls every active flow, every trigger and the organisation's flow settings from a Glific instance, and builds one page, `org_map.html`:

- **Programmes from Claude** (the default when the `anthropic` package and an API key are present): Claude reads the flows and explains what the bot does, as a few programmes made of parts, with a graph and a story for each.
- **Groups by links, without Claude** (`--no-claude`, no key, or Claude's answer unusable): Python groups flows that start each other, hand over data or fill a group a schedule sends to. The page has the same layout, with a "Built without Claude" banner saying why, and no summaries or roles.

Either way the full flow graph is one more view on the page: how every flow starts (schedule, keyword, another flow, a Glific setting or a contact group) and what it leads to. Every number, link and arrow comes from the export. Tags do not decide what is mapped; each flow shows its tag, and each card counts the tags of its flows.

| File | What it does | Output |
|---|---|---|
| [`build_org_map.py`](build_org_map.py) | **Runs everything:** pulls the data (or reads a saved run) and builds the page | all files below |
| [`glific_get_flows.py`](glific_get_flows.py) | Every **active** flow, with its full definition (credentials and sticky-note tokens blanked) | `flows.json` |
| [`glific_get_triggers.py`](glific_get_triggers.py) | Every **trigger**, active and inactive | `triggers.json` |
| [`glific_get_settings.py`](glific_get_settings.py) | The **organisation settings** that start flows: default, new contact, opt-in, out-of-office and regex flows | `settings.json` |
| [`graph_layout.py`](graph_layout.py) | Layered left-to-right graph layout (no dependencies) | |
| [`graph_svg.py`](graph_svg.py) | Draws a `GraphView` as SVG, one small function per kind of box | |
| [`cards.py`](cards.py), [`sections.py`](sections.py) | Flow and trigger cards; the tables under a graph | |
| [`programme_claude.py`](programme_claude.py) | One Claude call ([prompt](PROGRAMME_PROMPT.md)), then checks every reference against the facts | `claude_output.json` |
| [`render_org_map.py`](render_org_map.py) | The page: programme cards, a view per programme, and the full graph as one more view | `org_map.html` |
| [`page_check.py`](page_check.py) | Checks the finished page: tags balance, no em dashes | |
| [`assets/`](assets/) | Page markup, styles and scripts, inlined into the page at build time | |

Nothing is tied to a particular org: every active flow in the account is read.

Shared with the other features, in [`glific_common/`](../glific_common/):

- `api.py`, `flows.py`, `output.py`, `redact.py`, `privacy.py`: the Glific client (login, GraphQL paging, `.env`), flow export, run folders, credential redaction and the masking of personal data.
- [`org_facts/`](../glific_common/org_facts/): reading an export, which the MCP server also uses.

| `glific_common/org_facts/` | What it does | Output |
|---|---|---|
| `flow_reading.py` | Reads one flow: reachable nodes and a summary of what it calls, sends, sets, moves and logs | |
| `model.py` | The model of an export: scope, starts, callers, data links and the graph's flows | |
| `graph_view.py` | The boxes and edges for a set of flows (a `GraphView`); never changes the model | |
| `facts.py` | Cleaned facts about every flow, with IDs, for Claude | `claude_input.json` |
| `grouping.py` | Groups flows by their links, in the shape of Claude's answer, for runs without Claude | |
| `schedules.py`, `text.py` | Schedules in plain words; text helpers | |

## Usage

Set the variables in the [main README](../README.md#setup), then from the repo root:

```bash
./org_map.sh                # programmes from Claude
./org_map.sh --no-claude    # groups by links; nothing is sent to Anthropic
```

Each run writes to a new folder named by the local date and time:

```
output/org_programme_architecture/2026-11-13_22-31-13/
├── flows.json
├── triggers.json
├── settings.json
├── claude_input.json       # unless --no-claude: exactly what was sent to Claude
├── claude_output.json      # Claude's answer, when there is one (reuse it with --reuse-claude)
└── org_map.html            # open in a browser
```

### Options

| Option | Default | Meaning |
|---|---|---|
| `--project` | the organisation's name from Glific (`settings.json`), else "Glific chatbot" | Name for the page titles |
| `--tz` | `GLIFIC_TZ`, else `Asia/Kolkata` | Display time zone: `"IST, UTC+5:30"` or an IANA name. UTC is shown in brackets |
| `--date` | today, or the date the `--from-json` folder name starts with | Snapshot date (`YYYY-MM-DD`): decides which triggers have ended |
| `--no-claude` | off | Group flows by their links instead of asking Claude. See [Without Claude](#without-claude) |
| `--reuse-claude DIR` | | Use Claude's saved answer in `DIR/claude_output.json` instead of calling the API |
| `--from-json DIR` | | Rebuild from `flows.json`, `triggers.json` and, if present, `settings.json` saved earlier, with no Glific calls |
| `--footer` | none | One sentence for the footer |
| `--notes FILE` | none | Context notes shown with the full flow graph (format below) |

**Context notes file.** A line starting with `journey` becomes a strip of small boxes. `f:` marks field people (amber), `d:` data systems (grey) and `c:` chatbot messages (green). Every other line becomes a paragraph in a "Content and data" card.

```
journey Intervention areas, fed by CommCare: f:Home visit | f:Collect phone and LMP | d:Enter in CommCare | d:Data flows to Glific | c:Welcome message | c:Stage-based messages
Campaign messages are built by hand in Google Sheets.
```

Keep all the scripts in this folder: they import from each other.

### Tests

From the repo root: `python3 -m unittest discover -s tests -t .` (all features) or `python3 -m unittest discover -s tests/org_programme_architecture -t .` (this one). The tests live in [`tests/org_programme_architecture/`](../tests/org_programme_architecture/), grouped by module (for example `test_privacy.py`, `test_grouping.py`, `test_render_org_map.py`), with shared helpers in `helpers.py`. They use a made-up org in `fixtures/` (rebuilt by `fixtures/make_fixture.py`) and a stand-in for the Anthropic client, so they make no network calls; `GLIFIC_OUTPUT_ROOT` and `GLIFIC_NO_DOTENV` keep them away from your `output/` and `.env`. `test_snapshots.py` checks the pages byte for byte against `snapshots/`; after an intended change to the page, regenerate them with `UPDATE_SNAPSHOTS=1 python3 -m unittest tests.org_programme_architecture.test_snapshots` and review the diff before committing.

### Design history

The design and the build plan are in [`docs/superpowers/`](../docs/superpowers/) (`2026-11-13-org-programme-map*`). They record why it was built this way; this README is the reference for how it works now.

---

## Programmes from Claude

By default, Claude reads every active flow and works out what the bot does, in two levels: a few programmes (for example a maternal and child health pilot), each made of parts (registration, data sync, weekly nudges, question answering). The page opens on one card per programme, plus a card for the full flow graph, with its parts and pills (number of flows, how they start, outside systems, groups, concerns). Selecting one shows a graph of all its flows, each box striped in the colour of its part, beside a side pane with the programme's story end to end and a section per part. Selecting a box shows that flow's purpose, how it starts, where it leads and its full card. Flows from other programmes that connect to this one appear faded; selecting one jumps to its programme.

**What Claude decides, and what it does not.** Claude groups flows into parts and parts into programmes, names them, gives each flow a purpose and role (core, helper, shared, test, leftover) and writes the stories and concerns. Every number, schedule, group, link and arrow comes from the export. Claude may refer to flows, groups, triggers, links and message excerpts only by the IDs in the facts, and must cite them as evidence with a confidence level (clear, likely, a guess). Python checks every reference: anything that does not match is removed, Claude gets one chance to fix its answer, and whatever is still wrong is listed under "Dropped by validation". Selecting a confidence badge shows the evidence. Claude's text is always labelled "Claude's reading".

**What is sent to the API.** For each flow: its name, tag, keywords, how it starts (including Glific settings), what it leads to, what it touches (webhook hosts, sheets, fields, groups, labels, tickets, staff alerts by template) and up to 25 excerpts of its messages, interactive messages, template names and designers' sticky notes, sticky notes first. Excerpts are cut to 200 characters. Masking is done once, in `glific_common/privacy.py`, as the model is built, so it covers the page and the facts alike: phone numbers, emails and things shaped like keys or tokens are masked, links (with or without `http`) are cut to their host, and staff contact names from alerts and tickets become "a staff contact". This applies to flow, group, label and sheet names, router branches, ticket topics and keywords as well as to message excerpts. People named in message text who are not alert or ticket staff are not recognised as names. The exporter also blanks webhook credentials and tokens in sticky notes before anything is saved. The exact request is saved as `claude_input.json` before it is sent.

**Requirements and cost.** The `anthropic` package (in `.venv`, see the [main README](../README.md)), and an Anthropic API key in `ANTHROPIC_API_KEY` (or in `.env`). The step uses `claude-opus-5-5` in one call (two if a repair is needed); for an org with about 45 flows the input is roughly 30,000 tokens, the call takes about five minutes and costs under a dollar. Without the package or a key, or if Claude's answer is unusable, the run prints why and builds the page without Claude.

## Without Claude

With `--no-claude`, or when Claude cannot be used, nothing is sent to Anthropic and `glific_common/org_facts/grouping.py` groups the flows from the export alone. Flows belong together when one starts the other, when one hands data to the other through a contact field, or when one adds contacts to a group that a schedule starting the other sends to. A flow that starts nothing and is started from two or more places (a shared helper) joins the group holding most of its callers, so it does not glue unrelated groups together. A flow linked to nothing joins the one group whose main tag it carries (the tag of at least half its flows); the rest are listed together as "Not connected". A group is named after its main tag, else "Starts at" its entry flow. The page keeps the same layout, with a banner saying why Claude was not used; there are no summaries, stories or roles, since only Claude writes those.

---

## Flow graph

**Input checks.** The two files are hashed, and the run stops if they're identical. It also stops if `flows.json` holds only metadata and no nodes. Flows and triggers are joined on `uuid`, never on name.

**Scope.** The full graph holds every flow that starts or is started by another, hands over data, or has an active trigger, a keyword or a Glific setting, up to 30 flows with entry points first; the rest are listed under it as "Not on the graph". A trigger counts as active only when `isActive` is true and its end date hasn't passed.

**The graph.** Each flow, trigger, keyword and contact group is a small box, and `graph_layout.py` lays them out left to right: a flow sits one layer after the longest chain of starts or data hand-offs that leads to it, and each trigger, keyword or setting box sits just before its flow. Each flow box says in one line what it does (webhook, sends, waits, moves, alerts, sheet, unreachable step). A flow started by a Glific setting gets a grey "Glific setting" box naming it (for example "Default flow"); a flow that nothing in the export starts gets a dashed "No start found" box. A contact group that a schedule sends to gets a green box in the first column, with faint arrows back from the flows that fill or empty it. Solid arrows start a flow, dashed arrows hand over data through a contact field (drawn when one or two flows write that field). Selecting a box opens its full card in a side panel. The same export always gives the same picture.

**Flow cards** use these rows, each kept under 25 words:

| Row | Content |
|---|---|
| Calls | Webhooks by host and purpose |
| Sends | Message counts, interactive message names, templates |
| Routes | What the main routers branch on, and how many points wait for a reply |
| Sets, Counts | Contact fields set, and fields that count up (`+ 1`) |
| Moves | Group changes, with the router branch that decides them |
| Logs | Sheet reads and writes, by sheet and tab |
| Alerts | Templates sent to staff, by name and number of staff contacts |
| Labels, Ticket | Labels added; ticket topic and whether it is assigned (no names) |
| Starts, Feeds, Used by | Flows started (with counts), data handed on, callers (with counts) |
| Trigger | For flows with only inactive triggers |
| Note | Nodes no path reaches, for example a staff template that never sends |

**Below the graph:**
- a note on shared webhook hosts, groups, sheets, extra keywords and widely shared fields
- a table of flows not on the graph, and flows named in triggers or enter_flow actions that aren't in the export

**Built-in checks.** Before saving, the renderer confirms that:
- the HTML tags balance
- there are no em dashes
- every edge lands on a box
- every solid link matches an enter_flow action

The page never shows header values, tokens, full URLs, message bodies, phone numbers or contact names. It still contains flow, group, sheet and template names, so treat it as sensitive.

**Page text rules.** Plain words at the level of an informed senior professional, full sentences, typographic quotes, no em dashes, and none of the words leverage, unlock, seamless, robust or ecosystem. Claude's prompt follows the same rules.

---

## `glific_get_flows.py`

### How it works

1. Logs in at `POST /api/v1/session` and gets an access token (through `glific_common/api.py`).
2. Pages through the `flows` GraphQL query (100 per page) with the filter `isActive: true`.
3. Prints a count of active flows per tag to stderr, so you can see what was pulled.
4. Calls `exportFlow` for each flow to get its full definition (`glific_common/flows.py`, which blanks credentials with `glific_common/redact.py`). The export also contains any sub-flows the flow calls, so the script keeps only the definition whose UUID matches the flow.
5. Builds an edge list from each node's exits.

### Output

A JSON array with one object per flow:

| Field | Description |
|---|---|
| `id`, `uuid`, `name` | Flow identifiers |
| `versionNumber`, `flowType` | Flow metadata |
| `keywords` | Keywords that start the flow |
| `lastPublishedAt`, `lastChangedAt` | Timestamps |
| `isActive` | Always `true` (only active flows are fetched) |
| `tag` | `{ id, label }`, or `null` if the flow is untagged |
| `nodes` | Raw node list from the flow definition (actions, router, exits) |
| `edges` | `[{ from, exit, to }]`, one per node exit. `to` is `null` when the flow ends at that exit |
| `ui` | The editor's `_ui` block (node positions on the canvas) |

### Notes

- **Inactive flows are skipped.** To include them, remove `"isActive": True` from the filter in `get_all_flows`.
- **All active flows are saved and mapped.** Tags are shown on the page but do not decide what is mapped.
- **Credentials are blanked before saving.** Glific flow definitions hold webhook credentials in plain text. Before anything is written, the script replaces these with `[redacted]` and prints how many it blanked for each flow:
  - every webhook header value except `Content-Type` and `Accept` (for example `Authorization: Bearer ...`)
  - `user:password@` credentials and query-string values in webhook URLs
  - literal values (strings or numbers) of webhook body fields whose names contain `key`, `token`, `secret`, `passw`, `auth`, `credential` or `userid` (Glific `@...` expressions are kept)
  - anything shaped like a JWT or `Bearer` token anywhere in the definition

  To clean a `flows.json` exported before this was added, run `python3 org_programme_architecture/glific_get_flows.py --redact path/to/flows.json`. It rewrites the file in place and is safe to run more than once. The redacted export can't be re-imported into Glific as a working flow, because the credentials are gone.
- If a flow fails to export, the script logs the error to stderr and the flow gets empty `nodes` and `edges` lists. The run carries on.
- The script makes one export call per flow, so large instances take a while.

---

## `glific_get_settings.py`

Reads the organisation settings that start flows without a trigger or keyword, through the `organization` GraphQL query: `outOfOffice.defaultFlowId` (default flow, runs on any message that matches no keyword), `newcontactFlowId`, `optinFlowId`, `outOfOffice.flowId` (only when out-of-office is switched on) and `regxFlow.flowId`. Only the organisation's name (used for the page title), flow IDs and switches are read. If the settings cannot be read, it warns and returns `{}`, and those flows show as "No start found".

---

## `glific_get_triggers.py`

### How it works

1. Logs in and pages through the query with `glific_common/api.py`, and saves through `glific_get_flows.save_json`.
2. Pages through the `triggers` GraphQL query with no filter, so it returns both active and inactive triggers.
3. Adds a readable `schedule` string to each trigger.
4. Prints one line per trigger to stderr: status, name, the flow it starts, its schedule and its groups.

### Output

A JSON array with one object per trigger:

| Field | Description |
|---|---|
| `id`, `name`, `isActive` | Trigger identifiers and status |
| `isRepeating`, `frequency` | Whether it repeats, and how often (`daily`, `weekly`, `monthly`, `hourly`, ...) |
| `days` | Weekdays for weekly triggers (1 = Mon … 7 = Sun), or days of the month for monthly triggers |
| `hours` | Hours of the day for hourly triggers |
| `startAt`, `nextTriggerAt`, `endDate` | Schedule bounds, in **UTC** |
| `groupType`, `groups`, `waGroups` | Who receives it: contact groups or WhatsApp groups |
| `flow` | `{ id, uuid, name, isActive, tag }` of the flow it starts |
| `schedule` | Added by the script, e.g. `weekly on Mon, Thu from 2025-06-01T04:30:00Z until 2025-12-31` |

### Notes

- All times are UTC. Convert them for local schedules (IST is UTC+5:30).
- A trigger can point at a flow that `glific_get_flows.py` did not fetch because the flow is inactive. Check `flow.isActive`.

---

## Joining the two outputs

`trigger.flow.uuid` matches `flow.uuid`, so you can see which flows run on a schedule:

```python
import json
day = "output/org_programme_architecture/2026-11-11_21-43-05"   # the run you want
flows = {f["uuid"]: f for f in json.load(open(f"{day}/flows.json"))}
for t in json.load(open(f"{day}/triggers.json")):
    tf = t.get("flow") or {}
    if t["isActive"]:
        f = flows.get(tf.get("uuid"))
        print(t["name"], "->", tf.get("name"), "|", t["schedule"], "| nodes:", len(f["nodes"]) if f else "n/a")
```
