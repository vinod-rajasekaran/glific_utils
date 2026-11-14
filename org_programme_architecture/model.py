"""The model of an export: every active flow, how each starts and connects, and the main graph's view."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from flow_reading import FlowGraph, mask_summary, summarise
from graph_view import build_view
from glific_common.privacy import mask, staff_names
from text import fmt_day, join, names, parse_tz, parse_utc, plural


GRAPH_CAP = 30        # flow boxes on the graph layout


@dataclass
class Settings:
    project: str = "Glific chatbot"
    tz: str = "Asia/Kolkata"            # "IST, UTC+5:30" or an IANA name
    today: date = field(default_factory=date.today)
    footer: str = ""
    notes: str = ""                     # context notes text (see README for the format)


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
        """Every flow in the export is in scope; note flows that are started but not exported."""
        self.scope = set(self.flows)
        self.missing_targets = defaultdict(set)
        for u in self.flows:
            for v, vname in self.sum[u]["starts"]:
                if v not in self.flows:
                    self.missing_targets[vname].add(u)
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

    def _graph_map(self):
        """The main graph: every flow that starts, is started, hands over data, or has a trigger,
        keyword or Glific setting, up to GRAPH_CAP boxes with entry points first."""
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
        self.strip = [u for u in sorted((u for u in sc if u not in on and u not in overflow), key=by_name) + overflow
                      if u not in self.view.on_map]

    def report(self):
        """Findings worth printing after a run: trigger problems found while reading, steps no
        path reaches, flows started or triggered but missing from the export, unknown step types."""
        out = list(self.findings)
        for u in sorted(self.flows, key=self.name):
            if self.sum[u]["lost"]:
                out.append(f"{self.name(u)} holds {join(self.sum[u]['lost'], 3)} that no path reaches.")
        for n, us in sorted(self.missing_targets.items()):
            out.append(f"{n} is entered by {join(sorted(map(self.name, us)), 3)} but is not in the flows file.")
        for n, ts in sorted(self.missing_trig.items()):
            if any(t.get("isActive") for t in ts):
                out.append(f"An active trigger starts {n}, which is not in the flows file.")
        unknown = Counter(k for u in self.flows for k in self.sum[u]["other"])
        if unknown:
            out.append("Unrecognised step types: " + join([f"{k} ({n})" for k, n in unknown.items()]) + ".")
        return list(dict.fromkeys(out))

    def graph_view(self, flow_ids, add_fillers=False, no_starts=frozenset(), ignore_callers=frozenset()):
        """The boxes and edges for exactly these flows, as a GraphView. Nothing on the model changes."""
        return build_view(self, flow_ids, add_fillers, no_starts, ignore_callers, cap=GRAPH_CAP)
