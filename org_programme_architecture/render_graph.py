#!/usr/bin/env python3
"""Render flows.json + triggers.json into one self-contained HTML flow map.

The graph page. In short:
  scope      flows carrying the tag, every flow they enter, and flows active triggers start
  graph      triggers, settings, keywords, groups and flows as boxes, laid out left to right
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

from graph_layout import layout as graph_layout

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

WEEKDAYS = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
GRAPH_CAP = 30        # flow boxes on the graph layout
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
    scope_all: bool = False             # every flow in the export, not just the tag and what it reaches


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


# --------------------------------------------------------------------------- Glific settings

def setting_starts(org, flows):
    """{flow uuid: [(short label, sentence)]} for flows that Glific's organisation settings start.

    org is the settings.json content (see glific_get_settings.py); flows are matched on their
    numeric id, which is what the settings hold."""
    if not org:
        return {}
    by_id = {str(f.get("id")): f.get("uuid") for f in flows if f.get("id") and f.get("uuid")}
    ooo = org.get("outOfOffice") or {}
    regx = org.get("regxFlow") or {}
    found = [
        (ooo.get("defaultFlowId"), "Default flow", "Default flow: runs on any incoming message that matches no keyword"),
        (org.get("newcontactFlowId"), "New contact flow", "New contact flow: runs on the first message from a new contact"),
        (org.get("optinFlowId"), "Opt-in flow", "Opt-in flow: runs when a contact opts in"),
        (ooo.get("flowId") if ooo.get("enabled") else None, "Out-of-office flow",
         "Out-of-office flow: runs on messages that arrive outside working hours"),
        (regx.get("flowId"), "Regex flow", "Regex flow: runs on messages that match a pattern set in Glific"),
    ]
    out = defaultdict(list)
    for fid, short, text in found:
        if fid is not None and str(fid) in by_id:
            out[by_id[str(fid)]].append((short, text))
    return dict(out)


# --------------------------------------------------------------------------- model

class Model:
    def __init__(self, flows, triggers, st, org=None):
        self.st = st
        self.setting_starts = setting_starts(org, flows)
        self.tz, self.tz_label = parse_tz(st.tz)
        self.flows = {f.get("uuid"): f for f in flows if f.get("uuid")}
        self.graphs = {u: FlowGraph(f) for u, f in self.flows.items()}
        self.sum = {u: summarise(g) for u, g in self.graphs.items()}
        self.findings = []
        self.triggers = triggers
        self._triggers()
        self._scope()
        self._links()
        self._roles()
        self.no_start = []
        self.setting_flows = []
        self.group_nodes = {}
        self.linked_group = set()
        self._graph_map()

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
        self.missing_targets = defaultdict(set)
        if self.st.scope_all:
            self.scope = set(self.flows)
            self.linked_in = set()
            for u in self.flows:
                for v, vname in self.sum[u]["starts"]:
                    if v not in self.flows:
                        self.missing_targets[vname].add(u)
            self._callers()
            return
        if self.st.tag:
            seeds = [u for u in self.flows if self.tagged(u)]
        else:
            seeds = [u for u in self.flows if self.flows[u].get("keywords")]
        seeds += list(self.active_trig)
        scope, stack = set(), list(dict.fromkeys(seeds))
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
        # One step back: flows outside the tag that start a flow in scope. Only one step, and their
        # other starts are not followed, because callers of a shared flow can belong to other programmes.
        self.linked_in = {u for u in self.flows if u not in scope and any(v in scope for v, _ in self.sum[u]["starts"])}
        scope |= self.linked_in
        self.scope = scope
        self._callers()

    def _callers(self):
        scope = self.scope
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
        for v in sorted(self.scope, key=lambda u: (self.name(u).lower(), u)):
            for f in sorted(self.graphs[v].fields_read()):
                w = writers.get(f, set()) - {v}
                if not w:
                    continue
                if len(writers[f]) <= 2:
                    self.data_links += [(u, v, f) for u in sorted(w) if u in self.scope]
                else:
                    self.shared_fields[f] = writers[f]

    def _roles(self):
        """The role of each flow in scope, for the intermediate table: entry, journey, shared or strip."""
        sc = self.scope
        starts_any = lambda u: any(v in sc and v != u for v, _ in self.sum[u]["starts"])
        self.columns = {}
        for u in sc:
            if len(self.callers[u]) >= 2:
                self.columns[u] = "shared"
            elif len(self.callers[u]) == 1:
                self.columns[u] = "journey"
            elif self.active_trig.get(u) or (self.flows[u].get("keywords") and starts_any(u)):
                self.columns[u] = "entry"
            else:
                self.columns[u] = "strip"

    def _graph_map(self):
        """The graph has room for more than the card grid: every flow in scope that starts, is
        started, hands over data, or has a trigger or keyword. A flow on it that nothing in the
        export starts gets a 'No start found' box in front of it."""
        sc = self.scope
        linked = set()
        for u in sc:
            for v, _ in self.sum[u]["starts"]:
                if v in sc and v != u:
                    linked |= {u, v}
        for u, v, _ in self.data_links:
            if u in sc and v in sc:
                linked |= {u, v}
        linked |= {u for u in sc if self.active_trig.get(u) or self.flows[u].get("keywords")}
        by_name = lambda u: self.name(u).lower()
        order = sorted(linked, key=lambda u: (-len(self.callers[u]) - sum(1 for v, _ in self.sum[u]["starts"] if v in sc), by_name(u)))
        on = set(order[:GRAPH_CAP])
        overflow = sorted(order[GRAPH_CAP:], key=by_name)
        if overflow:
            self.findings.append(f"{plural(len(overflow), 'flow')} moved from the graph to the strip to keep it readable: {join(map(self.name, overflow), 8)}.")
        self.strip = sorted((u for u in sc if u not in on and u not in overflow), key=by_name) + overflow
        self.graph_view(on, add_fillers=True)
        self.strip = [u for u in self.strip if u not in self.on_map]

    def graph_view(self, flow_ids, add_fillers=False, no_starts=frozenset()):
        """Put exactly these flows on the graph and work out their trigger, keyword, no-start and
        group boxes. With add_fillers, flows outside the set that add contacts to a group a
        schedule on the graph sends to are added too. Flows in no_starts (faded neighbours) get
        no start boxes and do not pull their schedules' groups onto the graph."""
        on = set(flow_ids)
        by_name = lambda u: self.name(u).lower()
        self.on_map = on
        # Groups: a group that an active trigger on the graph sends to gets its own box, when some
        # flow adds contacts to it or removes them. Flows outside the scope that add contacts to it
        # join the graph, since they decide who the schedule reaches.
        targets = defaultdict(list)
        for u in sorted(on - set(no_starts), key=by_name):
            for t in self.active_trig.get(u, []):
                for gname in names(t.get("groups")):
                    targets[gname].append(u)
        self.linked_group = set()
        movers = defaultdict(lambda: {"into": [], "out of": []})
        for u in sorted(self.flows, key=by_name):
            for direction, gs, _ in self.sum[u]["moves"]:
                for gname in gs:
                    if gname not in targets:
                        continue
                    if u not in on:
                        if not add_fillers or direction != "into" or len(on) >= GRAPH_CAP:
                            continue
                        on.add(u)
                        self.linked_group.add(u)
                        self.scope.add(u)
                        self.columns[u] = "group"
                    if u not in movers[gname][direction]:
                        movers[gname][direction].append(u)
        self.group_nodes = {gname: {"adds": movers[gname]["into"], "removes": movers[gname]["out of"], "triggers": targets[gname]}
                            for gname in sorted(movers)}

        called = {u for u in on if any(c in on for c in self.callers[u])}
        # a keyword box only where the keyword is how the flow starts; otherwise its card lists the keywords
        own = on - set(no_starts)
        self.trigger_flows = sorted((u for u in own if self.active_trig.get(u) or (self.flows[u].get("keywords") and u not in called)),
                                    key=by_name)
        # Flows that Glific's organisation settings start get a "Glific setting" box
        self.setting_flows = sorted((u for u in own if u in self.setting_starts), key=by_name)
        # "No start found" only when nothing in scope starts the flow, not just nothing on this graph
        self.no_start = sorted((u for u in own if not self.callers[u] and u not in self.trigger_flows
                                and u not in self.setting_starts), key=by_name)
        self.entry = [u for u in self.trigger_flows if u not in called]

    def edges(self):
        out = []
        for u in self.trigger_flows:
            out.append([f"t-{u}" if self.active_trig.get(u) else f"k-{u}", f"f-{u}", "s"])
        for u in self.setting_flows:
            out.append([f"s-{u}", f"f-{u}", "s"])
        for u in self.no_start:
            out.append([f"x-{u}", f"f-{u}", "s"])
        for i, (gname, info) in enumerate(self.group_nodes.items()):
            gid = f"g-{i}"
            out += [[f"f-{u}", gid, "ga"] for u in info["adds"]]
            out += [[f"f-{u}", gid, "gr"] for u in info["removes"] if u not in info["adds"]]
            out += [[gid, f"t-{u}", "gt"] for u in info["triggers"]]
        key = lambda u: (self.name(u).lower(), u)
        for v in sorted(self.callers, key=key):   # sorted, so the layout is the same on every run
            for u in sorted(self.callers[v], key=key):
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
    used_txt = join([f"{m.name(c)}{times(n)}" for c, n in sorted(used.items(), key=lambda cn: (-cn[1], m.name(cn[0]).lower()))], 5)
    if used and sum(used.values()) > len(used):
        used_txt = f"Called {sum(used.values())} times: " + join([f"{n} in {m.name(c)}" for c, n in sorted(used.items(), key=lambda cn: (-cn[1], m.name(cn[0]).lower()))], 5)
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
        row("Setting", "; ".join(text for _, text in m.setting_starts.get(u, []))),
        row("Note", ". ".join(notes), "wn"),
    ])


