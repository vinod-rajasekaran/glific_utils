#!/usr/bin/env python3
"""Render flows.json + triggers.json into one self-contained HTML flow map.

Implements the spec in PROMPT.md. In short:
  scope      flows carrying the tag, every flow they enter, and flows active triggers start
  columns    When it starts (triggers) | Entry flows | Journey | Shared flows
  wires      solid = enter_flow (counted), dashed = contact field written by 1-2 flows
             and read in another flow's router operand
  cards      Calls, Sends, Routes, Sets, Counts, Moves, Logs, Alerts, Labels, Ticket,
             Starts, Feeds, Used by, Trigger, Note (rows kept under 25 words)
  below      shared resources, strip of other flows, missing flows, tagging gaps

Never prints header values, tokens, full URLs, message bodies or contact names.
No network access: this module only reads the data it is given.
"""
import html
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from string import Template
from urllib.parse import urlsplit

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

WEEKDAYS = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
MAP_CAP = 14          # flow cards on the map; the rest go to the strip
ROW_WORDS = 25        # word cap per card row
GENERIC_RESULT = {"", "result", "webhook", "response", "results"}
FIELD_IN_OPERAND = re.compile(r"fields\.([A-Za-z0-9_]+)")


# --------------------------------------------------------------------------- settings

@dataclass
class Settings:
    project: str = "Glific chatbot"
    tag: str = ""                       # empty: start from triggers and keywords instead
    tz: str = "Asia/Kolkata"            # "IST, UTC+5:30" or an IANA name
    today: date = field(default_factory=date.today)
    footer: str = ""
    notes: str = ""                     # context notes text (see README for the format)


def parse_tz(spec):
    """Return (tzinfo, label). Accepts 'IST, UTC+5:30', 'UTC+05:30' or 'Asia/Kolkata'."""
    spec = (spec or "UTC").strip()
    m = re.search(r"UTC\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", spec, re.I)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        offset = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)) * sign
        label = spec.split(",")[0].strip() if "," in spec else spec
        return timezone(offset), label
    if ZoneInfo and spec.upper() != "UTC":
        try:
            tz = ZoneInfo(spec)
            return tz, datetime.now(tz).tzname() or spec
        except Exception:
            pass
    return timezone.utc, "UTC"


# --------------------------------------------------------------------------- text helpers

def esc(value):
    """HTML-escape for text and attributes. Em dashes (banned on the page) become hyphens."""
    return html.escape(str(value).replace("\u2014", "-"), quote=True)


def typo(text):
    """Typographic apostrophes and quotes for visible text; no em dashes."""
    text = re.sub(r"(\w)'(\w)", "\\1\u2019\\2", str(text))
    text = re.sub(r'"([^"]*)"', "\u201c\\1\u201d", text)
    return text.replace("\u2014", ",")


