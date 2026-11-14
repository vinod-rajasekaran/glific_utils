"""Shared test helpers: the made-up org in fixtures/, a model or facts built from it, saved
Claude answers, and a stand-in for the Anthropic client. Nothing here touches a real org."""
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

from glific_common.org_facts import model as md  # noqa: E402
import programme_claude as uc  # noqa: E402
from glific_common.org_facts import facts as uf  # noqa: E402
import render_org_map as ru  # noqa: E402

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
TODAY = date(2026, 11, 13)
U = lambda n: f"00000000-0000-4000-8000-{n:012d}"  # noqa: E731   the fixture's flow uuids, 1 to 8
# Old draft (id "008") as the default flow and Welcome (id "001") as the new-contact flow
SETTINGS = {"newcontactFlowId": "001", "optinFlowId": None,
            "outOfOffice": {"enabled": False, "flowId": None, "defaultFlowId": "008"},
            "regxFlow": {"flowId": None, "regx": None}}


def load():
    """(flows, triggers) of the made-up org, freshly read so tests can change them."""
    return json.loads((FIX / "flows.json").read_text()), json.loads((FIX / "triggers.json").read_text())


def model(flows=None, triggers=None, org=None, **kw):
    """A Model of the made-up org (or of the given flows and triggers); kw goes to Settings."""
    f, t = load()
    return md.Model(flows or f, triggers or t, md.Settings(today=TODAY, **kw), org=org)


def facts():
    """The facts for the whole made-up org."""
    return uf.build_facts(model())


def raw():
    """A saved Claude answer for the made-up org, with deliberate faults (see the fixture)."""
    return json.loads((FIX / "claude_output.json").read_text())


def programmes_raw():
    """A saved Claude answer that also groups use cases into programmes, with faults."""
    return json.loads((FIX / "claude_output_programmes.json").read_text())


def validated(name="claude_output.json"):
    """(model, facts, validated answer, problems, settings) for a saved answer."""
    st = md.Settings(project="Demo", today=TODAY)
    m = md.Model(*load(), st)
    f = uf.build_facts(m)
    v, p = uc.validate(json.loads((FIX / name).read_text()), f)
    return m, f, v, p, st


def render_demo():
    """(programme page, validated answer) for the first saved answer."""
    st = md.Settings(project="Demo bot", today=TODAY)
    m = md.Model(*load(), st)
    f = uf.build_facts(m)
    v, p = uc.validate(raw(), f)
    return ru.render_org_map(m, f, v, p), v


def groups_page(flows=None, triggers=None, org=None, reason="it was run with --no-claude", **kw):
    """The page built without Claude, for the made-up org (or the given flows and triggers)."""
    from glific_common.org_facts.grouping import group_answer
    m = model(flows, triggers, org=org, **kw)
    return ru.render_org_map(m, uf.build_facts(m), group_answer(m, reason))


def uid(m, name):
    return next(u for u in m.flows if m.name(u) == name)


def by_name(flows, name):
    return next(f for f in flows if f["name"] == name)


def hostile():
    """The fixture with personal data and secrets planted in structural fields."""
    flows, triggers = load()
    w = by_name(flows, "Welcome")
    w["nodes"][0]["router"] = {"type": "switch", "operand": "@contact.phone",
                               "categories": [{"uuid": "c1", "name": "919876500001", "exit_uuid": "wel-e0"},
                                              {"uuid": "c2", "name": "Staff anil@example.org", "exit_uuid": "wel-e0"}],
                               "cases": []}
    w["nodes"][0]["actions"].append({"type": "add_input_labels", "uuid": "l1", "labels": [{"name": "call 9876512345"}]})
    w["nodes"][0]["actions"].append({"type": "open_ticket", "uuid": "t1", "topic": "Escalate to Meena 9876500003",
                                     "assignee": {"name": "Meena Rao"}})
    w["name"] = "Welcome 9876500009"
    w["ui"]["stickies"] = {"s": {"title": "Auth", "body": "Bearer SECRETBEARER123 key sk_live_ABC123SECRETxyz"}}
    return flows, triggers


SEEDS = ("919876500001", "anil@example.org", "9876512345", "9876500003", "Meena", "9876500009",
         "SECRETBEARER123", "sk_live_ABC123SECRETxyz")


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns the queued outputs in order (raising any that
    are exceptions) and records each request."""

    def __init__(self, *outputs, stop_reason="end_turn"):
        self.outputs, self.calls, self.stop_reason = list(outputs), [], stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append(kw)
        nxt = self.outputs.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        msg = SimpleNamespace(stop_reason=self.stop_reason, stop_details=None,
                              content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(nxt))])
        return _Stream(msg)


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return SimpleNamespace(get_final_message=lambda: self.msg)

    def __exit__(self, *a):
        return False


def stream_client(msg):
    """A client whose stream always returns this message (for checking how replies are read)."""
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: _Stream(msg))))
