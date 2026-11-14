"""Masking of personal data and secrets (privacy.py), and where masked text must appear."""
import json
import unicodedata
import unittest

from tests.helpers import TODAY, SEEDS, by_name, hostile, load, model  # also puts org_programme_architecture on sys.path
import flow_reading as fr  # noqa: E402
import model as md  # noqa: E402
import privacy as pv  # noqa: E402
import programme_facts as uf  # noqa: E402
import render_graph as ra  # noqa: E402


class CleanTextTest(unittest.TestCase):
    def test_masks_phone_and_email(self):
        out = pv.clean_text("call 9876543210 or +91 98765-43210 or a@b.org", set())
        self.assertNotRegex(out, r"\d{6}")
        self.assertNotIn("a@b.org", out)

    def test_strips_staff_names(self):
        self.assertEqual(pv.clean_text("Ask Asha Rao today", {"Asha Rao"}), "Ask a staff contact today")

    def test_url_to_host(self):
        self.assertEqual(pv.clean_text("see https://docs.google.com/x/y?z=1 now", set()), "see docs.google.com now")

    def test_keeps_expressions(self):
        self.assertEqual(pv.clean_text("Hi @contact.name, week @fields.week_number", set()),
                         "Hi @contact.name, week @fields.week_number")

    def test_cuts_by_characters(self):
        text = "नमस्ते दुनिया " * 200
        out = pv.clean_text(text, set())
        self.assertLessEqual(len(out), 201)
        self.assertTrue(out.endswith("…"))
        out.encode("utf-8").decode("utf-8")

    def test_staff_name_that_names_a_flow_is_kept(self):
        flows = {"a": {"name": "Helpline-support", "nodes": [{"actions": [
            {"type": "send_broadcast", "contacts": [{"name": "Helpline"}, {"name": "Ravi Kumar"}]}]}]}}
        self.assertEqual(pv.staff_names(flows), {"Ravi Kumar"})


class StaffPhoneAndLinkMasking(unittest.TestCase):
    def test_staff_name_needs_word_boundaries(self):
        self.assertEqual(pv.clean_text("The Program quality", {"Ram"}), "The Program quality")

    def test_staff_first_name_alone_is_masked(self):
        self.assertNotIn("Priya", pv.clean_text("Call Priya today", {"Priya Sharma"}))

    def test_flow_name_exemption_is_whole_words(self):
        flows = {"a": {"name": "Sanitation drive", "nodes": [{"actions": [{"type": "send_broadcast", "contacts": [{"name": "Anita"}]}]}]}}
        self.assertEqual(pv.staff_names(flows), {"Anita"})

    def test_phones_with_dots_and_brackets(self):
        out = pv.clean_text("call 98765.43210 or (022) 2345 6789", set())
        self.assertNotRegex(out, r"\d{4}")

    def test_schemeless_links_lose_path(self):
        self.assertNotIn("token", pv.clean_text("go to www.example.org/reset?token=abcDEF123 now", set()))

    def test_iso_dates_kept(self):
        self.assertIn("2025-11-13", pv.clean_text("starts on 2025-11-13", set()))


class DevanagariCut(unittest.TestCase):
    def test_cut_does_not_split_a_cluster(self):
        text = "स्वास्थ्य जानकारी " * 30
        for limit in range(190, 200):
            out = pv.clean_text(text, set(), limit)
            body = out.rstrip("…").rstrip()
            last = body[-1]
            self.assertFalse(unicodedata.category(last).startswith("M") and last == "्", (limit, out[-6:]))
            self.assertNotEqual(last, "्")
            if len(body) < len(text):
                nxt = text[len(body)]
                self.assertFalse(unicodedata.category(nxt).startswith("M"), (limit, out[-6:]))


class StructuralFieldsMasked(unittest.TestCase):
    def test_facts_and_page_have_no_planted_pii(self):
        flows, triggers = hostile()
        m = model(flows, triggers, scope_all=True)
        text = json.dumps(uf.build_facts(m), ensure_ascii=False)
        page, _ = ra.render_html(flows, triggers, md.Settings(today=TODAY))
        for seed in SEEDS[:6]:
            self.assertNotIn(seed, text, seed)
            self.assertNotIn(seed, page, seed)


