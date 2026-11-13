"""The use-case page: the org's use cases first, then each one as a graph with a side pane.

    render_usecase_page(model, facts, validated, dropped, settings) -> html

Everything Claude wrote is shown under "Claude's reading" with its confidence, and each
statement opens to the evidence it cites. Every number, link, schedule and group comes from
the model and the facts, not from Claude.
"""
import json
import re
from collections import Counter
from datetime import datetime
from string import Template

from render_architecture import (PAGE, _Balance, esc, flow_card, fmt_day, graph_svg, join, plural,
                                 shared_resources, typo)
from usecase_claude import MODEL

BASE_CSS = re.search(r"<style>(.*?)</style>", PAGE, re.S).group(1)
ROLE_LABEL = {"core": "Core", "helper": "Helper", "shared": "Shared", "test": "Test", "leftover": "Leftover", "unknown": "Role unclear"}
CONF_LABEL = {"clear": "clear", "likely": "likely", "guess": "a guess"}


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


def pills(cx, u, tag):
    m, members = cx.m, set(u["flows"])
    out = [(plural(len(members), "flow"), "")]
    kinds = Counter()
    for fid in members:
        for s in cx.flow[fid]["starts_from"]:
            if s["kind"] == "flow" and s["ref"] in members:
                continue
            kinds[s["kind"]] += 1
    names = {"trigger": "Schedule", "setting": "Glific setting", "keyword": "Keyword", "flow": "Started from another use case",
             "none": "No start found"}
    out += [(names[k], "warn" if k == "none" else "") for k in ("trigger", "setting", "keyword", "flow", "none") if kinds[k]]
    hosts, functions, sheets, alerts, groups = set(), False, False, False, set()
    for fid in members:
        s = m.sum[fid]
        for c in s["calls"]:
            if c.startswith("Glific function"):
                functions = True
            else:
                hosts.add(c.split(" ")[0].split(":")[0])
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
    if alerts:
        out.append(("Staff alerts", "warn"))
    if groups:
        out.append(("Groups: " + join(sorted(groups), 3), ""))
    if tag:
        untagged = sum(1 for fid in members if not cx.m.tagged(fid))
        if untagged:
            out.append((f"{untagged} of {len(members)} without the {tag} tag", "warn"))
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


def flow_pane(cx, fid, findings):
    f, c = cx.flow[fid], cx.claude_flow.get(fid, {})
    head = (f'<div class="fp-head"><h3>{t(f["name"])}</h3><span class="role r-{esc(c.get("role", "unknown"))}">'
            f'{esc(ROLE_LABEL.get(c.get("role", "unknown"), "Role unclear"))}</span></div>')
    purpose = ""
    if c.get("purpose"):
        items = "".join(cx.evidence_item(r) for r in c.get("evidence", []))
        purpose = (f'<p class="purpose">{claude_label(c.get("confidence", "guess"))}<br>{t(c["purpose"])}</p>'
                   + (f'<details class="evd"><summary>Evidence</summary><ul>{items}</ul></details>' if items else ""))
    home = cx.uc_of.get(fid)
    where = f'<p class="muted">Use case: <a href="#uc-{esc(home)}">{t(cx.uc_name[home])}</a></p>' if home else '<p class="muted">Not placed in a use case.</p>'

    def io(items, heading):
        rows = []
        for s in items:
            link = ""
            if s["kind"] in ("flow", "data") and s["ref"] in cx.flow:
                other = cx.uc_of.get(s["ref"])
                if other and other != home:
                    link = f' <a href="#uc-{esc(other)}">({t(cx.uc_name[other])})</a>'
            for eid in (f"edge:{s['ref']}:{fid}:start", f"edge:{fid}:{s['ref']}:start"):
                if eid in cx.edge_meaning:
                    link += f' <span class="meaning">(Claude: {t(cx.edge_meaning[eid])})</span>'
            rows.append(f"<li>{t(s['text'])}{link}</li>")
        return f'<h4>{esc(heading)}</h4><ul class="io">{"".join(rows)}</ul>' if rows else ""

    card = re.sub(r' data-id="[^"]*"', "", flow_card(cx.m, fid, placed=False))
    return (head + purpose + where + io(f["starts_from"], "How it starts") + io(f["leads_to"], "Where it leads")
            + card)


