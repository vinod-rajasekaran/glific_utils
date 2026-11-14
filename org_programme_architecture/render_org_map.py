"""The org map page: programmes (from Claude) or groups of linked flows (without Claude) first,
then each one as a graph with a side pane, and the full flow graph.

    render_org_map(model, facts, answer, dropped) -> html

Everything Claude wrote is shown under "Claude's reading" with its confidence, and each
statement opens to the evidence it cites. Every number, link, schedule and group comes from
the model and the facts, not from Claude.
"""
import json
from pathlib import Path
from collections import Counter
from datetime import datetime
from string import Template

from cards import flow_card
from graph_svg import graph_svg
from page_check import check_html
from sections import context_section, shared_resources, strip_section
from glific_common.org_facts.text import esc, fmt_day, join, plural, typo
from programme_claude import MODEL, wrap_use_case

ROLE_LABEL = {"core": "Core", "helper": "Helper", "shared": "Shared", "test": "Test", "leftover": "Leftover", "unknown": "Role unclear"}
CONF_LABEL = {"clear": "clear", "likely": "likely", "guess": "a guess"}

ASSETS = Path(__file__).resolve().parent / "assets"   # page markup, styles and scripts, inlined at build time


def t(text):
    """Escape Claude's or the export's text for the page."""
    return esc(typo(text))


class _Ctx:
    """Lookups the page needs, built once from the model, facts and Claude's validated answer."""

    def __init__(self, m, facts, uc):
        self.m, self.facts, self.uc = m, facts, uc
        self.flow = {f["id"]: f for f in facts["flows"]}
        self.claude_flow = {f["id"]: f for f in uc["flows"]}
        self.uc_of = {fid: u["id"] for u in uc["use_cases"] for fid in u["flows"]}
        self.uc_name = {u["id"]: u["name"] for u in uc["use_cases"]}
        self.use_case = {u["id"]: u for u in uc["use_cases"]}
        self.programmes = uc.get("programmes") or [wrap_use_case(u) for u in uc["use_cases"]]
        self.prog_of_uc = {pid: p["id"] for p in self.programmes for pid in p["parts"]}
        self.prog_of = {fid: self.prog_of_uc[u] for fid, u in self.uc_of.items() if u in self.prog_of_uc}
        self.prog_name = {p["id"]: p["name"] for p in self.programmes}
        self.prog_kind = {p["id"]: p["kind"] for p in self.programmes}
        self.claude = uc.get("source") != "structure"     # False: groups worked out without Claude
        self.excerpt = {e["id"]: (f["id"], e) for f in facts["flows"] for e in f["excerpts"]}
        self.group = {g["id"]: g for g in facts["groups"]}
        self.trigger = {x["id"]: x for x in facts["triggers"]}
        self.edge = {e["id"]: e for e in facts["edges"]}
        self.edge_meaning = {e["id"]: e["meaning"] for e in uc["edges"]}
        self.system = {s["host"]: s for s in uc["systems"]}

    def name(self, ref):
        if ref in self.flow:
            return self.flow[ref]["name"]
        if ref in self.group:
            return f"group {self.group[ref]['name']}"
        if ref in self.trigger:
            return f"the trigger that starts {self.flow.get(self.trigger[ref]['flow'], {}).get('name', 'a flow')}"
        return ref

    def evidence_item(self, ref):
        if ref in self.excerpt:
            fid, e = self.excerpt[ref]
            kind = {"message": "Message", "interactive": "Interactive message", "template": "Template", "sticky": "Designer’s note"}[e["kind"]]
            return f'<li><b>{esc(kind)} in {t(self.flow[fid]["name"])}:</b> “{t(e["text"])}”</li>'
        if ref in self.flow:
            f = self.flow[ref]
            start = "; ".join(s["text"] for s in f["starts_from"])
            return f'<li><b>Flow {t(f["name"])}:</b> starts when {t(start)}.</li>'
        if ref in self.group:
            g = self.group[ref]
            who = join([self.flow[x]["name"] for x in g["added_by"]], 4) or "no flow"
            return f'<li><b>Group {t(g["name"])}:</b> contacts are added by {t(who)}.</li>'
        if ref in self.trigger:
            x = self.trigger[ref]
            return f'<li><b>Trigger:</b> {t(x["schedule"])}, to {t(join(x["groups"], 4) or "no group")}, starts {t(self.name(x["flow"]))}.</li>'
        if ref in self.edge:
            e = self.edge[ref]
            return f'<li><b>Link:</b> {t(self.name(e["from"]))} → {t(self.name(e["to"]))} ({esc(e["kind"])}).</li>'
        return ""


