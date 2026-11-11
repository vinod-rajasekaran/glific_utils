# Get System Flow Architecture

Extracts every flow and trigger from a Glific instance, so you can map how the chatbot system fits together: which flows exist, how their nodes connect, and which flows are started on a schedule.

| Script | What it does | Output |
|---|---|---|
| [`build_flow_architecture.py`](build_flow_architecture.py) | **Runs everything:** pulls flows and triggers, then builds the HTML map | all three files below |
| [`glific_get_flows.py`](glific_get_flows.py) | Every **active** flow, with its full definition (nodes and edges) | `flows.json` |
| [`glific_get_triggers.py`](glific_get_triggers.py) | Every **trigger** (scheduled flow starts), active and inactive | `triggers.json` |
| [`render_architecture.py`](render_architecture.py) | Turns the two JSON files into `flow_architecture.html` (no API calls), following [`PROMPT.md`](PROMPT.md) | `flow_architecture.html` |

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

These are the settings from the [flow map spec](PROMPT.md):

| Option | Default | Meaning |
|---|---|---|
| `--project` | `GLIFIC_PROJECT`, else "Glific chatbot" | Project name for the title |
| `--tag` | `GLIFIC_TAG`, else none | Flow tag to start from. Without it, the map starts from active triggers and keywords |
| `--tz` | `GLIFIC_TZ`, else `Asia/Kolkata` | Display time zone: `"IST, UTC+5:30"` or an IANA name. UTC is always shown in brackets |
| `--date` | today, or the date the `--from-json` folder name starts with | Snapshot date (`YYYY-MM-DD`): decides which triggers have ended |
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

## `flow_architecture.html`

The page follows the [flow map spec](PROMPT.md), the prompt behind the hand-built reference page. All of it is generated from the two JSON files.

**Input checks.** The two files are hashed, and the run stops if they're identical. It also stops if `flows.json` holds only metadata and no nodes, because links can't be derived without them. Flows and triggers are joined on `uuid`, never on name.

**Scope.** The map starts from flows carrying `--tag`. It adds every flow they start through "enter flow", marked "not tagged" when the tag is missing, and every flow an active trigger starts. A trigger counts as active only when `isActive` is true and its end date hasn't passed.

**The map** has four columns joined by wires, with each trigger card in the same row as its flow:

| Column | Holds |
|---|---|
| When it starts | Active schedules, in local time with UTC in brackets, plus group, window and an "Earlier runs" summary. A keyword card lists every keyword spelling |
| Entry flows | Flows with a trigger or keyword that no other flow in scope enters |
| Journey | Flows that one other flow enters |
| Shared flows | Flows entered by two or more flows |

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
