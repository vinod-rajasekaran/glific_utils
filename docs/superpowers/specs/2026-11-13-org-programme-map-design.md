# Org programme map: design (began as the use-case flow map)

> **Updated 2026-11-14.** This is the record of how the feature was designed and planned; the [feature README](../../../org_programme_architecture/README.md) describes how it works now. What changed after it was written, in short: use cases are grouped into **programmes**, each made of parts; the export also reads Glific's organisation **settings** (`settings.json`), including the organisation's name for the page title; Claude is used by default when the `anthropic` package and an API key are present, and `--no-claude` (or no key) groups flows by their links in `grouping.py` on the same page; **tags no longer decide scope** (`--tag`, `GLIFIC_TAG`, `--programmes`, `GLIFIC_PROGRAMMES` and `GLIFIC_PROJECT` were removed); each run writes **one page**, `org_map.html`, with the full flow graph as one of its views; the column and lane layouts and `render_graph.py` were removed; masking moved to `privacy.py` and is applied once as the model is built; tests live in `tests/org_programme_architecture/`.

Date: 2026-11-13. Status: approved 2026-11-13; built on the usecase-flow-map branch.

## Intent

Glific orgs accumulate dozens of flows. Someone reviewing an implementation, or taking an org over, cannot tell from Glific itself:

1. what each flow is for, in plain words;
2. which flows matter (live journeys) and which are tests, prototypes or leftovers;
3. how each flow starts (another flow, a keyword message, a scheduled Glific trigger, a group a contact was put in, or nothing visible) and where it leads;
4. what it touches outside the bot: webhooks, Google Sheets, contact fields, and the groups (collections) it adds contacts to or removes them from.

Today `org_map.sh` builds a graph page from the flows and triggers exports. It answers (3) and (4) mechanically but cannot answer (1) and (2), and it starts from a tag, so it misses whole use cases. This work adds Claude to read the flows, work out the org's use cases and each flow's purpose, and produce a page organised by use case.

Readers: a reviewer checking an org's implementation, and a person taking over an org with nobody to ask. Success: a newcomer can explain each use case after ten minutes on the page, and a reviewer can spot problems (unreachable steps, test flows reading live fields, untagged flows that matter, flows with no visible start) without opening Glific.

## Goals

- One HTML page per run that opens on a list of the org's use cases and drills into each one.
- Claude does the interpretation: grouping flows into use cases, naming them, each flow's purpose and role, the story of each use case, what each hand-over means, and what to watch.
- Python does the facts: parsing, links, schedules, counts, groups, layout, rendering and validation.
- Runs inside `org_map.sh` with an `ANTHROPIC_API_KEY`.

## Non-goals

- Changing anything in Glific. The tool stays read-only.
- Reading conversations or contact data. Only flow and trigger definitions are used.
- A hosted service or shared database. Output is a local HTML file, as today.

## Anti-goals (failure even if it works)

- **Hallucination.** Any flow, link, group, schedule, number or purpose on the page that the export does not support. This is the user's stated top concern and drives the guardrails below.
- Interpretation that looks like fact. A reader must always be able to tell Python's facts from Claude's reading.
- Leaking secrets or personal data to the API or onto the page.

## Constraints

- Python 3 standard library only, as the repo is today (it calls Glific with `urllib`). Calling the Anthropic API with `urllib` keeps that; adding the `anthropic` SDK is the builder's call if it buys structured-output support that is hard to get otherwise.
- Without an API key, or if the Claude step fails, `org_map.sh` must still produce today's graph page (`--layout graph`), with a note that the use-case view was skipped and why.
- Page rules from the page rules in the feature README still apply (fonts, light and dark themes, plain words, no em dashes, privacy rules, the checks before finishing).
- Same input must give a comparable page: fixed model, fixed parameters, and a saved Claude response that can be re-rendered without calling the API again.

## Decided with the user

- Claude is part of `org_map.sh`, called with an API key.
- Claude returns structured data, not HTML. Python validates it and renders the page. (Proposed by me, accepted by the user.)
- Short message excerpts are sent to the API, with personal data stripped.
- First screen: a list of use cases, each with a short summary and pills (number of flows and other tags).
- Selecting a use case opens a page with the graph and a **side pane** (layout B in the mockups): the graph stays in view on the left; the right pane shows the use case's story and explanation until a box is selected, then that flow's full details and ins and outs.
- Flow detail stays as rich as today's cards ("all the intricacies of each flow").
- Message excerpts may appear on the page as evidence: they are text the bot sends programmatically, not personal data. This relaxes the the page rules in the feature README rule "never full bodies" for evidence only; the cleaning rules under Privacy still apply. Sends rows on flow cards keep describing purpose and template names.
- Active flows only for now (as `glific_get_flows.py` fetches today). "Leftover" means an active flow that nothing reaches or that Claude reads as unused. Inactive flows are a possible later option.

