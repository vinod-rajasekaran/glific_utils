"""Which boxes and edges a graph of some flows has: their starts, groups and links.

    build_view(model, flow_ids, ...) -> GraphView     reads the model, never changes it
    GraphView.edges(model) -> [[from, to, kind], ...]

Box ids: f- flow, t- trigger, k- keyword, s- Glific setting, x- no start found,
o- started by a flow off this graph, g- contact group.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from text import names

@dataclass
class GraphView:
    on_map: set
    trigger_flows: list = field(default_factory=list)    # flows with a trigger or keyword box
    setting_flows: list = field(default_factory=list)    # flows with a "Glific setting" box
    no_start: list = field(default_factory=list)         # nothing in the export starts them (or only ignored callers)
    offgraph_start: list = field(default_factory=list)   # started by a flow not drawn on this graph
    group_nodes: dict = field(default_factory=dict)      # group name -> {"adds", "removes", "triggers"}
    entry: list = field(default_factory=list)            # flows with a start box that no flow on the graph starts
    linked_group: set = field(default_factory=set)       # flows added because they fill a group a schedule sends to

    def edges(self, m):
        out = []
        for u in self.trigger_flows:
            out.append([f"t-{u}" if m.active_trig.get(u) else f"k-{u}", f"f-{u}", "s"])
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
        key = m.name_key
        for v in sorted(m.all_callers, key=key):   # sorted, so the layout is the same on every run
            for u in sorted(m.all_callers[v], key=key):
                if u in self.on_map and v in self.on_map:
                    out.append([f"f-{u}", f"f-{v}", "s"])
        solid = {(a, b) for a, b, _ in out}
        for u, v, _ in m.data_links:
            pair = (f"f-{u}", f"f-{v}")
            if u in self.on_map and v in self.on_map and pair not in solid and pair[::-1] not in solid:
                solid.add(pair)
                out.append([*pair, "d"])
        return out


def build_view(m, flow_ids, add_fillers=False, no_starts=frozenset(), ignore_callers=frozenset(), cap=30):
    """Put exactly these flows on the graph and work out their trigger, keyword, no-start and
    group boxes. With add_fillers, flows outside the set that add contacts to a group a
    schedule on the graph sends to are added too. Flows in no_starts (faded neighbours) get
    no start boxes and do not pull their schedules' groups onto the graph. Callers in
    ignore_callers (test flows left off the graph) do not count as a way the flow starts.
    Group fillers stop being added once the graph holds cap flows."""
    on = set(flow_ids)
    by_name = m.by_name
    view = GraphView(on_map=on)
    # Groups: a group that an active trigger on the graph sends to gets its own box, when some
    # flow adds contacts to it or removes them. Flows outside the scope that add contacts to it
    # join the graph, since they decide who the schedule reaches.
    targets = defaultdict(list)
    for u in sorted(on - set(no_starts), key=by_name):
        for t in m.active_trig.get(u, []):
            for gname in names(t.get("groups")):
                if u not in targets[gname]:
                    targets[gname].append(u)
    movers = defaultdict(lambda: {"into": [], "out of": []})
    for u in sorted(m.flows, key=by_name):
        for direction, gs, _ in m.sum[u]["moves"]:
            for gname in gs:
                if gname not in targets:
                    continue
                if u not in on:
                    if not add_fillers or direction != "into" or len(on) >= cap:
                        continue
                    on.add(u)
                    view.linked_group.add(u)
                if u not in movers[gname][direction]:
                    movers[gname][direction].append(u)
    view.group_nodes = {gname: {"adds": movers[gname]["into"], "removes": movers[gname]["out of"], "triggers": targets[gname]}
                        for gname in sorted(movers)}

    called = {u for u in on if any(c in on for c in m.callers[u])}
    # a keyword box only where the keyword is how the flow starts; otherwise its card lists the keywords
    own = on - set(no_starts)
    view.trigger_flows = sorted((u for u in own if m.active_trig.get(u) or (m.keywords(u) and u not in called)), key=by_name)
    # Flows that Glific's organisation settings start get a "Glific setting" box
    view.setting_flows = sorted((u for u in own if u in m.setting_starts), key=by_name)
    # A flow with no start box and no caller on this graph: "No start found" when nothing in the
    # export starts it (or only ignored test flows do); a "Started off this graph" box when a
    # flow that is not drawn here starts it.
    unstarted = [u for u in own if u not in view.trigger_flows and u not in m.setting_starts
                 and not (set(m.all_callers[u]) - set(ignore_callers)) & on]
    view.offgraph_start = sorted((u for u in unstarted if set(m.all_callers[u]) - set(ignore_callers)), key=by_name)
    view.no_start = sorted((u for u in unstarted if u not in view.offgraph_start), key=by_name)
    view.entry = [u for u in view.trigger_flows if u not in called]
    return view
