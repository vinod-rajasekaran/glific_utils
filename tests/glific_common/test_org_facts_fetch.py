"""Pulling an account's export (flows with definitions, triggers, settings) through a fake Glific.
No network."""
import contextlib
import io
import json
import unittest

from glific_common.api import GlificError
from glific_common.org_facts import fetch

U1, U2 = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
DEFINITION = {"uuid": U1, "_ui": {"nodes": {}}, "nodes": [
    {"uuid": "n1", "actions": [{"type": "call_webhook", "uuid": "a", "url": "https://h.org/x",
                                 "headers": {"Authorization": "Bearer SECRET"}}],
     "exits": [{"uuid": "e1", "destination_uuid": "n2"}]},
    {"uuid": "n2", "actions": [], "exits": [{"uuid": "e2"}]}]}
FLOWS = [{"id": "1", "uuid": U1, "name": "Welcome", "tag": {"label": "Pilot"}},
         {"id": "2", "uuid": U2, "name": "Broken", "tag": None}]
TRIGGERS = [{"id": "9", "name": "Nudge", "isActive": True, "isRepeating": True, "frequency": "weekly", "days": [1],
             "startAt": "2026-01-01T04:30:00Z", "flow": {"name": "Welcome"}}]
ORG = {"name": "Demo org", "newcontactFlowId": "1", "outOfOffice": {"enabled": False}}


def fake(flows_error=None):
    def post(path, payload, token=None):
        q = payload["query"]
        if "flows(" in q:
            if flows_error:
                return {"errors": [{"message": flows_error}]}
            return {"data": {"flows": FLOWS if payload["variables"]["opts"]["offset"] == 0 else []}}
        if "triggers(" in q:
            return {"data": {"triggers": TRIGGERS if payload["variables"]["opts"]["offset"] == 0 else []}}
        if "exportFlow(" in q:
            if payload["variables"]["id"] == "2":
                return {"data": {"exportFlow": {"errors": [{"message": "gone"}]}}}
            return {"data": {"exportFlow": {"exportData": json.dumps({"flows": [{"definition": DEFINITION}]})}}}
        if "organization" in q:
            return {"data": {"organization": {"organization": ORG}}}
        raise AssertionError(q[:40])
    return post


class FetchTest(unittest.TestCase):
    def pull(self, post):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = fetch.fetch_all("tok", post=post)
        self.assertEqual(out.getvalue(), "", "nothing may go to stdout: it is the MCP server's channel")
        return got

    def test_pulls_flows_triggers_and_settings(self):
        flows, triggers, org = self.pull(fake())
        welcome, broken = flows
        self.assertEqual([n["uuid"] for n in welcome["nodes"]], ["n1", "n2"])
        self.assertEqual(welcome["edges"][0], {"from": "n1", "exit": "e1", "to": "n2"})
        self.assertNotIn("SECRET", json.dumps(welcome))
        self.assertEqual((broken["nodes"], broken["edges"]), ([], []))   # a failed export leaves the flow empty
        self.assertEqual(triggers[0]["schedule"], "weekly on Mon from 2026-01-01T04:30:00Z")
        self.assertEqual(org["name"], "Demo org")

    def test_a_failed_flow_list_raises_instead_of_exiting(self):
        with self.assertRaises(GlificError):
            self.pull(fake(flows_error="unauthorized"))


class ExpiredTokenTest(unittest.TestCase):
    def test_an_expired_token_during_exports_is_raised_not_swallowed(self):
        inner = fake()

        def post(path, payload, token=None):
            if "exportFlow(" in payload["query"]:
                return {"data": {"exportFlow": {"errors": [{"message": "Unauthorized"}]}}}
            return inner(path, payload, token)
        with self.assertRaises(GlificError), contextlib.redirect_stderr(io.StringIO()):
            fetch.fetch_flows("tok", post=post)


if __name__ == "__main__":
    unittest.main()
