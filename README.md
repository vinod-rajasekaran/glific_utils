# Glific Utils

Small Python utilities for pulling data out of a [Glific](https://glific.org) instance through its GraphQL API. Use them to audit, back up or analyse your chatbot setup.

The scripts need only Python 3.9+ and its standard library. The optional programme page (`--programmes`) also needs the `anthropic` package and an Anthropic API key (`ANTHROPIC_API_KEY` in `.env`). Install the package into a virtual environment at the repo root, which `org_map.sh` uses automatically when it exists:

```bash
python3 -m venv .venv && .venv/bin/pip install anthropic
```

## Quick start

```bash
cp .env.example .env                                  # fill in URL, phone, password
./org_map.sh --project "My Bot" --tag "2025 Pilot"   # fetch flows and triggers, build the HTML, open it
```

`org_map.sh` runs the whole pipeline in one step and opens the page it wrote, `org_map.html`. Add `--programmes` to have Claude explain the bot as programmes and their parts (see the [feature README](org_programme_architecture/README.md#programme-page)). It works from any directory, and relative paths such as `--from-json ./export` are read from the directory you run it in. Run `./org_map.sh --help` for all options.

## Features

Each feature lives in its own folder with its own README.

| Feature | What it does |
|---|---|
| [`org_programme_architecture/`](org_programme_architecture/) | Extracts all active flows, triggers and flow settings, and builds a graph of how the flows start and connect; with `--programmes`, Claude also explains the bot as programmes and their parts. Run `./org_map.sh` |

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

Every run writes its results to a new folder, `output/<feature>/<YYYY-MM-DD_HH-MM-SS>/`, at the repo root, whatever directory you run it from. For example: `output/org_programme_architecture/2026-11-11_21-43-05/`. The folder is named by the local time the run started, and earlier runs are never overwritten. Delete old run folders when you no longer need them.

`output/` is git-ignored (only `output/.gitkeep` is tracked), so exported data cannot be committed by accident.

## Security

- Never commit credentials. `.env` is already in `.gitignore`.
- Webhook credentials (auth headers, API keys in URLs and bodies) are blanked before `flows.json` is saved. See the [feature README](org_programme_architecture/README.md#notes) for details.
- `--programmes` sends cleaned facts and short message excerpts to the Anthropic API. Staff names, phone numbers, emails and links are stripped first, and the exact request is saved as `claude_input.json`. It only runs when you ask for it.
- The exported JSON can contain message content, contact fields and webhook URLs. It stays in the git-ignored `output/` folder, and so does the generated HTML. Treat these files as sensitive and don't share them.

## License

MIT. See [LICENSE](LICENSE).