def tag_pill(m, u):
    label = m.tag_label(u)
    if label and m.tagged(u):
        return f'<span class="tag">{esc(label)}</span>'
    if label:
        return f'<span class="tag no">Tag: {esc(label)}</span>'
    return '<span class="tag no">No tag</span>'


def flow_card(m, u):
    cls = "card" if m.tagged(u) else "card untagged"
    attrs = "data-static"
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
    return (f'<article class="card trigger" data-static>'
            f'<div class="ch"><h3>{esc(schedule_title(ts))}</h3><span class="pill">Active</span></div>{body}</article>')


def keyword_card(m, u):
    kw = m.flows[u].get("keywords") or []
    runs = f"When a contact sends {join(kw, 30, 'or')}"
    return (f'<article class="card trigger" data-static>'
            f'<div class="ch"><h3>Keyword message</h3><span class="pill">Active</span></div>'
            f'{row("Runs", runs)}{row("Starts", m.name(u))}</article>')


# --------------------------------------------------------------------------- sections

def _used_by(m, us, limit=5):
    names_ = sorted(map(m.name, us), key=str.lower)
    return join(names_, limit)


def _table(caption, rows, heads):
    body = "".join("<tr>" + "".join(f"<td>{esc(typo(c))}</td>" for c in r) + "</tr>" for r in rows)
    head = "".join(f"<th>{esc(h)}</th>" for h in heads)
    return (f'<details class="tbl"><summary>{esc(caption)} ({len(rows)})</summary>'
            f'<div class="tblwrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></details>')


