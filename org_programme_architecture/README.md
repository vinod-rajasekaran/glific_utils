# Org Programme Architecture

Pulls every active flow, every trigger and the organisation's flow settings from a Glific instance, and builds two pages:

- **`graph.html`**, the flow map: how every flow starts (schedule, keyword, another flow, a Glific setting or a contact group) and what it leads to, as a graph. Built entirely in Python; no API key needed.
- **`programmes.html`**, with `--programmes`: Claude reads the flows and explains what the bot does, as a few programmes made of parts, with a graph and a story for each. Every number, link and arrow still comes from the export.

| File | What it does | Output |
|---|---|---|
| [`build_org_map.py`](build_org_map.py) | **Runs everything:** pulls the data, builds the graph page and, with `--programmes`, the programme page | all files below |
| [`glific_get_flows.py`](glific_get_flows.py) | Every **active** flow, with its full definition (credentials blanked) | `flows.json` |
| [`glific_get_triggers.py`](glific_get_triggers.py) | Every **trigger**, active and inactive | `triggers.json` |
| [`glific_get_settings.py`](glific_get_settings.py) | The **organisation settings** that start flows: default, new contact, opt-in, out-of-office and regex flows | `settings.json` |
| [`render_graph.py`](render_graph.py) | The model of flows, triggers, groups and links, and the graph page | `graph.html` |
| [`graph_layout.py`](graph_layout.py) | Layered left-to-right graph layout (no dependencies) | |
| [`programme_facts.py`](programme_facts.py) | Cleaned facts about every flow, with IDs, for Claude | `claude_input.json` |
| [`programme_claude.py`](programme_claude.py) | One Claude call ([prompt](PROGRAMME_PROMPT.md)), then checks every reference against the facts | `claude_output.json`, `programmes.json` |
| [`render_programmes.py`](render_programmes.py) | The programme page | `programmes.html` |

Nothing is tied to a particular org: the tag to focus the graph on is the `--tag` input, and the programme page reads every active flow.

## Usage