def claude_label(conf):
    return f'<span class="reading">Claude’s reading</span> <span class="conf c-{esc(conf)}">{esc(CONF_LABEL.get(conf, conf))}</span>'


def statement(cx, s):
    items = "".join(cx.evidence_item(r) for r in s["evidence"])
    ev = f'<ul class="ev" hidden>{items}</ul>' if items else '<p class="ev" hidden>No evidence was cited, so this is a guess.</p>'
    return (f'<li class="st"><span>{t(s["text"])}</span> <button type="button" class="conf c-{esc(s["confidence"])}" '
            f'aria-expanded="false" title="Show the evidence">{esc(CONF_LABEL.get(s["confidence"], s["confidence"]))}</button>{ev}</li>')


def statements(cx, heading, items, cls=""):
    if not items:
        return ""
    return f'<h3 class="ph{cls}">{esc(heading)}</h3><ul class="sts">{"".join(statement(cx, s) for s in items)}</ul>'


def _tags_pill(m, members):
    """The flows' tags with counts, most used first. Tags are shown, never used to decide scope."""
    tags = Counter(m.tag_label(fid) or "no tag" for fid in members)
    return "Tags: " + join([f"{tg} ({n})" for tg, n in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))], 3), "tags"


def pills(cx, u, brief=False):
    """Pills computed from the facts. brief keeps the first screen short: flows, how they start,
    tags, outside systems and Claude's concerns."""
    m, members = cx.m, set(u["flows"])
    out = [(plural(len(members), "flow"), "")]
    kinds = Counter()
    for fid in members:
        for s in cx.flow[fid]["starts_from"]:
            if s["kind"] == "flow" and s["ref"] in members:
                continue
            kinds[s["kind"]] += 1
    names = {"trigger": "Schedule", "setting": "Glific setting", "keyword": "Keyword", "flow": "Started from another part",
             "none": "No start found"}
    out += [(names[k], "warn" if k == "none" else "") for k in ("trigger", "setting", "keyword", "flow", "none") if kinds[k]]
    hosts, functions, sheets, alerts, groups = set(), False, False, False, set()
    for fid in members:
        s = m.sum[fid]
        hosts.update(s["hosts"])          # parsed hostnames, not the display text
        functions |= bool(s["functions"])
        sheets |= bool(s["logs"])
        alerts |= bool(s["alerts"])
        groups |= {g for d, gs, _ in s["moves"] if d == "into" for g in gs}
    for h in sorted(hosts):
        if h in cx.system:   # Claude's name for the host, marked as Claude's reading, with the real host kept
            out.append((f"{cx.system[h]['name']} ({h})", "sys claude"))
        else:
            out.append((h, "sys"))
    if functions:
        out.append(("Glific functions", "sys"))
    if sheets:
        out.append(("Google Sheets", "sys"))
    if brief:
        systems = [p for p in out if "sys" in p[1]]
        starts = [p for p in out[1:] if p[1] in ("", "warn") and p not in systems]
        sys_pill = [(f"{plural(len(systems), 'outside system')}", "sys")] if len(systems) > 1 else systems
        concerns = [(f"{plural(len(u['watch']), 'concern')} from Claude", "warn claude")] if u["watch"] else []
        out = out[:1] + starts[:2] + [_tags_pill(m, members)] + sys_pill + concerns
        return "".join(f'<span class="pill2 {c}">{t(p)}</span>' for p, c in out)
    if alerts:
        out.append(("Staff alerts", "warn"))
    if groups:
        out.append(("Groups: " + join(sorted(groups), 3), ""))
    out.append(_tags_pill(m, members))
    lost = sum(1 for fid in members if m.sum[fid]["lost"])
    if lost:
        out.append((f"{plural(lost, 'flow')} with unreachable steps", "warn"))
    if u["watch"]:
        out.append((f"{plural(len(u['watch']), 'concern')} from Claude", "warn claude"))
    return "".join(f'<span class="pill2 {c}"{" title=" + chr(34) + "Claude" + chr(8217) + "s reading" + chr(34) if "claude" in c else ""}>{t(p)}</span>'
                   for p, c in out)