def shared_resources(m):
    """Webhook hosts, groups and sheets used by two or more flows, extra keywords and widely written
    fields, as one collapsed table."""
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
    rows = []
    for label, d in (("Webhook", hosts), ("Group", groups), ("Sheet", sheets)):
        for k, us in sorted(d.items(), key=lambda x: (-len(x[1]), x[0])):
            if len(us) >= 2:
                rows.append((label, k, _used_by(m, us)))
    for u in sorted(m.scope, key=m.name):
        kw = m.flows[u].get("keywords") or []
        if kw and (u not in m.entry or m.active_trig.get(u)):
            rows.append(("Keywords", join(kw, 6, "or"), m.name(u)))
    for f, w in sorted(m.shared_fields.items()):
        rows.append(("Field", f, f"written by {plural(len(w), 'flow')}: {_used_by(m, w, 3)}"))
    if not rows:
        return ""
    return _table("Shared across flows", rows, ("Kind", "Name", "Used by"))


def strip_section(m):
    """Flows in scope that are not on the graph, untagged flows that change groups the graph uses,
    and flows named in triggers or starts but missing from the export: one row each."""
    def what(u):
        chips = [c for c, _ in node_chips(m, u)]
        return join(chips, 6) or "nothing that leaves the bot"

    rows = [(m.name(u), m.tag_label(u) or "No tag", what(u), "No link to the graph") for u in m.strip]
    scope_groups = {g for u in m.scope for _, gs, _ in m.sum[u]["moves"] for g in gs}
    scope_groups |= {g for u in m.scope for t in m.active_trig.get(u, []) + m.earlier_trig.get(u, []) for g in names(t.get("groups"))}
    matter = [u for u in m.flows if u not in m.scope and not m.tagged(u)
              and any(set(gs) & scope_groups for _, gs, _ in m.sum[u]["moves"])]
    rows += [(m.name(u), m.tag_label(u) or "No tag", what(u), "Changes groups the graph uses") for u in sorted(matter, key=m.name)]
    for n, ts in sorted(m.missing_trig.items()):
        rows.append((n, "", f"{plural(len(ts), 'trigger')}", "Named in triggers, not in the export"))
    for n, us in sorted(m.missing_targets.items()):
        rows.append((n, "", f"entered by {join(sorted(map(m.name, us)), 3)}", "Named in a start, not in the export"))
    if not rows:
        return ""
    return f'<section class="sect">{_table("Other flows in the account", rows, ("Flow", "Tag", "What it does", "Why it is listed"))}</section>'


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
    linked = sorted(m.name(u) for u in m.linked_in)
    if linked and m.st.tag:
        parts.append(f"{join(linked, 10)} {'starts' if len(linked) == 1 else 'start'} a flow on the map without the {m.st.tag} tag, "
                     f"so {'it was' if len(linked) == 1 else 'they were'} added. Check whether the tag was missed; "
                     f"{'its' if len(linked) == 1 else 'their'} starts of flows outside the map are not drawn.")
    via_group = sorted(m.name(u) for u in m.linked_group if not m.tagged(u))
    if via_group and m.st.tag:
        parts.append(f"{join(via_group, 10)} {'adds' if len(via_group) == 1 else 'add'} contacts to a group that a schedule on the map sends to, "
                     f"so {'it decides' if len(via_group) == 1 else 'they decide'} who that schedule reaches; check whether the {m.st.tag} tag was missed.")
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


