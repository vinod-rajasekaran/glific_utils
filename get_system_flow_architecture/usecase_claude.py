"""One Claude call that reads the facts and returns the org's use cases, then validation.

    run_usecases(facts, client=None) -> (raw, validated, notes)

Claude returns structured JSON (enforced by SCHEMA). validate() checks every ID and
evidence reference against the facts and drops what does not match. When the first
response has problems, Claude gets one chance to fix them; after that, problems only
remove the items they affect, and the notes say what was removed. A response that is
unusable as a whole raises UsecaseError, and the caller falls back to the graph page.
"""
import json
import re
from pathlib import Path

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 128000
PROMPT_PATH = Path(__file__).resolve().parent / "USECASE_PROMPT.md"
CONFIDENCE = ["clear", "likely", "guess"]
ROLES = ["core", "helper", "shared", "test", "leftover", "unknown"]
KINDS = ["journey", "support", "admin", "tests"]


class UsecaseError(Exception):
    """The Claude step produced nothing usable; the run continues with the graph page."""


def _obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STR = {"type": "string"}
_IDS = {"type": "array", "items": _STR}
_CONF = {"type": "string", "enum": CONFIDENCE}
def _statements(*sections):
    """One list of statements per object, each saying which section it belongs to. One list (not one per
    section) keeps the compiled grammar small enough for structured output."""
    return {"type": "array", "items": _obj(section={"type": "string", "enum": list(sections)}, text=_STR, refs=_IDS,
                                           evidence=_IDS, confidence=_CONF)}
SCHEMA = _obj(
    org_summary=_obj(text=_STR, evidence=_IDS, confidence=_CONF),
    use_cases={"type": "array", "items": _obj(
        id=_STR, name=_STR, summary=_STR, kind={"type": "string", "enum": KINDS}, flows=_IDS,
        statements=_statements("story", "how_it_works", "watch"), confidence=_CONF)},
    flows={"type": "array", "items": _obj(
        id=_STR, purpose=_STR, role={"type": "string", "enum": ROLES}, use_case=_STR, evidence=_IDS, confidence=_CONF)},
    programmes={"type": "array", "items": _obj(
        id=_STR, name=_STR, summary=_STR, kind={"type": "string", "enum": KINDS}, parts=_IDS,
        statements=_statements("story", "watch"), confidence=_CONF)},
    edges={"type": "array", "items": _obj(id=_STR, meaning=_STR)},
    systems={"type": "array", "items": _obj(host=_STR, name=_STR, confidence=_CONF)},
)


def _client():
    try:
        import anthropic
    except ImportError as e:
        raise UsecaseError("the anthropic package is not installed (pip install anthropic)") from e
    try:
        return anthropic.Anthropic()
    except Exception as e:   # no credentials found
        raise UsecaseError(f"no Anthropic credentials: {e}") from e