## How it works

```
flows.json + triggers.json
   │  Python: parse (render_graph.Model and summarise, as today)
   ▼
facts.json            every flow, trigger, group, link, with stable IDs
   │  Python: build the Claude payload (excerpts, stickies, PII stripped)
   ▼
claude_input.json  ──►  Claude (one call, JSON output)  ──►  claude_output.json
   │  Python: validate every ID and evidence reference; one repair call if invalid
   ▼
use-case page (HTML)   Python renders, using the existing graph layout per use case
```

All four JSON files are written to the run folder next to the HTML, so a reviewer can see exactly what Claude was given and what it said. `--from-json` re-renders from a saved run; a new `--reuse-claude` (name is the builder's call) re-renders from a saved `claude_output.json` without calling the API.

### Scope of the facts

The whole account, not just a tag: every active flow in `flows.json` and every trigger. Use cases are org-wide, and leftovers must be visible to be called leftovers. The tag, when given, becomes a pill and a filter, not the scope. The existing tag-based graph page stays available through `--layout graph`.

### Facts sent to Claude (`claude_input.json`)

Per flow, under a stable ID (the flow uuid):

- name, tag, keywords, active, version, last published date;
- how it starts, from Python: active and earlier triggers (schedule in plain words, target groups), keywords, flows that enter it, and "no start found";
- what it leads to: flows it enters (with counts), fields it sets that other flows read (data links);
- what it touches: webhook host and path (no query, no credentials), Glific function names, sheets and tabs, groups added to and removed from (with the deciding condition), labels, ticket topics, staff alerts by template and count of staff;
- routers: what they branch on and the category names;
- unreachable nodes and what they would have done;
- **excerpts**, each with its own evidence ID: message text (`send_msg`), interactive message text and options, template names and parameters, and sticky notes from `ui.stickies`. Each excerpt is cut to about 200 characters.

Org-level: groups with who adds and removes and which triggers target them; shared fields; webhook hosts; findings Python already computes.

Evidence IDs are short and stable, for example `msg:<flow uuid>:<n>`, `sticky:<flow uuid>:<n>`, `field:<key>`, `group:<name>`, `trigger:<id>`, `edge:<from>:<to>:<kind>`.

### Privacy (applied before anything is sent or rendered)

Checked against this org's export: credentials in webhook headers are already blanked by `glific_get_flows.py`; staff contacts in staff alerts (11) and ticket assignees (2) appear by name; sticky notes contain an email and a phone-like number; templating parameters and sheet ranges contain long digit strings; there are 32 Google Sheet URLs. No contact messages or contact phone numbers are in the exports.

Rules: replace staff names with "a staff contact"; mask anything that looks like a phone number or email in any text; reduce every URL to its host (and path for webhooks); never send header values, request bodies' literal values, sheet IDs or tokens. `@contact.*` and `@results.*` expressions are placeholders and may be sent. The same stripping applies to what the page shows.

### What Claude returns (`claude_output.json`)

A JSON object, enforced by schema (structured output or a tool call, builder's choice):

- `org_summary`: a paragraph, with evidence IDs.
- `use_cases[]`: `id`, `name`, `summary` (two lines), `flows` (flow IDs whose primary home is this use case), `story[]` (steps from the contact's side), `how_it_works[]` (why each hand-over happens, what data comes in and goes out), `watch[]` (concerns), and a `confidence` per use case.
- `flows{}`: for every flow ID, `purpose` (one sentence), `role` (core, helper, shared, test, leftover, unknown), `use_case` (primary, or none), `confidence`.
- `edges{}`: optional one-line meaning for an existing edge ID, for example "asks for consent, then hands to registration".
- `systems{}`: optional plain name for a webhook host (for example "CommCare via Hasura"), with confidence.

Every sentence-level item carries `refs` (the flow, group, trigger or edge IDs it talks about) and `evidence` (excerpt or fact IDs it rests on), plus `confidence`: `clear` (stated in the messages or notes), `likely`, or `guess`. "Cannot tell from the export" is an allowed answer, and the prompt says so.

A flow has one primary use case or none. Flows used by several use cases (such as a shared LLM flow) get `role: shared`, a primary home, and appear in the others as faded neighbours. Tests and leftovers go in one muted use case, "Tests and leftovers" (my call). `none` is only for flows Claude cannot place; they are listed under "Not placed" below the cards, with no graph.

### Guardrails against hallucination

1. **Facts never come from Claude.** Numbers, schedules, times, group names, links and every arrow on the page come from Python. Claude cannot add a flow, link or group.
2. **IDs, not names.** Claude refers to things only by the IDs in the facts. Python rejects any unknown ID or evidence reference, any flow assigned to two primary use cases, and any flow left out of `flows{}`.
3. **One repair call.** If validation fails, Python sends the errors back once and asks for a corrected response. If it fails again, invalid items are dropped and the page says what was dropped; a flow Claude never placed goes to "Not placed". Problems with single items degrade the page; only an unusable response (not JSON, wrong shape, or no use cases) counts as a failed Claude step and falls back to the graph page (my call).
4. **Evidence on the page.** Selecting a Claude statement shows its evidence (the excerpt, note, field or group). A statement with no evidence is shown as a guess, or dropped if the confidence is not `guess`.
5. **Visibly separate.** Claude's text sits under a "Claude's reading" label with its confidence; facts are styled as today.
6. **Saved and repeatable.** Input and output are saved; the model and parameters are fixed and printed in the page footer.

### Model and call

My call: the latest Claude model (Opus 5.5, `claude-opus-5-5`) in one call per run, with fixed parameters. The builder should read the `claude-api` skill before writing the call (structured output, token limits, prompt caching of the instructions). For this org the facts are roughly 44 flows and 153 messages, well within one call. For large orgs the builder should set a budget and trim excerpts per flow (keep stickies, then the first messages) before splitting the call; splitting is out of scope unless the budget is hit in practice.

The prompt lives in the repo as a file (for example `org_programme_architecture/PROGRAMME_PROMPT.md`) so it can be reviewed and versioned, and states: the readers, the task, the output schema, the evidence and confidence rules, "say you cannot tell", and the privacy rules.

## The page

### First screen

- Title and a one-paragraph org summary (Claude's reading, with evidence).
- A card per use case: name, two-line summary, and pills. Pills computed by Python from the member flows: number of flows, how it starts (schedule, keyword, another flow, no start found), outside systems (webhook hosts with Claude's plain names, Sheets, Glific LLM functions, staff alerts), groups, tag coverage (for example "2 of 7 untagged"), and number of issues. Tests and leftovers get a muted card.
- Below the cards: resources shared across use cases (groups, sheets, webhook hosts, shared fields) and flows that belong to no use case.

### Use-case page (side-pane layout)

- Left: the graph of this use case, drawn with the existing `graph_layout.py` and graph styling (triggers, keyword and no-start boxes, group boxes, data links, back arcs). Direct neighbours from other use cases appear faded at the edges; selecting one jumps to its use case. Edge labels may use Claude's edge meanings.
- Right pane, nothing selected: the story (steps from the contact's side), how it works, and what to watch, each with confidence and evidence on selection.
- Right pane, a box selected: Claude's purpose and role for that flow, then the full flow card as today (Calls, Sends, Routes, Sets, Counts, Moves, Logs, Alerts, Labels, Ticket, Starts, Feeds, Used by, Note), then its ins and outs: what starts it, what it starts, data in and out, groups in and out.
- Below the graph: all flow cards of the use case in story order, for search and printing.
- Navigation between the first screen and use cases without reloading (one self-contained HTML file); the URL hash keeps the selected use case so links can be shared.

Narrow screens follow today's rules: the graph scrolls sideways inside its box and the side pane stacks below it.

## Current state to build on

Uncommitted work in this repo already provides the graph mode: `graph_layout.py` (layered layout with waypoints, fixed layers and soft edges), and in `render_graph.py` the `graph` layout with trigger, keyword, no-start and group boxes, one-step-back scope, the slide-in panel and tag lines. `--layout columns|lanes|graph|all` exists. Commit that work first.

## Running it (my calls)

- The Claude step runs only when asked, with a flag (for example `--programmes`) or `GLIFIC_PROGRAMMES=1` in `.env`, and needs `ANTHROPIC_API_KEY`. A key sitting in `.env` alone never sends org data.
- The default layout becomes `graph`. With the Claude step on, a run writes the use-case page and the graph page, and opens the use-case page.
- `--tag` is optional: with the Claude step it only adds a tag pill and filter; for the graph page it keeps its current meaning.
- Tests use a small synthetic fixture (made-up flows, triggers and a matching `claude_output.json`) committed under `tests/`. The real org's data never goes into git; rendering this org is checked locally only.

## Left to the builder

- Module and file names, CLI flag names, and how the use-case page shares code with the current renderer.
- `urllib` or the `anthropic` SDK for the call.
- Exact excerpt length, token budget and trimming order.
- Visual details of pills, confidence badges and the evidence pop-over, within the existing design tokens.
- Whether to remove the `lanes` layout (the user found it unhelpful; nothing depends on it).
- Tests: at minimum, validation of Claude output (unknown IDs, double assignment, missing flows), PII stripping, and a render from the synthetic fixture.