# --------------------------------------------------------------------------- graph layout

NODE_W, NODE_H, TRIG_W, TRIG_H, GROUP_W, GROUP_H = 200, 70, 200, 52, 170, 52


def wrap(text, width, lines=2):
    """Split text into at most `lines` lines of about `width` characters, with an ellipsis when cut."""
    words, out, cur = re.split(r"(?<=[ _])", text), [], ""
    for w in words:
        if len(cur) + len(w) > width and cur:
            out.append(cur.rstrip())
            cur = ""
        while len(w) > width:
            out.append(w[:width])
            w = w[width:]
        cur += w
    if cur:
        out.append(cur.rstrip())
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][:width - 1].rstrip() + "\u2026"
    return out


def node_chips(m, u):
    s = m.sum[u]
    chips = []
    if s["calls"]:
        chips.append(("webhook", ""))
    n = len(s["messages"]) + len(s["templates"]) + len(s["interactive"])
    if n:
        chips.append((f"{n} send" + ("" if n == 1 else "s"), ""))
    if s["waits"]:
        chips.append((f"{s['waits']} wait" + ("" if s["waits"] == 1 else "s"), ""))
    if s["moves"]:
        chips.append(("moves", "mv"))
    if s["alerts"]:
        chips.append(("alerts", "wn"))
    if s["logs"]:
        chips.append(("sheet", ""))
    if s["lost"]:
        chips.append(("unreachable step", "wn"))
    out, used = [], 0
    for text, cls in chips:   # fit about 34 characters
        if used + len(text) > 34:
            break
        out.append((text, cls))
        used += len(text) + 3
    return out


def svg_path(pts):
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(y1 - y2) < 0.5:
            d += f" L{x2:.1f} {y2:.1f}"
        else:
            dx = (x2 - x1) / 2
            d += f" C{x1 + dx:.1f} {y1:.1f} {x2 - dx:.1f} {y2:.1f} {x2:.1f} {y2:.1f}"
    return d


