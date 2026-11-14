"""Facts about every flow, with stable IDs and cleaned excerpts, for the programme step.

    build_facts(model) -> dict     everything Claude may read, and the IDs it may cite
    clean_text(text, staff_names)  privacy cleaning applied to every excerpt

The facts are the only thing sent to Claude, and every reference Claude makes is checked
against them. Numbers, links, schedules and groups on the page also come from here or from
the model, never from Claude.
"""
import json
from collections import Counter

from privacy import _host, clean_text, staff_names  # noqa: F401  (re-exported for callers and tests)

from render_graph import join, names, schedule_text, times

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
    staff = staff_names(m.flows)
    order = sorted(m.scope, key=lambda u: (m.name(u).lower(), u))
    flows, edges, groups, triggers, hosts = [], [], {}, [], set()

    def group(name):
        return groups.setdefault(name, {"id": f"group:{name}", "name": name, "added_by": [], "removed_by": [], "triggers": [], "checked_by": []})

    for t in m.triggers:
        fl = (t.get("flow") or {}).get("uuid")
        if fl not in m.scope:
            continue
        active = t in m.active_trig.get(fl, [])
        gs = names(t.get("groups")) + names(t.get("waGroups"))
        tid = f"trigger:{t.get('id')}"
        triggers.append({"id": tid, "flow": fl, "schedule": schedule_text(t, m.tz, []), "groups": gs, "active": active})
        for g in gs:
            group(g)
        if active:
            edges.append({"id": f"edge:{tid}:{fl}:start", "from": tid, "to": fl, "kind": "start"})
            for g in gs:
                group(g)["triggers"].append(tid)
                edges.append({"id": f"edge:group:{g}:{tid}:schedule", "from": f"group:{g}", "to": tid, "kind": "schedule"})

    for u in order:
        s, f = m.sum[u], m.flows[u]
        starts_from = []
        for t in m.active_trig.get(u, []):
            gs = join(names(t.get("groups")) + names(t.get("waGroups")), 4) or "no group"
            starts_from.append({"kind": "trigger", "ref": f"trigger:{t.get('id')}", "text": f"{schedule_text(t, m.tz, [])}, to {gs}"})
        for _, text in m.setting_starts.get(u, []):
            starts_from.append({"kind": "setting", "ref": "", "text": text})
        if f.get("keywords"):
            starts_from.append({"kind": "keyword", "ref": "", "text": "a contact sends " + join(f["keywords"], 20, "or")})
        for c, n in sorted(m.callers.get(u, {}).items(), key=lambda cn: m.name(cn[0]).lower()):
            starts_from.append({"kind": "flow", "ref": c, "text": f"{m.name(c)} enters it{times(n)}"})
        if not starts_from:
            starts_from.append({"kind": "none", "ref": "", "text": "No trigger, keyword or flow in the export starts it"})

        leads_to = []
        for v, n in sorted(Counter(v for v, _ in s["starts"] if v != u and v in m.flows).items(), key=lambda vn: m.name(vn[0]).lower()):
            leads_to.append({"kind": "flow", "ref": v, "text": f"enters {m.name(v)}{times(n)}"})
            edges.append({"id": f"edge:{u}:{v}:start", "from": u, "to": v, "kind": "start"})
        for w, v, fld in m.data_links:
            if w == u:
                leads_to.append({"kind": "data", "ref": v, "text": f"sets {fld}, which {m.name(v)} reads"})
                eid = f"edge:{u}:{v}:data"
                if not any(e["id"] == eid for e in edges):
                    edges.append({"id": eid, "from": u, "to": v, "kind": "data"})
        for direction, gs, cond in s["moves"]:
            for g in gs:
                if g == "all groups":
                    continue
                rec = group(g)
                (rec["added_by"] if direction == "into" else rec["removed_by"]).append(u)
                leads_to.append({"kind": "group", "ref": f"group:{g}", "text": _move_text(direction, (g,), cond)})
                kind = "adds" if direction == "into" else "removes"
                eid = f"edge:{u}:group:{g}:{kind}"
                if not any(e["id"] == eid for e in edges):
                    edges.append({"id": eid, "from": u, "to": f"group:{g}", "kind": kind})

        for n in f.get("nodes") or []:
            for case in (n.get("router") or {}).get("cases") or []:
                if case.get("type") == "has_group" and case.get("arguments"):
                    rec = group(str(case["arguments"][-1]))
                    if u not in rec["checked_by"]:
                        rec["checked_by"].append(u)
            for a in n.get("actions") or []:
                if a.get("type") == "call_webhook" and "://" in str(a.get("url") or ""):
                    host = _host(str(a["url"]).strip())
                    if host != "[link]":
                        hosts.add(host)

        route = []
        if s["waits"]:
            route.append(f"waits for a reply at {s['waits']} points")
        route += [f"branches on {r}" for r in s["routes"]]
        flows.append({
            "id": u,
            "name": m.name(u),
            "tag": m.tag_label(u),
            "keywords": list(f.get("keywords") or []),
            "starts_from": starts_from,
            "leads_to": leads_to,
            "touches": _touches(m, u),
            "routes": route,
            "unreachable": list(s["lost"]),
            "earlier_triggers": len(m.earlier_trig.get(u, [])),
            "excerpts": _excerpts(f, u, staff),
        })

    for rec in groups.values():
        rec["added_by"] = sorted(set(rec["added_by"]), key=lambda u: m.name(u).lower())
        rec["removed_by"] = sorted(set(rec["removed_by"]), key=lambda u: m.name(u).lower())
    findings = [clean_text(x, staff, 400) for x in m.findings]
    for u in order:
        if m.sum[u]["lost"]:
            findings.append(f"{m.name(u)} holds {join(m.sum[u]['lost'], 3)} that no path reaches.")
    return {
        "flows": flows,
        "groups": sorted(groups.values(), key=lambda g: g["name"].lower()),
        "triggers": triggers,
        "edges": edges,
        "hosts": sorted(h for h in hosts if h),
        "findings": list(dict.fromkeys(findings)),
    }
