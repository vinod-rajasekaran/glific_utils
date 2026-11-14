# Glific Utils

Python tools for understanding, auditing and working with a [Glific](https://glific.org) chatbot through its GraphQL API. Each use case is a **feature**: a folder with its own scripts, README and tests, run with one command from the repo root.

## Features

| Feature | What it does | Run |
|---|---|---|
| [`org_programme_architecture/`](org_programme_architecture/) | Pulls every active flow, trigger and the organisation's flow settings, and builds one page, `org_map.html`: the bot's programmes (read by Claude, or grouped by their links with `--no-claude`), a graph of how each programme's flows start and connect, and the full flow graph | `./org_map.sh` |
| [`glific_mcp/`](glific_mcp/) | An MCP server that lets Claude (or any MCP client) read the account's flows with full definitions, collections, templates, tags, languages and settings; write tools only when switched on. **Moved here from [`glific-mcp`](https://github.com/vinod-rajasekaran/glific-mcp)** and rewritten in Python | `./glific_mcp.sh` |

Shared code (the Glific client, run folders, credential redaction, masking of personal data, and `org_facts/`, which reads an export into cleaned facts) lives in [`glific_common/`](glific_common/).

Each feature's README covers what it does, its options, its output and its privacy rules.

## Setup

Python 3.10 or later (developed and tested on 3.15). Create a virtual environment at the repo root and install the optional packages; the run scripts use `.venv` automatically when it exists:

```bash
python3.15 -m venv .venv
.venv/bin/pip install -e ".[claude,mcp]"   # anthropic for the org map's Claude step, mcp for the MCP server
```

The org map itself needs only the standard library, so `python3 org_programme_architecture/build_org_map.py --no-claude` also runs without the venv. `pyproject.toml` lists the packages; `pip install -e .` also makes the shared `glific_common` package importable.

The tools log in with a Glific staff account, read from a `.env` file at the repo root:

```bash
cp .env.example .env    # then fill in GLIFIC_URL, GLIFIC_PHONE and GLIFIC_PASSWORD
```

`.env` is git-ignored, so it is never committed. Variables already set in your shell take precedence over it, so you can also skip the file and export them directly:

```bash
export GLIFIC_URL=https://api.yourorg.glific.com   # your Glific API host (no trailing /api)
export GLIFIC_PHONE=91XXXXXXXXXX                    # login phone number, with country code
export GLIFIC_PASSWORD=secret
```

**Claude.** The org map asks Claude to read the flows when the `anthropic` package and an Anthropic API key (`ANTHROPIC_API_KEY` in `.env`) are present. Without them it still runs and groups flows by their links instead.

## Quick start

```bash
cp .env.example .env    # fill in URL, phone, password
./org_map.sh            # fetch flows, triggers and settings, build org_map.html, open it
./org_map.sh --help     # all options
./glific_mcp.sh --check # check the MCP server against your account, then see glific_mcp/README.md to connect it
```

The run scripts work from any directory; relative paths you pass (such as `--from-json ./export`) are read from the directory you run them in.

## Output

Every run writes to a new folder, `output/<feature>/<YYYY-MM-DD_HH-MM-SS>/`, at the repo root, whatever directory you run it from (for example `output/org_programme_architecture/2026-11-14_12-33-59/`). Earlier runs are never overwritten; delete old folders when you no longer need them. `output/` is git-ignored (only `output/.gitkeep` is tracked), so exported data cannot be committed by accident.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

Tests live in `tests/<feature>/` (shared code in `tests/glific_common/`), use made-up data, and make no network calls. Use `.venv/bin/python3`: the MCP server's tests are skipped where the `mcp` package is not installed.

## Security

- Never commit credentials. `.env` is git-ignored.
- Webhook credentials (auth headers, API keys in URLs and bodies) are blanked before `flows.json` is saved. See the [feature README](org_programme_architecture/README.md#notes).
- When an Anthropic API key is set, `org_map.sh` sends cleaned facts and short message excerpts to the Anthropic API. Staff names, phone numbers, emails and links are stripped first, and the exact request is saved as `claude_input.json`. Use `--no-claude` (or leave the key unset) to send nothing.
- The MCP server returns what its tools read to the assistant's model provider. It never reads contacts or message history, blanks webhook credentials and masks phone numbers, emails and links in message text; tools that change the account or message people are off unless `GLIFIC_MCP_ALLOW_WRITES=1`. See [its README](glific_mcp/README.md#privacy).
- Exported JSON can contain message content, contact fields and webhook URLs, and the generated pages contain flow, group and sheet names. They stay in the git-ignored `output/` folder. Treat them as sensitive and don't share them.

## Adding a feature

New use cases are added as features alongside the existing one. Keep to these conventions so the repo stays easy to navigate:

1. **One folder per feature** at the repo root, named for what it produces (`snake_case`), with a `README.md` covering: what it does and who it is for, a file table (file, what it does, output), usage, options, output files, and what data it reads, stores or sends anywhere.
2. **One run script** at the repo root (`<name>.sh`), modelled on `org_map.sh`: works from any directory, prefers `.venv/bin/python3`, passes `--help` through, and opens what it wrote when that makes sense.
3. **Output** goes to `output/<feature folder>/<YYYY-MM-DD_HH-MM-SS>/` and never overwrites an earlier run.
4. **Settings** come from `.env` through the existing loader. Add any new variable to `.env.example` with a comment, and remove variables the code no longer reads.
5. **Reuse shared code.** The Glific client (`.env` loading, login, GraphQL paging, a re-logging `Session` for long-running tools), flow export, run folders, credential redaction and masking of personal data live in [`glific_common/`](glific_common/). Import from there instead of copying; when a second feature needs something that lives in a feature folder, move it into `glific_common/` with its tests (in `tests/glific_common/`).
6. **Privacy by default.** Redact credentials before saving anything, mask personal data before anything is rendered or sent to an outside API, and make any call to an outside API (such as Claude) visible in the run's output and avoidable with a flag.
7. **Tests** in `tests/<feature folder>/` (with an `__init__.py`), using made-up fixtures in that folder, never real org data, and no network calls.
8. **Update this README**: add a row to the Features table, and anything the feature changes in Setup, Security or Output.
9. **Design notes** (optional) go in `docs/superpowers/specs/` and `docs/superpowers/plans/`, named `YYYY-MM-DD-<feature>-design.md` and `YYYY-MM-DD-<feature>.md`. They record why a feature was built the way it was; the feature README stays the reference for how it works now.

## License

MIT. See [LICENSE](LICENSE).
