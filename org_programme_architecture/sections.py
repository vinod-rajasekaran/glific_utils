"""The sections under a graph: shared resources, other flows and context notes."""
import re
from collections import defaultdict

from cards import node_chips
from glific_common.org_facts.text import esc, join, plural, typo


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
        if kw and (u not in m.view.entry or m.active_trig.get(u)):
            rows.append(("Keywords", join(kw, 6, "or"), m.name(u)))
    for f, w in sorted(m.shared_fields.items()):
        rows.append(("Field", f, f"written by {plural(len(w), 'flow')}: {_used_by(m, w, 3)}"))
    if not rows:
        return ""
    return _table("Shared across flows", rows, ("Kind", "Name", "Used by"))


def strip_section(m):
    """Flows that are not on the graph, and flows named in triggers or starts but missing from the
    export: one row each."""
    def what(u):
        chips = [c for c, _ in node_chips(m, u)]
        return join(chips, 6) or "nothing that leaves the bot"

    rows = [(m.name(u), m.tag_label(u) or "No tag", what(u), "Not on the graph") for u in m.strip]
    for n, ts in sorted(m.missing_trig.items()):
        rows.append((n, "", f"{plural(len(ts), 'trigger')}", "Named in triggers, not in the export"))
    for n, us in sorted(m.missing_targets.items()):
        rows.append((n, "", f"entered by {join(sorted(map(m.name, us)), 3)}", "Named in a start, not in the export"))
    if not rows:
        return ""
    return f'<section class="sect">{_table("Other flows in the account", rows, ("Flow", "Tag", "What it does", "Why it is listed"))}</section>'


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