Set the variables in the [main README](../README.md#setup), then from the repo root:

```bash
./org_map.sh --project "My Bot" --tag "2025 Pilot"                 # graph page
./org_map.sh --project "My Bot" --tag "2025 Pilot" --programmes    # graph page and programme page
```

Each run writes to a new folder named by the local date and time:

```
output/org_programme_architecture/2026-11-13_22-31-13/
├── flows.json
├── triggers.json
├── settings.json
├── graph.html
├── claude_input.json       # with --programmes: exactly what was sent to Claude
├── claude_output.json      # Claude's raw answer
├── programmes.json         # the validated answer, and what validation dropped
└── programmes.html
```

### Options

| Option | Default | Meaning |
|---|---|---|
| `--project` | `GLIFIC_PROJECT`, else "Glific chatbot" | Project name for the titles |
| `--tag` | `GLIFIC_TAG`, else none | Flow tag the graph starts from. Without it, the graph starts from active triggers and keywords |
| `--tz` | `GLIFIC_TZ`, else `Asia/Kolkata` | Display time zone: `"IST, UTC+5:30"` or an IANA name. UTC is shown in brackets |
| `--date` | today, or the date the `--from-json` folder name starts with | Snapshot date (`YYYY-MM-DD`): decides which triggers have ended |
| `--programmes` | `GLIFIC_PROGRAMMES=1`, else off | Also ask Claude for the programme page. See [Programme page](#programme-page-programmeshtml) |
| `--reuse-claude DIR` | | Use Claude's saved answer in `DIR/claude_output.json` instead of calling the API (implies `--programmes`) |
| `--from-json DIR` | | Rebuild from `flows.json`, `triggers.json` and, if present, `settings.json` saved earlier, with no Glific calls |
| `--footer` | none | One sentence for the footer |
| `--notes FILE` | none | Context notes for the graph page (format below) |

**Context notes file.** A line starting with `journey` becomes a strip of small boxes. `f:` marks field people (amber), `d:` data systems (grey) and `c:` chatbot messages (green). Every other line becomes a paragraph in a "Content and data" card.

```
journey Intervention areas, fed by CommCare: f:Home visit | f:Collect phone and LMP | d:Enter in CommCare | d:Data flows to Glific | c:Welcome message | c:Stage-based messages
Campaign messages are built by hand in Google Sheets.
```

Keep all the scripts in this folder: they import from each other. Tests: `python3 -m unittest discover -s tests` from the repo root (they use a made-up org in `tests/fixtures`; `GLIFIC_OUTPUT_ROOT` and `GLIFIC_NO_DOTENV` keep them away from your `output/` and `.env`).

---

## Programme page (`programmes.html`)

With `--programmes`, Claude reads every active flow and works out what the bot does, in two levels: a few programmes (for example a maternal and child health pilot), each made of parts (registration, data sync, weekly nudges, question answering). The page opens on one card per programme, with its parts and pills (number of flows, how they start, outside systems, groups, concerns). Selecting one shows a graph of all its flows, each box striped in the colour of its part, beside a side pane with the programme's story end to end and a section per part. Selecting a box shows that flow's purpose, how it starts, where it leads and its full card. Flows from other programmes that connect to this one appear faded; selecting one jumps to its programme.

**What Claude decides, and what it does not.** Claude groups flows into parts and parts into programmes, names them, gives each flow a purpose and role (core, helper, shared, test, leftover) and writes the stories and concerns. Every number, schedule, group, link and arrow comes from the export. Claude may refer to flows, groups, triggers, links and message excerpts only by the IDs in the facts, and must cite them as evidence with a confidence level (clear, likely, a guess). Python checks every reference: anything that does not match is removed, Claude gets one chance to fix its answer, and whatever is still wrong is listed under "Dropped by validation". Selecting a confidence badge shows the evidence. Claude's text is always labelled "Claude's reading".

**What is sent to the API.** For each flow: its name, tag, keywords, how it starts (including Glific settings), what it leads to, what it touches (webhook hosts, sheets, fields, groups, labels, tickets, staff alerts by template) and up to 25 excerpts of its messages, interactive messages, template names and designers' sticky notes, sticky notes first. Excerpts are cut to 200 characters. Staff contact names become "a staff contact", phone numbers and emails are masked, and links are cut to their host. Webhook credentials were already blanked by the exporter. The exact request is saved as `claude_input.json` before it is sent.

**Requirements and cost.** The `anthropic` package (in `.venv`, see the [main README](../README.md)), and an Anthropic API key in `ANTHROPIC_API_KEY` (or in `.env`). The step uses `claude-opus-5-5` in one call (two if a repair is needed); for an org with about 45 flows the input is roughly 30,000 tokens, the call takes about five minutes and costs under a dollar. Without the package or a key, or if Claude's answer is unusable, the run prints why and still writes the graph page.

---

## Graph page (`graph.html`)

**Input checks.** The two files are hashed, and the run stops if they're identical. It also stops if `flows.json` holds only metadata and no nodes. Flows and triggers are joined on `uuid`, never on name.

**Scope.** The graph starts from flows carrying `--tag`, adds every flow they start, every flow an active trigger starts, and takes one step back: a flow anywhere in the account that starts a flow in scope is added (its other starts are not followed). A trigger counts as active only when `isActive` is true and its end date hasn't passed.

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
- a strip of tagged flows with no link, overflow flows, untagged flows that change groups the map uses, and flows named in triggers or enter_flow actions that aren't in the export
- a "Tagging gaps" paragraph, where name-prefix guesses are labelled as guesses

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

1. Logs in at `POST /api/v1/session` and gets an access token.
2. Pages through the `flows` GraphQL query (100 per page) with the filter `isActive: true`.
3. Prints a count of active flows per tag to stderr, so you can see what was pulled.
4. Calls `exportFlow` for each flow to get its full definition. The export also contains any sub-flows the flow calls, so the script keeps only the definition whose UUID matches the flow.
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
- **All active flows are saved.** The flow map narrows them down with `--tag` when it renders the page.
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

Reads the organisation settings that start flows without a trigger or keyword, through the `organization` GraphQL query: `outOfOffice.defaultFlowId` (default flow, runs on any message that matches no keyword), `newcontactFlowId`, `optinFlowId`, `outOfOffice.flowId` (only when out-of-office is switched on) and `regxFlow.flowId`. Only flow IDs and switches are read. If the settings cannot be read, it warns and returns `{}`, and those flows show as "No start found".

---

## `glific_get_triggers.py`

### How it works

1. Reuses `login()`, `post()`, `save_json()` and `PAGE_SIZE` from `glific_get_flows.py`.
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
