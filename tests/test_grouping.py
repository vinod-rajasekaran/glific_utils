"""Grouping flows by their links, for runs without Claude, and the page built from those groups."""
import unittest

from tests.helpers import SEEDS, by_name, groups_page, hostile, load, model, uid  # also puts org_programme_architecture on sys.path
from grouping import NOT_CONNECTED, group_answer, group_flows  # noqa: E402


def names(m):
    return {n: [m.name(u) for u in us] for n, us in group_flows(m)}


class GroupFlowsTest(unittest.TestCase):
    def test_fixture_groups(self):
        self.assertEqual(names(model()), {
            "Demo": ["Ask AI", "Profile", "Weekly tip", "Welcome"],
            "Starts at Survey start": ["Survey save", "Survey start"],
            NOT_CONNECTED: ["Ask AI copy", "Old draft"],
        })

    def test_every_flow_placed_once(self):
        m = model()
        placed = [u for _, us in group_flows(m) for u in us]
        self.assertEqual(sorted(placed), sorted(m.flows))

    def test_not_connected_comes_last(self):
        self.assertEqual(group_flows(model())[-1][0], NOT_CONNECTED)

    def test_unlinked_flow_joins_the_group_whose_tag_it_carries(self):
        flows, triggers = load()
        by_name(flows, "Old draft")["tag"] = {"label": "Demo"}
        self.assertIn("Old draft", names(model(flows, triggers))["Demo"])

    def test_untagged_group_named_after_its_entry_flow(self):
        flows, triggers = load()
        for f in flows:
            f["tag"] = None
        got = names(model(flows, triggers))
        self.assertIn("Starts at Survey start", got)
        self.assertNotIn("Demo", got)

    def test_shared_helper_does_not_glue_groups_together(self):
        flows, triggers = load()
        helper = by_name(flows, "Old draft")               # starts nothing; make Welcome and Survey start both enter it
        for caller in ("Welcome", "Survey start"):
            by_name(flows, caller)["nodes"][0]["actions"].append(
                {"type": "enter_flow", "uuid": f"h-{caller}", "flow": {"uuid": helper["uuid"], "name": "Old draft"}})
        got = names(model(flows, triggers))
        self.assertFalse(any("Welcome" in us and "Survey start" in us for us in got.values()))
        self.assertTrue(any("Old draft" in us and len(us) > 1 for us in got.values()))


class GroupAnswerTest(unittest.TestCase):
    def test_shape_and_source(self):
        m = model()
        a = group_answer(m, "it was run with --no-claude")
        self.assertEqual(a["source"], "structure")
        self.assertEqual(a["reason"], "it was run with --no-claude")
        self.assertEqual([p["parts"] for p in a["programmes"]], [[c["id"]] for c in a["use_cases"]])
        self.assertEqual({f["id"] for f in a["flows"]}, set(m.flows))
        self.assertEqual(a["use_cases"][-1]["kind"], "tests")
        self.assertEqual(len({c["id"] for c in a["use_cases"]}), len(a["use_cases"]))

    def test_flow_points_to_its_group(self):
        m = model()
        a = group_answer(m, "x")
        uc_of = {f["id"]: f["use_case"] for f in a["flows"]}
        survey = next(c["id"] for c in a["use_cases"] if c["name"] == "Starts at Survey start")
        self.assertEqual(uc_of[uid(m, "Survey save")], survey)


class StructurePageTest(unittest.TestCase):
    def test_banner_says_why_and_no_claude_labels(self):
        page = groups_page(reason="no Anthropic API key was found")
        self.assertIn("Built without Claude", page)
        self.assertIn("no Anthropic API key was found", page)
        self.assertNotIn('title="Claude’s reading"', page)
        self.assertNotIn('class="role claude', page)

    def test_each_flow_shows_its_tag(self):
        page = groups_page()
        self.assertIn("Tags: Demo", page)

    def test_hostile_export_leaks_nothing(self):
        page = groups_page(*hostile())
        for seed in SEEDS:
            self.assertNotIn(seed, page)



if __name__ == "__main__":
    unittest.main()
