"""Facts about every flow, with stable IDs and cleaned excerpts, for the programme step.

    build_facts(model) -> dict     everything Claude may read, and the IDs it may cite
    clean_text(text, staff_names)  privacy cleaning applied to every excerpt

The facts are the only thing sent to Claude, and every reference Claude makes is checked
against them. Numbers, links, schedules and groups on the page also come from here or from
the model, never from Claude.
"""
import json
from collections import Counter

from privacy import clean_text, host_of, mask, staff_names  # noqa: F401  (re-exported for callers and tests)

from schedules import schedule_text
from text import join, names, times

MAX_EXCERPTS = 25                                   # per flow: sticky notes first, then messages in order


def _excerpts(flow, uid, staff):
    out = []
    count = Counter()

    def add(kind, prefix, text):
        text = clean_text(text, staff)
        if text:
            count[prefix] += 1
            out.append({"id": f"{prefix}:{uid}:{count[prefix]}", "kind": kind, "text": text})

    for n in flow.get("nodes") or []:
        for a in n.get("actions") or []:
            kind = a.get("type")
            tpl = ((a.get("templating") or {}).get("template") or {}).get("name")
            if kind == "send_msg":
                if tpl:
                    add("template", "tpl", f"template {tpl}")
                add("message", "msg", a.get("text"))
            elif kind == "send_broadcast":
                add("template", "tpl", f"staff alert template {tpl}" if tpl else f"staff alert: {a.get('text') or ''}")
            elif kind == "send_interactive_msg":
                add("interactive", "int", _interactive_text(a))
    stickies = []
    for st in ((flow.get("ui") or {}).get("stickies") or {}).values():
        if isinstance(st, dict):
            text = clean_text(" ".join(str(st.get(k) or "") for k in ("title", "body")), staff)
            if text:
                stickies.append({"id": f"sticky:{uid}:{len(stickies) + 1}", "kind": "sticky", "text": text})
    return (stickies + out)[:MAX_EXCERPTS]   # designers' notes say most about intent, so they go first


def _interactive_text(a):
    raw = a.get("text")
    try:
        msg = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError:
        return f"{a.get('name') or ''}: {raw}"
    if not isinstance(msg, dict):            # a number, a list or null: show it as text
        return f"{a.get('name') or 'interactive'}: {raw}"
    content = msg.get("content") if isinstance(msg.get("content"), dict) else {}
    body = content.get("text") or content.get("caption") or content.get("header") or msg.get("body") or ""
    opts = [o.get("title") for o in msg.get("options") or [] if isinstance(o, dict)]
    for item in msg.get("items") or []:
        if isinstance(item, dict):
            opts += [o.get("title") for o in (item.get("options") or []) if isinstance(o, dict)]
    text = f"{a.get('name') or 'interactive'}: {body}"
    if opts:
        text += " Options: " + ", ".join(str(o) for o in opts if o)
    return text


def _touches(m, u):
    s = m.sum[u]
    out = [f"calls {c}{times(n)}" for c, n in Counter(s["calls"]).items()]
    out += [str(x) for x in s["logs"]]
    if s["sets"]:
        out.append("sets fields " + join(sorted(set(s["sets"])), 12))
    if s["counts"]:
        out.append("counts in fields " + join(sorted(set(s["counts"])), 8))
    out += [f"staff alert: {x}" for x in s["alerts"]]
    if s["labels"]:
        out.append("labels " + join(sorted(set(s["labels"])), 8))
    out += [str(x) for x in s["tickets"]]
    return out


def _move_text(direction, groups, cond):
    verb = "adds contacts to" if direction == "into" else "removes contacts from"
    text = f"{verb} {join(list(groups), 4)}"
    if cond and cond[0] and cond[2]:
        text += f" when {cond[0]} {(cond[1] + ' ') if cond[1] else ''}{cond[2]}"
    return text


def build_facts(m):
    """Facts for every flow in the model's scope (use Settings(scope_all=True) for the whole export)."""
    return _Facts(m).build()


