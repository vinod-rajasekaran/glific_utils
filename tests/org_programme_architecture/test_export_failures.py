"""Flows Glific could not export are named on the page, in the facts and in the run's findings."""
import unittest

from tests.org_programme_architecture.helpers import by_name, facts, groups_page, load, model  # also puts org_programme_architecture on sys.path
from glific_common.org_facts import facts as uf  # noqa: E402

REASON = "Flow doesn't exist, Name - Other options flow, UUID - 6c362d4a-01cd-47cb-a03c-1dfb294faa63"


def broken():
    flows, triggers = load()
    for name in ("Survey save", "Old draft"):
        f = by_name(flows, name)
        f["nodes"], f["edges"], f["export_error"] = [], [], REASON
    return flows, triggers


class ExportFailuresTest(unittest.TestCase):
    def test_finding_names_the_flows_and_glifics_reason(self):
        m = model(*broken())
        found = [f for f in m.report() if "could not be exported" in f]
        self.assertEqual(len(found), 1, m.report())
        self.assertIn("2 flows", found[0])
        self.assertIn("Old draft", found[0])
        self.assertIn("Survey save", found[0])
        self.assertIn("Other options flow", found[0])
        self.assertNotIn("6c362d4a", found[0])   # the uuid adds nothing for a reader

    def test_in_the_facts_sent_to_claude_and_the_mcp(self):
        f = uf.build_facts(model(*broken()))
        self.assertTrue(any("could not be exported" in x for x in f["findings"]))

    def test_on_the_page(self):
        page = groups_page(*broken())
        self.assertIn("Not exported", page)
        self.assertIn("Other options flow", page)

    def test_nothing_when_every_export_worked(self):
        self.assertFalse([f for f in model().report() if "could not be exported" in f])
        self.assertNotIn("Not exported", groups_page())
        self.assertFalse([x for x in facts()["findings"] if "could not be exported" in x])


if __name__ == "__main__":
    unittest.main()
