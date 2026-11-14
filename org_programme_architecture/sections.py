"""The sections under a graph: shared resources, other flows, tagging gaps and context notes."""
import re
from collections import Counter, defaultdict

from cards import node_chips
from text import esc, join, names, plural, typo


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
        kw = m.keywords(u)
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
