# Decision log

Only the big decisions: the ones that shape how the repo works and would be costly to reverse. Each entry says what was decided, why, and what was turned down. Newest first. Smaller choices live in commit messages; how things work now lives in each feature's README.

---

## 2026-11-14: The MCP server serves the org map's cleaned facts; the assistant does the reading

**Decided.** The MCP server has four read-only org tools (`get_org_overview`, `get_flow_facts`, `get_org_facts`, `get_org_map`). They pull the account live and return the same cleaned facts the org map sends to Claude, plus the programmes from the latest saved `org_map.json`. The MCP server never calls a model itself. Building the page, with Claude's checked and evidenced answer, stays a separate step the user runs (`./org_map.sh`).

**Why.** The facts are the valuable part, and in a chat the assistant can answer follow-up questions the page doesn't. The page needs one answer of about 20K tokens that follows a schema, cites evidence and passes validation with a repair round. A chat client writing that in one tool call is unreliable. Keeping the API call in the org map also keeps "send the facts to Anthropic, and pay for it" a decision the user makes.

**Turned down.** A `build_org_map` MCP tool (Claude could start paid runs on its own), and serving only saved runs (answers would go stale).

## 2026-11-14: Fact building moves to `glific_common/org_facts/`

**Decided.** The model, flow reading, fact building, link grouping and fetching moved from the org map into `glific_common/org_facts/`. The org map keeps the page and the Claude call.

**Why.** A second feature (the MCP server) needed them, and the repo rule is to share rather than copy. Checked: the real org's pages, and a live pull, are byte-identical before and after.

## 2026-11-14: The Glific MCP server moves into this repo, rewritten in Python

**Decided.** `vinod-rajasekaran/glific-mcp` (Node.js) was rewritten as `glific_mcp/` on the shared Python client. The old repo got a "moved" note and was archived.

- Write tools (create flow or collection, start flows) are off unless `GLIFIC_MCP_ALLOW_WRITES=1`. The start tools are marked destructive.
- No tool reads contacts or message history. Credentials are blanked; free text is masked.

**Why.**
- One language and one `.env` for every tool.
- The Node repo had drifted from its README, committed `node_modules`, and logged the login reply, which holds the access token.
- Tools that message real people should not be one model decision away by default.

## 2026-11-14: One repo, many features, shared `glific_common/`

**Decided.** Each use case is a feature folder with its own run script, README and `tests/<feature>/`. Shared code (Glific client, run folders, redaction, masking) lives in `glific_common/`. Python 3.10 is the minimum, and development happens on 3.15. `anthropic` and `mcp` are optional extras.

**Why.** More use cases are coming. The conventions are written down in the README's "Adding a feature" checklist so each new feature lands the same way.

## 2026-11-13 / 14: Claude reads the flows; Python supplies facts, checks the answer and draws the page

**Decided.** `org_map.html` shows the bot as programmes made of parts. Claude writes the summaries, stories and roles from cleaned facts, and every claim cites fact IDs. Python builds the facts, checks every ID and piece of evidence, and drops what fails after one repair round. Python also draws every graph. Everything else is computed from the export: numbers, links and starts. Tags no longer decide what is mapped.

**Why.** Python alone can't say what a flow is *for*. Claude alone can't be trusted on structure. Splitting the work this way means anything Claude gets wrong is caught or labelled, never drawn as fact.

**Turned down.** Per-tag maps and use-case pages, both replaced by one page per run. A spec to paste into an LLM by hand.

## 2026-11-13 / 14: Privacy by default for anything that leaves the machine

**Decided.**
- Credentials are blanked before anything is saved.
- Staff names, phone numbers, emails and links are masked before anything is sent to Anthropic or rendered.
- What is sent is saved as `claude_input.json`.
- `--no-claude` (or no API key) sends nothing and groups flows by their links instead.

**Why.** The exports hold real people's data and the org's credentials. Sending cleaned excerpts gives Claude enough to read purpose without the personal data.

---

## Open

- **Which model reads the flows for the page.** It is `claude-opus-5-5` at effort `high`. A comparison with Sonnet 5.5 and Haiku 5.5 is proposed; record the outcome here.
