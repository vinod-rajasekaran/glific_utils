"""One Claude call that reads the facts and returns the org's use cases, then validation.

    run_programmes(facts, client=None) -> (raw, validated, notes)

Claude returns structured JSON (enforced by SCHEMA). validate() checks every ID and
evidence reference against the facts and drops what does not match. When the first
response has problems, Claude gets one chance to fix them; after that, problems only
remove the items they affect, and the notes say what was removed. A response that is
unusable as a whole raises ProgrammeError, and the caller groups the flows by their links instead.
"""
import json
import re
from pathlib import Path

MODEL = "claude-opus-5-5"
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]   # --model choices
EFFORT = "high"
MAX_TOKENS = 128000
# Models that take server-side refusal fallbacks ("default" routing); Haiku has none
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
PROMPT_PATH = Path(__file__).resolve().parent / "PROGRAMME_PROMPT.md"
CONFIDENCE = ["clear", "likely", "guess"]
ROLES = ["core", "helper", "shared", "test", "leftover", "unknown"]
KINDS = ["journey", "support", "admin", "tests"]


class ProgrammeError(Exception):
    """The Claude step produced nothing usable; the run groups the flows by their links instead."""


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
        raise ProgrammeError("the anthropic package is not installed (pip install anthropic)") from e
    try:
        return anthropic.Anthropic()
    except Exception as e:   # no credentials found
        raise ProgrammeError(f"no Anthropic credentials: {e}") from e