class _Facts:
    """Builds the facts in one pass: triggers first, then each flow in name order. Groups and
    edges are collected along the way, keyed by the IDs Claude must cite."""

    def __init__(self, m):
        self.m = m
        self.staff = m.staff
        self.order = sorted(m.scope, key=m.name_key)
        self.edges, self.groups, self.triggers, self.hosts = [], {}, [], set()

    def group(self, name):
        return self.groups.setdefault(name, {"id": f"group:{name}", "name": name, "added_by": [], "removed_by": [],
                                             "triggers": [], "checked_by": []})

    def add_edge(self, eid, frm, to, kind, once=False):
        if once and any(e["id"] == eid for e in self.edges):
            return
        self.edges.append({"id": eid, "from": frm, "to": to, "kind": kind})

    def build(self):
        m = self.m
        self.add_triggers()
        flows = [self.flow(u) for u in self.order]
        for rec in self.groups.values():
            rec["added_by"] = sorted(set(rec["added_by"]), key=m.by_name)
            rec["removed_by"] = sorted(set(rec["removed_by"]), key=m.by_name)
        findings = [clean_text(x, self.staff, 400) for x in m.findings]
        findings += [f"{m.name(u)} holds {join(m.sum[u]['lost'], 3)} that no path reaches." for u in self.order if m.sum[u]["lost"]]
        return {
            "flows": flows,
            "groups": sorted(self.groups.values(), key=lambda g: g["name"].lower()),
            "triggers": self.triggers,
            "edges": self.edges,
            "hosts": sorted(h for h in self.hosts if h),
            "findings": list(dict.fromkeys(findings)),
        }

    def add_triggers(self):
        m = self.m
        for t in m.triggers:
            fl = (t.get("flow") or {}).get("uuid")
            if fl not in m.scope:
                continue
            active = t in m.active_trig.get(fl, [])
            gs = names(t.get("groups")) + names(t.get("waGroups"))
            tid = f"trigger:{t.get('id')}"
            self.triggers.append({"id": tid, "flow": fl, "schedule": schedule_text(t, m.tz, []), "groups": gs, "active": active})
            for g in gs:
                self.group(g)
            if active:
                self.add_edge(f"edge:{tid}:{fl}:start", tid, fl, "start")
                for g in gs:
                    self.group(g)["triggers"].append(tid)
                    self.add_edge(f"edge:group:{g}:{tid}:schedule", f"group:{g}", tid, "schedule")

    def starts_from(self, u):
        m = self.m
        out = []
        for t in m.active_trig.get(u, []):
            gs = join(names(t.get("groups")) + names(t.get("waGroups")), 4) or "no group"
            out.append({"kind": "trigger", "ref": f"trigger:{t.get('id')}", "text": f"{schedule_text(t, m.tz, [])}, to {gs}"})
        for _, text in m.setting_starts.get(u, []):
            out.append({"kind": "setting", "ref": "", "text": text})
        if m.keywords(u):
            out.append({"kind": "keyword", "ref": "", "text": "a contact sends " + join(m.keywords(u), 20, "or")})
        for c, n in sorted(m.callers.get(u, {}).items(), key=lambda cn: m.name(cn[0]).lower()):
            out.append({"kind": "flow", "ref": c, "text": f"{m.name(c)} enters it{times(n)}"})
        return out or [{"kind": "none", "ref": "", "text": "No trigger, keyword or flow in the export starts it"}]

    def leads_to(self, u):
        m, s = self.m, self.m.sum[u]
        out = []
        for v, n in sorted(Counter(v for v, _ in s["starts"] if v != u and v in m.flows).items(), key=lambda vn: m.name(vn[0]).lower()):
            out.append({"kind": "flow", "ref": v, "text": f"enters {m.name(v)}{times(n)}"})
            self.add_edge(f"edge:{u}:{v}:start", u, v, "start")
        for w, v, fld in m.data_links:
            if w == u:
                out.append({"kind": "data", "ref": v, "text": f"sets {fld}, which {m.name(v)} reads"})
                self.add_edge(f"edge:{u}:{v}:data", u, v, "data", once=True)
        for direction, gs, cond in s["moves"]:
            for g in gs:
                if g == "all groups":
                    continue
                rec = self.group(g)
                (rec["added_by"] if direction == "into" else rec["removed_by"]).append(u)
                out.append({"kind": "group", "ref": f"group:{g}", "text": _move_text(direction, (g,), cond)})
                kind = "adds" if direction == "into" else "removes"
                self.add_edge(f"edge:{u}:group:{g}:{kind}", u, f"group:{g}", kind, once=True)
        return out

    def scan_nodes(self, u):
        """Groups that routers check, and webhook hosts."""
        for n in self.m.flows[u].get("nodes") or []:
            for case in (n.get("router") or {}).get("cases") or []:
                if case.get("type") == "has_group" and case.get("arguments"):
                    rec = self.group(mask(str(case["arguments"][-1])))   # masked like every group name
                    if u not in rec["checked_by"]:
                        rec["checked_by"].append(u)
            for a in n.get("actions") or []:
                if a.get("type") == "call_webhook" and "://" in str(a.get("url") or ""):
                    host = host_of(str(a["url"]).strip())
                    if host != "[link]":
                        self.hosts.add(host)

    def flow(self, u):
        m, s, f = self.m, self.m.sum[u], self.m.flows[u]
        starts_from, leads_to = self.starts_from(u), self.leads_to(u)
        self.scan_nodes(u)
        route = ([f"waits for a reply at {s['waits']} points"] if s["waits"] else []) + [f"branches on {r}" for r in s["routes"]]
        return {
            "id": u,
            "name": m.name(u),
            "tag": m.tag_label(u),
            "keywords": m.keywords(u),
            "starts_from": starts_from,
            "leads_to": leads_to,
            "touches": _touches(m, u),
            "routes": route,
            "unreachable": list(s["lost"]),
            "earlier_triggers": len(m.earlier_trig.get(u, [])),
            "excerpts": _excerpts(f, u, self.staff),
        }
