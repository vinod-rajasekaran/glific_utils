"""The Glific export: credential scrubbing, .env loading and the settings fetch."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, SETTINGS  # also puts org_programme_architecture on sys.path
import glific_get_flows as gf  # noqa: E402
import glific_get_settings as gs  # noqa: E402
import privacy as pv  # noqa: E402


class EmptyEnvValues(unittest.TestCase):
    def test_empty_values_are_not_exported(self):
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("ZZ_TEST_EMPTY=\nZZ_TEST_SET=1\n")
        os.environ.pop("ZZ_TEST_EMPTY", None)
        os.environ.pop("ZZ_TEST_SET", None)
        saved = os.environ.pop("GLIFIC_NO_DOTENV", None)
        try:
            gf.load_env(path)
        finally:
            if saved is not None:
                os.environ["GLIFIC_NO_DOTENV"] = saved
        self.assertNotIn("ZZ_TEST_EMPTY", os.environ)
        self.assertEqual(os.environ.pop("ZZ_TEST_SET"), "1")

    def test_env_example_has_no_empty_key_line(self):
        self.assertNotRegex((ROOT / ".env.example").read_text(), r"(?m)^ANTHROPIC_API_KEY=\s*$")


class StickySecrets(unittest.TestCase):
    def test_exporter_scrubs_ui(self):
        definition = {"nodes": [], "_ui": {"stickies": {"s": {"body": "Bearer SECRETBEARER123"}}}}
        gf.redact_definition(definition)
        self.assertNotIn("SECRETBEARER123", json.dumps(definition))

    def test_clean_text_masks_tokens(self):
        out = pv.clean_text("Bearer SECRETBEARER123 key sk_live_ABC123SECRETxyz and AIzaSyA1234567890abcdefghij", set())
        for s in ("SECRETBEARER123", "sk_live_ABC123SECRETxyz", "AIzaSyA1234567890abcdefghij"):
            self.assertNotIn(s, out)

    def test_redact_file_covers_ui(self):
        p = Path(tempfile.mkdtemp()) / "flows.json"
        p.write_text(json.dumps([{"nodes": [], "ui": {"stickies": {"s": {"body": "Bearer SECRETBEARER123"}}}}]))
        gf.redact_file(p)
        self.assertNotIn("SECRETBEARER123", p.read_text())


class SettingsFetchTest(unittest.TestCase):
    def test_fetch_settings_reads_organization(self):
        calls = []

        def fake_post(path, payload, token=None):
            calls.append(payload["query"])
            return {"data": {"organization": {"organization": dict(SETTINGS, name="Demo org")}}}
        got = gs.fetch_settings("tok", post=fake_post)
        self.assertEqual(got["outOfOffice"]["defaultFlowId"], "008")
        self.assertNotIn("email", calls[0])

    def test_fetch_settings_survives_errors(self):
        got = gs.fetch_settings("tok", post=lambda *a, **k: {"errors": [{"message": "unauthorized"}]})
        self.assertEqual(got, {})


if __name__ == "__main__":
    unittest.main()
