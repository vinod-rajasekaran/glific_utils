"""The MCP server, called through an in-process MCP client against a fake Glific. No network."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

try:
    from mcp import Client
except ImportError:   # the mcp package is optional (pip install -e ".[mcp]")
    raise unittest.SkipTest("the mcp package is not installed")

from glific_common.org_facts import org_map_file  # noqa: E402
from tests.org_programme_architecture.helpers import SEEDS, SETTINGS, hostile, load as load_fixture, validated  # noqa: E402

SERVER = Path(__file__).resolve().parents[2] / "glific_mcp" / "server.py"
ENV = {"GLIFIC_URL": "https://api.example.org", "GLIFIC_PHONE": "910000000000", "GLIFIC_PASSWORD": "x", "GLIFIC_NO_DOTENV": "1"}
READ_TOOLS = {"list_flows", "get_flow", "list_collections", "get_collection", "list_templates", "list_tags",
              "get_organization_info", "list_languages", "get_org_overview", "get_flow_facts", "get_org_facts", "get_org_map"}
WRITE_TOOLS = {"create_flow", "create_collection", "start_flow_for_contact", "start_flow_for_collection"}

DEFINITION = {"uuid": "00000000-0000-4000-8000-000000000001", "nodes": [{"uuid": "11111111-0000-4000-8000-000000000002", "exits": [], "actions": [
    {"type": "send_msg", "uuid": "a1", "text": "Call 9876543210 or write to anil@example.org", "quick_replies": ["Yes 9876500001"]},
    {"type": "call_webhook", "uuid": "a2", "url": "https://h.org/x?key=SECRET1", "headers": {"Authorization": "Bearer SECRET2"}}]}],
    "_ui": {"stickies": {"s": {"title": "Note", "body": "ring 9876500003"}}}}


def load(**env):
    """A fresh copy of the server module, imported with these settings."""
    with mock.patch.dict(os.environ, {**ENV, **env}, clear=True):
        spec = importlib.util.spec_from_file_location(f"glific_mcp_server_{len(env)}_{id(env)}", SERVER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class FakeGlific:
    def __init__(self, **answers):
        self.answers, self.calls, self.logins = answers, [], 0

    def __call__(self, path, payload, token=None):
        if path == "/api/v1/session":
            self.logins += 1
            return {"data": {"access_token": f"t{self.logins}"}}
        self.calls.append((payload["query"], payload.get("variables"), token))
        for key, answer in self.answers.items():
            if f"{key}(" in payload["query"]:
                return answer(payload.get("variables"), token) if callable(answer) else answer
        raise AssertionError("unexpected query: " + payload["query"][:60])


class ToolsTest(unittest.IsolatedAsyncioTestCase):
    async def tools(self, mod):
        async with Client(mod.server) as c:
            return {t.name: t for t in (await c.list_tools()).tools}

    async def test_read_only_by_default(self):
        tools = await self.tools(load())
        self.assertEqual(set(tools), READ_TOOLS)
        self.assertTrue(all(t.annotations.read_only_hint for t in tools.values()))

    async def test_write_tools_only_when_switched_on(self):
        tools = await self.tools(load(GLIFIC_MCP_ALLOW_WRITES="1"))
        self.assertEqual(set(tools), READ_TOOLS | WRITE_TOOLS)
        self.assertTrue(tools["start_flow_for_collection"].annotations.destructive_hint)
        self.assertFalse(tools["create_flow"].annotations.read_only_hint)


class CallsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV, clear=True)
        self.env.start()
        self.mod = load()

    def tearDown(self):
        self.env.stop()

    async def call(self, fake, name, args=None):
        self.mod.session(post=fake)
        async with Client(self.mod.server) as c:
            return await c.call_tool(name, args or {})

    def data(self, r):
        self.assertFalse(r.is_error, r.content)
        s = r.structured_content
        return s.get("result", s)

    async def test_list_flows_sends_filter_and_page(self):
        fake = FakeGlific(flows={"data": {"flows": [{"id": "1", "name": "Welcome"}]}})
        got = self.data(await self.call(fake, "list_flows", {"name_filter": "Wel", "limit": 5, "offset": 10, "active_only": True}))
        self.assertEqual(got, [{"id": "1", "name": "Welcome"}])
        self.assertEqual(fake.calls[0][1], {"filter": {"name": "Wel", "isActive": True}, "opts": {"limit": 5, "offset": 10}})

    async def test_get_flow_blanks_credentials_and_masks_text_but_keeps_ids(self):
        fake = FakeGlific(
            flow={"data": {"flow": {"flow": {"id": "7", "uuid": DEFINITION["uuid"], "name": "Welcome"}, "errors": None}}},
            exportFlow={"data": {"exportFlow": {"exportData": json.dumps({"flows": [DEFINITION]}), "errors": None}}})
        got = json.dumps(self.data(await self.call(fake, "get_flow", {"id": "7"})))
        for secret in ("9876543210", "anil@example.org", "9876500001", "9876500003", "SECRET1", "SECRET2"):
            self.assertNotIn(secret, got)
        self.assertIn(DEFINITION["uuid"], got)
        self.assertIn("11111111-0000-4000-8000-000000000002", got)
        self.assertIn("[number]", got)

    async def test_template_bodies_are_masked(self):
        fake = FakeGlific(sessionTemplates={"data": {"sessionTemplates": [{"id": "3", "label": "t", "body": "Call 9876543210"}]}})
        got = self.data(await self.call(fake, "list_templates"))
        self.assertEqual(got[0]["body"], "Call [number]")

    async def test_glific_errors_come_back_as_tool_errors(self):
        fake = FakeGlific(groups={"errors": [{"message": "bad filter"}]})
        r = await self.call(fake, "list_collections")
        self.assertTrue(r.is_error)
        self.assertIn("bad filter", r.content[0].text)

    async def test_expired_token_logs_in_again(self):
        def tags(variables, token):
            return {"errors": [{"message": "Unauthorized"}]} if token == "t1" else {"data": {"tags": []}}
        fake = FakeGlific(tags=tags)
        self.assertEqual(self.data(await self.call(fake, "list_tags")), [])
        self.assertEqual(fake.logins, 2)

    async def test_missing_settings_say_what_to_set(self):
        self.mod._session = None
        with mock.patch.dict(os.environ, {"GLIFIC_URL": "https://x"}, clear=True):
            async with Client(self.mod.server) as c:
                r = await c.call_tool("list_tags", {})
        self.assertTrue(r.is_error)
        self.assertIn("GLIFIC_PHONE, GLIFIC_PASSWORD", r.content[0].text)


class WriteCallsTest(unittest.IsolatedAsyncioTestCase):
    async def test_refusal_from_glific_is_an_error(self):
        with mock.patch.dict(os.environ, ENV, clear=True):
            mod = load(GLIFIC_MCP_ALLOW_WRITES="1")
            mod.session(post=FakeGlific(createGroup={"data": {"createGroup": {"group": None, "errors": [{"key": "label", "message": "taken"}]}}}))
            async with Client(mod.server) as c:
                r = await c.call_tool("create_collection", {"label": "Pilot"})
        self.assertTrue(r.is_error)
        self.assertIn("taken", r.content[0].text)


def fixture_glific(flows, triggers, settings=None, fail_flows=False):
    """A fake Glific serving a made-up account: its flow list, each flow's export, triggers and settings."""
    by_id = {f["id"]: f for f in flows}
    calls = Counter()

    def post(path, payload, token=None):
        if path == "/api/v1/session":
            return {"data": {"access_token": "t"}}
        q, v = payload["query"], payload.get("variables") or {}
        first = (v.get("opts") or {}).get("offset", 0) == 0
        if "flows(" in q:
            calls["flows"] += 1
            if fail_flows:
                return {"errors": [{"message": "flows are down"}]}
            return {"data": {"flows": [{k: f[k] for k in ("id", "uuid", "name", "keywords", "tag") if k in f} for f in flows] if first else []}}
        if "exportFlow(" in q:
            f = by_id[v["id"]]
            return {"data": {"exportFlow": {"exportData": json.dumps({"flows": [{"definition": {
                "uuid": f["uuid"], "nodes": f["nodes"], "_ui": f.get("ui")}}]})}}}
        if "triggers(" in q:
            return {"data": {"triggers": triggers if first else []}}
        if "organization" in q:
            return {"data": {"organization": {"organization": settings or {"name": "Demo org"}}}}
        raise AssertionError(q[:60])
    post.calls = calls
    return post


