# Glific Utils

Small Python utilities for pulling data out of a [Glific](https://glific.org) instance through its GraphQL API. Use them to audit, back up or analyse your chatbot setup.

The scripts need only Python 3.9+ and its standard library. The optional use-case page (`--usecases`) also needs the `anthropic` package and an Anthropic API key (`ANTHROPIC_API_KEY` in `.env`). Install the package into a virtual environment at the repo root, which `flow_map.sh` uses automatically when it exists:

```bash
python3 -m venv .venv && .venv/bin/pip install anthropic
```

## Quick start

```bash
cp .env.example .env                                  # fill in URL, phone, password
./flow_map.sh --project "My Bot" --tag "2025 Pilot"   # fetch flows and triggers, build the HTML, open it
```

`flow_map.sh` runs the whole flow-architecture pipeline in one step and opens the pages it wrote. Add `--usecases` to have Claude group the flows into use cases as well (see the [feature README](get_system_flow_architecture/README.md#use-case-page-flow_usecaseshtml)). It works from any directory, and relative paths such as `--from-json ./export` are read from the directory you run it in. Run `./flow_map.sh --help` for all options.

## Features

Each feature lives in its own folder with its own README.

| Feature | What it does |
|---|---|
| [`get_system_flow_architecture/`](get_system_flow_architecture/) | Extracts all active flows (with nodes and edges) and all triggers (scheduled flow starts), and builds an HTML map of how they connect. Run `python3 get_system_flow_architecture/build_flow_architecture.py` |

## Setup

The scripts log in with a Glific staff account. The easiest way is a `.env` file at the repo root:

```bash
cp .env.example .env    # then edit .env with your values
```

The scripts load `.env` automatically. It is git-ignored, so it is never committed. Variables already set in your shell take precedence over `.env`. You can also skip the file and export the variables directly:

```bash
export GLIFIC_URL=https://api.yourorg.glific.com   # your Glific API host (no trailing /api)
export GLIFIC_PHONE=91XXXXXXXXXX                             # login phone number, with country code
export GLIFIC_PASSWORD=secret
```

## Output

Every run writes its results to a new folder, `output/<feature>/<YYYY-MM-DD_HH-MM-SS>/`, at the repo root, whatever directory you run it from. For example: `output/get_system_flow_architecture/2026-11-11_21-43-05/`. The folder is named by the local time the run started, and earlier runs are never overwritten. Delete old run folders when you no longer need them.

`output/` is git-ignored (only `output/.gitkeep` is tracked), so exported data cannot be committed by accident.

## Security

- Never commit credentials. `.env` is already in `.gitignore`.
- Webhook credentials (auth headers, API keys in URLs and bodies) are blanked before `flows.json` is saved. See the [feature README](get_system_flow_architecture/README.md#notes) for details.
- `--usecases` sends cleaned facts and short message excerpts to the Anthropic API. Staff names, phone numbers, emails and links are stripped first, and the exact request is saved as `claude_input.json`. It only runs when you ask for it.
- The exported JSON can contain message content, contact fields and webhook URLs. It stays in the git-ignored `output/` folder, and so does the generated HTML. Treat these files as sensitive and don't share them.

## License

MIT. See [LICENSE](LICENSE).