def neighbours(cx, members):
    """Flows in other use cases that start, are started by, or share data with a member."""
    out = set()
    for e in cx.facts["edges"]:
        a, b = e["from"], e["to"]
        if a in members and b in cx.flow and b not in members:
            out.add(b)
        if b in members and a in cx.flow and a not in members:
            out.add(a)
    return out


def flow_pane(cx, fid, findings, view=None):
    f, c = cx.flow[fid], cx.claude_flow.get(fid, {})
    role = (f'<span class="role claude r-{esc(c.get("role", "unknown"))}" title="Claude\u2019s reading">'
            f'{esc(ROLE_LABEL.get(c.get("role", "unknown"), "Role unclear"))}</span>') if cx.claude else ""
    head = f'<div class="fp-head"><h3>{t(f["name"])}</h3>{role}</div>'
    purpose = ""
    if c.get("purpose"):
        items = "".join(cx.evidence_item(r) for r in c.get("evidence", []))
        purpose = (f'<p class="purpose">{claude_label(c.get("confidence", "guess"))}<br>{t(c["purpose"])}</p>'
                   + (f'<details class="evd"><summary>Evidence</summary><ul>{items}</ul></details>' if items else ""))
    part, home = cx.uc_of.get(fid), cx.prog_of.get(fid)
    if home:
        in_part = f"{t(cx.uc_name[part])}, in " if cx.prog_name[home] != cx.uc_name[part] else ""
        where = f'<p class="muted">Part of {in_part}<a href="#uc-{esc(home)}">{t(cx.prog_name[home])}</a></p>'
    else:
        where = '<p class="muted">Not placed in a use case.</p>'

    def io(items, heading):
        rows = []
        for s in items:
            link = ""
            if s["kind"] in ("flow", "data") and s["ref"] in cx.flow:
                other = cx.prog_of.get(s["ref"])
                if other and other != home:
                    link = f' <a href="#uc-{esc(other)}">({t(cx.prog_name[other])})</a>'
            if s["kind"] == "group":
                eids = (f"edge:{fid}:{s['ref']}:adds", f"edge:{fid}:{s['ref']}:removes")
            else:
                kind = "data" if s["kind"] == "data" else "start"
                eids = (f"edge:{s['ref']}:{fid}:{kind}", f"edge:{fid}:{s['ref']}:{kind}")
            for eid in eids:
                if eid in cx.edge_meaning:
                    link += f' <span class="meaning">(Claude: {t(cx.edge_meaning[eid])})</span>'
            rows.append(f"<li>{t(s['text'])}{link}</li>")
        return f'<h4>{esc(heading)}</h4><ul class="io">{"".join(rows)}</ul>' if rows else ""

    card = flow_card(cx.m, fid, view)
    return (head + purpose + where + io(f["starts_from"], "How it starts") + io(f["leads_to"], "Where it leads")
            + card)


def programme_whole(prog, parts):
    """A programme as one use case for the pills: all its parts' flows and every concern."""
    return {"flows": [fid for u in parts for fid in u["flows"]], "watch": prog["watch"] + [w for u in parts for w in u["watch"]]}


def part_chip(n, name):
    return f'<span class="partchip"><i class="pdot p{n}"></i>{t(name)}</span>'