def edge_label_at(pts):
    """A point in the middle of the edge, in its longest stretch, and how wide that stretch is."""
    best = max(zip(pts, pts[1:]), key=lambda p: p[1][0] - p[0][0])
    (x1, y1), (x2, y2) = best
    return (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1


def names_of(m, us):
    return join([m.name(u) for u in us], 6)


def graph_section(m, edges, findings):
    """The map drawn as a graph: small nodes, edges laid out left to right, details on click."""
    svg, tpls = graph_svg(m, edges, findings)
    html_ = ('<p class="ghint">Each box is a flow, and time runs left to right. Solid arrows start a flow, '
             'dashed arrows hand over data through a contact field. Select a box to read what it does.</p>'
             f'<div class="gscroll">{svg}</div>'
             '<aside id="panel" class="panel" aria-live="polite" hidden><button type="button" class="close" aria-label="Close">\u00d7</button>'
             '<div id="panel-body"></div></aside>' + "".join(tpls))
    return html_, GRAPH_JS


def graph_svg(m, edges, findings, ns="", faded=frozenset(), part_of=None):
    """The graph as an SVG string plus one <template> per box holding its full card. Every id in
    both is prefixed with ns, so several graphs can share a page. Flows in faded are drawn faded.
    part_of maps a flow uuid to a part number (1 to 6); the box gets a coloured stripe for its part."""
    sizes, kinds = {}, {}
    def size(n):
        if n[0] in "tkxs":
            return TRIG_W, TRIG_H
        if n[0] == "g":
            return GROUP_W, GROUP_H
        return NODE_W, NODE_H + (0 if m.tagged(n[2:]) else 16)   # room for the tag line
    for a, b, k in edges:
        sizes[a], sizes[b] = size(a), size(b)
        kinds[(a, b)] = k
    for u in sorted(m.on_map, key=lambda u: (m.name(u).lower(), u)):
        sizes.setdefault(f"f-{u}", size(f"f-{u}"))
    groups = list(m.group_nodes.items())
    # Edges into a group close loops in time (a flow adds contacts to the group its own schedule
    # sends to). Groups go in the first column, as the pools schedules draw from, and the edges
    # that fill them run back to that column.
    soft = {(a, b) for a, b, k in edges if k in ("ga", "gr")}
    flows_only = {n: sz for n, sz in sizes.items() if n.startswith("f-")}
    first = graph_layout(flows_only, [(a, b) for a, b, _ in edges if a in flows_only and b in flows_only])
    # Columns: groups (if any), then one "when it starts" column holding every trigger, keyword,
    # setting and no-start box, then the flows. One column for all starts, so the schedules line up.
    shift = 2 if groups else 1
    fixed = {n: L + shift for n, L in first.layer.items()}
    for a, b, _ in edges:
        if a[0] in "tkxs":
            fixed[a] = shift - 1
    for i in range(len(groups)):
        fixed[f"g-{i}"] = shift - 2
    g = graph_layout(sizes, [(a, b) for a, b, _ in edges], fixed, soft=soft)

    fields = defaultdict(list)
    for u, v, f in m.data_links:
        fields[(f"f-{u}", f"f-{v}")].append(f)

    parts = []
    for a, b, k in edges:
        pts = g.paths.get((a, b))
        if not pts:
            continue
        if (a, b) in g.reversed:
            (ax, ay), (bx, by) = g.pos[a], g.pos[b]
            (aw, ah), (bw, bh) = sizes[a], sizes[b]
            if bx + bw < ax:   # leave by the left side, arrive from below
                x1, y1, x2, y2 = ax, ay + ah / 2, bx + bw / 2, by + bh + 3
                c1, c2 = (x1 - 50, y1), (x2, y2 + 40)
            else:              # same column: loop below both
                x1, y1, x2, y2 = ax + aw / 2, ay + ah, bx + bw / 2, by + bh + 3
                c1, c2 = (x1, y1 + 50), (x2, y2 + 50)
            d = f"M{x1:.1f} {y1:.1f} C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {x2:.1f} {y2:.1f}"
            mid = (0.125 * x1 + 0.375 * c1[0] + 0.375 * c2[0] + 0.125 * x2, 0.125 * y1 + 0.375 * c1[1] + 0.375 * c2[1] + 0.125 * y2)
        else:
            pts = pts[:-1] + [(pts[-1][0] - 3, pts[-1][1])]
            d = svg_path(pts)
        if k == "d":
            fs = sorted(set(fields[(a, b)]))
            label, full = (join(fs[:2], 2) + (f" +{len(fs) - 2}" if len(fs) > 2 else "")), "Hands over " + join(fs, 20)
        elif k in ("ga", "gr", "gt"):
            gname = groups[int((b if k != "gt" else a)[2:])][0]
            if k == "gt":
                label, full = "", f"Schedule sends to {gname} and starts {m.name(b[2:])}"
            else:
                verb = "adds contacts to" if k == "ga" else "removes contacts from"
                label, full = ("adds" if k == "ga" else "removes"), f"{m.name(a[2:])} {verb} {gname}"
        elif a.startswith("f-"):
            n = m.callers[b[2:]][a[2:]]
            label, full = (f"\u00d7{n}" if n > 1 else ""), f"{m.name(a[2:])} starts {m.name(b[2:])}" + (f" from {n} places" if n > 1 else "")
        else:
            label, full = "", f"Starts {m.name(b[2:])}"
        ecls = {"d": " data", "ga": " grp", "gr": " grp rm", "gt": " grp"}.get(k, "") + (" back" if (a, b) in g.reversed else "")
        parts.append(f'<g class="edge{ecls}" data-from="{esc(ns + a)}" data-to="{esc(ns + b)}">'
                     f'<title>{esc(typo(full))}</title><path d="{d}" marker-end="url(#{ns}gah)"/>')
        if label:
            if (a, b) in g.reversed:
                lx, ly, room = mid[0], mid[1] + 4, 200
            else:
                lx, ly, room = edge_label_at(pts)
            fit = max(0, int((room - 8) / 6.2))   # about 6.2px a character at 11.5px
            if len(label) > fit:
                label = label[:fit - 1].rstrip(" ,") + "\u2026" if fit >= 6 else ""
        if label:
            parts.append(f'<text class="elabel" x="{lx:.1f}" y="{ly - 5:.1f}" text-anchor="middle">{esc(label)}</text>')
        parts.append("</g>")

    tpls = []
    for n, (x, y) in g.pos.items():
        w, h = sizes[n]
        u = n[2:]
        if n.startswith("f-"):
            outside = bool(m.st.tag) and not m.tagged(u)
            cls = "node flow" + (" untagged" if outside else "")
            lines = wrap(m.name(u), 24)
            ty = y + (24 if len(lines) == 2 else 30)
            txt = "".join(f'<text class="nname" x="{x + 12:.1f}" y="{ty + i * 17:.1f}">{esc(t)}</text>' for i, t in enumerate(lines))
            if not m.tagged(u):   # say which tag it has instead, since this is where tags get missed
                tl = m.tag_label(u)
                tag_line = f"Tag: {tl}" if tl else "No tag"
                txt += f'<text class="ntag{"" if outside else " plain"}" x="{x + 12:.1f}" y="{y + h - 29:.1f}">{esc(wrap(tag_line, 30, 1)[0])}</text>'
            chips = node_chips(m, u)
            spans = '<tspan class="sep"> \u00b7 </tspan>'.join(f'<tspan class="{c}">{esc(t)}</tspan>' for t, c in chips)
            txt += f'<text class="nmeta" x="{x + 12:.1f}" y="{y + h - 11:.1f}">{spans}</text>'
            card = flow_card(m, u)
            label = m.name(u)
        elif n.startswith("g-"):
            gname, info = groups[int(u)]
            cls = "node grp"
            sched = len(info["triggers"])
            txt = (f'<text class="tname" x="{x + 12:.1f}" y="{y + 21:.1f}">{esc(wrap(gname, 19, 1)[0])}</text>'
                   f'<text class="tmeta" x="{x + 12:.1f}" y="{y + 40:.1f}">Group, {plural(sched, "schedule")}</text>')
            card = (f'<article class="card" data-static><div class="ch"><h3>{esc(gname)}</h3><span class="tag no">Group</span></div>'
                    + row("Added by", names_of(m, info["adds"]) or "No flow on the graph")
                    + (row("Removed by", names_of(m, info["removes"]), "mv") if info["removes"] else "")
                    + row("Schedules", "Active triggers that send to this group start " + names_of(m, info["triggers"]))
                    + "</article>")
            label = f"Group {gname}"
        elif n.startswith("s-"):
            cls = "node setting"
            shorts = [x[0] for x in m.setting_starts.get(u, [])]
            txt = (f'<text class="tname" x="{x + 12:.1f}" y="{y + 21:.1f}">Glific setting</text>'
                   f'<text class="tmeta" x="{x + 12:.1f}" y="{y + 40:.1f}">{esc(wrap(join(shorts, 2), 28, 1)[0])}</text>')
            card = ('<article class="card" data-static><div class="ch"><h3>Glific setting</h3></div>'
                    + row("Starts", m.name(u))
                    + "".join(row("Runs", text) for _, text in m.setting_starts.get(u, []))
                    + row("Note", "Set in Glific under Settings, not by a trigger or keyword, so it does not appear in the trigger list.")
                    + "</article>")
            label = f"Glific setting that starts {m.name(u)}"
        elif n.startswith("x-"):
            cls = "node nostart"
            txt = (f'<text class="tname" x="{x + 12:.1f}" y="{y + 21:.1f}">No start found</text>'
                   f'<text class="tmeta" x="{x + 12:.1f}" y="{y + 40:.1f}">No trigger, keyword or flow</text>')
            card = ('<article class="card untagged" data-static><div class="ch"><h3>No start found</h3></div>'
                    + row("Starts", m.name(u))
                    + row("Note", "No trigger, keyword or flow in the export starts this flow. It may be the opt-in or "
                                  "opt-out flow in Glific settings, or started by hand or through the API.")
                    + "</article>")
            label = f"No start found for {m.name(u)}"
        else:
            cls = "node trig"
            if n.startswith("t-"):
                ts = m.active_trig[u]
                line1 = re.sub(r"\s*\([^)]*UTC\)", "", schedule_text(ts[0], m.tz, [])) + (f" +{len(ts) - 1}" if len(ts) > 1 else "")
                line2 = "To " + (join(names(ts[0].get("groups")) + names(ts[0].get("waGroups")), 2) or "no group")
                card = trigger_card(m, u, findings)
            else:
                kw = m.flows[u].get("keywords") or []
                line1 = "Keyword"
                line2 = join(kw, 3, "or")
                card = keyword_card(m, u)
            if len(line1) > 23:
                line1 = line1.replace(" at ", " ")
            line1, line2 = wrap(typo(line1), 23, 1)[0], wrap(typo(line2), 28, 1)[0]
            txt = (f'<text class="tname" x="{x + 12:.1f}" y="{y + 21:.1f}">{esc(line1)}</text>'
                   f'<text class="tmeta" x="{x + 12:.1f}" y="{y + 40:.1f}">{esc(line2)}</text>')
            label = f"Trigger for {m.name(u)}"
        if n.startswith("f-") and u in faded:
            cls += " faded"
        stripe = ""
        if n.startswith("f-") and u in (part_of or {}):
            stripe = f'<rect class="pstripe p{part_of[u]}" x="{x + 3:.1f}" y="{y + 8:.1f}" width="5" height="{h - 16}" rx="2.5"/>'
        parts.append(f'<g class="{cls}" data-id="{esc(ns + n)}" tabindex="0" role="button" aria-label="{esc(label)}">'
                     f'<rect x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="10"/>{stripe}{txt}</g>')
        card = re.sub(r' data-id="[^"]*"', "", card)   # the box carries the id; the card copy must not
        tpls.append(f'<template id="tpl-{esc(ns + n)}">{card}</template>')

    svg = (f'<svg id="{ns}graph" class="fgraph" viewBox="0 0 {g.width:.0f} {g.height:.0f}" width="{g.width:.0f}" height="{g.height:.0f}" '
           f'style="--w:{g.width:.0f}px" role="group" aria-label="Flow graph">'
           f'<defs><marker id="{ns}gah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>'
           + "".join(p for p in parts if not p.startswith('<g class="node'))   # edges first, so nodes sit on top
           + "".join(p for p in parts if p.startswith('<g class="node'))
           + "</svg>")
    return svg, tpls

# --------------------------------------------------------------------------- page

def render_html(flows, triggers, settings=None, out=None, org=None):
    """Return (html, findings). Prints intermediate tables to `out` when given. org is settings.json."""
    st = settings or Settings()
    m = Model(flows, triggers, st, org=org)
    findings = m.findings
    edges = m.edges()

    edges_js = json.dumps(edges).replace("</", "<\\/")
    map_html, script = graph_section(m, edges, findings)
    script = Template(script).substitute(edges=edges_js)

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
            f"Times are in {m.tz_label}, with UTC in brackets. Select a box in the graph to read what that flow does.")
    footer = " ".join(x for x in [st.footer.strip(), "Generated from flows.json and triggers.json by glific_utils."] if x)
    page = Template(PAGE).substitute(
        title=esc(f"{st.project} flow map"),
        h1=esc(typo(f"{st.project}: how the flows start and connect")),
        lede=esc(typo(lede)),
        tag_legend=esc(f"Flow tagged {st.tag}" if st.tag else "Flow"),
        untag_legend='<span><i class="sw u"></i>Flow without that tag</span>' if st.tag else "",
        map=map_html,
        legend_extra=('\n  <span><i class="sw s"></i>Glific setting</span><span><i class="sw g"></i>Contact group</span><span><i class="ln g"></i>Adds to or removes from a group</span>'
                      '\n  <span><i class="sw s"></i>No start found in the export</span>'),
        script=script,
        notes=shared_resources(m),
        context=context_section(st.notes),
        strip=strip_section(m),
        gaps=tagging_gaps(m),
        footer=esc(typo(footer)),
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
.ln.g{border-top:3px dotted var(--chat)}
.canvas{position:relative}
#wires{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:0;overflow:visible}
.wire{fill:none;stroke:var(--wire);stroke-width:1.7;transition:opacity .15s,stroke .15s}
.wire.data{stroke-dasharray:6 5}
.wire.dim{opacity:.12}
.wire.hot{stroke:var(--flow);stroke-width:2.6}
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
.tbl{margin:22px 0 0;border:1px solid var(--line);border-radius:10px;background:var(--surface)}
.tbl summary{cursor:pointer;padding:10px 14px;font-family:var(--head);font-weight:700;font-size:16px}
.tblwrap{overflow-x:auto;padding:0 14px 12px}
.tbl table{border-collapse:collapse;width:100%;font-size:13.5px}
.tbl th{text-align:left;font-weight:700;color:var(--muted);padding:6px 10px 6px 0;border-bottom:1px solid var(--line)}
.tbl td{padding:6px 10px 6px 0;border-bottom:1px solid var(--soft);vertical-align:top;overflow-wrap:anywhere}
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
.ghint{margin:0 0 12px;font-size:14px;color:var(--muted);max-width:90ch}
.gscroll{margin-bottom:22px;overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.fgraph{display:block;width:100%;min-width:calc(var(--w) * .75);height:auto}
.fgraph .edge path{fill:none;stroke:var(--wire);stroke-width:1.6;transition:opacity .15s,stroke .15s}
.fgraph .edge.data path{stroke-dasharray:6 5}
.fgraph .edge.hot path{stroke:var(--flow);stroke-width:2.6}
.fgraph .edge.dim{opacity:.12}
.fgraph .elabel{font-size:11.5px;fill:var(--muted);paint-order:stroke;stroke:var(--surface);stroke-width:4px;stroke-linejoin:round}
.fgraph .edge.hot .elabel{fill:var(--flow);font-weight:700}
.fgraph .node{cursor:pointer;transition:opacity .15s}
.fgraph .node rect{fill:var(--flow-bg);stroke:var(--flow);stroke-width:1.3}
.fgraph .node.untagged rect{fill:var(--surface);stroke:var(--muted);stroke-dasharray:5 4}
.fgraph .node.trig rect{fill:var(--trig-bg);stroke:var(--trig)}
.fgraph .pstripe{stroke:none}
.fgraph .node.setting rect{fill:var(--slate-bg);stroke:var(--slate)}
.fgraph .node.nostart rect{fill:var(--slate-bg);stroke:var(--slate);stroke-dasharray:3 3}
.fgraph .node.grp rect{fill:var(--chat-bg);stroke:var(--chat);rx:26}
.fgraph .edge.grp path{stroke:var(--chat);stroke-dasharray:2 4;stroke-linecap:round}
.fgraph .edge.grp.rm path{stroke:var(--warn)}
.fgraph .edge.grp.hot path{stroke-width:2.6}
.fgraph .edge.back{opacity:.45}
.fgraph .edge.back .elabel{display:none}
.fgraph .edge.back.hot{opacity:1}
.fgraph .edge.back.hot .elabel{display:inline}
.fgraph .edge.back.dim{opacity:.08}
.fgraph .ntag{font-size:12px;fill:var(--trig);font-style:italic}
.fgraph .ntag.plain{fill:var(--muted)}
.fgraph .node.on rect{stroke-width:2.6}
.fgraph .node:focus{outline:none}
.fgraph .node:focus-visible rect{stroke-width:3;stroke:var(--ink)}
.fgraph .node.dim{opacity:.35}
.fgraph .nname,.fgraph .tname{font-family:var(--head);font-weight:700;font-size:14px;fill:var(--ink)}
.fgraph .nmeta,.fgraph .tmeta{font-size:12px;fill:var(--muted)}
.fgraph .nmeta .mv{fill:var(--trig);font-weight:700}
.fgraph .nmeta .wn{fill:var(--warn);font-weight:700}
.panel{position:fixed;top:0;right:0;bottom:0;width:min(420px,100vw);overflow:auto;z-index:10;background:var(--bg);border-left:1px solid var(--line);
  box-shadow:-8px 0 24px rgba(0,0,0,.18);padding:calc(16px + env(safe-area-inset-top,0px)) 16px 24px}
.panel[hidden]{display:none}
.panel .close{float:right;font:inherit;font-size:22px;line-height:1;width:36px;height:36px;border-radius:8px;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer;margin:0 0 10px 10px}
.panel .card{clear:both}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media (min-width:1100px){
  .strip{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media (min-width:700px) and (max-width:1099px){
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
$untag_legend
  <span><i class="ln"></i>Starts the flow</span>
  <span><i class="ln d"></i>Hands over data through a contact field</span>$legend_extra
</div>
$map
$notes
</section>
$strip
$gaps
</main>
<footer>$footer</footer>
</div>
$script
</body>
</html>
"""

GRAPH_JS = """<script>
(function(){
  var edges=$edges;
  var svg=document.getElementById('graph'),panel=document.getElementById('panel'),body=document.getElementById('panel-body');
  var nodes={},sel=null;
  svg.querySelectorAll('.node').forEach(function(n){nodes[n.getAttribute('data-id')]=n;});
  var wires=Array.prototype.slice.call(svg.querySelectorAll('.edge'));
  function light(id){
    var near={};near[id]=1;
    edges.forEach(function(e){if(e[0]===id)near[e[1]]=1;if(e[1]===id)near[e[0]]=1;});
    Object.keys(nodes).forEach(function(k){nodes[k].classList.toggle('dim',!near[k]);nodes[k].classList.toggle('on',k===id);});
    wires.forEach(function(w){var hot=w.getAttribute('data-from')===id||w.getAttribute('data-to')===id;w.classList.toggle('hot',hot);w.classList.toggle('dim',!hot);});
  }
  function clear(){
    if(sel){light(sel);return;}
    Object.keys(nodes).forEach(function(k){nodes[k].classList.remove('dim','on');});
    wires.forEach(function(w){w.classList.remove('hot','dim');});
  }
  function open(id){
    var t=document.getElementById('tpl-'+id);if(!t)return;
    sel=id;body.innerHTML='';body.appendChild(t.content.cloneNode(true));panel.hidden=false;light(id);
  }
  function close(){
    var was=sel;sel=null;panel.hidden=true;clear();if(was&&nodes[was])nodes[was].focus();
  }
  Object.keys(nodes).forEach(function(id){
    var n=nodes[id];
    n.addEventListener('mouseenter',function(){light(id);});
    n.addEventListener('mouseleave',clear);
    n.addEventListener('focus',function(){light(id);});
    n.addEventListener('blur',clear);
    n.addEventListener('click',function(){open(id);});
    n.addEventListener('keydown',function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();open(id);}});
  });
  panel.querySelector('.close').addEventListener('click',close);
  document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&!panel.hidden)close();});
  svg.addEventListener('click',function(ev){if(ev.target===svg)close();});
})();
</script>"""
