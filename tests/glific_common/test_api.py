"""The shared Glific client: paging, errors, re-login, run folders and .env loading. No network."""
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from glific_common import api, output
from glific_common.flows import export_definition


class FakeGlific:
    """Answers post(path, payload, token) like Glific: a login, and queries from a script."""

    def __init__(self, *replies, tokens=("t1", "t2")):
        self.replies, self.tokens, self.calls = list(replies), list(tokens), []

    def __call__(self, path, payload, token=None):
        self.calls.append((path, payload, token))
        if path == "/api/v1/session":
            return {"data": {"access_token": self.tokens.pop(0)}}
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


ENV = {"GLIFIC_URL": "https://api.example.org", "GLIFIC_PHONE": "910000000000", "GLIFIC_PASSWORD": "x"}


class PagedTest(unittest.TestCase):
    def test_reads_every_page(self):
        fake = FakeGlific({"data": {"flows": [1, 2]}}, {"data": {"flows": [3]}})
        self.assertEqual(api.paged("q", "flows", "t", page_size=2, post=fake), [1, 2, 3])
        self.assertEqual([c[1]["variables"]["opts"]["offset"] for c in fake.calls], [0, 2])

    def test_graphql_errors_raise(self):
        fake = FakeGlific({"errors": [{"message": "bad filter"}]})
        with self.assertRaisesRegex(api.GlificError, "bad filter"):
            api.paged("q", "flows", "t", post=fake)


@mock.patch.dict(os.environ, ENV)
class SessionTest(unittest.TestCase):
    def test_logs_in_once_and_reuses_the_token(self):
        fake = FakeGlific({"data": {"a": 1}}, {"data": {"b": 2}})
        s = api.Session(post=fake)
        self.assertEqual(s.query("q1"), {"a": 1})
        self.assertEqual(s.query("q2"), {"b": 2})
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "/api/v1/session"), 1)
        self.assertEqual([c[2] for c in fake.calls if c[0] == "/api"], ["t1", "t1"])

    def test_logs_in_again_when_the_token_expires(self):
        expired = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        fake = FakeGlific(expired, {"data": {"ok": True}})
        self.assertEqual(api.Session(post=fake).query("q"), {"ok": True})
        self.assertEqual([c[2] for c in fake.calls if c[0] == "/api"], ["t1", "t2"])

    def test_other_errors_are_not_retried(self):
        fake = FakeGlific({"errors": [{"message": "no such field"}]})
        with self.assertRaises(api.GlificError):
            api.Session(post=fake).query("q")
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "/api/v1/session"), 1)


class ExportTest(unittest.TestCase):
    def test_definition_is_redacted(self):
        import json
        definition = {"uuid": "u1", "nodes": [{"uuid": "n", "exits": [], "actions": [
            {"type": "call_webhook", "uuid": "a", "url": "https://h.org/x?key=SECRET1", "headers": {"Authorization": "Bearer SECRET2"}}]}]}
        fake = FakeGlific({"data": {"exportFlow": {"exportData": json.dumps({"flows": [definition]}), "errors": None}}})
        got, n = export_definition("1", "u1", "t", post=fake)
        self.assertGreaterEqual(n, 2)
        self.assertNotIn("SECRET", json.dumps(got))

    def test_export_errors_raise(self):
        fake = FakeGlific({"data": {"exportFlow": {"exportData": None, "errors": [{"key": "id", "message": "not found"}]}}})
        with self.assertRaisesRegex(api.GlificError, "not found"):
            export_definition("9", "u9", "t", post=fake)


class SettingsTest(unittest.TestCase):
    def test_missing_settings_named(self):
        with mock.patch.dict(os.environ, {"GLIFIC_URL": "https://x"}, clear=True):
            self.assertEqual(api.missing_settings(), ["GLIFIC_PHONE", "GLIFIC_PASSWORD"])

    def test_env_file_does_not_override_the_shell(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"GLIFIC_PHONE": "shell"}, clear=True):
            env = Path(d) / ".env"
            env.write_text('GLIFIC_PHONE=file\nGLIFIC_URL="https://q.org"\nEMPTY=\n')
            api.load_env(env)
            self.assertEqual(os.environ["GLIFIC_PHONE"], "shell")
            self.assertEqual(os.environ["GLIFIC_URL"], "https://q.org")
            self.assertNotIn("EMPTY", os.environ)


class RunDirTest(unittest.TestCase):
    def test_one_folder_per_feature_per_run(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"GLIFIC_OUTPUT_ROOT": d}):
            output._run_dirs.clear()
            a, b = output.run_dir("x"), output.run_dir("x")
            self.assertIs(a, b)
            self.assertTrue(a.is_dir())
            self.assertEqual(output.save_json({"k": 1}, "f.json", a).read_text(), '{\n  "k": 1\n}')
            output._run_dirs.clear()


if __name__ == "__main__":
    unittest.main()
