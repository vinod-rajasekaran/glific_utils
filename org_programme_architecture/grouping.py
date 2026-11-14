"""Groups of flows worked out from the export alone, for runs without Claude.

    group_answer(model, reason) -> dict     the same shape as Claude's validated answer

Flows belong together when one starts the other, when one hands data to the other through a
contact field, or when one adds contacts to a group that a schedule starting the other sends to.
A flow that starts nothing and is started from several places (a shared helper) joins the group
holding most of its callers, so it does not glue unrelated groups together; a data hand-over to
a flow started only by a keyword (often a test copy) does not join groups either. A flow linked
to nothing joins the group whose main tag it carries; the rest are listed as not connected.
"""
import re
from collections import Counter, defaultdict

from text import plural

NOT_CONNECTED = "Not connected"


def _union_find(items):
    parent = {u: u for u in items}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def union(a, b):
        parent[find(a)] = find(b)
    return parent, find, union


def group_flows(m):
    """[(name, [flow uuids])], biggest group first, not-connected flows last."""
    flows = sorted(m.flows, key=m.name_key)
    parent, find, union = _union_find(flows)
    starts = {u: [v for v, _ in m.sum[u]["starts"] if v in m.flows and v != u] for u in flows}
    shared = {v for v in flows if not starts[v] and len(m.all_callers[v]) >= 2}
    keyword_only = {u for u in flows if m.keywords(u) and not m.active_trig.get(u) and u not in m.setting_starts and not m.all_callers[u]}

    for u in flows:
        for v in starts[u]:
            if v not in shared:
                union(u, v)
    for w, r, _ in m.data_links:
        if w not in keyword_only and r not in keyword_only:
            union(w, r)
    scheduled = defaultdict(set)             # group name -> flows whose active schedules send to it
    for u in flows:
        for t in m.active_trig.get(u, []):
            for g in t.get("groups") or []:
                scheduled[g].add(u)
    for u in flows:
        for direction, gs, _ in m.sum[u]["moves"]:
            if direction == "into":
                for g in gs:
                    for v in sorted(scheduled.get(g, ())):
                        union(u, v)
    for v in sorted(shared, key=m.name_key):  # a shared helper joins where most of its callers are
        roots = Counter(find(c) for c in m.all_callers[v])
        parent[v] = max(roots.items(), key=lambda kv: (kv[1], kv[0]))[0]

    members = defaultdict(list)
    for u in flows:
        members[find(u)].append(u)
    groups = [us for us in members.values() if len(us) > 1]
    loose = [us[0] for us in members.values() if len(us) == 1]
    main_tag = [_main_tag(m, us) for us in groups]
    leftover = []
    for u in loose:                           # an unlinked flow joins the one group whose main tag it carries
        tag = m.tag_label(u)
        matches = [i for i, t in enumerate(main_tag) if tag and t == tag]
        if len(matches) == 1:
            groups[matches[0]].append(u)
        else:
            leftover.append(u)
    groups.sort(key=lambda us: (-len(us), m.name_key(us[0])))
    out = [(_name(m, us), sorted(us, key=m.name_key)) for us in groups]
    if leftover:
        out.append((NOT_CONNECTED, sorted(leftover, key=m.name_key)))
    return out


def _main_tag(m, us):
    """The tag at least half the group's flows carry, if any."""
    tags = Counter(m.tag_label(u) for u in us if m.tag_label(u))
    if tags:
        tag, n = tags.most_common(1)[0]
        if n * 2 >= len(us):
            return tag
    return ""


def _name(m, us):
    tag = _main_tag(m, us)
    if tag:
        return tag
    entries = [u for u in us if m.active_trig.get(u) or m.keywords(u) or u in m.setting_starts or not m.all_callers[u]]
    first = min(entries or us, key=lambda u: (-sum(1 for v in us if v in _reach(m, u)), m.name_key(u)))
    return f"Starts at {m.name(first)}"


def _reach(m, u):
    seen, stack = set(), [u]
    while stack:
        x = stack.pop()
        if x not in seen:
            seen.add(x)
            stack += [v for v, _ in m.sum[x]["starts"] if v in m.flows]
    return seen


def _slug(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "group"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def group_answer(m, reason):
    """The groups in the shape of Claude's validated answer, marked as worked out without Claude."""
    taken, use_cases = set(), []
    for name, us in group_flows(m):
        gid = _slug(name, taken)
        if name == NOT_CONNECTED:
            summary, kind = "Flows that no other flow starts or shares data with, and no schedule reaches through a group.", "tests"
        else:
            summary = f"{plural(len(us), 'flow')} that start each other, hand over data or fill a group a schedule sends to."
            kind = "journey"
        use_cases.append({"id": gid, "name": name, "summary": summary, "kind": kind, "flows": us,
                          "story": [], "how_it_works": [], "watch": [], "confidence": "guess"})
    uc_of = {u: c["id"] for c in use_cases for u in c["flows"]}
    return {
        "source": "structure", "reason": reason, "model": "",
        "org_summary": {"text": "", "evidence": [], "confidence": "guess"},
        "programmes": [{"id": c["id"], "name": c["name"], "summary": c["summary"], "kind": c["kind"], "parts": [c["id"]],
                        "story": [], "watch": [], "confidence": "guess"} for c in use_cases],
        "use_cases": use_cases,
        "flows": [{"id": u, "purpose": "", "role": "unknown", "use_case": uc_of.get(u, ""), "evidence": [], "confidence": "guess"}
                  for u in sorted(m.flows, key=m.name_key)],
        "not_placed": [], "edges": [], "systems": [],
    }