def usecase_view(cx, u, findings, tag):
    m, members = cx.m, list(u["flows"])
    near = neighbours(cx, set(members))
    m.graph_view(set(members) | near)
    svg, tpls = graph_svg(m, m.edges(), findings, ns=f"{u['id']}-", faded=near)
    panes = "".join(f'<template id="pane-{esc(u["id"])}-f-{esc(fid)}">{flow_pane(cx, fid, findings)}</template>'
                    for fid in sorted(m.on_map, key=lambda x: cx.flow[x]["name"].lower()) if fid in cx.flow)
    story = (f'<div class="pane-story"><p class="muted">{claude_label(u["confidence"])}</p>'
             + statements(cx, "What happens", u["story"])
             + statements(cx, "How it works", u["how_it_works"])
             + statements(cx, "What to watch", u["watch"], " w")
             + '<p class="hint">Select a box in the graph to see that flow in detail. Faded boxes belong to other use cases.</p></div>')
    cards = "".join(f'<div class="fcard" id="card-{esc(u["id"])}-{esc(fid)}">{flow_pane(cx, fid, findings)}</div>' for fid in members)
    return (f'<section class="ucview" id="uc-{esc(u["id"])}" hidden>'
            f'<p><a class="back" href="#">← All use cases</a></p>'
            f'<h2>{t(u["name"])}</h2><p class="lede2"><span class="reading">Claude\u2019s reading</span><br>{t(u["summary"])}</p><div class="pills">{pills(cx, u, tag)}</div>'
            f'<div class="ucgrid"><div class="gscroll">{svg}</div>'
            f'<aside class="pane" aria-live="polite"><button type="button" class="pane-back" hidden>← Back to the story</button>'
            f'<div class="pane-body">{story}</div><template class="story-tpl">{story}</template></aside></div>'
            f'<h3 class="sub">Every flow in this use case</h3><div class="fcards">{cards}</div>'
            + "".join(tpls) + panes + "</section>")


def render_usecase_page(m, facts, uc, dropped, st):
    cx = _Ctx(m, facts, uc)
    findings = list(m.findings)
    order = sorted(uc["use_cases"], key=lambda u: u["kind"] == "tests")
    cards = "".join(
        f'<a class="uccard{" muted-card" if u["kind"] == "tests" else ""}" href="#uc-{esc(u["id"])}">'
        f'<h3>{t(u["name"])}</h3><p><span class="reading">Claude\u2019s reading</span><br>{t(u["summary"])}</p>'
        f'<div class="pills">{pills(cx, u, st.tag)}</div></a>'
        for u in order)
    views = "".join(usecase_view(cx, u, findings, st.tag) for u in order)

    org = uc["org_summary"]
    org_items = "".join(cx.evidence_item(r) for r in org["evidence"])
    org_html = (f'<div class="org"><p class="muted">{claude_label(org["confidence"])}</p><p>{t(org["text"])}</p>'
                + (f'<details class="evd"><summary>Evidence</summary><ul>{org_items}</ul></details>' if org_items else "") + "</div>")

    not_placed = ""
    if uc["not_placed"]:
        rows = "".join(f'<li><b>{t(cx.flow[f]["name"])}</b>{": " + t(cx.claude_flow[f]["purpose"]) if cx.claude_flow.get(f, {}).get("purpose") else ""}</li>'
                       for f in uc["not_placed"])
        not_placed = f'<section class="sect"><h2>Not placed</h2><p>Claude could not tell which use case these flows belong to.</p><ul class="plain">{rows}</ul></section>'
    dropped_html = ""
    if dropped:
        dropped_html = (f'<section class="sect"><details><summary>Dropped by validation ({len(dropped)})</summary>'
                        '<p>These parts of Claude’s answer referred to things that are not in the export, or had no evidence, so they are not shown.</p>'
                        f'<ul class="plain">{"".join(f"<li>{t(d)}</li>" for d in dropped)}</ul></details></section>')

    active_n = sum(map(len, m.active_trig.values()))
    lede = (f"{plural(len(facts['flows']), 'active flow')} in the export, grouped by Claude into "
            f"{plural(len(uc['use_cases']), 'use case')}. {plural(active_n, 'trigger')} "
            f"{'is' if active_n == 1 else 'are'} active on {fmt_day(datetime.combine(st.today, datetime.min.time()))}. "
            f"Times are in {m.tz_label}.")
    footer = " ".join(x for x in [st.footer.strip(), f"Use cases and descriptions by Claude ({MODEL}); every number, link and "
                                  "schedule comes from flows.json and triggers.json. Generated by glific_utils."] if x)
    page = Template(UC_PAGE).substitute(
        css=BASE_CSS + UC_CSS, title=esc(f"{st.project} use cases"), h1=t(f"{st.project}: what the bot does"),
        lede=t(lede), org=org_html, cards=cards, shared=shared_resources(m), not_placed=not_placed,
        dropped=dropped_html, views=views, footer=t(footer),
        uc_of=json.dumps({f"f-{k}": v for k, v in cx.uc_of.items()}).replace("</", "<\\/"))
    b = _Balance()
    b.feed(page)
    if b.errors or b.stack:
        raise ValueError(f"Use-case page tags do not balance: {b.errors[:3]} open={b.stack[-3:]}")
    return page


