"""The model of an export: which flows are in scope, how they start and connect, and the graph's view."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from flow_reading import FlowGraph, mask_summary, summarise
from graph_view import build_view
from privacy import mask, staff_names
from text import fmt_day, join, names, parse_tz, parse_utc, plural


GRAPH_CAP = 30        # flow boxes on the graph layout


@dataclass
class Settings:
    project: str = "Glific chatbot"
    tag: str = ""                       # empty: start from triggers and keywords instead
    tz: str = "Asia/Kolkata"            # "IST, UTC+5:30" or an IANA name
    today: date = field(default_factory=date.today)
    footer: str = ""
    notes: str = ""                     # context notes text (see README for the format)
    scope_all: bool = False             # every flow in the export, not just the tag and what it reaches


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


class Model:
    def __init__(self, flows, triggers, st, org=None):
        self.st = st
        self.setting_starts = setting_starts(org, flows)
        self.tz, self.tz_label = parse_tz(st.tz)
        self.flows = {f.get("uuid"): f for f in flows if f.get("uuid")}
        self.staff = staff_names(self.flows)
        # Masked once here: names are read in every sort key and on every box
        self._names = {u: mask(f.get("name") or u, self.staff) for u, f in self.flows.items()}
        self.graphs = {u: FlowGraph(f) for u, f in self.flows.items()}
        self.sum = {u: mask_summary(summarise(g), self.staff) for u, g in self.graphs.items()}
        self.findings = []
        self.triggers = [self._masked_trigger(t) for t in triggers]
        self._triggers()
        self._scope()
        self._links()
        self._roles()
        self._graph_map()

    def _masked_trigger(self, t):
        """A copy of a trigger whose group names are masked like the group names in flows (with
        the staff list too), so a schedule's group still matches the group a flow fills."""
        t = dict(t)
        for key in ("groups", "waGroups"):
            if t.get(key):
                t[key] = [mask(g, self.staff) for g in names(t[key])]
        return t

    def name(self, u):
        return self._names[u] if u in self._names else mask(u, self.staff)

    def by_name(self, u):
        """Sort key: the flow's name, ignoring case."""
        return self.name(u).lower()

    def name_key(self, u):
        """Sort key that never ties: the name, then the uuid."""
        return (self.name(u).lower(), u)

    def tag_label(self, u):
        return mask((((self.flows.get(u) or {}).get("tag") or {}).get("label") or "").strip())

    def keywords(self, u):
        return [mask(k) for k in (self.flows.get(u) or {}).get("keywords") or []]

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
                self.missing_trig[mask(fl.get("name") or "a flow with no name", self.staff)].append(t)
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
        else:   # without a tag: everything a contact or a schedule can start, including Glific settings
            seeds = [u for u in self.flows if self.keywords(u)] + sorted(self.setting_starts)
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
        self.all_callers = defaultdict(Counter)   # across the whole export, to tell "no start" from "started elsewhere"
        for u in self.flows:
            for v, _ in self.sum[u]["starts"]:
                if v in self.flows and v != u:
                    self.all_callers[v][u] += 1
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
        for v in sorted(self.scope, key=self.name_key):
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
            elif self.active_trig.get(u) or (self.keywords(u) and starts_any(u)):
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
        entry = {u for u in sc if self.active_trig.get(u) or self.keywords(u) or u in self.setting_starts}
        linked |= entry
        by_name = self.by_name
        degree = lambda u: len(self.callers[u]) + sum(1 for v, _ in self.sum[u]["starts"] if v in sc)
        # Entry points first (schedules, keywords, settings), so the cap never hides how things start
        order = sorted(linked, key=lambda u: (u not in entry, -degree(u), by_name(u)))
        on = set(order[:GRAPH_CAP])
        overflow = sorted(order[GRAPH_CAP:], key=by_name)
        if overflow:
            self.findings.append(f"{plural(len(overflow), 'flow')} moved from the graph to the strip to keep it readable: {join(map(self.name, overflow), 8)}.")
        self.view = self.graph_view(on, add_fillers=True)
        # Flows that fill a group a schedule on the graph sends to join the scope, and the table
        self.scope |= self.view.linked_group
        for u in self.view.linked_group:
            self.columns[u] = "group"
        self.strip = [u for u in sorted((u for u in sc if u not in on and u not in overflow), key=by_name) + overflow
                      if u not in self.view.on_map]

    def graph_view(self, flow_ids, add_fillers=False, no_starts=frozenset(), ignore_callers=frozenset()):
        """The boxes and edges for exactly these flows, as a GraphView. Nothing on the model changes."""
        return build_view(self, flow_ids, add_fillers, no_starts, ignore_callers, cap=GRAPH_CAP)
