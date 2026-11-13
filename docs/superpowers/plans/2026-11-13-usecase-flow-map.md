# Use-case flow map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `flow_map.sh --usecases` sends cleaned facts about every active flow to Claude, validates what Claude returns, and renders a page that opens on the org's use cases and drills into each one with a graph and a side pane.

**Architecture:** Python builds `facts` (IDs, structure, cleaned excerpts) from the existing `Model`; `usecase_claude.py` makes one structured-output call (plus at most one repair call) and validates every reference against the facts; `render_usecases.py` draws the page, reusing `graph_layout.py` and the graph renderer per use case. Facts never come from Claude.

**Tech Stack:** Python 3 standard library; `anthropic` SDK (lazy import, only for the Claude step); `unittest` for tests; Microsoft Edge headless for screenshots.

**Spec:** `docs/superpowers/specs/2026-11-13-usecase-flow-map-design.md`

## Global Constraints

- Model `claude-opus-5-5`, `output_config.effort` `"high"`, structured output via `output_config.format` JSON schema, streaming with `max_tokens` 64000, server-side refusal fallback (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`), system prompt cached with `cache_control`.
- The Claude step runs only with `--usecases` or `GLIFIC_USECASES=1`, and needs Anthropic credentials. Without them, or on an unusable response, the run still writes the graph page and prints why the use-case page was skipped.
- Default `--layout` becomes `graph`.
- Excerpts are cut to 200 characters. Staff names become "a staff contact"; phone-like numbers and emails are masked; URLs are reduced to host (webhooks: host and path).
- Page rules from `PROMPT_SPEC.md` apply: fonts, light and dark tokens, no em dashes, HTML tags balance, script passes `node --check`. Message excerpts may appear as evidence.
- No org data in git: tests use the synthetic fixture under `tests/fixtures/`.
- Run folder gets `claude_input.json`, `claude_output.json` (raw), `usecases.json` (validated), `flow_usecases.html`.

## Review Focus

- Claude names a flow by name instead of ID, or invents an ID: the item is dropped, listed under "Dropped by validation", and the page renders. (Task 3 test)
- A use case left with no valid flows after validation: hidden from the first screen and listed as dropped. (Task 3 test)
- Claude text containing `<script>` or quotes: escaped everywhere it is shown. (Task 4 test)
- `--usecases` with no `anthropic` package or no credentials: graph page written, one-line reason printed, exit code 0. (Task 5 test)
- A 1,500-character Devanagari message: cut at 200 characters, not bytes, without breaking a character. (Task 2 test)

---

### Task 1: Whole-account scope and subset graphs

**Files:**
- Modify: `get_system_flow_architecture/render_architecture.py` (Settings, `Model._scope`, `Model._graph_map`, `graph_section`)
- Create: `tests/fixtures/flows.json`, `tests/fixtures/triggers.json`, `tests/__init__.py`, `tests/test_graph_subset.py`

**Interfaces:**
- Produces: `Settings.scope_all: bool = False` (scope = every flow in the export); `Model.graph_view(flow_ids: set[str]) -> None` (sets `on_map` to exactly those flows and recomputes `trigger_flows`, `no_start`, `group_nodes`, `entry`; group-filling flows outside the set are not added); `graph_svg(m, edges, findings, ns: str = "", faded: set[str] = frozenset()) -> tuple[str, list[str]]` returning the SVG and a list of `<template>` strings, with every DOM id and `data-id` prefixed by `ns`, and faded flows drawn with class `faded`. `graph_section` keeps its current output by calling `graph_svg` with `ns=""`.

- [ ] **Step 1: Write the synthetic fixture.** Eight made-up flows in two use cases plus a test copy: `Welcome` (keyword `hi`, enters `Profile`), `Profile` (sets field `stage`, adds to group `Members`), `Weekly tip` (active weekly trigger to group `Members`, reads `stage`, enters `Ask AI`), `Ask AI` (webhook host `api.example.org`), `Ask AI copy` (keyword `test`, reads `stage`), `Survey start` (keyword `survey`, enters `Survey save`), `Survey save` (Google Sheet `Responses`, staff alert template `survey_alert` to 1 staff contact named "Asha Rao", sticky note containing "call 9876543210"), `Old draft` (no links). Messages include one 1,500-character Devanagari string.
- [ ] **Step 2: Write failing tests** in `tests/test_graph_subset.py`: `test_scope_all_includes_unlinked` (`Old draft` in `Model(..., Settings(scope_all=True, layout="graph")).scope`); `test_graph_view_limits_nodes` (after `graph_view({Welcome, Profile})`, `on_map` is those two and `edges()` has no `Weekly tip` node); `test_graph_svg_namespaces_ids` (two calls with `ns="u1-"` and `ns="u2-"` give no shared `id=`/`data-id=` values); `test_faded_class` (faded flow's `<g>` has class containing `faded`).
- [ ] **Step 3: Run** `python3 -m unittest tests.test_graph_subset -v`. Expected: FAIL (`scope_all` unknown).
- [ ] **Step 4: Implement** the interfaces above. Split `_graph_map` into scope selection and a `graph_view` recompute; move the SVG building out of `graph_section` into `graph_svg`.
- [ ] **Step 5: Run** the tests and `python3 get_system_flow_architecture/build_flow_architecture.py --from-json tests/fixtures --layout graph`. Expected: tests PASS; page written.
- [ ] **Step 6: Commit** `Add whole-account scope and namespaced subset graphs`.

### Task 2: Facts and privacy cleaning

**Files:**
- Create: `get_system_flow_architecture/usecase_facts.py`, `tests/test_usecase_facts.py`

**Interfaces:**
- Consumes: `Model` with `scope_all=True` (Task 1).
- Produces: `clean_text(text: str, staff_names: set[str], limit: int = 200) -> str`; `build_facts(m: Model) -> dict` with keys `flows` (list of dicts: `id`, `name`, `tag`, `keywords`, `starts_from` (list of `{kind, ref, text}` with kind in `trigger|keyword|flow|none`), `leads_to` (list of `{kind, ref, text}` with kind in `flow|data|group`), `touches` (list of strings), `routes`, `unreachable`, `excerpts` (list of `{id, kind, text}` with kind in `message|interactive|template|sticky`)), `groups` (list `{id, name, added_by, removed_by, triggers}`), `triggers` (list `{id, flow, schedule, groups, active}`), `edges` (list `{id, from, to, kind}`), `hosts` (list of strings), `findings` (list of strings). IDs: flow uuid; `msg:<uuid>:<n>`, `int:<uuid>:<n>`, `tpl:<uuid>:<n>`, `sticky:<uuid>:<n>`; `group:<name>`; `trigger:<id>`; `edge:<from>:<to>:<kind>`.

- [ ] **Step 1: Write failing tests:** `test_masks_phone_and_email` (`clean_text("call 9876543210 or a@b.org", set())` contains neither); `test_strips_staff_names` ("Asha Rao" becomes "a staff contact"); `test_url_to_host` (`https://docs.google.com/x/y?z=1` becomes `docs.google.com`); `test_keeps_expressions` (`@contact.name` unchanged); `test_cuts_by_characters` (1,500-char Devanagari string gives ≤201 characters, ends with "…", decodes cleanly); `test_facts_shape` (fixture: 8 flows, every excerpt id unique, `Survey save` sticky excerpt has no digits run ≥8, no "Asha"); `test_facts_json_has_no_secrets` (dumped facts contain no `[redacted]` header values, no `Authorization`).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_usecase_facts -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `usecase_facts.py`. Staff names come from `send_broadcast.contacts[].name` and `open_ticket.assignee.name` across the export. Phone pattern: 8 or more digits allowing spaces, dashes and a leading `+`. Reuse `summarise` output and `webhook_desc` for `touches`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `Build cleaned facts for the use-case step`.

### Task 3: Prompt, call and validation

**Files:**
- Create: `get_system_flow_architecture/USECASE_PROMPT.md`, `get_system_flow_architecture/usecase_claude.py`, `tests/fixtures/claude_output.json`, `tests/test_usecase_claude.py`

**Interfaces:**
- Consumes: `build_facts` output (Task 2).
- Produces: `SCHEMA: dict` (JSON schema, arrays not keyed objects: `org_summary` {text, evidence, confidence}; `use_cases` [{id, name, summary, kind (`journey|support|admin|tests`), flows, story[{text, refs, evidence, confidence}], how_it_works[same], watch[same], confidence}]; `flows` [{id, purpose, role (`core|helper|shared|test|leftover|unknown`), use_case (string or `""`), evidence, confidence}]; `edges` [{id, meaning}]; `systems` [{host, name, confidence}]; confidence in `clear|likely|guess`); `call_claude(facts: dict, client=None, repair_errors: list[str] | None = None, previous: dict | None = None) -> dict`; `validate(out: dict, facts: dict) -> tuple[dict, list[str]]` returning the cleaned result and a list of human-readable problems; `run_usecases(facts: dict, client=None) -> tuple[dict, dict, list[str]]` returning raw output, validated output and dropped-item notes (raises `UsecaseError` when unusable).
- Validation rules: unknown flow, group, trigger, edge or evidence IDs are removed from `refs`/`evidence`; a statement whose evidence list becomes empty is kept only with confidence `guess`; a flow claimed by two use cases keeps the first; a flow missing from `flows` or with `use_case` `""` goes to `not_placed`; a use case with no flows left is dropped; `systems` hosts not in `facts.hosts` are dropped. Unusable = not a dict, no `use_cases`, or every use case dropped.

- [ ] **Step 1: Write the prompt** `USECASE_PROMPT.md`: readers (reviewer, newcomer), task, "refer only by IDs given", evidence and confidence rules, "say you cannot tell", one primary use case per flow, tests and leftovers into one use case of kind `tests`, plain words, no em dashes, story from the contact's side.
- [ ] **Step 2: Write the fixture** `tests/fixtures/claude_output.json` for the synthetic org with deliberate faults: one unknown flow ID, one evidence ID that does not exist on a `clear` statement, `Profile` in two use cases, `Old draft` missing, a `systems` entry for an unknown host, a summary containing `<script>alert(1)</script>`.
- [ ] **Step 3: Write failing tests:** `test_unknown_ids_dropped`; `test_unsupported_clear_becomes_dropped_or_guess`; `test_double_assignment_keeps_first`; `test_missing_flow_not_placed` (`Old draft` in `not_placed`); `test_empty_use_case_dropped`; `test_unusable_raises` (`run_usecases` with a fake client returning `{}` twice raises `UsecaseError`); `test_repair_called_once` (fake client returns invalid then valid output; client called exactly twice, second call carries the errors); `test_request_shape` (fake client records kwargs: model `claude-opus-5-5`, `output_config.format.type == "json_schema"`, `effort == "high"`, system block has `cache_control`).
- [ ] **Step 4: Run** `python3 -m unittest tests.test_usecase_claude -v`. Expected: FAIL.
- [ ] **Step 5: Implement** `usecase_claude.py`. Import `anthropic` inside `call_claude` only when `client` is None. Use `client.beta.messages.stream(...)` and `get_final_message()`; check `stop_reason` (`refusal` or `max_tokens` → `UsecaseError` with the reason) before reading the first text block. Repair = one more call with the previous output and the problem list appended as a user turn.
- [ ] **Step 6: Run** the tests. Expected: PASS.
- [ ] **Step 7: Commit** `Add the Claude use-case call and validation`.

### Task 4: Use-case page

**Files:**
- Create: `get_system_flow_architecture/render_usecases.py`, `tests/test_render_usecases.py`

**Interfaces:**
- Consumes: `Model.graph_view`, `graph_svg` (Task 1); facts (Task 2); validated output and dropped notes (Task 3); `flow_card`, `trigger_card`, `keyword_card`, `check_page`, `PAGE` tokens from `render_architecture.py`.
- Produces: `render_usecase_page(m: Model, facts: dict, uc: dict, dropped: list[str], settings: Settings) -> str`.

Page: first screen (title; org summary under "Claude's reading" with confidence; one card per use case, tests last and muted, pills from facts: flow count, start kinds, hosts with Claude's names, Sheets, staff alerts, groups, untagged count, issue count; shared resources; "Not placed"; "Dropped by validation"). Use-case view per use case (hidden until selected; `location.hash` = `#uc-<id>`): left graph of member flows plus faded direct neighbours (selecting a faded flow jumps to its use case), right pane with story, how it works and watch, each statement showing its confidence and, on selection, its evidence excerpts; selecting a box swaps the pane to Claude's purpose and role, the flow card and its ins and outs (from facts `starts_from`/`leads_to`), with a back link to the story. Flow cards in story order below the graph. Below 1100px the pane stacks under the graph. Footer names the model and run date.

- [ ] **Step 1: Write failing tests** (render fixture facts + validated fixture output): `test_lists_use_cases` (each valid use-case name appears once in the first screen); `test_escapes_claude_text` (`<script>alert` absent, `&lt;script&gt;` present); `test_page_checks` (`check_page`-style: tags balance, no em dash, extracted script passes `node --check` when `node` exists); `test_no_pii` (no "Asha", no 10-digit run, no `docs.google.com/` path); `test_dropped_listed` ("Dropped by validation" section lists the unknown ID note); `test_not_placed_listed` (`Old draft` under "Not placed").
- [ ] **Step 2: Run** `python3 -m unittest tests.test_render_usecases -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `render_usecases.py` with its own page template (same tokens and fonts as `PAGE`) and one script handling hash routing, per-graph hover and selection, the side pane and evidence toggles.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Render** the fixture to the scratchpad and screenshot it with Edge headless at 1400px (first screen and one use case selected via hash). Expected: cards visible; graph and pane side by side.
- [ ] **Step 6: Commit** `Render the use-case page`.

### Task 5: Command line, fallback and docs

**Files:**
- Modify: `get_system_flow_architecture/build_flow_architecture.py`, `flow_map.sh`, `get_system_flow_architecture/README.md`, `get_system_flow_architecture/PROMPT_SPEC.md`, `README.md`, `.env.example`
- Create: `tests/test_build_cli.py`

**Interfaces:**
- Consumes: Tasks 2 to 4.
- Produces: options `--usecases` (env `GLIFIC_USECASES=1`), `--reuse-claude DIR` (validate and render a saved `claude_output.json` without calling the API); default `--layout graph`; stdout lists the use-case page first.

- [ ] **Step 1: Write failing tests** (subprocess on the fixture): `test_reuse_claude_writes_page` (`--from-json tests/fixtures --usecases --reuse-claude tests/fixtures` writes `flow_usecases.html`, `usecases.json`, the graph page, and prints the use-case page first); `test_no_credentials_falls_back` (`--usecases` with `ANTHROPIC_API_KEY` unset and `anthropic` import forced to fail via `GLIFIC_FAKE_NO_SDK=1`: exit 0, graph page written, stderr says why); `test_default_layout_graph`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_build_cli -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the options; write `claude_input.json` before calling; on `UsecaseError` or import or auth failure, print the reason and continue with the graph page.
- [ ] **Step 4: Run** all tests `python3 -m unittest discover -s tests -v`. Expected: all PASS.
- [ ] **Step 5: Update docs**: README sections for `--usecases`, privacy, files written, cost note; `PROMPT_SPEC.md` points to `USECASE_PROMPT.md`; `.env.example` adds `ANTHROPIC_API_KEY=` and `GLIFIC_USECASES=`.
- [ ] **Step 6: Commit** `Wire the use-case page into flow_map.sh`.

### Task 6: Run on the real export and show it

- [ ] **Step 1:** Build facts for the 2026-11-13 export and inspect `claude_input.json` for names, digits runs and URLs.
- [ ] **Step 2:** With credentials, run `./flow_map.sh --from-json output/get_system_flow_architecture/2026-11-13_20-49-46 --usecases`. Without credentials, produce `claude_output.json` by following `USECASE_PROMPT.md` by hand in this session, save it in the run folder, render with `--reuse-claude`, and say so plainly.
- [ ] **Step 3:** Screenshot the first screen and two use cases; check the validation notes; open the page for the user.