def test_readers_note(cx, members, tests):
    """One line, from the export alone, naming test flows that connect to this programme."""
    if not tests:
        return ""
    fields, other = set(), False
    for w, r, fld in cx.m.data_links:
        if w in members and r in tests:
            fields.add(fld)
    other = any(e["kind"] != "data" and ({e["from"], e["to"]} & tests) and ({e["from"], e["to"]} & members) for e in cx.facts["edges"])
    names = join(sorted((cx.flow[f]["name"] for f in tests), key=str.lower), 4)
    what = f"read fields this programme sets: {join(sorted(fields), 5)}" if fields else "connect to flows in this programme"
    if fields and other:
        what += ", and start or are started by its flows"
    return (f'<p class="factnote"><span class="reading">From the export</span><br>'
            f'{plural(len(tests), "test flow")} ({t(names)}) {esc(what)}. They are left off this graph.</p>')


def programme_view(cx, prog, findings):
    """One programme: a graph of all its parts' flows (each box striped by its part) beside a pane
    with the programme's story and a section per part."""
    m, pid = cx.m, prog["id"]
    parts = [cx.use_case[x] for x in prog["parts"]]
    part_no = {u["id"]: min(i, 6) for i, u in enumerate(parts, 1)}
    members = [fid for u in parts for fid in u["flows"]]
    part_of = {fid: part_no[cx.uc_of[fid]] for fid in members} if len(parts) > 1 else {}
    near = neighbours(cx, set(members))
    # Test copies and leftovers are not drawn as neighbours: a warning from the export says which
    # of them read or touch this programme's data instead
    tests = {f for f in near if cx.prog_kind.get(cx.prog_of.get(f)) == "tests"}
    near -= tests
    view = m.graph_view(set(members) | near, no_starts=near, ignore_callers=tests)
    svg, tpls = graph_svg(m, view, findings, ns=f"{pid}-", faded=near, part_of=part_of)
    test_note = test_readers_note(cx, set(members), tests)
    panes = "".join(f'<template id="pane-{esc(pid)}-f-{esc(fid)}">{flow_pane(cx, fid, findings, view)}</template>'
                    for fid in sorted(view.on_map, key=m.by_name) if fid in cx.flow)
    sections = ""
    if len(parts) > 1:
        for k, u in enumerate(parts):
            sections += (f'<details class="part"{" open" if k == 0 else ""}><summary>{part_chip(part_no[u["id"]], u["name"])}</summary>'
                         f'<p class="psum">{t(u["summary"])}</p>'
                         + statements(cx, "What happens", u["story"])
                         + statements(cx, "How it works", u["how_it_works"])
                         + statements(cx, "What to watch", u["watch"], " w") + "</details>")
    else:
        u = parts[0]
        sections = (statements(cx, "What happens", u["story"]) + statements(cx, "How it works", u["how_it_works"])
                    + statements(cx, "What to watch", u["watch"], " w"))
    reading = f'<p class="muted">{claude_label(prog["confidence"])}</p>' if cx.claude else ""
    story = (f'<div class="pane-story">{reading}'
             + statements(cx, "The programme end to end", prog["story"])
             + (f'<h3 class="ph w">What to watch across it</h3>{test_note}' if test_note and not prog["watch"] else "")
             + (statements(cx, "What to watch across it", prog["watch"], " w").replace('<ul class="sts">', f'{test_note}<ul class="sts">', 1)
                if prog["watch"] else "")
             + ('<h3 class="ph">Its parts</h3>' if len(parts) > 1 else "") + sections
             + '<p class="hint">Select a box in the graph to see that flow in detail. Faded boxes belong to other programmes.</p></div>')
    legend = f'<div class="partlegend">{"".join(part_chip(part_no[u["id"]], u["name"]) for u in parts)}</div>' if len(parts) > 1 else ""
    cards = ""
    for u in parts:
        if len(parts) > 1:
            cards += f'<h4 class="cardgroup">{part_chip(part_no[u["id"]], u["name"])}</h4>'
        cards += '<div class="fcards">' + "".join(
            f'<div class="fcard" id="card-{esc(pid)}-{esc(fid)}">{flow_pane(cx, fid, findings, view)}</div>' for fid in u["flows"]) + "</div>"
    whole = programme_whole(prog, parts)
    return (f'<section class="ucview" id="uc-{esc(pid)}" hidden>'
            f'<p><a class="back" href="#">\u2190 All programmes</a></p>'
            f'<h2>{t(prog["name"])}</h2><p class="lede2">{reading_label(cx)}{t(prog["summary"])}</p>'
            f'<div class="pills">{pills(cx, whole)}</div>{legend}'
            f'<div class="ucgrid"><div class="gscroll">{svg}</div>'
            f'<aside class="pane" aria-live="polite"><button type="button" class="pane-back" hidden>\u2190 Back to the story</button>'
            f'<div class="pane-body">{story}</div><template class="story-tpl">{story}</template></aside></div>'
            f'<h3 class="sub">Every flow in this programme</h3>{cards}'
            + "".join(tpls) + panes + "</section>")