def split_top(text, sep):
    """Split on sep, but not inside brackets."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and text.startswith(sep, i):
            parts.append(cur)
            cur, i = "", i + len(sep)
            continue
        cur += ch
        i += 1
    return parts + [cur]


def cap_words(text, limit=ROW_WORDS):
    """Keep rows under the word limit, cutting at clause or list boundaries where possible."""
    text = str(text)
    if len(text.split()) <= limit:
        return text
    for sep in ("; ", ". ", ", "):
        parts = split_top(text, sep)
        if len(parts) < 2:
            continue
        kept = []
        for part in parts:
            if len(" ".join(kept + [part]).split()) + 2 > limit:
                break
            kept.append(part)
        if kept:
            return sep.join(kept).rstrip(",;. ") + (", and more" if sep == ", " else f"{sep.strip()} And more" if sep == ". " else "; and more")
    return " ".join(text.split()[:limit]).rstrip(",;:") + " and more"


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def join(items, limit=6, last="and"):
    items = [str(i) for i in dict.fromkeys(items) if str(i)]
    extra = len(items) - limit
    if extra > 0:
        items = items[:limit] + [f"{extra} more"]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def names(items):
    """Groups and labels arrive as strings or as {name|label: ...} objects."""
    out = []
    for item in items or []:
        if isinstance(item, dict):
            item = item.get("name") or item.get("label")
        if item:
            out.append(str(item))
    return out


def times(n):
    return "" if n == 1 else (" twice" if n == 2 else f" {n} times")


def sentence(text):
    text = str(text).strip()
    return (text[0].upper() + text[1:]) if text else ""


# --------------------------------------------------------------------------- dates

def parse_utc(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_day(dt):
    return f"{dt.day} {dt:%b %Y}" if dt else ""


# --------------------------------------------------------------------------- per-flow graph

def webhook_desc(action):
    url = str(action.get("url") or "").strip()
    if "://" in url:
        parts = urlsplit(url)
        what = (parts.hostname or "unknown host") + (f":{parts.port}" if parts.port else "")
        tail = [p for p in parts.path.split("/") if p]
        # Show the last path segment only when it is a plain word, never a token-like string
        if tail and re.fullmatch(r"[A-Za-z][A-Za-z_-]{0,24}", tail[-1]):
            what += f" ({tail[-1]})"
    else:
        what = f"Glific function {url.split('?')[0] or 'unnamed'}"
    purpose = str(action.get("result_name") or "").strip()
    return what + (f" for {purpose}" if purpose.lower() not in GENERIC_RESULT else "")


def short_operand(op):
    op = str(op or "")
    m = FIELD_IN_OPERAND.search(op)
    if m:
        return m.group(1)
    m = re.search(r"results\.([A-Za-z0-9_]+)", op)
    if m:
        return "the webhook result" if m.group(1).lower() in GENERIC_RESULT else f"result {m.group(1)}"
    if "groups" in op:
        return "the contact's group"
    if "input" in op:
        return "the reply"
    return op.strip("@() ") or "a value"


class FlowGraph:
    """Nodes, parents and reachability for one flow."""

    def __init__(self, flow):
        self.nodes = [n for n in (flow.get("nodes") or []) if isinstance(n, dict)]
        self.by_uuid = {n.get("uuid"): n for n in self.nodes}
        self.parents = defaultdict(list)   # node uuid -> [(parent node, category name or None)]
        for n in self.nodes:
            cats = {c.get("exit_uuid"): c.get("name") for c in ((n.get("router") or {}).get("categories") or [])}
            for ex in n.get("exits") or []:
                dest = ex.get("destination_uuid")
                if dest:
                    self.parents[dest].append((n, cats.get(ex.get("uuid"))))
        self.reachable = self._walk()

    def _walk(self):
        if not self.nodes:
            return set()
        seen, stack = set(), [self.nodes[0].get("uuid")]
        while stack:
            u = stack.pop()
            if u in seen or u not in self.by_uuid:
                continue
            seen.add(u)
            stack += [ex.get("destination_uuid") for ex in self.by_uuid[u].get("exits") or [] if ex.get("destination_uuid")]
        return seen

    def actions(self):
        for n in self.nodes:
            for a in n.get("actions") or []:
                yield n, a

    def condition(self, node, depth=0):
        """The router branch that leads to this node, walking back through plain action nodes."""
        for parent, cat in self.parents.get(node.get("uuid"), []):
            if cat:
                kinds = {a.get("type") for a in parent.get("actions") or []}
                operand = short_operand((parent.get("router") or {}).get("operand"))
                if cat.lower() in ("success", "failure"):
                    what = "webhook call" if "call_webhook" in kinds else ("sheet read" if "link_google_sheet" in kinds else "step")
                    return (f"the {what}", "", "succeeds" if cat.lower() == "success" else "fails")
                if cat.lower() == "other":
                    return (operand, "", "matches nothing else")
                return (operand, "is", cat)
        ps = self.parents.get(node.get("uuid"), [])
        if len(ps) == 1 and depth < 6:
            return self.condition(ps[0][0], depth + 1)
        return None

    def fields_read(self):
        out = set()
        for n in self.nodes:
            out.update(FIELD_IN_OPERAND.findall(str((n.get("router") or {}).get("operand") or "")))
        return out


def summarise(g):
    """Everything a card needs, extracted from the definition."""
    s = defaultdict(list)
    s["waits"] = 0
    branches = defaultdict(list)   # operand -> categories, merged across routers
    for n in g.nodes:
        r = n.get("router") or {}
        operand = str(r.get("operand") or "")
        if r.get("wait"):
            s["waits"] += 1
        elif r.get("type") == "random":
            s["random"].append(len(r.get("categories") or []))
        elif operand and not operand.startswith("@child") and \
                not any(a.get("type") in ("call_webhook", "link_google_sheet", "enter_flow") for a in n.get("actions") or []):
            cats = [c.get("name") for c in r.get("categories") or [] if c.get("name") and c.get("name").lower() != "other"]
            if len(cats) >= 2 or (cats and "fields" in operand):
                branches[short_operand(operand)] += cats
    s["routes"] = [f"{op} ({join(cats, 3, 'or')})" for op, cats in branches.items()]
    for n, a in g.actions():
        kind = a.get("type") or "unknown"
        tpl = ((a.get("templating") or {}).get("template") or {}).get("name")
        if kind == "send_msg":
            if tpl:
                s["templates"].append("templates chosen at run time" if tpl.lower() == "expression" else f"template {tpl}")
            else:
                s["messages"].append(1)
        elif kind == "send_interactive_msg":
            s["interactive"].append(a.get("name") or "interactive message")
        elif kind == "send_broadcast":
            staff = len(a.get("contacts") or [])
            to = join(([plural(staff, "staff contact")] if staff else []) + names(a.get("groups")))
            s["alerts"].append(f"template {tpl} to {to or 'nobody set'}" if tpl else f"a message to {to or 'nobody set'}")
        elif kind in ("enter_flow", "start_session"):
            target = a.get("flow") or {}
            s["starts"].append((target.get("uuid"), target.get("name") or target.get("uuid") or "unnamed flow"))
        elif kind in ("add_contact_groups", "remove_contact_groups"):
            groups = ["all groups"] if a.get("all_groups") else names(a.get("groups"))
            s["moves"].append(("into" if kind.startswith("add") else "out of", tuple(groups), g.condition(n)))
        elif kind == "set_contact_field":
            key = (a.get("field") or {}).get("key") or (a.get("field") or {}).get("name")
            if key:
                s["counts" if re.search(r"\+\s*1\b", str(a.get("value"))) else "sets"].append(key)
        elif kind == "set_contact_name":
            s["sets"].append("name")
        elif kind == "set_contact_language":
            s["sets"].append("language")
        elif kind == "call_webhook":
            s["calls"].append(webhook_desc(a))
        elif kind == "link_google_sheet":
            tab = str(a.get("range") or "").split("!")[0]
            mode = "writes" if str(a.get("action_type") or "").upper() == "WRITE" else "reads"
            s["logs"].append(f"{mode} {a.get('name') or 'a sheet'}" + (f", {tab} tab" if tab else ""))
            s["sheets"].append(a.get("name") or "a sheet")
        elif kind == "add_input_labels":
            s["labels"] += names(a.get("labels"))
        elif kind == "open_ticket":
            topic = (a.get("topic") or {}).get("name") if isinstance(a.get("topic"), dict) else a.get("topic")
            who = "assigned to a staff member" if a.get("assignee") else "left unassigned"
            s["tickets"].append(f"opens a ticket on {topic or 'no topic'}, {who}")
        elif kind in ("set_run_result", "wait_for_time"):
            pass
        else:
            s["other"].append(kind)
    # Nodes no path reaches, and what they would have done
    lost = []
    for n in g.nodes:
        if n.get("uuid") in g.reachable:
            continue
        for a in n.get("actions") or []:
            tpl = ((a.get("templating") or {}).get("template") or {}).get("name")
            if a.get("type") == "send_broadcast":
                lost.append(f"a staff template ({tpl})" if tpl else "a staff message")
            elif a.get("type") == "send_msg":
                lost.append(f"template {tpl}" if tpl else "a message")
            elif a.get("type") == "call_webhook":
                lost.append("a webhook call")
    s["unreachable"] = len(g.nodes) - len(g.reachable)
    s["lost"] = list(dict.fromkeys(lost))
    return s


# --------------------------------------------------------------------------- model

class Model:
    def __init__(self, flows, triggers, st):
        self.st = st
        self.tz, self.tz_label = parse_tz(st.tz)
        self.flows = {f.get("uuid"): f for f in flows if f.get("uuid")}
        self.graphs = {u: FlowGraph(f) for u, f in self.flows.items()}
        self.sum = {u: summarise(g) for u, g in self.graphs.items()}
        self.findings = []
        self.triggers = triggers
        self._triggers()
        self._scope()
        self._links()
        self._layout()

    def name(self, u):
        return (self.flows.get(u) or {}).get("name") or u

    def tag_label(self, u):
        return (((self.flows.get(u) or {}).get("tag") or {}).get("label") or "").strip()

    def tagged(self, u):
        return bool(self.st.tag) and self.tag_label(u).lower() == self.st.tag.strip().lower()

    def _triggers(self):
        """Join on flow uuid. Active means isActive and the end date has not passed."""
        self.active_trig = defaultdict(list)
        self.earlier_trig = defaultdict(list)
        self.missing_trig = defaultdict(list)
        for t in self.triggers:
            fl = t.get("flow") or {}
            u = fl.get("uuid")
            end = parse_utc(t.get("endDate"))
            ended = bool(end and end.date() < self.st.today)
            if t.get("isActive") and ended:
                self.findings.append(f"Trigger {t.get('name')} is marked active but ended on {fmt_day(end)}, so it is treated as inactive.")
            active = bool(t.get("isActive")) and not ended
            if u not in self.flows:
                self.missing_trig[fl.get("name") or "a flow with no name"].append(t)
                continue
            (self.active_trig if active else self.earlier_trig)[u].append(t)
            if active and not (names(t.get("groups")) or names(t.get("waGroups"))):
                self.findings.append(f"Active trigger {t.get('name')} has no target group.")

    def _scope(self):
        if self.st.tag:
            seeds = [u for u in self.flows if self.tagged(u)]
        else:
            seeds = [u for u in self.flows if self.flows[u].get("keywords")]
        seeds += list(self.active_trig)
        scope, stack = set(), list(dict.fromkeys(seeds))
        self.missing_targets = defaultdict(set)
        while stack:
            u = stack.pop()
            if u in scope:
                continue
            scope.add(u)
            for v, vname in self.sum[u]["starts"]:
                if v in self.flows:
                    stack.append(v)
                else:
                    self.missing_targets[vname].add(u)
        self.scope = scope
        self.callers = defaultdict(Counter)   # v -> {caller u: number of enter_flow actions}
        for u in scope:
            for v, _ in self.sum[u]["starts"]:
                if v in scope and v != u:
                    self.callers[v][u] += 1

    def _links(self):
        writers = defaultdict(set)
        for u in self.flows:
            for f in self.sum[u]["sets"] + self.sum[u]["counts"]:
                writers[f].add(u)
        self.data_links = []          # (writer, reader, field)
        self.shared_fields = {}
        for v in self.scope:
            for f in sorted(self.graphs[v].fields_read()):
                w = writers.get(f, set()) - {v}
                if not w:
                    continue
                if len(writers[f]) <= 2:
                    self.data_links += [(u, v, f) for u in sorted(w) if u in self.scope]
                else:
                    self.shared_fields[f] = writers[f]

    def _layout(self):
        sc = self.scope

        def starts_any(u):
            return any(v in sc and v != u for v, _ in self.sum[u]["starts"])

        shared = [u for u in sc if len(self.callers[u]) >= 2]
        entry = [u for u in sc if not self.callers[u] and (self.active_trig.get(u) or (self.flows[u].get("keywords") and starts_any(u)))]
        journey = [u for u in sc if len(self.callers[u]) == 1]
        placed = set(shared) | set(entry) | set(journey)
        strip = [u for u in sc if u not in placed]

        def by_name(u):
            return self.name(u).lower()

        entry.sort(key=lambda u: (bool(self.active_trig.get(u)), by_name(u)))
        priority = entry + sorted(shared, key=lambda u: (-sum(self.callers[u].values()), by_name(u))) + \
            sorted(journey, key=lambda u: (-starts_any(u), by_name(u)))
        on_map = set(priority[:MAP_CAP])
        overflow = priority[MAP_CAP:]
        if overflow:
            self.findings.append(f"{plural(len(overflow), 'flow')} moved from the map to the strip to keep it readable: {join(map(self.name, overflow), 8)}.")

        self.row, self.col = {}, {}
        taken = defaultdict(set)

        def place(u, col, want):
            r = max(2, want)
            while r in taken[col]:
                r += 1
            taken[col].add(r)
            self.row[u], self.col[u] = r, col

        entry_on = [u for u in entry if u in on_map]
        for i, u in enumerate(entry_on):
            place(u, 2, 2 + i)
        queue, seen = list(entry_on), set(entry_on)
        while queue:  # breadth first, so chains read left to right and top to bottom
            u = queue.pop(0)
            for v, _ in self.sum[u]["starts"]:
                if v in on_map and v not in seen:
                    seen.add(v)
                    rows = [self.row[c] for c in self.callers[v] if c in self.row]
                    place(v, 4 if v in shared else 3, min(rows) if rows else 2)
                    queue.append(v)
        for u in sorted(on_map - set(self.row), key=by_name):   # reached only from flows off the map
            place(u, 4 if u in shared else 3, 2)

        # Trigger cards sit in column 1, in the row of their flow (or the next free row)
        self.trig_row = {}
        self.trigger_flows = entry_on + sorted((u for u in on_map if u not in entry_on and self.active_trig.get(u)),
                                               key=lambda u: self.row[u])
        for u in self.trigger_flows:
            r = self.row[u]
            while r in taken[1]:
                r += 1
            taken[1].add(r)
            self.trig_row[u] = r

        self.on_map = on_map
        self.entry = entry_on
        self.strip = sorted(strip, key=by_name) + overflow
        self.columns = {u: ("entry" if u in entry else "shared" if u in shared else "journey" if u in journey else "strip") for u in sc}

    def edges(self):
        out = []
        for u in self.trigger_flows:
            out.append([f"t-{u}" if self.active_trig.get(u) else f"k-{u}", f"f-{u}", "s"])
        for v, cs in self.callers.items():
            for u in cs:
                if u in self.on_map and v in self.on_map:
                    out.append([f"f-{u}", f"f-{v}", "s"])
        solid = {(a, b) for a, b, _ in out}
        for u, v, _ in self.data_links:
            pair = (f"f-{u}", f"f-{v}")
            if u in self.on_map and v in self.on_map and pair not in solid and pair[::-1] not in solid:
                solid.add(pair)
                out.append([*pair, "d"])
        return out


# --------------------------------------------------------------------------- trigger text

def trigger_days(t):
    """Weekday numbers from the structured days field (1 = Monday ... 7 = Sunday)."""
    return [d for d in (t.get("days") or []) if isinstance(d, int)]


def clock(tz, start, hour_utc=None):
    """'06:00 (00:30 UTC)' in the display zone, or just UTC when the zone is UTC."""
    base = start or datetime.now(timezone.utc)
    utc = base.replace(hour=hour_utc, minute=0) if hour_utc is not None else base
    local = utc.astimezone(tz)
    if local.utcoffset() == timedelta(0):
        return f"{utc:%H:%M} UTC"
    return f"{local:%H:%M} ({utc:%H:%M} UTC)"


def schedule_text(t, tz, findings):
    start = parse_utc(t.get("startAt"))
    at = clock(tz, start) if start else "a time that could not be read"
    freq = (t.get("frequency") or "").lower() if t.get("isRepeating") else "once"
    if freq == "daily":
        return f"Every day at {at}"
    if freq == "weekly":
        days = trigger_days(t)
        return f"Every {join([WEEKDAYS.get(d, str(d)) for d in days], 7) or 'week, day not set,'} at {at}"
    if freq == "monthly":
        return f"Every month on day {join(map(str, t.get('days') or []), 31) or 'not set'} at {at}"
    if freq == "hourly":
        hours = [h for h in (t.get("hours") or []) if isinstance(h, int) and 0 <= h < 24]
        return f"Every day at {join([clock(tz, start, h) for h in hours], 24) or 'hours not set'}"
    if start:
        return f"Once on {fmt_day(start.astimezone(tz))} at {at}"
    return "Once, at a time that could not be read"


def window_text(t, tz):
    if not t.get("isRepeating"):
        return ""
    start, end = parse_utc(t.get("startAt")), parse_utc(t.get("endDate"))
    if start and end:
        return f"{fmt_day(start.astimezone(tz))} to {fmt_day(end)}"
    return f"From {fmt_day(start.astimezone(tz))}, with no end date" if start else ""


def schedule_title(ts):
    if len(ts) > 1:
        return f"{len(ts)} schedules"
    t = ts[0]
    if not t.get("isRepeating"):
        return "One-off run"
    return f"{(t.get('frequency') or 'Repeating').capitalize()} schedule"


def earlier_runs(ts, tz):
    starts = [d for d in (parse_utc(t.get("startAt")) for t in ts) if d]
    ends = [d for d in ((parse_utc(t.get("endDate")) if t.get("isRepeating") else None) or parse_utc(t.get("startAt")) for t in ts) if d]
    one_off = sum(1 for t in ts if not t.get("isRepeating"))
    freq = Counter((t.get("frequency") or "repeating").lower() for t in ts if t.get("isRepeating"))
    kinds = join(([f"{one_off} one-off"] if one_off else []) + [f"{n} {k}" for k, n in freq.most_common()])
    span = ""
    if starts:
        a, b = min(starts).astimezone(tz), max(ends + starts).astimezone(tz)
        span = f" on {fmt_day(a)}" if fmt_day(a) == fmt_day(b) else f" between {fmt_day(a)} and {fmt_day(b)}"
    groups = join([g for t in ts for g in names(t.get("groups")) + names(t.get("waGroups"))], 5)
    text = f"{plural(len(ts), 'earlier trigger')}{span}: {kinds}."
    return text + (f" Groups: {groups}." if groups else "")


# --------------------------------------------------------------------------- cards

def row(label, text, cls=""):
    if not text:
        return ""
    return f'<div class="r"><span class="k {cls}">{esc(label)}</span><span>{esc(typo(cap_words(text)))}</span></div>'


def flow_rows(m, u):
    s, f = m.sum[u], m.flows[u]
    calls = join([f"{c}{times(n)}" for c, n in Counter(s["calls"]).items()], 4)
    sends = []
    if s["messages"]:
        sends.append(plural(len(s["messages"]), "message"))
    if s["interactive"]:
        sends.append(f"{plural(len(s['interactive']), 'interactive message')} ({join(s['interactive'], 3)})")
    if s["templates"]:
        sends.append(join(s["templates"], 3))
    moves = defaultdict(list)   # (direction, groups, subject, verb) -> values
    for direction, groups, cond in s["moves"]:
        subject, verb, value = cond or ("", "", "")
        moves[(direction, groups, subject, verb)].append(value)
    clauses = []
    for (d, groups, subject, verb), values in moves.items():
        values = [v for v in dict.fromkeys(values) if v]
        when = f" when {subject} {(verb + ' ') if verb else ''}{join(values, 3, 'or')}" if subject and values else ""
        clauses.append(f"{d} {join(groups, 4)}{when}")
    move_txt = "; ".join(clauses)
    starts = Counter(name for v, name in s["starts"] if v != u)
    used = m.callers.get(u) or Counter()
    used_txt = join([f"{m.name(c)}{times(n)}" for c, n in used.most_common()], 5)
    if used and sum(used.values()) > len(used):
        used_txt = f"Called {sum(used.values())} times: " + join([f"{n} in {m.name(c)}" for c, n in used.most_common()], 5)
    by_reader = defaultdict(list)
    for w, v, fld in m.data_links:
        if w == u:
            by_reader[v].append(fld)
    feeds = [f"{m.name(v)} reads {join(fs, 4)}" for v, fs in by_reader.items()]
    reads = [f"reads {fld} set by {m.name(w)}" for w, v, fld in m.data_links if v == u and w not in m.on_map]
    notes = []
    if not f.get("nodes"):
        notes.append("No definition was exported for this flow")
    elif s["lost"]:
        notes.append(f"Holds {join(s['lost'], 3)} that no path reaches, so it never runs")
    elif s["unreachable"]:
        notes.append(f"{plural(s['unreachable'], 'node')} that no path reaches")
    if s["other"]:
        notes.append("Has unrecognised steps: " + join([f"{k}{times(n)}" for k, n in Counter(s["other"]).items()], 4))
    if reads:
        notes.append(sentence(join(reads, 2)))
    trig = ""
    if m.active_trig.get(u) and u not in m.on_map:
        trig = "Active: " + "; ".join(schedule_text(t, m.tz, m.findings) for t in m.active_trig[u])
    elif u not in m.active_trig and m.earlier_trig.get(u):
        trig = "None active. " + earlier_runs(m.earlier_trig[u], m.tz)
    route_parts = []
    if s["waits"]:
        route_parts.append(f"Waits for a reply at {plural(s['waits'], 'point')}")
    if s["routes"]:
        route_parts.append(f"Branches on {join(s['routes'], 1)}")
    if s["random"]:
        route_parts.append(f"Picks one of {s['random'][0]} branches at random")
    routes = ". ".join(route_parts)
    return "".join([
        row("Calls", calls),
        row("Sends", sentence(join(sends, 3))),
        row("Routes", routes),
        row("Sets", join(s["sets"], 8)),
        row("Counts", join(s["counts"], 5)),
        row("Moves", sentence(f"contact {move_txt}") if move_txt else "", "mv"),
        row("Logs", sentence(join(s["logs"], 4))),
        row("Alerts", sentence(join(s["alerts"], 3)), "wn"),
        row("Labels", join(s["labels"], 5)),
        row("Ticket", sentence(join(s["tickets"], 2))),
        row("Starts", join([f"{n}{times(c)}" for n, c in starts.items()], 5)),
        row("Feeds", sentence("; ".join(feeds))),
        row("Used by", used_txt),
        row("Trigger", trig),
        row("Note", ". ".join(notes), "wn"),
    ])


def tag_pill(m, u):
    label = m.tag_label(u)
    if label and m.tagged(u):
        return f'<span class="tag">{esc(label)}</span>'
    if label:
        return f'<span class="tag no">Tag: {esc(label)}</span>'
    return '<span class="tag no">No tag</span>'


def flow_card(m, u, placed=True):
    cls = "card" if m.tagged(u) else "card untagged"
    attrs = f'data-id="f-{esc(u)}" tabindex="0" style="--r:{m.row[u]};--c:{m.col[u]}"' if placed else "data-static"
    return (f'<article class="{cls}" {attrs}><div class="ch"><h3>{esc(m.name(u))}</h3>{tag_pill(m, u)}</div>'
            f'{flow_rows(m, u)}</article>')


def trigger_card(m, u, findings):
    ts = m.active_trig[u]
    blocks = []
    for t in ts:
        groups = join(names(t.get("groups")) + names(t.get("waGroups")), 4)
        blocks.append(row("Runs", schedule_text(t, m.tz, findings)) + row("Group", groups) + row("Window", window_text(t, m.tz)))
    body = '<div class="sep"></div>'.join(blocks) + row("Starts", m.name(u))
    kw = m.flows[u].get("keywords") or []
    if kw:
        body += row("Keyword", f"Also starts when a contact sends {join(kw, 20, 'or')}")
    if m.earlier_trig.get(u):
        body += f'<details><summary>Earlier runs</summary><p>{esc(typo(earlier_runs(m.earlier_trig[u], m.tz)))}</p></details>'
    return (f'<article class="card trigger" data-id="t-{esc(u)}" tabindex="0" style="--r:{m.trig_row[u]};--c:1">'
            f'<div class="ch"><h3>{esc(schedule_title(ts))}</h3><span class="pill">Active</span></div>{body}</article>')


def keyword_card(m, u):
    kw = m.flows[u].get("keywords") or []
    runs = f"When a contact sends {join(kw, 30, 'or')}"
    return (f'<article class="card trigger" data-id="k-{esc(u)}" tabindex="0" style="--r:{m.trig_row[u]};--c:1">'
            f'<div class="ch"><h3>Keyword message</h3><span class="pill">Active</span></div>'
            f'{row("Runs", runs)}{row("Starts", m.name(u))}</article>')


# --------------------------------------------------------------------------- sections

def shared_resources(m):
    hosts, groups, sheets = defaultdict(set), defaultdict(set), defaultdict(set)
    for u in m.scope:
        s = m.sum[u]
        for c in s["calls"]:
            hosts[c.split(" for ")[0].split(" (")[0]].add(u)
        for _, gs, _ in s["moves"]:
            for g in gs:
                groups[g].add(u)
        for sh in s["sheets"]:
            sheets[sh].add(u)
    parts = []
    for label, d in (("webhook host", hosts), ("group", groups), ("sheet", sheets)):
        for k, us in sorted(d.items(), key=lambda x: (-len(x[1]), x[0])):
            if len(us) >= 2:
                parts.append(f"The {label} {k} is used by {join(sorted(map(m.name, us)), 5)}.")
    kw = [f"{k} ({m.name(u)})" for u in sorted(m.scope, key=m.name)
          if u not in m.entry or m.active_trig.get(u) for k in (m.flows[u].get("keywords") or [])]
    if kw:
        parts.append(f"Keywords that also start flows directly: {join(kw, 12)}.")
    if m.shared_fields:
        fs = [f"{f} ({plural(len(w), 'writer')})" for f, w in sorted(m.shared_fields.items())]
        parts.append(f"These contact fields are written by more than two flows and read by others, so no line is drawn for them: {join(fs, 8)}.")
    if not parts:
        return ""
    return f'<p class="note">{esc(typo(" ".join(parts)))}</p>'


def strip_section(m):
    cards = [flow_card(m, u, placed=False) for u in m.strip]
    # untagged flows outside scope that change groups the scope uses
    scope_groups = {g for u in m.scope for _, gs, _ in m.sum[u]["moves"] for g in gs}
    scope_groups |= {g for u in m.scope for t in m.active_trig.get(u, []) + m.earlier_trig.get(u, []) for g in names(t.get("groups"))}
    matter = [u for u in m.flows if u not in m.scope and not m.tagged(u)
              and any(set(gs) & scope_groups for _, gs, _ in m.sum[u]["moves"])]
    cards += [flow_card(m, u, placed=False) for u in sorted(matter, key=m.name)[:8]]
    rows_ = []
    if m.missing_trig:
        items = []
        for n, ts in sorted(m.missing_trig.items()):
            last = max((d for d in (parse_utc(t.get("startAt")) for t in ts) if d), default=None)
            items.append(f"{n} ({plural(len(ts), 'trigger')}{' up to ' + fmt_day(last) if last else ''})")
        rows_.append(row("Triggers", join(items, 6)))
    if m.missing_targets:
        rows_.append(row("Starts", join([f"{n} (entered by {join(sorted(map(m.name, us)), 3)})" for n, us in sorted(m.missing_targets.items())], 5)))
    if rows_:
        cards.append('<article class="card untagged" data-static><div class="ch"><h3>Named but not exported</h3>'
                     '<span class="tag no">Missing</span></div>' + "".join(rows_) + "</article>")
    if not cards:
        return ""
    intro = ("These flows have no start link to the map, were moved off the map to keep it readable, "
             "or sit outside the tag but change groups the map uses.")
    return f'<section class="sect"><h2>Other flows in the account</h2><p>{esc(typo(intro))}</p><div class="strip">{"".join(cards)}</div></section>'


def name_prefix(names_):
    for k in (2, 1):
        # re.split with a capture group keeps the separators: ['2025', '_', 'Pilot', '_', ...]
        pieces = [re.split(r"([_ ])", n) for n in names_]
        c = Counter("".join(p[:2 * k - 1]) for p in pieces if len(p) > 2 * k - 1)
        if c:
            p, n = c.most_common(1)[0]
            if n >= 2 and n * 2 >= len(names_):
                return p
    return ""


def tagging_gaps(m):
    parts = []
    untagged = sorted(m.name(u) for u in m.scope if not m.tagged(u))
    if untagged and m.st.tag:
        parts.append(f"{join(untagged, 10)} {'is' if len(untagged) == 1 else 'are'} in scope without the {m.st.tag} tag.")
    tagged_names = [m.name(u) for u in m.flows if m.tagged(u)]
    prefix = name_prefix(tagged_names)
    if prefix:
        outside = sorted(m.name(u) for u in m.flows if not m.tagged(u) and m.name(u).startswith(prefix))
        off = sorted(n for n in tagged_names if not n.startswith(prefix))
        if outside:
            verb = "shares" if len(outside) == 1 else "share"
            parts.append(f"Guess from names: {join(outside, 8)} {verb} the {prefix} prefix but {'lacks' if len(outside) == 1 else 'lack'} the tag. No links are drawn for this guess.")
        if off:
            parts.append(f"Guess from names: {join(off, 8)} carry the tag without the {prefix} prefix, so a search by name misses them.")
    if not parts:
        return ""
    return f'<section class="sect gaps"><h2>Tagging gaps</h2><p>{esc(typo(" ".join(parts)))}</p></section>'


def context_section(notes):
    """Context notes: 'journey Title: f:step | d:step | c:step' lines; other lines become paragraphs."""
    if not notes or not notes.strip():
        return ""
    journeys, paras = [], []
    for line in notes.splitlines():
        line = line.strip()
        mm = re.match(r"journey\b([^:]*):(.*)", line, re.I)
        if mm:
            steps = []
            for step in mm.group(2).split("|"):
                kind, sep, text = step.strip().partition(":")
                cls = kind.strip().lower() if sep and kind.strip().lower() in ("f", "d", "c") else ""
                if not cls:
                    cls, text = "c", step.strip()
                steps.append(f'<div class="step {cls}">{esc(typo(text.strip()))}</div>')
            title = mm.group(1).strip()
            heading = f"<h3>{esc(typo(title))}</h3>" if title else ""
            journeys.append(f'<div class="jrow">{heading}<div class="steps">{"".join(steps)}</div></div>')
        elif line:
            paras.append(f"<p>{esc(typo(line))}</p>")
    out = '<section class="sect" style="margin-top:20px"><h2 style="margin-bottom:14px">How it works today</h2>'
    if journeys:
        out += ('<div class="legend"><span><i class="sw t"></i>People in the field</span>'
                '<span><i class="sw s"></i>Data systems</span><span><i class="sw g"></i>Chatbot messages</span></div>' + "".join(journeys))
    if paras:
        out += f'<article class="card ctx"><div class="ch"><h3>Content and data</h3></div><div class="body">{"".join(paras)}</div></article>'
    return out + "</section>"


# --------------------------------------------------------------------------- checks

class _Balance(HTMLParser):
    VOID = {"meta", "link", "br", "img", "input", "hr", "source", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"unexpected </{tag}>")


def check_page(page, m, edges):
    problems = []
    b = _Balance()
    b.feed(page)
    if b.errors or b.stack:
        problems.append(f"HTML tags do not balance: {b.errors[:3]} open={b.stack[-3:]}")
    if "\u2014" in page:
        problems.append("page contains an em dash")
    ids = set(re.findall(r'data-id="([^"]+)"', page))
    bad = [e for e in edges if e[0] not in ids or e[1] not in ids]
    if bad:
        problems.append(f"wires without cards: {bad[:3]}")
    for a, b_, kind in edges:
        if kind == "s" and a.startswith("f-"):
            u, v = a[2:], b_[2:]
            if not any(t == v for t, _ in m.sum[u]["starts"]):
                problems.append(f"solid link {m.name(u)} to {m.name(v)} has no enter_flow action")
    return problems


def print_tables(m, out):
    print(f"\nScope: {len(m.scope)} flows ({'tag ' + m.st.tag if m.st.tag else 'from triggers and keywords'})", file=out)
    print(f"  {'column':8} {'map':4} {'tagged':6} {'called':>6} {'starts':>6}  flow", file=out)
    for u in sorted(m.scope, key=lambda u: (m.columns[u], m.name(u).lower())):
        print(f"  {m.columns[u]:8} {'yes' if u in m.on_map else 'no':4} {'yes' if m.tagged(u) else 'no':6} "
              f"{sum(m.callers[u].values()):>6} {len([1 for v, _ in m.sum[u]['starts'] if v in m.scope and v != u]):>6}  {m.name(u)}", file=out)
    print(f"\nActive triggers ({sum(map(len, m.active_trig.values()))}):", file=out)
    for u, ts in m.active_trig.items():
        for t in ts:
            print(f"  {m.name(u)} | {schedule_text(t, m.tz, [])} | {join(names(t.get('groups')))} | {window_text(t, m.tz)}", file=out)
    links = ", ".join(f"{m.name(a)} -> {m.name(b)} ({f})" for a, b, f in m.data_links) or "none"
    print(f"\nData links: {links}", file=out)


# --------------------------------------------------------------------------- page

def render_html(flows, triggers, settings=None, out=None):
    """Return (html, findings). Prints intermediate tables to `out` when given."""
    st = settings or Settings()
    m = Model(flows, triggers, st)
    findings = m.findings
    edges = m.edges()

    cards = [trigger_card(m, u, findings) if m.active_trig.get(u) else keyword_card(m, u) for u in m.trigger_flows]
    cards += [flow_card(m, u) for u in sorted(m.on_map, key=lambda u: (m.col[u], m.row[u]))]
    cols_used = {m.col[u] for u in m.on_map}
    cards += [f'<p class="empty" style="--r:2;--c:{c}">None</p>' for c in (3, 4) if c not in cols_used]

    for u in sorted(m.scope, key=m.name):
        if m.sum[u]["lost"]:
            findings.append(f"{m.name(u)} holds {join(m.sum[u]['lost'], 3)} that no path reaches.")
    for n, us in sorted(m.missing_targets.items()):
        findings.append(f"{n} is entered by {join(sorted(map(m.name, us)), 3)} but is not in the flows file.")
    for n, ts in sorted(m.missing_trig.items()):
        if any(t.get("isActive") for t in ts):
            findings.append(f"An active trigger starts {n}, which is not in the flows file.")
    unknown = Counter(k for u in m.scope for k in m.sum[u]["other"])
    if unknown:
        findings.append("Unrecognised step types: " + join([f"{k} ({n})" for k, n in unknown.items()]) + ".")

    tagged_n = sum(1 for u in m.flows if m.tagged(u))
    active_n = sum(map(len, m.active_trig.values()))
    start_from = f", starting from the {plural(tagged_n, 'flow')} tagged {st.tag}" if st.tag else ", starting from triggers and keywords"
    lede = (f"This page maps {plural(len(m.scope), 'flow')} of the {plural(len(m.flows), 'flow')} in the export{start_from}. "
            f"{plural(active_n, 'trigger')} {'is' if active_n == 1 else 'are'} active on {fmt_day(datetime.combine(st.today, datetime.min.time()))}. "
            f"Times are in {m.tz_label}, with UTC in brackets. Hover over or tab to a card to see what it connects to.")
    footer = " ".join(x for x in [st.footer.strip(), "Generated from flows.json and triggers.json by glific_utils."] if x)
    page = Template(PAGE).substitute(
        title=esc(f"{st.project} flow map"),
        h1=esc(typo(f"{st.project}: how the flows start and connect")),
        lede=esc(typo(lede)),
        tag_legend=esc(f"Flow tagged {st.tag}" if st.tag else "Tagged flow"),
        cards="".join(cards),
        notes=shared_resources(m),
        context=context_section(st.notes),
        strip=strip_section(m),
        gaps=tagging_gaps(m),
        footer=esc(typo(footer)),
        edges=json.dumps(edges).replace("</", "<\\/"),
    )
    if out:
        print_tables(m, out)
    problems = check_page(page, m, edges)
    if problems:
        raise ValueError("Page checks failed: " + "; ".join(problems))
    return page, list(dict.fromkeys(findings))


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>$title</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Bricolage+Grotesque:wght@500;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#F2F5F5; --surface:#FFFFFF; --ink:#15202B; --muted:#55616D; --line:#D5DCE0; --soft:#E8EDEF;
  --flow:#1B5A70; --flow-bg:#E4EFF3; --trig:#9A5A08; --trig-bg:#FBEFD9; --ok:#2B7A4B; --wire:#8593A0; --warn:#9B3B2E;
  --chat:#2B6B45; --chat-bg:#E2F1E7; --slate:#4A5663; --slate-bg:#E8ECEF;
  --head:"Bricolage Grotesque","Trebuchet MS",system-ui,sans-serif;
  --body:"Atkinson Hyperlegible","Segoe UI",system-ui,sans-serif;
  padding-top:env(safe-area-inset-top,0px); padding-bottom:env(safe-area-inset-bottom,0px);
  padding-left:env(safe-area-inset-left,0px); padding-right:env(safe-area-inset-right,0px);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#10171C; --surface:#18222A; --ink:#E7EDF1; --muted:#9AA7B3; --line:#2B3843; --soft:#222E37;
    --flow:#86C6DA; --flow-bg:#1B3441; --trig:#E6AC55; --trig-bg:#3A2D16; --ok:#6CC38D; --wire:#6F7F8D; --warn:#E58A7B;
    --chat:#7FCB9C; --chat-bg:#1B3325; --slate:#A9B6C2; --slate-bg:#222C34; color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#10171C; --surface:#18222A; --ink:#E7EDF1; --muted:#9AA7B3; --line:#2B3843; --soft:#222E37;
  --flow:#86C6DA; --flow-bg:#1B3441; --trig:#E6AC55; --trig-bg:#3A2D16; --ok:#6CC38D; --wire:#6F7F8D; --warn:#E58A7B;
  --chat:#7FCB9C; --chat-bg:#1B3325; --slate:#A9B6C2; --slate-bg:#222C34; color-scheme:dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.55}
.page{max-width:1400px;margin:0 auto;padding:40px 16px 28px}
h1{font-family:var(--head);font-weight:700;font-size:32px;line-height:1.15;margin:0 0 12px;max-width:30ch;overflow-wrap:anywhere}
h2{font-family:var(--head);font-weight:700;font-size:22px;line-height:1.25;margin:0}
h3{font-family:var(--head);font-weight:700;font-size:19px;line-height:1.25;margin:0}
.lede{max-width:75ch;color:var(--muted);margin:0 0 20px}
.legend{display:flex;flex-wrap:wrap;gap:10px 26px;font-size:14px;color:var(--muted);margin:0 0 26px;align-items:center}
.legend span{display:inline-flex;align-items:center;gap:8px}
.sw{width:22px;height:14px;border-radius:4px;border:1px solid var(--line);display:inline-block}
.sw.t{background:var(--trig-bg);border-color:var(--trig)}
.sw.f{background:var(--flow-bg);border-color:var(--flow)}
.sw.u{background:var(--surface);border:1px dashed var(--muted)}
.sw.s{background:var(--slate-bg);border-color:var(--slate)}
.sw.g{background:var(--chat-bg);border-color:var(--chat)}
.ln{width:30px;height:0;border-top:2px solid var(--wire);display:inline-block}
.ln.d{border-top-style:dashed}
.canvas{position:relative}
#wires{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:visible}
.wire{fill:none;stroke:var(--wire);stroke-width:1.7;transition:opacity .15s,stroke .15s}
.wire.data{stroke-dasharray:6 5}
.wire.dim{opacity:.12}
.wire.hot{stroke:var(--flow);stroke-width:2.6}
.grid{position:relative;z-index:1;display:grid;grid-template-columns:1fr;gap:18px}
.colhead{padding-bottom:6px;border-bottom:2px solid var(--ink);margin-top:14px}
.colhead p{margin:4px 0 0;font-size:13px;color:var(--muted);line-height:1.4}
.empty{color:var(--muted);font-size:14px;margin:0}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden;transition:opacity .15s,box-shadow .15s}
.card:focus-visible{outline:3px solid var(--flow);outline-offset:2px}
.card.dim{opacity:.4}
.card.on{box-shadow:0 0 0 2px var(--flow)}
.card.untagged{border-style:dashed;border-color:var(--muted)}
.ch{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;padding:11px 14px;background:var(--flow-bg);border-bottom:1px solid var(--line)}
.trigger .ch{background:var(--trig-bg)}
.ch h3{overflow-wrap:anywhere;min-width:0}
.tag,.pill{flex:none;font-size:12px;line-height:1;padding:5px 8px;border-radius:99px;background:var(--surface);white-space:nowrap;max-width:45%;overflow:hidden;text-overflow:ellipsis}
.tag{border:1px solid var(--flow);color:var(--flow)}
.tag.no{border-style:dashed;color:var(--muted);border-color:var(--muted)}
.pill{border:1px solid var(--ok);color:var(--ok)}
.r{display:grid;grid-template-columns:62px 1fr;gap:8px;padding:8px 14px;font-size:14px;line-height:1.45;border-top:1px solid var(--soft)}
.r span:last-child{overflow-wrap:anywhere;min-width:0}
.ch + .r{border-top:0}
.sep{border-top:2px solid var(--line)}
.k{font-weight:700;font-size:13px;color:var(--flow)}
.trigger .k{color:var(--trig)}
.k.mv{color:var(--trig)}
.k.wn{color:var(--warn)}
details{padding:8px 14px 11px;border-top:1px solid var(--soft);font-size:13.5px;color:var(--muted)}
summary{cursor:pointer;font-weight:700;color:var(--ink);font-size:13px}
summary:focus-visible{outline:3px solid var(--flow);outline-offset:2px}
details p{margin:6px 0 0}
.note{margin:18px 0 0;font-size:14px;color:var(--muted);max-width:95ch}
.sect{margin-top:44px}
.sect h2{margin-bottom:6px}
.sect>p{margin:0 0 16px;color:var(--muted);max-width:80ch}
.strip{display:grid;grid-template-columns:1fr;gap:18px;align-items:start}
.gaps p{margin:0 0 10px;max-width:85ch;color:var(--ink)}
.jrow{margin:0 0 22px}
.jrow h3{margin-bottom:10px}
.steps{display:flex;flex-wrap:wrap;gap:12px 26px}
.step{position:relative;width:118px;min-height:64px;padding:8px 9px;border-radius:8px;border:1px solid var(--line);font-size:13.5px;line-height:1.35;display:flex;align-items:center;justify-content:center;text-align:center}
.step:not(:last-child)::after{content:"";position:absolute;right:-17px;top:50%;width:9px;height:9px;border-top:2px solid var(--wire);border-right:2px solid var(--wire);transform:translateY(-50%) rotate(45deg)}
.step.f{background:var(--trig-bg);border-color:var(--trig)}
.step.d{background:var(--slate-bg);border-color:var(--slate)}
.step.c{background:var(--chat-bg);border-color:var(--chat)}
.ctx{max-width:760px}
.ctx .body{padding:8px 14px;font-size:14px}
.ctx .body p{margin:6px 0}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media (min-width:1100px){
  .grid{grid-template-columns:repeat(4,minmax(0,1fr));column-gap:58px;row-gap:20px;align-items:start}
  .grid>*{grid-row:var(--r);grid-column:var(--c)}
  .colhead{margin-top:0}
  .strip{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media (min-width:700px) and (max-width:1099px){
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));column-gap:20px;align-items:start}
  .colhead{grid-column:1/-1}
  .strip{grid-template-columns:repeat(2,minmax(0,1fr))}
}
</style>
</head>
<body>
<div class="page">
<header>
  <h1>$h1</h1>
  <p class="lede">$lede</p>
</header>
<main>
$context
<section class="sect" style="margin-top:20px">
<h2 style="margin-bottom:14px">Flows and triggers</h2>
<div class="legend" aria-label="Legend">
  <span><i class="sw t"></i>Trigger</span>
  <span><i class="sw f"></i>$tag_legend</span>
  <span><i class="sw u"></i>Flow without that tag</span>
  <span><i class="ln"></i>Starts the flow</span>
  <span><i class="ln d"></i>Hands over data through a contact field</span>
</div>
<div class="canvas" id="canvas">
<svg id="wires" aria-hidden="true">
  <defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>
</svg>
<div class="grid">
  <div class="colhead" style="--r:1;--c:1"><h2>When it starts</h2><p>Active triggers and keywords</p></div>
  <div class="colhead" style="--r:1;--c:2"><h2>Entry flows</h2><p>Where a contact or a schedule enters</p></div>
  <div class="colhead" style="--r:1;--c:3"><h2>Journey</h2><p>Flows that one other flow enters</p></div>
  <div class="colhead" style="--r:1;--c:4"><h2>Shared flows</h2><p>Entered by two or more flows</p></div>
  $cards
</div>
</div>
$notes
</section>
$strip
$gaps
</main>
<footer>$footer</footer>
</div>
<script>
(function(){
  var edges=$edges;
  var canvas=document.getElementById('canvas'),svg=document.getElementById('wires'),NS='http://www.w3.org/2000/svg';
  var cards={};
  canvas.querySelectorAll('.card[data-id]').forEach(function(c){cards[c.getAttribute('data-id')]=c;});
  function pos(n){var r=n.getBoundingClientRect(),c=canvas.getBoundingClientRect();return{l:r.left-c.left,r:r.right-c.left,t:r.top-c.top,b:r.bottom-c.top,cx:(r.left+r.right)/2-c.left};}
  function draw(){
    Array.prototype.slice.call(svg.querySelectorAll('.wire')).forEach(function(n){n.remove();});
    if(window.innerWidth<1100){return;}
    var out={},inn={};
    edges.forEach(function(e){if(!cards[e[0]]||!cards[e[1]])return;(out[e[0]]=out[e[0]]||[]).push(e);(inn[e[1]]=inn[e[1]]||[]).push(e);});
    Object.keys(out).forEach(function(k){out[k].sort(function(a,b){return pos(cards[a[1]]).t-pos(cards[b[1]]).t;});});
    Object.keys(inn).forEach(function(k){inn[k].sort(function(a,b){return pos(cards[a[0]]).t-pos(cards[b[0]]).t;});});
    edges.forEach(function(e){
      var A=cards[e[0]],B=cards[e[1]];if(!A||!B)return;
      var P=pos(A),Q=pos(B),d;
      if(Math.abs(P.cx-Q.cx)<40){
        var down=Q.t>P.t,k=out[e[0]].indexOf(e),x=P.cx+(k-(out[e[0]].length-1)/2)*14;
        d='M'+x+' '+(down?P.b:P.t)+' L'+x+' '+(down?Q.t-3:Q.b+3);
      }else{
        var fwd=Q.l>P.r,i=out[e[0]].indexOf(e),j=inn[e[1]].indexOf(e);
        var y1=P.t+32+Math.min(i,10)*14,y2=Q.t+32+Math.min(j,10)*14;
        var x1=fwd?P.r:P.l,x2=fwd?Q.l-3:Q.r+3,dx=(x2-x1)*0.5;
        d='M'+x1+' '+y1+' C'+(x1+dx)+' '+y1+' '+(x2-dx)+' '+y2+' '+x2+' '+y2;
      }
      var p=document.createElementNS(NS,'path');
      p.setAttribute('d',d);p.setAttribute('class','wire'+(e[2]==='d'?' data':''));
      p.setAttribute('marker-end','url(#ah)');p.setAttribute('data-from',e[0]);p.setAttribute('data-to',e[1]);
      svg.appendChild(p);
    });
  }
  function focusOn(id){
    var near={};near[id]=1;
    edges.forEach(function(e){if(e[0]===id)near[e[1]]=1;if(e[1]===id)near[e[0]]=1;});
    Object.keys(cards).forEach(function(k){cards[k].classList.toggle('dim',!near[k]);cards[k].classList.toggle('on',k===id);});
    svg.querySelectorAll('.wire').forEach(function(w){
      var hot=w.getAttribute('data-from')===id||w.getAttribute('data-to')===id;
      w.classList.toggle('hot',hot);w.classList.toggle('dim',!hot);
    });
  }
  function clear(){
    Object.keys(cards).forEach(function(k){cards[k].classList.remove('dim','on');});
    svg.querySelectorAll('.wire').forEach(function(w){w.classList.remove('hot','dim');});
  }
  Object.keys(cards).forEach(function(id){
    var c=cards[id];
    c.addEventListener('mouseenter',function(){focusOn(id);});
    c.addEventListener('mouseleave',clear);
    c.addEventListener('focus',function(){focusOn(id);});
    c.addEventListener('blur',clear);
  });
  if(window.ResizeObserver){new ResizeObserver(draw).observe(canvas);}
  window.addEventListener('resize',draw);
  window.addEventListener('load',draw);
  document.addEventListener('visibilitychange',function(){if(!document.hidden){draw();}});
  if(document.fonts&&document.fonts.ready){document.fonts.ready.then(draw);}
  canvas.addEventListener('toggle',draw,true);
  draw();
})();
</script>
</body>
</html>
"""
