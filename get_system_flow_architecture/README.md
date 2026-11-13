# Get System Flow Architecture

Extracts every flow and trigger from a Glific instance, so you can map how the chatbot system fits together: which flows exist, how their nodes connect, and which flows are started on a schedule.

| Script | What it does | Output |
|---|---|---|
| [`build_flow_architecture.py`](build_flow_architecture.py) | **Runs everything:** pulls flows and triggers, then builds the HTML map | all three files below |
| [`glific_get_flows.py`](glific_get_flows.py) | Every **active** flow, with its full definition (nodes and edges) | `flows.json` |
| [`glific_get_settings.py`](glific_get_settings.py) | The **organisation settings** that start flows: default, new contact, opt-in, out-of-office and regex flows | `settings.json` |
| [`glific_get_triggers.py`](glific_get_triggers.py) | Every **trigger** (scheduled flow starts), active and inactive | `triggers.json` |
| [`graph_layout.py`](graph_layout.py) | Layered left-to-right layout for `--layout graph` (no dependencies) | |
| [`render_architecture.py`](render_architecture.py) | Turns the two JSON files into `flow_architecture.html` (no API calls) | `flow_architecture.html` |
| [`usecase_facts.py`](usecase_facts.py) | With `--usecases`: cleaned facts about every flow, with IDs, for Claude | `claude_input.json` |
| [`usecase_claude.py`](usecase_claude.py) | With `--usecases`: one Claude call ([prompt](USECASE_PROMPT.md)), then checks every reference against the facts | `claude_output.json`, `usecases.json` |
| [`render_usecases.py`](render_usecases.py) | With `--usecases`: the page organised by use case | `flow_usecases.html` |

[`PROMPT_SPEC.md`](PROMPT_SPEC.md) is the written spec for the page. It began as a prompt you could paste into an LLM, but **`render_architecture.py` implements it directly in Python** — no model or Claude key is involved when you run the scripts. The spec file is kept as documentation and as an alternative way to build the page by hand. The two stay in sync by convention, not automatically.

This feature is not tied to any particular instance. Nothing in the code is hardcoded to a specific flow, tag, group, or template; the tag to focus on is the `--tag` input. It works on any Glific instance's export, as long as the JSON has the shape the Glific API returns (the node and action types documented below).

## Usage

