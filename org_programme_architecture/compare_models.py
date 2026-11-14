#!/usr/bin/env python3
"""Compare Claude models on the org map's one Claude call, using the facts a run already sent.

Each model gets the identical request (claude_input.json from the run), with the same repair
round the org map uses. Each answer is scored with the org map's own checks and drawn as a page
from the run's saved export, so the pages can be read side by side. Nothing is sent that the run
did not already send to Anthropic. It costs money: see the estimate it prints before starting.

Usage:
  .venv/bin/python3 org_programme_architecture/compare_models.py RUN_DIR [--models a,b,c] [--runs 2]
  .venv/bin/python3 org_programme_architecture/compare_models.py RUN_DIR --judge ANSWER_DIR [ANSWER_DIR ...]

--judge asks Opus to compare the given answers blind (labelled A, B, C in shuffled order) against the
same facts, and writes judgement.json next to the first answer's comparison folder.

Writes output/org_programme_architecture/<stamp>/ with one folder per model and run
(claude_output.json, org_map.html, metrics.json) and comparison.json for all of them.
"""
import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

importlib.import_module("glific_common.api")   # loads .env, which holds the Anthropic key
from glific_get_flows import run_dir, save_json  # noqa: E402
from programme_claude import _client, _serious, run_programmes, validate, ProgrammeError  # noqa: E402

from programme_claude import MODELS  # noqa: E402
# $ per million tokens: input, output, cache read, cache write (5-minute). Haiku's prices hold up to 100K-token prompts.
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.20, 5.00), "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
          "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125)}


class Recorder:
    """Wraps the Anthropic client and keeps every final message, so each call's answer and usage are kept."""
    def __init__(self, client):
        self.client, self.messages = client, []
        outer = self

        class _Messages:
            def stream(self, **kw):
                return _Wrapped(outer.client.beta.messages.stream(**kw), outer.messages)
        self.beta = type("Beta", (), {"messages": _Messages()})()


class _Wrapped:
    def __init__(self, cm, sink):
        self.cm, self.sink = cm, sink

    def __enter__(self):
        stream = self.cm.__enter__()
        sink = self.sink

        class _S:
            def get_final_message(self):
                msg = stream.get_final_message()
                sink.append(msg)
                return msg
        return _S()

    def __exit__(self, *a):
        return self.cm.__exit__(*a)


def cost(model, usage):
    p_in, p_out, p_read, p_write = PRICES[model]
    return (usage["input_tokens"] * p_in + usage["output_tokens"] * p_out + usage["cache_read_input_tokens"] * p_read
            + usage["cache_creation_input_tokens"] * p_write) / 1e6


def metrics(model, facts, msgs, raw, validated, notes, seconds):
    usage = {k: sum(getattr(m.usage, k, 0) or 0 for m in msgs)
             for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    first_problems = None
    if msgs:
        try:
            text = "".join(b.text for b in msgs[0].content if getattr(b, "type", "") == "text")
            first_problems = len(_serious(validate(json.loads(text), facts)[1]))
        except (ValueError, ProgrammeError):
            first_problems = "unusable"
    statements = [s for p in validated["programmes"] for s in p.get("story", []) + p.get("watch", [])] + [
        s for u in validated["use_cases"] for s in u.get("story", []) + u.get("how_it_works", []) + u.get("watch", [])]
    total = len(facts["flows"])
    placed = len({f for u in validated["use_cases"] for f in u["flows"]})
    return {
        "model": model, "answered_by": [m.model for m in msgs], "calls": len(msgs), "seconds": round(seconds),
        "usage": usage, "cost_usd": round(cost(model, usage), 3),
        "first_answer_problems": first_problems, "dropped_after_repair": len(notes),
        "programmes": len(validated["programmes"]), "parts": len(validated["use_cases"]),
        "flows_placed": f"{placed}/{total}", "flows_with_purpose": sum(1 for f in validated["flows"] if f.get("purpose")),
        "statements": len(statements),
        "confidence": {c: sum(1 for s in statements if s.get("confidence") == c) for c in ("clear", "likely", "guess")},
        "org_summary_words": len((validated.get("org_summary") or {}).get("text", "").split()),
    }


def one(model, n, facts, run, out):
    folder = out / f"{model.removeprefix('claude-')}-{n}"
    folder.mkdir(parents=True)
    rec = Recorder(_client())
    start = time.monotonic()
    try:
        raw, validated, notes = run_programmes(facts, client=rec, model=model)
    except ProgrammeError as e:
        m = {"model": model, "failed": str(e), "calls": len(rec.messages), "seconds": round(time.monotonic() - start)}
        save_json(m, "metrics.json", folder)
        return m
    m = metrics(model, facts, rec.messages, raw, validated, notes, time.monotonic() - start)
    save_json(raw, "claude_output.json", folder)
    save_json(m, "metrics.json", folder)
    env = {**os.environ, "GLIFIC_OUTPUT_ROOT": str(folder / "page")}
    p = subprocess.run([sys.executable, str(HERE / "build_org_map.py"), "--from-json", str(run), "--reuse-claude", str(folder)],
                       capture_output=True, text=True, env=env)
    m["page"] = p.stdout.strip() or f"page failed: {p.stderr[-300:]}"
    save_json(m, "metrics.json", folder)
    print(f"{folder.name}: done in {m['seconds']}s, ${m['cost_usd']}", file=sys.stderr)
    return m


JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answers", "ranking", "summary"], "properties": {
    "answers": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["label", "accuracy", "usefulness", "coverage", "errors", "strengths"], "properties": {
                    "label": {"type": "string"},
                    "accuracy": {"type": "integer", "description": "1-5: are its claims supported by the facts?"},
                    "usefulness": {"type": "integer", "description": "1-5: would a programme manager understand the bot from it?"},
                    "coverage": {"type": "integer", "description": "1-5: are the programmes and flows grouped sensibly and completely?"},
                    "errors": {"type": "array", "items": {"type": "string"}, "description": "specific wrong or unsupported claims"},
                    "strengths": {"type": "array", "items": {"type": "string"}}}}},
    "ranking": {"type": "array", "items": {"type": "string"}, "description": "labels, best first"},
    "summary": {"type": "string"}}}