class OrgToolsTest(unittest.IsolatedAsyncioTestCase):
    """The org tools on the made-up org, with personal data and secrets planted in it."""
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {**ENV, "GLIFIC_OUTPUT_ROOT": self.out}, clear=True)
        self.env.start()
        self.mod = load()
        flows, triggers = hostile()
        self.fake = fixture_glific(flows, triggers, SETTINGS | {"name": "Demo org"})
        self.mod.session(post=self.fake)

    def tearDown(self):
        self.env.stop()

    async def call(self, name, args=None):
        with contextlib.redirect_stderr(io.StringIO()):
            async with Client(self.mod.server) as c:
                return await c.call_tool(name, args or {})

    async def data(self, name, args=None):
        r = await self.call(name, args)
        self.assertFalse(r.is_error, r.content)
        s = r.structured_content
        return s.get("result", s)

    async def test_overview_lists_flows_groups_and_settings(self):
        got = await self.data("get_org_overview")
        self.assertEqual(got["organisation"], "Demo org")
        self.assertEqual(got["counts"]["active_flows"], 8)
        self.assertIn("Survey start", [f["name"] for f in got["flows"]])
        self.assertTrue(any("New contact flow" in s["settings"] for s in got["started_by_settings"]))
        self.assertTrue(got["groups_by_links"])
        self.assertIsNone(got["saved_org_map"])

    async def test_nothing_planted_comes_out(self):
        seen = []
        for name, args in (("get_org_overview", None), ("get_org_facts", {"include_excerpts": True}),
                           ("get_flow_facts", {"flow": "Welcome"})):
            seen.append(json.dumps(await self.data(name, args)))
        for seed in SEEDS:
            for text in seen:
                self.assertNotIn(seed, text)

    async def test_flow_facts_by_name_part_or_id(self):
        got = await self.data("get_flow_facts", {"flow": "ask ai"})
        self.assertEqual(got["name"], "Ask AI")
        self.assertEqual(got["starts_from"][0]["flow"], "Weekly tip")
        self.assertTrue(got["excerpts"])
        self.assertEqual((await self.data("get_flow_facts", {"flow": got["id"]}))["name"], "Ask AI")

    async def test_unknown_or_ambiguous_flow_is_an_error(self):
        r = await self.call("get_flow_facts", {"flow": "nothing like it"})
        self.assertTrue(r.is_error)
        self.assertIn("get_org_overview", r.content[0].text)
        r = await self.call("get_flow_facts", {"flow": "e"})
        self.assertTrue(r.is_error)
        self.assertIn("flows match", r.content[0].text)

    async def test_the_account_is_pulled_once(self):
        await self.data("get_org_overview")
        await self.data("get_flow_facts", {"flow": "survey st"})
        await self.data("get_org_facts")
        self.assertEqual(self.fake.calls["flows"], 1)
        await self.data("get_org_overview", {"refresh": True})
        self.assertEqual(self.fake.calls["flows"], 2)

    async def test_org_facts_leave_out_excerpts_by_default(self):
        got = await self.data("get_org_facts")
        self.assertTrue(all("excerpts" not in f for f in got["flows"]))
        self.assertTrue(any(f["excerpt_count"] for f in got["flows"]))
        full = await self.data("get_org_facts", {"include_excerpts": True})
        self.assertTrue(any(f["excerpts"] for f in full["flows"]))

    async def test_a_failed_pull_is_an_error_and_the_server_keeps_going(self):
        flows, triggers = load_fixture()
        self.mod.session(post=fixture_glific(flows, triggers, fail_flows=True))
        r = await self.call("get_org_overview")
        self.assertTrue(r.is_error)
        self.assertIn("flows are down", r.content[0].text)
        self.mod.session(post=fixture_glific(flows, triggers))
        self.assertEqual((await self.data("get_org_overview"))["counts"]["active_flows"], 8)

    async def test_no_saved_org_map_says_how_to_build_one(self):
        r = await self.call("get_org_map")
        self.assertTrue(r.is_error)
        self.assertIn("./org_map.sh", r.content[0].text)

    async def test_saved_org_map_programmes_and_detail(self):
        m, _, answer, dropped, _ = validated("claude_output_programmes.json")
        run = Path(self.out) / "2026-11-14_10-00-00"
        run.mkdir()
        (run / "org_map.json").write_text(json.dumps(org_map_file.record(m, answer, dropped)))
        got = await self.data("get_org_map")
        self.assertEqual(got["source"], "Claude")
        self.assertEqual(got["run"], "2026-11-14_10-00-00")
        prog = got["programmes"][0]
        self.assertEqual(prog["name"], "Healthy families programme")
        self.assertIn("Welcome", prog["parts"][0]["flows"])
        detail = await self.data("get_org_map", {"programme": "healthy-families"})
        self.assertEqual(detail["story"][0]["about"], ["Welcome", "Weekly tip"])
        flows = {f["name"]: f for p in detail["parts"] for f in p["flows"]}
        self.assertEqual(flows["Ask AI"]["purpose"], "Answers a question through an outside service.")
        ask = await self.data("get_flow_facts", {"flow": "Ask AI"})
        self.assertEqual(ask["org_map"]["part"], "Weekly pregnancy tips")
        self.assertEqual((await self.data("get_org_overview"))["saved_org_map"]["source"], "claude")


if __name__ == "__main__":
    unittest.main()