def call_claude(facts, client=None, repair_errors=None, previous=None, model=MODEL):
    """Send the facts (and, for a repair, the previous answer and its problems); return the parsed JSON."""
    client = client or _client()
    # The facts are the big part of the request; caching them makes a repair call a cache read
    messages = [{"role": "user", "content": [{"type": "text", "cache_control": {"type": "ephemeral"},
                                              "text": "Facts about every active flow in this org, as JSON:\n\n"
                                              + json.dumps(facts, ensure_ascii=False, sort_keys=True)}]}]
    if repair_errors is not None:
        messages += [
            {"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)},
            {"role": "user", "content": "Checking your answer against the facts found these problems:\n- "
             + "\n- ".join(repair_errors) + "\n\nReturn the full corrected answer. Use only IDs from the facts."},
        ]
    try:
        fallback = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in FALLBACK_MODELS else {}
        with client.beta.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            **fallback,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            system=[{"type": "text", "text": PROMPT_PATH.read_text(encoding="utf-8"), "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
    except ProgrammeError:
        raise
    except Exception as e:   # API, network and auth errors all end the Claude step the same way
        raise ProgrammeError(f"the Claude API call failed: {type(e).__name__}: {e}") from e
    if msg.stop_reason == "refusal":
        detail = getattr(getattr(msg, "stop_details", None), "category", None)
        raise ProgrammeError(f"Claude declined the request{f' ({detail})' if detail else ''}")
    if msg.stop_reason == "max_tokens":
        raise ProgrammeError("Claude's answer was cut off at the output limit")
    # Join every text block: after a mid-stream refusal fallback the answer continues in a new block
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        out = json.loads(text)
    except ValueError as e:
        raise ProgrammeError("Claude's answer was not valid JSON") from e
    if isinstance(out, dict) and isinstance(getattr(msg, "model", None), str):
        u = getattr(msg, "usage", None)   # a server-side fallback can answer with another model
        out["_meta"] = {"model": msg.model, **{k: getattr(u, k, None) for k in
                        ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
                        if isinstance(getattr(u, k, None), int)}}
    return out


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
    """Return (cleaned output, problems). Raises ProgrammeError when nothing usable is left.

    Every ID Claude gives must be in the facts; anything else is removed and reported."""
    if not isinstance(out, dict) or not isinstance(out.get("use_cases"), list):
        raise ProgrammeError("Claude's answer has no list of use cases")
    c = _Checker(facts)
    use_cases, slug_of = c.use_cases(out)
    if not use_cases:
        raise ProgrammeError("none of Claude's use cases refer to flows in the facts")
    # Checked in this order so the problem list reads the same way every time
    flows, not_placed = c.flows(out, use_cases)
    edges, systems = c.edges(out), c.systems(out)
    org_summary = c.org_summary(out)
    programmes = c.programmes(out, use_cases, slug_of)
    meta = out.get("_meta") if isinstance(out.get("_meta"), dict) else {}
    return ({"model": meta.get("model") if isinstance(meta.get("model"), str) else MODEL,
             "org_summary": org_summary, "programmes": programmes, "use_cases": use_cases,
             "flows": flows, "not_placed": not_placed, "edges": edges, "systems": systems}, c.problems)


def _choice(value, allowed, default):
    return value if value in allowed else default


def _ids(value):
    """The strings in a list of IDs from Claude's answer; anything that is not a list gives none."""
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def _keys(value):
    """IDs that may come back as numbers (use-case IDs), as strings; anything else is dropped."""
    return [str(x) for x in value if isinstance(x, (str, int)) and not isinstance(x, bool)] if isinstance(value, list) else []


def _items(value):
    """The dicts in a list from Claude's answer, skipping anything else."""
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


class _Checker:
    """Checks each part of Claude's answer against the facts, collecting problems as it goes."""

    def __init__(self, facts):
        self.facts = facts
        self.flow_ids = [f["id"] for f in facts["flows"]]
        self.names = {f["id"]: f["name"] for f in facts["flows"]}
        self.known_refs = set(self.flow_ids) | {g["id"] for g in facts["groups"]} | {t["id"] for t in facts["triggers"]}
        self.edge_ids = {e["id"] for e in facts["edges"]}
        self.evidence_ids = self.known_refs | self.edge_ids | {e["id"] for f in facts["flows"] for e in f["excerpts"]}
        self.problems = []

    def statements(self, items, where):
        kept = []
        for s in items if isinstance(items, list) else []:
            if not isinstance(s, dict) or not str(s.get("text") or "").strip():
                continue
            refs, evidence = _ids(s.get("refs")), _ids(s.get("evidence"))
            bad = [x for x in refs if x not in self.known_refs] + [x for x in evidence if x not in self.evidence_ids]
            if bad:
                self.problems.append(f"{where}: unknown IDs {', '.join(map(str, bad[:5]))} in \"{str(s['text'])[:60]}\"")
            # Keep only checked fields: text as a string, known IDs, and a confidence from the list
            s = {"text": str(s["text"]), "refs": [x for x in refs if x in self.known_refs],
                 "evidence": [x for x in evidence if x in self.evidence_ids], "confidence": _choice(s.get("confidence"), CONFIDENCE, "guess")}
            if not s["evidence"] and s["confidence"] != "guess":
                self.problems.append(f"{where}: dropped \"{str(s['text'])[:60]}\" because none of its evidence is in the facts")
                continue
            kept.append(s)
        return kept

    def use_cases(self, out):
        """Use cases with at least one flow; each flow in one use case at most. Returns (use cases,
        Claude's id -> the slug it is shown under, so programme parts can follow it)."""
        owner, use_cases, taken, slug_of = {}, [], set(), {}
        for u in _items(out["use_cases"]):
            name = str(u.get("name") or "Unnamed use case")
            flows = []
            for fid in _ids(u.get("flows")):
                if fid not in self.names:
                    self.problems.append(f"use case {name}: unknown flow ID {fid}")
                elif fid in owner:
                    self.problems.append(f"use case {name}: {self.names[fid]} is already in use case {owner[fid]}; a flow has one primary use case")
                elif fid in flows:
                    self.problems.append(f"use case {name}: {self.names[fid]} is listed twice")
                else:
                    flows.append(fid)
            if not flows:
                self.problems.append(f"use case {name} was dropped because none of its flows are in the facts")
                continue
            uid = _slug(u.get("id") or name, taken)
            slug_of.setdefault(str(u.get("id") or name), uid)
            slug_of.setdefault(uid, uid)
            for fid in flows:
                owner[fid] = name
            use_cases.append({
                "id": uid, "name": name, "summary": str(u.get("summary") or ""),
                "kind": _choice(u.get("kind"), KINDS, "journey"), "flows": flows,
                "story": self.statements(_section(u, "story"), f"{name}, story"),
                "how_it_works": self.statements(_section(u, "how_it_works"), f"{name}, how it works"),
                "watch": self.statements(_section(u, "watch"), f"{name}, watch"),
                "confidence": _choice(u.get("confidence"), CONFIDENCE, "guess"),
            })
        return use_cases, slug_of

    def flows(self, out, use_cases):
        """A purpose and role for every flow in the facts, in facts order. Returns (flows, not placed)."""
        uc_of = {fid: u["id"] for u in use_cases for fid in u["flows"]}
        given = {}
        for f in _items(out.get("flows")):
            if f.get("id") not in self.names:
                self.problems.append(f"flows: unknown flow ID {f.get('id')}")
            elif f["id"] not in given:
                given[f["id"]] = f
        flows = []
        for fid in self.flow_ids:
            f = given.get(fid)
            if f is None:
                self.problems.append(f"flows: no purpose given for {self.names[fid]}")
                f = {"purpose": "", "role": "unknown", "evidence": [], "confidence": "guess"}
            bad = [x for x in _ids(f.get("evidence")) if x not in self.evidence_ids]
            if bad:
                self.problems.append(f"flows: unknown evidence IDs {', '.join(map(str, bad[:5]))} for {self.names[fid]}")
            ev = [x for x in _ids(f.get("evidence")) if x in self.evidence_ids]
            conf = _choice(f.get("confidence"), CONFIDENCE, "guess")
            if not ev and f.get("purpose") and conf != "guess":
                self.problems.append(f"flows: the purpose of {self.names[fid]} cites no evidence in the facts, so it is shown as a guess")
            flows.append({"id": fid, "purpose": str(f.get("purpose") or ""), "role": _choice(f.get("role"), ROLES, "unknown"),
                          "use_case": uc_of.get(fid, ""), "evidence": ev, "confidence": conf if ev else "guess"})
        return flows, [fid for fid in self.flow_ids if fid not in uc_of]

    def edges(self, out):
        edges = []
        for e in _items(out.get("edges")):
            if e.get("id") in self.edge_ids and str(e.get("meaning") or "").strip():
                edges.append({"id": e["id"], "meaning": str(e["meaning"])})
            else:
                self.problems.append(f"edges: unknown edge ID {e.get('id')}")
        return edges

    def systems(self, out):
        systems = []
        for s in _items(out.get("systems")):
            if s.get("host") in self.facts["hosts"] and str(s.get("name") or "").strip():
                systems.append({"host": s["host"], "name": str(s.get("name") or ""), "confidence": _choice(s.get("confidence"), CONFIDENCE, "guess")})
            else:
                self.problems.append(f"systems: host {s.get('host')} is not a webhook host in the facts")
        return systems

    def org_summary(self, out):
        summary = out.get("org_summary") if isinstance(out.get("org_summary"), dict) else {}
        bad = [x for x in _ids(summary.get("evidence")) if x not in self.evidence_ids]
        if bad:
            self.problems.append(f"org summary: unknown evidence IDs {', '.join(map(str, bad[:5]))}")
        ev = [x for x in _ids(summary.get("evidence")) if x in self.evidence_ids]
        if not ev and summary.get("text") and summary.get("confidence") != "guess":
            self.problems.append("org summary: cites no evidence in the facts, so it is shown as a guess")
        return {"text": str(summary.get("text") or ""), "evidence": ev,
                "confidence": _choice(summary.get("confidence"), CONFIDENCE, "guess") if ev else "guess"}

    def programmes(self, out, use_cases, slug_of):
        """Group the validated use cases into programmes. An answer without programmes (from before
        they existed) gets one programme per use case; a use case left out of every programme gets
        its own, and that is reported."""
        by_id = {u["id"]: u for u in use_cases}
        if not isinstance(out.get("programmes"), list):
            return [wrap_use_case(u) for u in use_cases]
        owner, programmes, taken = {}, [], set()
        for p in _items(out["programmes"]):
            name = str(p.get("name") or "Unnamed programme")
            parts = []
            for pid in _keys(p.get("parts")):
                pid = slug_of.get(pid, pid)
                if pid not in by_id:
                    self.problems.append(f"programme {name}: unknown use case ID {pid}")
                elif pid in owner:
                    self.problems.append(f"programme {name}: use case {by_id[pid]['name']} is already in programme {owner[pid]}")
                elif pid not in parts:
                    parts.append(pid)
            if not parts:
                self.problems.append(f"programme {name} was dropped because none of its parts are use cases in the answer")
                continue
            for pid in parts:
                owner[pid] = name
            programmes.append({
                "id": _slug(p.get("id") or name, taken), "name": name, "summary": str(p.get("summary") or ""),
                "kind": _choice(p.get("kind"), KINDS, by_id[parts[0]]["kind"]), "parts": parts,
                "story": self.statements(_section(p, "story"), f"{name}, story"),
                "watch": self.statements(_section(p, "watch"), f"{name}, watch"),
                "confidence": _choice(p.get("confidence"), CONFIDENCE, "guess"),
            })
        for u in use_cases:
            if u["id"] not in owner:
                self.problems.append(f"use case {u['name']} is not in any programme, so it is shown as its own")
                programmes.append(wrap_use_case(u, {p["id"] for p in programmes}))
        return programmes


def wrap_use_case(u, taken=()):
    """A programme of one: the use case as its only part."""
    pid = u["id"] if u["id"] not in taken else _slug(u["id"], set(taken))
    return {"id": pid, "name": u["name"], "summary": u["summary"], "kind": u["kind"], "parts": [u["id"]],
            "story": [], "watch": [], "confidence": u["confidence"]}


COSMETIC = ("flows: no purpose given", "flows: the purpose of", "org summary: cites no evidence")


def _serious(problems):
    """Problems worth a second (paid) call: anything but a missing purpose or a claim shown as a guess."""
    return [p for p in problems if not p.startswith(COSMETIC)]


def run_programmes(facts, client=None, model=MODEL):
    """Call Claude, validate, and repair once if the answer has problems that matter.
    Returns (raw answer, validated, notes on what was dropped).

    Whichever answer places more flows (then has fewer problems) is kept, and if the repair call fails the first answer
    is kept, so a paid-for usable answer is never thrown away."""
    client = client or _client()
    raw = call_claude(facts, client, model=model)
    try:
        validated, problems = validate(raw, facts)
    except ProgrammeError as e:
        problems, validated = [str(e)], None
    try:
        return _repair_if_needed(facts, client, raw, validated, problems, model)
    except ProgrammeError as e:
        if getattr(e, "raw", None) is None:
            e.raw = raw            # so the caller can save the paid-for answer even when it is unusable
        raise


def _repair_if_needed(facts, client, raw, validated, problems, model=MODEL):
    if not _serious(problems):
        return raw, validated, problems
    raw2 = None
    try:
        raw2 = call_claude(facts, client, repair_errors=problems, previous=raw, model=model)
        validated2, problems2 = validate(raw2, facts)
    except ProgrammeError as e:
        if validated is None:
            e.raw = raw2 if raw2 is not None else raw
            raise
        return raw, validated, problems + [f"The repair call failed ({e}), so Claude's first answer is shown."]

    def score(v, probs):   # more flows placed first, then fewer problems that matter
        return (sum(len(u["flows"]) for u in v["use_cases"]), -len(_serious(probs)))
    if validated is not None and score(validated, problems) > score(validated2, problems2):
        return raw, validated, problems + ["The repair answer had more problems, so Claude's first answer is shown."]
    return raw2, validated2, problems2