Set the environment variables listed in the [main README](../README.md#setup), then run from the repo root:

```bash
python3 get_system_flow_architecture/build_flow_architecture.py --project "Phonewali Didi" --tag "2025 Pilot"
```

This logs in once and writes all three files to a new folder for this run, named by the local date and time:

```
output/get_system_flow_architecture/2026-11-11_21-43-05/
├── flows.json
├── triggers.json
└── flow_architecture.html     # open in a browser
```

Every run gets its own folder, so nothing is overwritten. Re-rendering with `--from-json` also creates a new run folder: it copies the two JSON files there and leaves the source folder untouched. The terminal shows the intermediate tables (flows in scope with their column, active triggers, data links) and a list of findings.

### Options

These are the settings from the [flow map spec](PROMPT_SPEC.md):

| Option | Default | Meaning |
|---|---|---|
| `--project` | `GLIFIC_PROJECT`, else "Glific chatbot" | Project name for the title |
| `--tag` | `GLIFIC_TAG`, else none | Flow tag to start from. Without it, the map starts from active triggers and keywords |
| `--tz` | `GLIFIC_TZ`, else `Asia/Kolkata` | Display time zone: `"IST, UTC+5:30"` or an IANA name. UTC is always shown in brackets |
| `--date` | today, or the date the `--from-json` folder name starts with | Snapshot date (`YYYY-MM-DD`): decides which triggers have ended |
| `--usecases` | `GLIFIC_USECASES=1`, else off | Also ask Claude to group every active flow into use cases and write `flow_usecases.html`. See [Use-case page](#use-case-page-flow_usecaseshtml) |
| `--reuse-claude DIR` | | Use Claude's saved answer in `DIR/claude_output.json` instead of calling the API (implies `--usecases`) |
| `--layout` | `GLIFIC_LAYOUT`, else `graph` | `columns` groups cards by role, `lanes` gives each journey its own lane with columns by step, `graph` draws small boxes laid out left to right with details on click, `all` writes every layout (as `flow_architecture.html`, `_lanes.html` and `_graph.html`) |
| `--footer` | none | One sentence for the footer |
| `--notes FILE` | none | Context notes (format below) |
| `--from-json DIR` | | Rebuild only the HTML from JSON saved earlier, with no login or API calls |

```bash
# Rebuild the HTML from an earlier run
python3 get_system_flow_architecture/build_flow_architecture.py --from-json output/get_system_flow_architecture/2026-11-11_21-43-05 --tag "2025 Pilot"

# Pull just one of the JSON files (written to the same dated folder)
python3 get_system_flow_architecture/glific_get_flows.py
python3 get_system_flow_architecture/glific_get_triggers.py
```

**Context notes file.** A line starting with `journey` becomes a strip of small boxes. `f:` marks field people (amber), `d:` data systems (grey) and `c:` chatbot messages (green). Every other line becomes a paragraph in a "Content and data" card.

```
journey Intervention areas, fed by CommCare: f:Home visit | f:Collect phone and LMP | d:Enter in CommCare | d:Data flows to Glific | c:Welcome message | c:Stage-based messages
Campaign messages are built by hand in Google Sheets.
Glific stores every message in BigQuery.
```

Keep all the scripts in this folder: they import from each other.

---

## Use-case page (`flow_usecases.html`)

With `--usecases`, the run also asks Claude to read every active flow and work out what the org's bot does, in two levels: a few programmes (for example a maternal and child health pilot), each made of parts (registration, data sync, weekly nudges, question answering). The page opens on one card per programme, with its parts and pills (number of flows, how they start, outside systems, groups, concerns). Selecting one shows a graph of all its flows, each box striped in the colour of its part, beside a side pane with the programme's story end to end and a section per part. Selecting a box shows that flow's purpose, how it starts, where it leads, and its full card. Flows from other use cases that connect to this one appear faded; selecting one jumps to its use case.

**What Claude decides, and what it does not.** Claude groups the flows, names the use cases, gives each flow a purpose and role (core, helper, shared, test, leftover) and writes the story and the concerns. Every number, schedule, group, link and arrow on the page comes from the export, not from Claude. Claude may refer to flows, groups, triggers, links and message excerpts only by the IDs in the facts, and must cite them as evidence with a confidence level (clear, likely, a guess). Python checks every reference: anything that does not match is removed, Claude gets one chance to fix its answer, and whatever is still wrong is listed under "Dropped by validation". Selecting a confidence badge shows the evidence behind a statement.

**What is sent to the API.** `usecase_facts.py` builds the facts: for each flow its name, tag, keywords, how it starts, what it leads to, what it touches (webhook hosts, sheets, fields, groups, labels, tickets, staff alerts by template) and excerpts of its messages, interactive messages, template names and designers' sticky notes. Excerpts are cut to 200 characters. Staff contact names become "a staff contact", phone numbers and emails are masked, and links are cut to their host. Webhook credentials were already blanked by the exporter. The exact request is saved as `claude_input.json` in the run folder before it is sent.

**Requirements and cost.** The `anthropic` package (in `.venv`, see the [main README](../README.md)), and an Anthropic API key in `ANTHROPIC_API_KEY` (or in `.env`). The step uses `claude-opus-5-5` in one call (two if a repair is needed); for an org with about 45 flows the input is roughly 30,000 tokens and the call takes about five minutes. Each flow sends at most 25 excerpts, sticky notes first. Without the package or a key, or if Claude's answer is unusable, the run prints why and still writes the graph page.

```bash
./flow_map.sh --from-json output/get_system_flow_architecture/2026-11-13_20-49-46 --usecases
./flow_map.sh --from-json output/get_system_flow_architecture/2026-11-13_20-49-46 --reuse-claude output/get_system_flow_architecture/2026-11-13_22-30-00
```

The run folder then also holds `claude_input.json` (what was sent), `claude_output.json` (Claude's raw answer), `usecases.json` (the validated answer and what was dropped) and `flow_usecases.html`.

## `flow_architecture.html`

The page follows the [flow map spec](PROMPT_SPEC.md) and is generated entirely from the two JSON files by `render_architecture.py` in Python. The spec reads like a prompt, but at runtime no LLM is called.

**Input checks.** The two files are hashed, and the run stops if they're identical. It also stops if `flows.json` holds only metadata and no nodes, because links can't be derived without them. Flows and triggers are joined on `uuid`, never on name.

**Scope.** The map starts from flows carrying `--tag`. It adds every flow they start through "enter flow", marked "not tagged" when the tag is missing, and every flow an active trigger starts. It then takes one step back: a flow anywhere in the account that starts a flow in scope is added, because it is connected even when its tag was missed. Its other starts are not followed, since callers of a shared flow can belong to other programmes. The Tagging gaps section names these flows. A trigger counts as active only when `isActive` is true and its end date hasn't passed.

**The map** has four columns joined by wires, with each trigger card in the same row as its flow:

| Column | Holds |
|---|---|
| When it starts | Active schedules, in local time with UTC in brackets, plus group, window and an "Earlier runs" summary. A keyword card lists every keyword spelling |
| Entry flows | Flows with a trigger or keyword that no other flow in scope enters |
| Journey | Flows that one other flow enters |
| Shared flows | Flows entered by two or more flows |

With `--layout lanes` the cards are regrouped so a path reads left to right. Each lane holds one journey: the entry flows that reach the same flows, through starts or data links, and everything they reach. The columns become steps, so a flow sits one column after the longest chain of starts that leads to it. A flow that starts nothing and is entered from more than one journey goes to a Shared flows lane at the bottom, and flows with no links share a last lane. On narrow screens the cards stack lane by lane.

With `--layout graph` the map is a graph instead of a grid of cards. Each flow and trigger is a small box, and `graph_layout.py` lays them out left to right in layers: a flow sits one layer after the longest chain of starts or data hand-offs that leads to it, and each trigger sits just before its flow. Long edges run through the gaps between boxes. Each flow box lists in one line what the flow does (webhook, sends, waits, moves, alerts, sheet, unreachable step). A flow that no trigger, keyword or flow in the export starts gets a grey "No start found" box in front of it; it may be the opt-in or opt-out flow in Glific settings, or started by hand or through the API. Boxes for flows without the tag show the tag they do have. A contact group that an active schedule on the graph sends to gets a green box in the first column, when some flow adds contacts to it or removes them. Dotted arrows run from the group to its schedules, and faint dotted arrows run back from each flow that fills or empties the group; they light up when you point at either end. A flow outside the scope that adds contacts to such a group joins the graph, because it decides who the schedule reaches. Selecting a box opens its full card in a side panel. Edge labels give the number of places one flow starts another and the fields a data link hands over. On narrow screens the graph scrolls sideways.

Solid wires are enter_flow actions. Dashed wires mean one flow sets a contact field that another reads in a router; they're drawn only when one or two flows write that field. The map holds at most 14 flow cards and the rest move to the strip below. Wires show at 1100px and wider. Below that the cards stack in two columns, or one, and each card's Starts row keeps the links readable.

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

**Below the map:**
- a note on shared webhook hosts, groups, sheets, extra keywords and widely shared fields
- a strip of tagged flows with no link, overflow flows, untagged flows that change groups the map uses, and flows named in triggers or enter_flow actions that aren't in the export
- a "Tagging gaps" paragraph, where name-prefix guesses are labelled as guesses

**Built-in checks.** Before saving, the renderer confirms that:
- the HTML tags balance
- there are no em dashes
- every wire lands on a card
- every solid link matches an enter_flow action

The page never shows header values, tokens, full URLs, message bodies, phone numbers or contact names. It still contains flow, group, sheet and template names, so treat it as sensitive.

Future-architecture or design tabs aren't generated, because they can't be derived from Glific data.

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

  To clean a `flows.json` exported before this was added, run `python3 get_system_flow_architecture/glific_get_flows.py --redact path/to/flows.json`. It rewrites the file in place and is safe to run more than once. The redacted export can't be re-imported into Glific as a working flow, because the credentials are gone.
- If a flow fails to export, the script logs the error to stderr and the flow gets empty `nodes` and `edges` lists. The run carries on.
- The script makes one export call per flow, so large instances take a while.

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
day = "output/get_system_flow_architecture/2026-11-11_21-43-05"   # the run you want
flows = {f["uuid"]: f for f in json.load(open(f"{day}/flows.json"))}
for t in json.load(open(f"{day}/triggers.json")):
    tf = t.get("flow") or {}
    if t["isActive"]:
        f = flows.get(tf.get("uuid"))
        print(t["name"], "->", tf.get("name"), "|", t["schedule"], "| nodes:", len(f["nodes"]) if f else "n/a")
```
