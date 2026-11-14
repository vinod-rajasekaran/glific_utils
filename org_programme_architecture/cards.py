"""Flow, trigger and keyword cards, and the one-line summary on each graph box."""
from collections import Counter, defaultdict

from schedules import earlier_runs, schedule_text, schedule_title, window_text
from text import cap_words, esc, join, names, plural, sentence, times, typo


def row(label, text, cls=""):
    if not text:
        return ""
    return f'<div class="r"><span class="k {cls}">{esc(label)}</span><span>{esc(typo(cap_words(text)))}</span></div>'


def flow_rows(m, u, view=None):
    """The rows of a flow's card, as seen from the graph it is drawn in (the model's main view by default)."""
    on_map = (view or m.view).on_map
    s, f = m.sum[u], m.flows[u]
    calls = join([f"{c}{times(n)}" for c, n in Counter(s["calls"]).items()], 4)
    sends = []
    if s["messages"]:
        sends.append(plural(len(s["messages"]), "message"))
    if s["interactive"]:
        sends.append(f"{plural(len(s['interactive']), 'interactive message')} ({join(s['interactive'], 3)})")
    if s["templates"]:
        sends.append(join(s["templates"], 3))
    moves = defaultdict(list)   # (direction, groups, subject, verb) -> values
    for direction, groups, cond in s["moves"]:
        subject, verb, value = cond or ("", "", "")
        moves[(direction, groups, subject, verb)].append(value)
    clauses = []
    for (d, groups, subject, verb), values in moves.items():
        values = [v for v in dict.fromkeys(values) if v]
        when = f" when {subject} {(verb + ' ') if verb else ''}{join(values, 3, 'or')}" if subject and values else ""
        clauses.append(f"{d} {join(groups, 4)}{when}")
    move_txt = "; ".join(clauses)
    starts = Counter(name for v, name in s["starts"] if v != u)
    used = m.callers.get(u) or Counter()
    used_txt = join([f"{m.name(c)}{times(n)}" for c, n in sorted(used.items(), key=lambda cn: (-cn[1], m.name(cn[0]).lower()))], 5)
    if used and sum(used.values()) > len(used):
        used_txt = f"Called {sum(used.values())} times: " + join([f"{n} in {m.name(c)}" for c, n in sorted(used.items(), key=lambda cn: (-cn[1], m.name(cn[0]).lower()))], 5)
    by_reader = defaultdict(list)
    for w, v, fld in m.data_links:
        if w == u:
            by_reader[v].append(fld)
    feeds = [f"{m.name(v)} reads {join(fs, 4)}" for v, fs in by_reader.items()]
    reads = [f"reads {fld} set by {m.name(w)}" for w, v, fld in m.data_links if v == u and w not in on_map]
    notes = []
    if not f.get("nodes"):
        notes.append("No definition was exported for this flow")
    elif s["lost"]:
        notes.append(f"Holds {join(s['lost'], 3)} that no path reaches, so it never runs")
    elif s["unreachable"]:
        notes.append(f"{plural(s['unreachable'], 'node')} that no path reaches")
    if s["other"]:
        notes.append("Has unrecognised steps: " + join([f"{k}{times(n)}" for k, n in Counter(s["other"]).items()], 4))
    if reads:
        notes.append(sentence(join(reads, 2)))
    trig = ""
    if m.active_trig.get(u) and u not in on_map:
        trig = "Active: " + "; ".join(schedule_text(t, m.tz, m.findings) for t in m.active_trig[u])
    elif u not in m.active_trig and m.earlier_trig.get(u):
        trig = "None active. " + earlier_runs(m.earlier_trig[u], m.tz)
    route_parts = []
    if s["waits"]:
        route_parts.append(f"Waits for a reply at {plural(s['waits'], 'point')}")
    if s["routes"]:
        route_parts.append(f"Branches on {join(s['routes'], 1)}")
    if s["random"]:
        route_parts.append(f"Picks one of {s['random'][0]} branches at random")
    routes = ". ".join(route_parts)
    return "".join([
        row("Calls", calls),
        row("Sends", sentence(join(sends, 3))),
        row("Routes", routes),
        row("Sets", join(s["sets"], 8)),
        row("Counts", join(s["counts"], 5)),
        row("Moves", sentence(f"contact {move_txt}") if move_txt else "", "mv"),
        row("Logs", sentence(join(s["logs"], 4))),
        row("Alerts", sentence(join(s["alerts"], 3)), "wn"),
        row("Labels", join(s["labels"], 5)),
        row("Ticket", sentence(join(s["tickets"], 2))),
        row("Starts", join([f"{n}{times(c)}" for n, c in starts.items()], 5)),
        row("Feeds", sentence("; ".join(feeds))),
        row("Used by", used_txt),
        row("Trigger", trig),
        row("Setting", "; ".join(text for _, text in m.setting_starts.get(u, []))),
        row("Note", ". ".join(notes), "wn"),
    ])


def tag_pill(m, u):
    label = m.tag_label(u)
    return f'<span class="tag">{esc(label)}</span>' if label else '<span class="tag no">No tag</span>'


def flow_card(m, u, view=None):
    return (f'<article class="card"><div class="ch"><h3>{esc(m.name(u))}</h3>{tag_pill(m, u)}</div>'
            f'{flow_rows(m, u, view)}</article>')


def trigger_card(m, u, findings):
    ts = m.active_trig[u]
    blocks = []
    for t in ts:
        groups = join(names(t.get("groups")) + names(t.get("waGroups")), 4)
        blocks.append(row("Runs", schedule_text(t, m.tz, findings)) + row("Group", groups) + row("Window", window_text(t, m.tz)))
    body = '<div class="sep"></div>'.join(blocks) + row("Starts", m.name(u))
    kw = m.keywords(u)
    if kw:
        body += row("Keyword", f"Also starts when a contact sends {join(kw, 20, 'or')}")
    if m.earlier_trig.get(u):
        body += f'<details><summary>Earlier runs</summary><p>{esc(typo(earlier_runs(m.earlier_trig[u], m.tz)))}</p></details>'
    return (f'<article class="card trigger">'
            f'<div class="ch"><h3>{esc(schedule_title(ts))}</h3><span class="pill">Active</span></div>{body}</article>')


def keyword_card(m, u):
    kw = m.keywords(u)
    runs = f"When a contact sends {join(kw, 30, 'or')}"
    return (f'<article class="card trigger">'
            f'<div class="ch"><h3>Keyword message</h3><span class="pill">Active</span></div>'
            f'{row("Runs", runs)}{row("Starts", m.name(u))}</article>')


def node_chips(m, u):
    s = m.sum[u]
    chips = []
    if s["calls"]:
        chips.append(("webhook", ""))
    n = len(s["messages"]) + len(s["templates"]) + len(s["interactive"])
    if n:
        chips.append((f"{n} send" + ("" if n == 1 else "s"), ""))
    if s["waits"]:
        chips.append((f"{s['waits']} wait" + ("" if s["waits"] == 1 else "s"), ""))
    if s["moves"]:
        chips.append(("moves", "mv"))
    if s["alerts"]:
        chips.append(("alerts", "wn"))
    if s["logs"]:
        chips.append(("sheet", ""))
    if s["lost"]:
        chips.append(("unreachable step", "wn"))
    out, used = [], 0
    for text, cls in chips:   # fit about 34 characters
        if used + len(text) > 34:
            break
        out.append((text, cls))
        used += len(text) + 3
    return out