UC_CSS = """
.uccards{display:grid;grid-template-columns:1fr;gap:16px;margin-top:8px}
.uccard{display:block;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px;color:var(--ink);text-decoration:none;transition:box-shadow .15s,border-color .15s}
.uccard:hover,.uccard:focus-visible{border-color:var(--flow);box-shadow:0 0 0 2px var(--flow);outline:none}
.uccard h3{margin-bottom:6px}
.uccard p{margin:0 0 10px;font-size:14px;color:var(--muted)}
.muted-card{opacity:.75}
.pills{display:flex;flex-wrap:wrap;gap:6px}
.pill2{font-size:12px;line-height:1;padding:5px 8px;border-radius:99px;border:1px solid var(--line);background:var(--soft);color:var(--ink)}
.pill2.sys{border-color:var(--slate);background:var(--slate-bg)}
.pill2.warn{border-color:var(--trig);background:var(--trig-bg);color:var(--trig)}
.pill2.claude{border-style:dashed}
.org{max-width:80ch;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 8px}
.org p{margin:4px 0}
.reading{font-size:12px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;color:var(--muted)}
.conf{font:inherit;font-size:11.5px;line-height:1;padding:3px 7px;border-radius:99px;border:1px solid var(--line);background:var(--surface);color:var(--muted);cursor:pointer;vertical-align:1px}
.conf.c-clear{border-color:var(--ok);color:var(--ok)}
.conf.c-likely{border-color:var(--flow);color:var(--flow)}
.conf.c-guess{border-color:var(--trig);color:var(--trig);border-style:dashed}
span.conf{cursor:default}
.muted{color:var(--muted);font-size:13.5px;margin:0 0 6px}
.lede2{color:var(--muted);max-width:80ch;margin:4px 0 10px}
.back,.pane-back{font-size:14px;color:var(--flow)}
.pane-back{font:inherit;font-size:14px;background:none;border:0;padding:0;margin:0 0 10px;cursor:pointer}
.ucgrid{display:grid;grid-template-columns:1fr;gap:18px;margin-top:14px}
.ucgrid .gscroll{margin-bottom:0;align-self:start}
.pane{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.ph{font-size:16px;margin:14px 0 6px}
.ph.w{color:var(--warn)}
.sts{margin:0;padding-left:18px}
.st{margin:0 0 8px;font-size:14px;line-height:1.5}
.ev{margin:6px 0 4px;padding:8px 10px 8px 22px;background:var(--soft);border-radius:8px;font-size:13px}
.ev li{margin:0 0 4px}
p.ev{padding-left:10px}
.hint{font-size:13px;color:var(--muted);margin:14px 0 0}
.fp-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:8px}
.role{font-size:12px;padding:4px 8px;border-radius:99px;border:1px solid var(--flow);color:var(--flow);white-space:nowrap}
.role.r-test,.role.r-leftover{border-color:var(--trig);color:var(--trig)}
.purpose{font-size:14px;margin:0 0 6px}
.evd{padding:0 0 8px;border:0;font-size:13px}
.evd ul{margin:6px 0 0;padding-left:18px}
.io{margin:0 0 8px;padding-left:18px;font-size:13.5px}
.io li{margin:0 0 3px}
.meaning{color:var(--muted);font-style:italic}
.pane h4{font-family:var(--head);font-size:14px;margin:10px 0 4px}
.pane .card{margin-top:10px}
.sub{margin:28px 0 10px}
.fcards{display:grid;grid-template-columns:1fr;gap:16px}
.fcard{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.plain{margin:0;padding-left:18px}
.plain li{margin:0 0 4px}
.fgraph .node.faded{opacity:.4}
.fgraph .node.faded rect{stroke-dasharray:4 3}
.fgraph .node.sel rect{stroke-width:3;stroke:var(--ink)}
@media (min-width:1100px){
  .uccards{grid-template-columns:repeat(3,minmax(0,1fr))}
  .ucgrid{grid-template-columns:minmax(0,1fr) 400px}
  .pane{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto}
  .fcards{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (min-width:700px) and (max-width:1099px){
  .uccards{grid-template-columns:repeat(2,minmax(0,1fr))}
}
"""

