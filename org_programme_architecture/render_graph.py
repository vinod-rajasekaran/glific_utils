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
import json
import re
from pathlib import Path
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from string import Template

from cards import flow_card, node_chips  # noqa: F401
from flow_reading import FlowGraph, summarise, webhook_desc  # noqa: F401
from graph_svg import graph_svg  # noqa: F401
from model import GRAPH_CAP, Model, Settings, setting_starts  # noqa: F401
from schedules import WEEKDAYS, schedule_text, window_text  # noqa: F401
from sections import context_section, shared_resources, strip_section, tagging_gaps  # noqa: F401
from text import esc, fmt_day, join, names, plural, typo  # noqa: F401

ASSETS = Path(__file__).resolve().parent / "assets"   # page markup, styles and scripts, inlined at build time


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


def graph_section(m, edges, findings):
    """The map drawn as a graph: small nodes, edges laid out left to right, details on click."""
    svg, tpls = graph_svg(m, edges, findings)
    html_ = ('<p class="ghint">Each box is a flow, and time runs left to right. Solid arrows start a flow, '
             'dashed arrows hand over data through a contact field. Select a box to read what it does.</p>'
             f'<div class="gscroll">{svg}</div>'
             '<aside id="panel" class="panel" aria-live="polite" hidden><button type="button" class="close" aria-label="Close">\u00d7</button>'
             '<div id="panel-body"></div></aside>' + "".join(tpls))
    return html_, GRAPH_JS


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


PAGE = (ASSETS / "graph_page.html").read_text(encoding="utf-8")


GRAPH_JS = (ASSETS / "graph.js").read_text(encoding="utf-8")
