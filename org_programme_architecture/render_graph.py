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
}
@media (min-width:700px) and (max-width:1099px){
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
