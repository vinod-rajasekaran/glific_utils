"""The graph as an SVG: boxes, edges and their labels, laid out by graph_layout."""
import re
from collections import defaultdict

from cards import flow_card, keyword_card, node_chips, row, trigger_card
from graph_layout import layout as graph_layout
from schedules import schedule_text
from text import esc, join, names, plural, typo, wrap


NODE_W, NODE_H, TRIG_W, TRIG_H, GROUP_W, GROUP_H = 200, 70, 200, 52, 170, 52


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


def graph_svg(m, view, findings, ns="", faded=frozenset(), part_of=None):
    """The graph as an SVG string plus one <template> per box holding its full card. Every id in
    both is prefixed with ns, so several graphs can share a page. Flows in faded are drawn faded.
    part_of maps a flow uuid to a part number (1 to 6); the box gets a coloured stripe for its part."""
    sizes, kinds = {}, {}
    def size(n):
        if n[0] in "tkxso":
            return TRIG_W, TRIG_H
        if n[0] == "g":
            return GROUP_W, GROUP_H
        return NODE_W, NODE_H + (0 if m.tagged(n[2:]) else 16)   # room for the tag line
    edges = view.edges(m)
    for a, b, k in edges:
        sizes[a], sizes[b] = size(a), size(b)
        kinds[(a, b)] = k
    for u in sorted(view.on_map, key=lambda u: (m.name(u).lower(), u)):
        sizes.setdefault(f"f-{u}", size(f"f-{u}"))
    groups = list(view.group_nodes.items())
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
        if a[0] in "tkxso":
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
            card = (f'<article class="card"><div class="ch"><h3>{esc(gname)}</h3><span class="tag no">Group</span></div>'
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
            card = ('<article class="card"><div class="ch"><h3>Glific setting</h3></div>'
                    + row("Starts", m.name(u))
                    + "".join(row("Runs", text) for _, text in m.setting_starts.get(u, []))
                    + row("Note", "Set in Glific under Settings, not by a trigger or keyword, so it does not appear in the trigger list.")
                    + "</article>")
            label = f"Glific setting that starts {m.name(u)}"
        elif n.startswith("o-"):   # started by a flow that is not drawn on this graph
            cls = "node nostart"
            callers = sorted(map(m.name, m.all_callers[u]), key=str.lower)
            txt = (f'<text class="tname" x="{x + 12:.1f}" y="{y + 21:.1f}">Started off this graph</text>'
                   f'<text class="tmeta" x="{x + 12:.1f}" y="{y + 40:.1f}">{esc(wrap("By " + join(callers, 2), 28, 1)[0])}</text>')
            card = ('<article class="card untagged"><div class="ch"><h3>Started off this graph</h3></div>'
                    + row("Starts", m.name(u)) + row("Started by", join(callers, 6))
                    + row("Note", "The flows that start this one are not drawn on this graph.") + "</article>")
            label = f"{m.name(u)} is started by a flow not on this graph"
        elif n.startswith("x-") and m.all_callers[u]:   # started only by flows left off this graph (test flows)
            cls = "node nostart"
            txt = (f'<text class="tname" x="{x + 12:.1f}" y="{y + 21:.1f}">Only test flows start it</text>'
                   f'<text class="tmeta" x="{x + 12:.1f}" y="{y + 40:.1f}">They are left off this graph</text>')
            card = ('<article class="card untagged"><div class="ch"><h3>Only test flows start it</h3></div>'
                    + row("Starts", m.name(u))
                    + row("Started by", join(sorted(map(m.name, m.all_callers[u])), 4))
                    + row("Note", "The only flows that start this one were left off this graph as tests or leftovers.")
                    + "</article>")
            label = f"Only test flows start {m.name(u)}"
        elif n.startswith("x-"):
            cls = "node nostart"
            txt = (f'<text class="tname" x="{x + 12:.1f}" y="{y + 21:.1f}">No start found</text>'
                   f'<text class="tmeta" x="{x + 12:.1f}" y="{y + 40:.1f}">No trigger, keyword or flow</text>')
            card = ('<article class="card untagged"><div class="ch"><h3>No start found</h3></div>'
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
                kw = m.keywords(u)
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
        tpls.append(f'<template id="tpl-{esc(ns + n)}">{card}</template>')

    svg = (f'<svg id="{ns}graph" class="fgraph" viewBox="0 0 {g.width:.0f} {g.height:.0f}" width="{g.width:.0f}" height="{g.height:.0f}" '
           f'style="--w:{g.width:.0f}px" role="group" aria-label="Flow graph">'
           f'<defs><marker id="{ns}gah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>'
           + "".join(p for p in parts if not p.startswith('<g class="node'))   # edges first, so nodes sit on top
           + "".join(p for p in parts if p.startswith('<g class="node'))
           + "</svg>")
    return svg, tpls