def call_claude(facts, client=None, repair_errors=None, previous=None):
    """Send the facts (and, for a repair, the previous answer and its problems); return the parsed JSON."""
    client = client or _client()
    messages = [{"role": "user", "content": "Facts about every active flow in this org, as JSON:\n\n"
                 + json.dumps(facts, ensure_ascii=False, sort_keys=True)}]
    if repair_errors is not None:
        messages += [
            {"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)},
            {"role": "user", "content": "Checking your answer against the facts found these problems:\n- "
             + "\n- ".join(repair_errors) + "\n\nReturn the full corrected answer. Use only IDs from the facts."},
        ]
    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            system=[{"type": "text", "text": PROMPT_PATH.read_text(encoding="utf-8"), "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
    except UsecaseError:
        raise
    except Exception as e:   # API, network and auth errors all end the Claude step the same way
        raise UsecaseError(f"the Claude API call failed: {type(e).__name__}: {e}") from e
    if msg.stop_reason == "refusal":
        detail = getattr(getattr(msg, "stop_details", None), "category", None)
        raise UsecaseError(f"Claude declined the request{f' ({detail})' if detail else ''}")
    if msg.stop_reason == "max_tokens":
        raise UsecaseError("Claude's answer was cut off at the output limit")
    # Join every text block: after a mid-stream refusal fallback the answer continues in a new block
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        return json.loads(text)
    except ValueError as e:
        raise UsecaseError("Claude's answer was not valid JSON") from e


def _slug(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "use-case"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def _section(obj, name):
    """Statements of one section, from the schema's single "statements" list or an older answer's per-section lists."""
    if isinstance(obj.get("statements"), list):
        return [x for x in obj["statements"] if isinstance(x, dict) and x.get("section") == name]
    return obj.get(name)


def validate(out, facts):
    """Return (cleaned output, problems). Raises UsecaseError when nothing usable is left."""
    if not isinstance(out, dict) or not isinstance(out.get("use_cases"), list):
        raise UsecaseError("Claude's answer has no list of use cases")
    flow_ids = [f["id"] for f in facts["flows"]]
    names = {f["id"]: f["name"] for f in facts["flows"]}
    known_refs = set(flow_ids) | {g["id"] for g in facts["groups"]} | {t["id"] for t in facts["triggers"]}
    edge_ids = {e["id"] for e in facts["edges"]}
    evidence_ids = known_refs | edge_ids | {e["id"] for f in facts["flows"] for e in f["excerpts"]}
    problems = []

    def statements(items, where):
        kept = []
        for s in items if isinstance(items, list) else []:
            if not isinstance(s, dict) or not str(s.get("text") or "").strip():
                continue
            bad = [x for x in s.get("refs", []) if x not in known_refs] + [x for x in s.get("evidence", []) if x not in evidence_ids]
            if bad:
                problems.append(f"{where}: unknown IDs {', '.join(map(str, bad[:5]))} in \"{str(s['text'])[:60]}\"")
            s = dict(s, refs=[x for x in s.get("refs", []) if x in known_refs],
                     evidence=[x for x in s.get("evidence", []) if x in evidence_ids])
            if not s["evidence"] and s.get("confidence") != "guess":
                problems.append(f"{where}: dropped \"{str(s['text'])[:60]}\" because none of its evidence is in the facts")
                continue
            kept.append(s)
        return kept

    owner, use_cases, taken = {}, [], set()
    for u in out["use_cases"]:
        if not isinstance(u, dict):
            continue
        name = str(u.get("name") or "Unnamed use case")
        flows = []
        for fid in u.get("flows", []):
            if fid not in names:
                problems.append(f"use case {name}: unknown flow ID {fid}")
            elif fid in owner:
                problems.append(f"use case {name}: {names[fid]} is already in use case {owner[fid]}; a flow has one primary use case")
            else:
                flows.append(fid)
        if not flows:
            problems.append(f"use case {name} was dropped because none of its flows are in the facts")
            continue
        uid = _slug(u.get("id") or name, taken)
        for fid in flows:
            owner[fid] = name
        use_cases.append({
            "id": uid, "name": name, "summary": str(u.get("summary") or ""),
            "kind": u.get("kind") if u.get("kind") in KINDS else "journey", "flows": flows,
            "story": statements(_section(u, "story"), f"{name}, story"),
            "how_it_works": statements(_section(u, "how_it_works"), f"{name}, how it works"),
            "watch": statements(_section(u, "watch"), f"{name}, watch"),
            "confidence": u.get("confidence") if u.get("confidence") in CONFIDENCE else "guess",
        })
    if not use_cases:
        raise UsecaseError("none of Claude's use cases refer to flows in the facts")
    uc_of = {fid: u["id"] for u in use_cases for fid in u["flows"]}

    given = {}
    for f in out.get("flows", []) if isinstance(out.get("flows"), list) else []:
        if not isinstance(f, dict):
            continue
        if f.get("id") not in names:
            problems.append(f"flows: unknown flow ID {f.get('id')}")
        elif f["id"] not in given:
            given[f["id"]] = f
    flows = []
    for fid in flow_ids:
        f = given.get(fid)
        if f is None:
            problems.append(f"flows: no purpose given for {names[fid]}")
            f = {"purpose": "", "role": "unknown", "evidence": [], "confidence": "guess"}
        bad = [x for x in f.get("evidence", []) if x not in evidence_ids]
        if bad:
            problems.append(f"flows: unknown evidence IDs {', '.join(map(str, bad[:5]))} for {names[fid]}")
        ev = [x for x in f.get("evidence", []) if x in evidence_ids]
        conf = f.get("confidence") if f.get("confidence") in CONFIDENCE else "guess"
        if not ev and f.get("purpose") and conf != "guess":
            problems.append(f"flows: the purpose of {names[fid]} cites no evidence in the facts, so it is shown as a guess")
        flows.append({"id": fid, "purpose": str(f.get("purpose") or ""), "role": f.get("role") if f.get("role") in ROLES else "unknown",
                      "use_case": uc_of.get(fid, ""), "evidence": ev, "confidence": conf if ev else "guess"})
    not_placed = [fid for fid in flow_ids if fid not in uc_of]

    edges = []
    for e in out.get("edges", []) if isinstance(out.get("edges"), list) else []:
        if isinstance(e, dict) and e.get("id") in edge_ids and str(e.get("meaning") or "").strip():
            edges.append({"id": e["id"], "meaning": str(e["meaning"])})
        elif isinstance(e, dict):
            problems.append(f"edges: unknown edge ID {e.get('id')}")
    systems = []
    for s in out.get("systems", []) if isinstance(out.get("systems"), list) else []:
        if isinstance(s, dict) and s.get("host") in facts["hosts"] and str(s.get("name") or "").strip():
            systems.append({"host": s["host"], "name": str(s.get("name") or ""),
                            "confidence": s.get("confidence") if s.get("confidence") in CONFIDENCE else "guess"})
        elif isinstance(s, dict):
            problems.append(f"systems: host {s.get('host')} is not a webhook host in the facts")

    summary = out.get("org_summary") if isinstance(out.get("org_summary"), dict) else {}
    bad = [x for x in summary.get("evidence", []) if x not in evidence_ids]
    if bad:
        problems.append(f"org summary: unknown evidence IDs {', '.join(map(str, bad[:5]))}")
    ev = [x for x in summary.get("evidence", []) if x in evidence_ids]
    if not ev and summary.get("text") and summary.get("confidence") != "guess":
        problems.append("org summary: cites no evidence in the facts, so it is shown as a guess")
    org_summary = {"text": str(summary.get("text") or ""), "evidence": ev,
                   "confidence": (summary.get("confidence") if summary.get("confidence") in CONFIDENCE else "guess") if ev else "guess"}

    programmes = _programmes(out, use_cases, statements, problems)

    return ({"org_summary": org_summary, "programmes": programmes, "use_cases": use_cases, "flows": flows,
             "not_placed": not_placed, "edges": edges, "systems": systems}, problems)


def _programmes(out, use_cases, statements, problems):
    """Group the validated use cases into programmes. An answer without programmes (from before
    they existed) gets one programme per use case; a use case left out of every programme gets
    its own, and that is reported."""
    by_id = {u["id"]: u for u in use_cases}
    given = out.get("programmes")
    if not isinstance(given, list):
        return [_wrap(u) for u in use_cases]
    owner, programmes, taken = {}, [], set()
    for p in given:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "Unnamed programme")
        parts = []
        for pid in p.get("parts", []) if isinstance(p.get("parts"), list) else []:
            if pid not in by_id:
                problems.append(f"programme {name}: unknown use case ID {pid}")
            elif pid in owner:
                problems.append(f"programme {name}: use case {by_id[pid]['name']} is already in programme {owner[pid]}")
            elif pid not in parts:
                parts.append(pid)
        if not parts:
            problems.append(f"programme {name} was dropped because none of its parts are use cases in the answer")
            continue
        for pid in parts:
            owner[pid] = name
        programmes.append({
            "id": _slug(p.get("id") or name, taken), "name": name, "summary": str(p.get("summary") or ""),
            "kind": p.get("kind") if p.get("kind") in KINDS else by_id[parts[0]]["kind"], "parts": parts,
            "story": statements(_section(p, "story"), f"{name}, story"),
            "watch": statements(_section(p, "watch"), f"{name}, watch"),
            "confidence": p.get("confidence") if p.get("confidence") in CONFIDENCE else "guess",
        })
    for u in use_cases:
        if u["id"] not in owner:
            problems.append(f"use case {u['name']} is not in any programme, so it is shown as its own")
            programmes.append(_wrap(u, {p["id"] for p in programmes}))
    return programmes


def _wrap(u, taken=()):
    pid = u["id"] if u["id"] not in taken else _slug(u["id"], set(taken))
    return {"id": pid, "name": u["name"], "summary": u["summary"], "kind": u["kind"], "parts": [u["id"]],
            "story": [], "watch": [], "confidence": u["confidence"]}


def run_usecases(facts, client=None):
    """Call Claude, validate, and repair once if needed. Returns (raw answer, validated, notes on what was dropped).

    If the repair call fails or its answer is unusable, the first answer is kept (with its problems
    listed), so a paid-for usable answer is never thrown away."""
    client = client or _client()
    raw = call_claude(facts, client)
    try:
        validated, problems = validate(raw, facts)
    except UsecaseError as e:
        problems, validated = [str(e)], None
    if not problems:
        return raw, validated, []
    try:
        raw2 = call_claude(facts, client, repair_errors=problems, previous=raw)
        validated2, problems2 = validate(raw2, facts)
    except UsecaseError as e:
        if validated is None:
            raise
        return raw, validated, problems + [f"The repair call failed ({e}), so Claude's first answer is shown."]
    return raw2, validated2, problems2
