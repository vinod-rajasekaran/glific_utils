"""The MCP server, called through an in-process MCP client against a fake Glific. No network."""
import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest import mock

try:
    from mcp import Client
except ImportError:   # the mcp package is optional (pip install -e ".[mcp]")
    raise unittest.SkipTest("the mcp package is not installed")

SERVER = Path(__file__).resolve().parents[2] / "glific_mcp" / "server.py"
ENV = {"GLIFIC_URL": "https://api.example.org", "GLIFIC_PHONE": "910000000000", "GLIFIC_PASSWORD": "x", "GLIFIC_NO_DOTENV": "1"}
READ_TOOLS = {"list_flows", "get_flow", "list_collections", "get_collection", "list_templates", "list_tags",
              "get_organization_info", "list_languages"}
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


if __name__ == "__main__":
    unittest.main()