class BareLinks(unittest.TestCase):
    def test_bare_host_with_path_cut_to_host(self):
        out = pv.clean_text("see bit.ly/secretdoc or docs.google.com/spreadsheets/d/SHEETID12345 now", set())
        self.assertNotIn("SHEETID12345", out)
        self.assertNotIn("secretdoc", out)
        self.assertIn("docs.google.com", out)

    def test_plain_sentences_untouched(self):
        self.assertEqual(pv.clean_text("Rest well. Drink water.", set()), "Rest well. Drink water.")


class WebhookPaths(unittest.TestCase):
    def test_schemeless_url_not_printed_whole(self):
        d = fr.webhook_desc({"url": "hooks.example.com/services/T0000/B0000/SECRETPATHTOKEN?x=1"})
        self.assertNotIn("SECRETPATHTOKEN", d)

    def test_mixed_case_last_segment_hidden(self):
        self.assertNotIn("SecretAlphaToken", fr.webhook_desc({"url": "https://hooks.example.com/services/SecretAlphaToken"}))

    def test_glific_function_names_kept(self):
        self.assertIn("filesearch-gpt", fr.webhook_desc({"url": "filesearch-gpt"}))


class OverMasking(unittest.TestCase):
    def test_number_ranges_are_not_phones(self):
        self.assertEqual(pv.clean_text("birth_weight (1 - 2500 or 2501 - 4000)", set()), "birth_weight (1 - 2500 or 2501 - 4000)")

    def test_phones_still_masked(self):
        for p in ("+91 98765 43210", "98765-43210", "(022) 2345 6789", "98765.43210", "9876543210"):
            self.assertNotRegex(pv.clean_text(f"call {p} now", set()), r"\d{4}", p)

    def test_cloud_run_host_kept(self):
        host = "volunteer-digital-onboarding-238853749053.europe-west1.run.app"
        self.assertEqual(pv.clean_text(f"calls {host} (validate)", set()), f"calls {host} (validate)")
        self.assertIn(host, fr.webhook_desc({"url": f"https://{host}/validate"}))
        m = model(scope_all=True)
        self.assertNotIn("[secret]", json.dumps(uf.build_facts(m)))


if __name__ == "__main__":
    unittest.main()


class MaskingRegressions(unittest.TestCase):
    """Masking must not get weaker while keeping hostnames and number ranges readable."""

    def test_phone_before_a_full_stop(self):
        for text in ("call me on 9876543210.Thanks", "98765-43210.ok", "9876543210.pdf"):
            self.assertNotIn("43210", pv.mask(text), text)

    def test_phone_with_spaced_dash_or_double_space(self):
        for text in ("98765 - 43210", "98765  43210"):
            self.assertNotIn("43210", pv.mask(text), text)

    def test_hyphenated_and_dotted_tokens(self):
        for token in ("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6-x9y8", "ya29.a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8"):
            self.assertNotIn("a1b2c3d4e5f6a7b8", pv.mask(f"token {token}"), token)

    def test_hosts_and_ranges_still_kept(self):
        host = "volunteer-digital-onboarding-238853749053.europe-west1.run.app"
        self.assertEqual(pv.mask(f"calls {host} now"), f"calls {host} now")
        self.assertEqual(pv.mask("weight 1 - 2500 or 2501 - 4000"), "weight 1 - 2500 or 2501 - 4000")

    def test_group_names_masked_with_staff_names(self):
        flows, triggers = load()
        by_name(flows, "Survey save")["nodes"][1]["actions"][0]["contacts"].append({"uuid": "c-2", "name": "Priya Sharma"})
        by_name(flows, "Profile")["nodes"][2]["actions"][0]["groups"] = [{"uuid": "g1", "name": "Priya Sharma follow-ups"}]
        triggers[-1]["groups"] = ["Priya Sharma follow-ups"]
        m = model(flows, triggers, scope_all=True)
        self.assertNotIn("Priya", json.dumps(uf.build_facts(m)))
        self.assertTrue(any(info["triggers"] and info["adds"] for info in m.view.group_nodes.values()))   # still joined up
