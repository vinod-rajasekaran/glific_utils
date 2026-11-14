"""The model of an export: which flows are in scope, how they start and connect, and the graph's view."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from flow_reading import FlowGraph, mask_summary, summarise
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
        self.graphs = {u: FlowGraph(f) for u, f in self.flows.items()}
        self.sum = {u: mask_summary(summarise(g), self.staff) for u, g in self.graphs.items()}
        self.findings = []
        self.triggers = triggers
        self._triggers()
        self._scope()
        self._links()
        self._roles()
        self.no_start = []
        self.offgraph_start = []
        self.setting_flows = []
        self.group_nodes = {}
        self.linked_group = set()
        self._graph_map()

    def name(self, u):
        return mask((self.flows.get(u) or {}).get("name") or u, self.staff)

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
        by_name = lambda u: self.name(u).lower()
        degree = lambda u: len(self.callers[u]) + sum(1 for v, _ in self.sum[u]["starts"] if v in sc)
        # Entry points first (schedules, keywords, settings), so the cap never hides how things start
        order = sorted(linked, key=lambda u: (u not in entry, -degree(u), by_name(u)))
        on = set(order[:GRAPH_CAP])
        overflow = sorted(order[GRAPH_CAP:], key=by_name)
        if overflow:
            self.findings.append(f"{plural(len(overflow), 'flow')} moved from the graph to the strip to keep it readable: {join(map(self.name, overflow), 8)}.")
        self.strip = sorted((u for u in sc if u not in on and u not in overflow), key=by_name) + overflow
        self.graph_view(on, add_fillers=True)
        self.strip = [u for u in self.strip if u not in self.on_map]

    def graph_view(self, flow_ids, add_fillers=False, no_starts=frozenset(), ignore_callers=frozenset()):
        """Put exactly these flows on the graph and work out their trigger, keyword, no-start and
        group boxes. With add_fillers, flows outside the set that add contacts to a group a
        schedule on the graph sends to are added too. Flows in no_starts (faded neighbours) get
        no start boxes and do not pull their schedules' groups onto the graph. Callers in
        ignore_callers (test flows left off the graph) do not count as a way the flow starts."""
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
                    if u not in targets[gname]:
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
        self.trigger_flows = sorted((u for u in own if self.active_trig.get(u) or (self.keywords(u) and u not in called)),
                                    key=by_name)
        # Flows that Glific's organisation settings start get a "Glific setting" box
        self.setting_flows = sorted((u for u in own if u in self.setting_starts), key=by_name)
        # A flow with no start box and no caller on this graph: "No start found" when nothing in the
        # export starts it (or only ignored test flows do); a "Started off this graph" box when a
        # flow that is not drawn here starts it.
        unstarted = [u for u in own if u not in self.trigger_flows and u not in self.setting_starts
                     and not (set(self.all_callers[u]) - set(ignore_callers)) & on]
        self.offgraph_start = sorted((u for u in unstarted if set(self.all_callers[u]) - set(ignore_callers)), key=by_name)
        self.no_start = sorted((u for u in unstarted if u not in self.offgraph_start), key=by_name)
        self.entry = [u for u in self.trigger_flows if u not in called]

    def edges(self):
        out = []
        for u in self.trigger_flows:
            out.append([f"t-{u}" if self.active_trig.get(u) else f"k-{u}", f"f-{u}", "s"])
        for u in self.setting_flows:
            out.append([f"s-{u}", f"f-{u}", "s"])
        for u in self.no_start:
            out.append([f"x-{u}", f"f-{u}", "s"])
        for u in self.offgraph_start:
            out.append([f"o-{u}", f"f-{u}", "s"])
        for i, (gname, info) in enumerate(self.group_nodes.items()):
            gid = f"g-{i}"
            out += [[f"f-{u}", gid, "ga"] for u in info["adds"]]
            out += [[f"f-{u}", gid, "gr"] for u in info["removes"] if u not in info["adds"]]
            out += [[gid, f"t-{u}", "gt"] for u in info["triggers"]]
        key = lambda u: (self.name(u).lower(), u)
        for v in sorted(self.all_callers, key=key):   # sorted, so the layout is the same on every run
            for u in sorted(self.all_callers[v], key=key):
                if u in self.on_map and v in self.on_map:
                    out.append([f"f-{u}", f"f-{v}", "s"])
        solid = {(a, b) for a, b, _ in out}
        for u, v, _ in self.data_links:
            pair = (f"f-{u}", f"f-{v}")
            if u in self.on_map and v in self.on_map and pair not in solid and pair[::-1] not in solid:
                solid.add(pair)
                out.append([*pair, "d"])
        return out