UC_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>$title</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Bricolage+Grotesque:wght@500;700&display=swap" rel="stylesheet">
<style>$css</style>
</head>
<body>
<div class="page">
<header>
  <h1>$h1</h1>
  <p class="lede">$lede</p>
</header>
<main>
<section id="home">
$org
<h2 style="margin:26px 0 6px">Use cases</h2>
<p class="muted">Names, summaries and dashed pills are Claude\u2019s reading of the flows. Everything else comes from the export.</p>
<div class="uccards">$cards</div>
$shared
</section>
$not_placed
$dropped
$views
</main>
<footer>$footer</footer>
</div>
<script>
(function(){
  var ucOf=$uc_of;
  var home=document.getElementById('home');
  var extras=[].slice.call(document.querySelectorAll('main > section.sect'));
  function show(){
    var h=location.hash.slice(1),view=h&&document.getElementById(h);
    var isView=!!(view&&view.classList.contains('ucview'));
    home.hidden=isView;extras.forEach(function(s){s.hidden=isView;});
    document.querySelectorAll('.ucview').forEach(function(v){v.hidden=(v!==view);});
    setTimeout(function(){window.scrollTo(0,0);},0);   // undo the browser's jump to the anchor
  }
  window.addEventListener('hashchange',show);
  window.addEventListener('load',function(){if(location.hash)setTimeout(function(){window.scrollTo(0,0);},0);});
  document.addEventListener('click',function(ev){
    var b=ev.target.closest('button.conf');
    if(b){var e=b.parentNode.querySelector('.ev');if(e){e.hidden=!e.hidden;b.setAttribute('aria-expanded',String(!e.hidden));}}
  });
  document.querySelectorAll('.ucview').forEach(function(view){
    var ns=view.id.slice(3)+'-',svg=view.querySelector('svg.fgraph'),pane=view.querySelector('.pane'),body=pane.querySelector('.pane-body');
    var back=pane.querySelector('.pane-back'),storyTpl=pane.querySelector('.story-tpl'),sel=null;
    var nodes={};svg.querySelectorAll('.node').forEach(function(n){nodes[n.getAttribute('data-id')]=n;});
    var wires=[].slice.call(svg.querySelectorAll('.edge'));
    function light(id){
      var near={};near[id]=1;
      wires.forEach(function(w){var a=w.getAttribute('data-from'),b=w.getAttribute('data-to');if(a===id)near[b]=1;if(b===id)near[a]=1;});
      Object.keys(nodes).forEach(function(k){nodes[k].classList.toggle('dim',!near[k]);});
      wires.forEach(function(w){var hot=w.getAttribute('data-from')===id||w.getAttribute('data-to')===id;w.classList.toggle('hot',hot);w.classList.toggle('dim',!hot);});
    }
    function clear(){
      if(sel){light(sel);return;}
      Object.keys(nodes).forEach(function(k){nodes[k].classList.remove('dim');});
      wires.forEach(function(w){w.classList.remove('hot','dim');});
    }
    function story(){
      if(sel&&nodes[sel])nodes[sel].classList.remove('sel');
      sel=null;body.innerHTML='';body.appendChild(storyTpl.content.cloneNode(true));back.hidden=true;clear();
    }
    function open(id){
      var n=nodes[id],key=id.slice(ns.length);
      if(n&&n.classList.contains('faded')&&ucOf[key]){location.hash='uc-'+ucOf[key];return;}
      var tpl=document.getElementById('pane-'+id)||document.getElementById('tpl-'+id);if(!tpl)return;
      if(sel&&nodes[sel])nodes[sel].classList.remove('sel');
      sel=id;if(n)n.classList.add('sel');
      body.innerHTML='';body.appendChild(tpl.content.cloneNode(true));back.hidden=false;light(id);pane.scrollTop=0;
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
    back.addEventListener('click',story);
    view.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&sel)story();});
  });
  show();
})();
</script>
</body>
</html>
"""