FULL_GRAPH = "-graph"
GRAPH_LEGEND = ('<div class="legend" aria-label="Legend"><span><i class="sw t"></i>Trigger or keyword</span>'
                '<span><i class="sw s"></i>Glific setting or no start found</span><span><i class="sw g"></i>Contact group</span>'
                '<span><i class="sw f"></i>Flow</span><span><i class="ln"></i>Starts the flow</span>'
                '<span><i class="ln d"></i>Hands over data</span><span><i class="ln g"></i>Fills or empties a group</span></div>')


def full_graph_view(m, findings):
    """The model's main graph, straight from the export, as one more view."""
    # "-graph" can never be a programme id (slugs never start with "-"), and the page script
    # derives each graph's id prefix from its section id, so the two must match
    svg, tpls = graph_svg(m, m.view, findings, ns=f"{FULL_GRAPH}-")
    story = ('<div class="pane-story"><h3 class="ph">How to read it</h3><p class="muted">The graph shows '
             f'{plural(len(m.view.on_map), "flow")}: every flow that starts or is started by another, hands over data, or has a '
             'trigger, keyword or Glific setting. Time runs left to right: how each flow starts, then what it starts or hands '
             'data to. Select a box to see that flow in detail.</p></div>')
    return (f'<section class="ucview" id="uc-{FULL_GRAPH}" hidden>'
            f'<p><a class="back" href="#">\u2190 All programmes</a></p>'
            f'<h2>Full flow graph</h2><p class="lede2">Every flow and how it starts, from the export alone.</p>'
            f'{GRAPH_LEGEND}'
            f'<div class="ucgrid"><div class="gscroll">{svg}</div>'
            f'<aside class="pane" aria-live="polite"><button type="button" class="pane-back" hidden>\u2190 Back</button>'
            f'<div class="pane-body">{story}</div><template class="story-tpl">{story}</template></aside></div>'
            f'{strip_section(m)}' + "".join(tpls) + "</section>")


def reading_label(cx):
    return '<span class="reading">Claude\u2019s reading</span><br>' if cx.claude else ""


