"""Reading one flow definition: its nodes, reachability, and a summary of what it does."""
import re
from collections import defaultdict
from urllib.parse import urlsplit

from privacy import host_of, mask
from text import join, names, plural


GENERIC_RESULT = {"", "result", "webhook", "response", "results"}


FIELD_IN_OPERAND = re.compile(r"fields\.([A-Za-z0-9_]+)")


def webhook_desc(action):
    url = str(action.get("url") or "").strip()
    try:
        parts = urlsplit(url) if "://" in url else None
        port = parts.port if parts else None
    except ValueError:   # a malformed URL (an unclosed [ for example) must not stop the run
        return "an unreadable webhook address"
    if parts:
        what = (parts.hostname or "unknown host") + (f":{port}" if port else "")
        tail = [p for p in parts.path.split("/") if p]
        # Show the last path segment only when it is a short lowercase word, never a token-like string
        if tail and re.fullmatch(r"[a-z][a-z_-]{0,19}", tail[-1]):
            what += f" ({tail[-1]})"
    elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,40}", url.split("?")[0] or ""):
        what = f"Glific function {url.split('?')[0]}"
    else:
        what = "a webhook without a full address"
    purpose = str(action.get("result_name") or "").strip()
    return what + (f" for {purpose}" if purpose.lower() not in GENERIC_RESULT else "")


def short_operand(op):
    op = str(op or "")
    m = FIELD_IN_OPERAND.search(op)
    if m:
        return m.group(1)
    m = re.search(r"results\.([A-Za-z0-9_]+)", op)
    if m:
        return "the webhook result" if m.group(1).lower() in GENERIC_RESULT else f"result {m.group(1)}"
    if "groups" in op:
        return "the contact's group"
    if "input" in op:
        return "the reply"
    return op.strip("@() ") or "a value"


class FlowGraph:
    """Nodes, parents and reachability for one flow."""

    def __init__(self, flow):
        self.nodes = [n for n in (flow.get("nodes") or []) if isinstance(n, dict)]
        self.by_uuid = {n.get("uuid"): n for n in self.nodes}
        self.parents = defaultdict(list)   # node uuid -> [(parent node, category name or None)]
        for n in self.nodes:
            cats = {c.get("exit_uuid"): c.get("name") for c in ((n.get("router") or {}).get("categories") or [])}
            for ex in n.get("exits") or []:
                dest = ex.get("destination_uuid")
                if dest:
                    self.parents[dest].append((n, cats.get(ex.get("uuid"))))
        self.reachable = self._walk()

    def _walk(self):
        if not self.nodes:
            return set()
        seen, stack = set(), [self.nodes[0].get("uuid")]
        while stack:
            u = stack.pop()
            if u in seen or u not in self.by_uuid:
                continue
            seen.add(u)
            stack += [ex.get("destination_uuid") for ex in self.by_uuid[u].get("exits") or [] if ex.get("destination_uuid")]
        return seen

    def actions(self):
        for n in self.nodes:
            for a in n.get("actions") or []:
                yield n, a

    def condition(self, node, depth=0):
        """The router branch that leads to this node, walking back through plain action nodes."""
        for parent, cat in self.parents.get(node.get("uuid"), []):
            if cat:
                kinds = {a.get("type") for a in parent.get("actions") or []}
                operand = short_operand((parent.get("router") or {}).get("operand"))
                if cat.lower() in ("success", "failure"):
                    what = "webhook call" if "call_webhook" in kinds else ("sheet read" if "link_google_sheet" in kinds else "step")
                    return (f"the {what}", "", "succeeds" if cat.lower() == "success" else "fails")
                if cat.lower() == "other":
                    return (operand, "", "matches nothing else")
                return (operand, "is", cat)
        ps = self.parents.get(node.get("uuid"), [])
        if len(ps) == 1 and depth < 6:
            return self.condition(ps[0][0], depth + 1)
        return None

    def fields_read(self):
        out = set()
        for n in self.nodes:
            out.update(FIELD_IN_OPERAND.findall(str((n.get("router") or {}).get("operand") or "")))
        return out