JUDGE_PROMPT = """You are judging answers that each describe a WhatsApp chatbot (built in Glific) from the same facts.
Each answer groups the flows into programmes and parts and writes summaries, stories, how each part works,
what to watch, and each flow's purpose, citing fact IDs as evidence. The facts are the only truth: judge each
claim against them. Score each answer 1-5 for accuracy, usefulness to a programme manager, and coverage; list
specific errors (quote the claim and say what the facts show) and strengths; rank the answers best first.
Do not reward length for its own sake. The answers are labelled; you are not told who wrote them."""


def judge(run, folders):
    import random
    facts = json.loads((run / "claude_input.json").read_text())["facts"]
    answers = []
    for f in folders:
        raw = json.loads((f / "claude_output.json").read_text())
        validated, _ = validate(raw, facts)
        answers.append((f.name, {k: v for k, v in validated.items() if k not in ("model", "_meta")}))
    random.shuffle(answers)
    labels = {chr(65 + i): name for i, (name, _) in enumerate(answers)}
    body = "Facts:\n\n" + json.dumps(facts, ensure_ascii=False, sort_keys=True) + "".join(
        f"\n\nAnswer {chr(65 + i)}:\n\n" + json.dumps(a, ensure_ascii=False) for i, (_, a) in enumerate(answers))
    rec = Recorder(_client())
    with rec.beta.messages.stream(model="claude-opus-5-5", max_tokens=64000, system=JUDGE_PROMPT,
                                  output_config={"effort": "high", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
                                  messages=[{"role": "user", "content": body}]) as s:
        msg = s.get_final_message()
    verdict = json.loads("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
    usage = {k: getattr(msg.usage, k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    out = {"labels": labels, "verdict": verdict, "judge_cost_usd": round(cost("claude-opus-5-5", usage), 3)}
    path = save_json(out, "judgement.json", folders[0].parent)
    print(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", type=Path, help="a run folder holding claude_input.json, flows.json and triggers.json")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--runs", type=int, default=2, help="runs per model (default 2)")
    ap.add_argument("--judge", nargs="+", type=Path, metavar="ANSWER_DIR", help="compare these answers blind with Opus")
    args = ap.parse_args()
    if args.judge:
        return judge(args.run, args.judge)
    facts = json.loads((args.run / "claude_input.json").read_text())["facts"]
    models = [m for m in args.models.split(",") if m]
    out = run_dir()
    print(f"{len(models)} models x {args.runs} runs on {len(facts['flows'])} flows -> {out}", file=sys.stderr)
    jobs = [(m, n) for m in models for n in range(1, args.runs + 1)]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(lambda j: one(j[0], j[1], facts, args.run, out), jobs))
    save_json({"run": str(args.run), "results": results}, "comparison.json", out)
    print(out / "comparison.json")


if __name__ == "__main__":
    main()
