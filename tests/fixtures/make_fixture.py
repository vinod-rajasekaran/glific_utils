#!/usr/bin/env python3
"""Write the synthetic flows.json and triggers.json used by the tests.

Everything here is made up: no real org's flows, people or numbers.
Run from the repo root:  python3 tests/fixtures/make_fixture.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LONG_HINDI = ("नमस्ते, यह एक लंबा संदेश है जो गर्भावस्था के हर सप्ताह के बारे में जानकारी देता है। " * 20)[:1500]


def node(uid, actions=(), exits=None, router=None):
    n = {"uuid": uid, "actions": list(actions), "exits": exits or [{"uuid": uid + "-x", "destination_uuid": None}]}
    if router:
        n["router"] = router
    return n


def chain(prefix, steps, router0=None):
    """Linear nodes: each step is a list of actions; each node exits to the next."""
    nodes = []
    for i, acts in enumerate(steps):
        nxt = f"{prefix}-n{i + 1}" if i + 1 < len(steps) else None
        nodes.append(node(f"{prefix}-n{i}", acts, [{"uuid": f"{prefix}-e{i}", "destination_uuid": nxt}], router0 if i == 0 else None))
    return nodes


def msg(text, uid):
    return {"type": "send_msg", "uuid": uid, "text": text, "quick_replies": [], "attachments": [], "labels": [], "all_urns": False}


def enter(flow_uuid, name, uid):
    return {"type": "enter_flow", "uuid": uid, "flow": {"uuid": flow_uuid, "name": name}}


def flow(uuid, name, nodes, keywords=(), tag=None, stickies=None):
    return {"uuid": uuid, "id": uuid[-3:], "name": name, "keywords": list(keywords), "isActive": True,
            "tag": {"label": tag} if tag else None, "versionNumber": "13.2.0", "lastPublishedAt": "2026-10-01T00:00:00Z",
            "lastChangedAt": "2026-10-01T00:00:00Z", "flowType": "MESSAGE", "edges": [], "nodes": nodes,
            "ui": {"stickies": stickies or {}}}


U = {n: f"00000000-0000-4000-8000-{i:012d}" for i, n in enumerate(
    ["Welcome", "Profile", "Weekly tip", "Ask AI", "Ask AI copy", "Survey start", "Survey save", "Old draft"], 1)}

stage_router = {"type": "switch", "operand": "@fields.stage",
                "categories": [{"uuid": "c1", "name": "Early", "exit_uuid": "rx1"}, {"uuid": "c2", "name": "Late", "exit_uuid": "rx2"}],
                "cases": [{"uuid": "k1", "type": "has_any_word", "arguments": ["early"], "category_uuid": "c1"},
                          {"uuid": "k2", "type": "has_any_word", "arguments": ["late"], "category_uuid": "c2"}]}

staff_router = {"type": "switch", "operand": "@contact.groups",
                "categories": [{"uuid": "sc1", "name": "Staff", "exit_uuid": "wel-e0"}],
                "cases": [{"uuid": "sk1", "type": "has_group", "arguments": ["g9", "Staff"], "category_uuid": "sc1"}]}

flows = [
    flow(U["Welcome"], "Welcome", chain("wel", [
        [msg("Welcome to the Healthy Families service. Reply 1 to join.", "wel-a1")],
        [enter(U["Profile"], "Profile", "wel-a2")],
    ], router0=staff_router), keywords=["hi", "hello"], tag="Demo"),
    flow(U["Profile"], "Profile", chain("pro", [
        [msg("Which month of pregnancy are you in?", "pro-a1")],
        [{"type": "set_contact_field", "uuid": "pro-a2", "field": {"key": "stage", "name": "stage"}, "value": "@results.month"}],
        [{"type": "add_contact_groups", "uuid": "pro-a3", "groups": [{"uuid": "g1", "name": "Members"}]}],
    ]), tag="Demo"),
    flow(U["Weekly tip"], "Weekly tip", [
        node("tip-n0", [], [{"uuid": "rx1", "destination_uuid": "tip-n1"}, {"uuid": "rx2", "destination_uuid": "tip-n2"}], stage_router),
        node("tip-n1", [msg("Tip for early pregnancy: rest well and drink water.", "tip-a1"), msg(LONG_HINDI, "tip-a1b")],
             [{"uuid": "tip-e1", "destination_uuid": "tip-n3"}]),
        node("tip-n2", [msg("Tip for late pregnancy: pack your hospital bag.", "tip-a2")], [{"uuid": "tip-e2", "destination_uuid": "tip-n3"}]),
        node("tip-n3", [enter(U["Ask AI"], "Ask AI", "tip-a3")]),
    ], tag="Demo"),
    flow(U["Ask AI"], "Ask AI", chain("ai", [
        [msg("Ask me any question about your health.", "ai-a1")],
        [{"type": "call_webhook", "uuid": "ai-a2", "method": "POST", "url": "https://api.example.org/answer",
          "headers": {"Authorization": "[redacted]", "Content-Type": "application/json"}, "body": "{}", "result_name": "answer"}],
        [msg("@results.answer", "ai-a3")],
    ]), tag="Demo"),
    flow(U["Ask AI copy"], "Ask AI copy", [
        node("cp-n0", [msg("Test copy of the AI flow.", "cp-a1")], [{"uuid": "rx1", "destination_uuid": None}, {"uuid": "rx2", "destination_uuid": None}],
             stage_router),
    ], keywords=["test"], tag="Testing"),
    flow(U["Survey start"], "Survey start", chain("sv", [
        [msg("Thank you for helping with our survey.", "sv-a1")],
        [enter(U["Survey save"], "Survey save", "sv-a2")],
    ]), keywords=["survey"]),
    flow(U["Survey save"], "Survey save", chain("ss", [
        [{"type": "link_google_sheet", "uuid": "ss-a1", "action_type": "WRITE", "name": "Responses", "range": "Sheet1!A1",
          "url": "https://docs.google.com/spreadsheets/d/abc123/edit", "sheet_id": "1", "row": [], "row_data": [], "result_name": "sheet"}],
        [{"type": "send_broadcast", "uuid": "ss-a2", "text": "", "contacts": [{"uuid": "c-1", "name": "Asha Rao"}], "groups": [],
          "templating": {"template": {"name": "survey_alert", "uuid": "t1"}, "variables": []}, "attachments": [], "legacy_vars": [], "compose": None}],
    ]), stickies={"s1": {"title": "Note", "body": "If the sheet fails call 9876543210 or mail lead@example.org"}}),
    flow(U["Old draft"], "Old draft", chain("od", [[msg("Draft message that is no longer used.", "od-a1")]])),
]

triggers = [
    {"id": "502", "name": "Old cohort tips", "isActive": False, "isRepeating": False, "frequency": "none", "days": [], "hours": [],
     "groups": ["Old cohort"], "waGroups": None, "groupType": "WABA", "startAt": "2026-01-05T09:30:00Z", "endDate": "2026-01-06",
     "nextTriggerAt": None, "schedule": "once from 2026-01-05T09:30:00Z until 2026-01-06",
     "flow": {"uuid": U["Weekly tip"], "name": "Weekly tip", "id": "3", "isActive": True, "tag": None}},
    {"id": "501", "name": "Weekly tips", "isActive": True, "isRepeating": True, "frequency": "weekly", "days": [3], "hours": [],
     "groups": ["Members"], "waGroups": None, "groupType": "WABA", "startAt": "2026-07-01T09:30:00Z", "endDate": "2028-06-25",
     "nextTriggerAt": "2026-11-18T09:30:00Z", "schedule": "weekly on Wednesday at 09:30 from 2026-07-01T09:30:00Z until 2028-06-25",
     "flow": {"uuid": U["Weekly tip"], "name": "Weekly tip", "id": "3", "isActive": True, "tag": None}},
]

if __name__ == "__main__":
    (HERE / "flows.json").write_text(json.dumps(flows, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "triggers.json").write_text(json.dumps(triggers, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", HERE / "flows.json", HERE / "triggers.json")