def summarise(g):
    """Everything a card needs, extracted from the definition."""
    s = defaultdict(list)
    s["waits"] = 0
    branches = defaultdict(list)   # operand -> categories, merged across routers
    for n in g.nodes:
        r = n.get("router") or {}
        operand = str(r.get("operand") or "")
        if r.get("wait"):
            s["waits"] += 1
        elif r.get("type") == "random":
            s["random"].append(len(r.get("categories") or []))
        elif operand and not operand.startswith("@child") and \
                not any(a.get("type") in ("call_webhook", "link_google_sheet", "enter_flow") for a in n.get("actions") or []):
            cats = [c.get("name") for c in r.get("categories") or [] if c.get("name") and c.get("name").lower() != "other"]
            if len(cats) >= 2 or (cats and "fields" in operand):
                branches[short_operand(operand)] += cats
    s["routes"] = [f"{op} ({join(cats, 3, 'or')})" for op, cats in branches.items()]
    for n, a in g.actions():
        kind = a.get("type") or "unknown"
        tpl = ((a.get("templating") or {}).get("template") or {}).get("name")
        if kind == "send_msg":
            if tpl:
                s["templates"].append("templates chosen at run time" if tpl.lower() == "expression" else f"template {tpl}")
            else:
                s["messages"].append(1)
        elif kind == "send_interactive_msg":
            s["interactive"].append(a.get("name") or "interactive message")
        elif kind == "send_broadcast":
            staff = len(a.get("contacts") or [])
            to = join(([plural(staff, "staff contact")] if staff else []) + names(a.get("groups")))
            s["alerts"].append(f"template {tpl} to {to or 'nobody set'}" if tpl else f"a message to {to or 'nobody set'}")
        elif kind in ("enter_flow", "start_session"):
            target = a.get("flow") or {}
            s["starts"].append((target.get("uuid"), target.get("name") or target.get("uuid") or "unnamed flow"))
        elif kind in ("add_contact_groups", "remove_contact_groups"):
            groups = ["all groups"] if a.get("all_groups") else names(a.get("groups"))
            s["moves"].append(("into" if kind.startswith("add") else "out of", tuple(groups), g.condition(n)))
        elif kind == "set_contact_field":
            key = (a.get("field") or {}).get("key") or (a.get("field") or {}).get("name")
            if key:
                s["counts" if re.search(r"\+\s*1\b", str(a.get("value"))) else "sets"].append(key)
        elif kind == "set_contact_name":
            s["sets"].append("name")
        elif kind == "set_contact_language":
            s["sets"].append("language")
        elif kind == "call_webhook":
            s["calls"].append(webhook_desc(a))
            url = str(a.get("url") or "").strip()
            if "://" in url:
                host = host_of(url)
                if host != "[link]":
                    s["hosts"].append(host)
            elif url:
                s["functions"].append(url.split("?")[0])
        elif kind == "link_google_sheet":
            tab = str(a.get("range") or "").split("!")[0]
            mode = "writes" if str(a.get("action_type") or "").upper() == "WRITE" else "reads"
            s["logs"].append(f"{mode} {a.get('name') or 'a sheet'}" + (f", {tab} tab" if tab else ""))
            s["sheets"].append(a.get("name") or "a sheet")
        elif kind == "add_input_labels":
            s["labels"] += names(a.get("labels"))
        elif kind == "open_ticket":
            topic = (a.get("topic") or {}).get("name") if isinstance(a.get("topic"), dict) else a.get("topic")
            who = "assigned to a staff member" if a.get("assignee") else "left unassigned"
            s["tickets"].append(f"opens a ticket on {topic or 'no topic'}, {who}")
        elif kind in ("set_run_result", "wait_for_time"):
            pass
        else:
            s["other"].append(kind)
    # Nodes no path reaches, and what they would have done
    lost = []
    for n in g.nodes:
        if n.get("uuid") in g.reachable:
            continue
        for a in n.get("actions") or []:
            tpl = ((a.get("templating") or {}).get("template") or {}).get("name")
            if a.get("type") == "send_broadcast":
                lost.append(f"a staff template ({tpl})" if tpl else "a staff message")
            elif a.get("type") == "send_msg":
                lost.append(f"template {tpl}" if tpl else "a message")
            elif a.get("type") == "call_webhook":
                lost.append("a webhook call")
    s["unreachable"] = len(g.nodes) - len(g.reachable)
    s["lost"] = list(dict.fromkeys(lost))
    return s


TEXT_KEYS = ("routes", "tickets", "logs", "sheets", "alerts", "calls", "labels", "interactive", "templates", "lost")


def mask_summary(s, staff):
    """Mask personal data in every name and label a summary holds, once, so the page and the
    facts sent to Claude never see it: router branches, ticket topics, sheets, labels, alerts,
    group-move conditions and the names of flows a flow starts."""
    for key in TEXT_KEYS:
        s[key] = [mask(x, staff) for x in s[key]]
    # group names with the staff list too, as the model does for the groups triggers send to
    s["moves"] = [(d, tuple(mask(g, staff) for g in gs), tuple(mask(c, staff) for c in cond) if cond else cond)
                  for d, gs, cond in s["moves"]]
    s["starts"] = [(v, mask(name, staff)) for v, name in s["starts"]]
    return s