def render_org_map(m, facts, answer, dropped=()):
    """The page: a card per programme (from Claude) or per group of linked flows (without Claude),
    a view for each, and the full flow graph. answer is Claude's validated answer, or
    grouping.group_answer() when Claude was not used."""
    st, cx = m.st, _Ctx(m, facts, answer)
    findings = list(m.findings)
    order = sorted(cx.programmes, key=lambda p: p["kind"] == "tests")
    cards = ""
    for p in order:
        parts = [cx.use_case[x] for x in p["parts"]]
        chips = (f'<div class="partlegend">{"".join(part_chip(min(i, 6), u["name"]) for i, u in enumerate(parts, 1))}</div>'
                 if len(parts) > 1 else "")
        cards += (f'<a class="uccard{" muted-card" if p["kind"] == "tests" else ""}" href="#uc-{esc(p["id"])}">'
                  f'<h3>{t(p["name"])}</h3><p>{reading_label(cx)}{t(p["summary"])}</p>'
                  f'{chips}<div class="pills">{pills(cx, programme_whole(p, parts), brief=True)}</div></a>')
    cards += (f'<a class="uccard graphcard" href="#uc-{FULL_GRAPH}"><h3>Full flow graph</h3>'
              '<p>Every flow, how it starts and what it leads to, straight from the export.</p></a>')
    views = "".join(programme_view(cx, p, findings) for p in order) + full_graph_view(m, findings)

    if cx.claude:
        org = answer["org_summary"]
        org_items = "".join(cx.evidence_item(r) for r in org["evidence"])
        intro = (f'<div class="org"><p class="muted">{claude_label(org["confidence"])}</p><p>{t(org["text"])}</p>'
                 + (f'<details class="evd"><summary>Evidence</summary><ul>{org_items}</ul></details>' if org_items else "") + "</div>")
    else:
        intro = (f'<div class="org banner"><p><b>Built without Claude</b>: {t(answer.get("reason") or "it was not asked for")}.</p>'
                 '<p>The groups below are flows that start each other, hand over data, or fill a group a schedule sends to, '
                 'named after the tag most of their flows carry. Run with an Anthropic API key for programme names, stories '
                 'and what each flow is for.</p></div>')

    not_placed = ""
    if answer["not_placed"]:
        rows = "".join(f'<li><b>{t(cx.flow[f]["name"])}</b>{": " + t(cx.claude_flow[f]["purpose"]) if cx.claude_flow.get(f, {}).get("purpose") else ""}</li>'
                       for f in answer["not_placed"])
        not_placed = f'<section class="sect"><h2>Not placed</h2><p>Claude could not tell which programme these flows belong to.</p><ul class="plain">{rows}</ul></section>'
    if m.export_failed:
        rows = "".join(f'<li><b>{t(m.name(u))}</b>: {t(why)}</li>' for u, why in sorted(m.export_failed.items(), key=lambda kv: m.name_key(kv[0])))
        not_placed += ('<section class="sect"><h2>Not exported</h2><p>Glific could not export these flows, so they show with no '
                       f'steps here. Open them in the Glific flow editor to fix them.</p><ul class="plain">{rows}</ul></section>')
    dropped_html = ""
    if dropped:
        dropped_html = (f'<section class="sect"><details><summary>Dropped by validation ({len(dropped)})</summary>'
                        '<p>These parts of Claude\u2019s answer referred to things that are not in the export, or had no evidence, so they are not shown.</p>'
                        f'<ul class="plain">{"".join(f"<li>{t(d)}</li>" for d in dropped)}</ul></details></section>')

    active_n = sum(map(len, m.active_trig.values()))
    grouped = (f"grouped by Claude into {plural(len(cx.programmes), 'programme')} with {plural(len(answer['use_cases']), 'part')}"
               if cx.claude else f"grouped by their links into {plural(len(cx.programmes), 'group')}")
    lede = (f"{plural(len(facts['flows']), 'active flow')} in the export, {grouped}. {plural(active_n, 'trigger')} "
            f"{'is' if active_n == 1 else 'are'} active on {fmt_day(datetime.combine(st.today, datetime.min.time()))}. "
            f"Times are in {m.tz_label}.")
    made = (f"Programmes and descriptions by Claude ({answer.get('model') or MODEL}); every number, link and schedule comes from "
            "flows.json and triggers.json." if cx.claude else "Groups worked out from the flows\u2019 links; no Claude was used.")
    footer = " ".join(x for x in [st.footer.strip(), made, "Generated by glific_utils."] if x)
    page = Template(UC_PAGE).substitute(
        css=BASE_CSS + UC_CSS, title=esc(f"{st.project} org map"), h1=t(f"{st.project}: what the bot does"),
        lede=t(lede), reading=t("Programme and part names, summaries and dashed pills are Claude\u2019s reading of the flows. "
                                "Everything else comes from the export." if cx.claude else
                                "Groups worked out from the flows\u2019 links; every name, number and link comes from the export."),
        org=intro + context_section(st.notes), cards=cards, shared=shared_resources(m), not_placed=not_placed,
        dropped=dropped_html, views=views, footer=t(footer),
        uc_of=json.dumps({f"f-{k}": v for k, v in cx.prog_of.items()}).replace("</", "<\\/"))
    check_html(page)
    return page


BASE_CSS = (ASSETS / "base.css").read_text(encoding="utf-8")
UC_CSS = (ASSETS / "programmes.css").read_text(encoding="utf-8")

UC_PAGE = (ASSETS / "programmes_page.html").read_text(encoding="utf-8")
