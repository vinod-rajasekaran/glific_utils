"""The model's scope and the graph views built from it: starts, groups, links, the cap and boxes."""
import copy
import re
import sys
import unittest
from datetime import date

from tests.org_programme_architecture.helpers import ROOT, U, SETTINGS, load, model, uid, by_name, groups_page  # also puts org_programme_architecture on sys.path
import graph_svg as gsvg  # noqa: E402
import model as md  # noqa: E402


class GraphSubsetTest(unittest.TestCase):
    def test_scope_all_includes_unlinked(self):
        m = model()
        self.assertIn(uid(m, "Old draft"), m.scope)

    def test_graph_view_limits_nodes(self):
        m = model()
        keep = {uid(m, "Welcome"), uid(m, "Profile")}
        v = m.graph_view(keep)
        self.assertEqual(v.on_map, keep)
        ids = {n for e in v.edges(m) for n in e[:2]}
        self.assertNotIn(f"f-{uid(m, 'Weekly tip')}", ids)

    def test_graph_svg_namespaces_ids(self):
        m = model()
        a, ta = gsvg.graph_svg(m, m.graph_view({uid(m, "Welcome"), uid(m, "Profile")}), [], ns="u1-")
        b, tb = gsvg.graph_svg(m, m.graph_view({uid(m, "Weekly tip"), uid(m, "Ask AI")}), [], ns="u2-")
        ids = lambda s: set(re.findall(r'(?:\bid|data-id)="([^"]+)"', s))
        self.assertTrue(ids(a + "".join(ta)))
        self.assertFalse(ids(a + "".join(ta)) & ids(b + "".join(tb)))

    def test_faded_class(self):
        m = model()
        welcome, profile = uid(m, "Welcome"), uid(m, "Profile")
        svg, _ = gsvg.graph_svg(m, m.graph_view({welcome, profile}), [], ns="u1-", faded={profile})
        self.assertRegex(svg, rf'<g class="node flow[^"]*faded[^"]*" data-id="u1-f-{profile}"')


    def test_render_is_deterministic(self):
        import subprocess
        code = "from tests.org_programme_architecture.helpers import groups_page; print(groups_page())"
        outs = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                               env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}).stdout for seed in ("1", "2", "3")}
        self.assertEqual(len(outs), 1)


    def test_no_start_boxes_for_neighbours(self):
        m = model()
        copy = uid(m, "Ask AI copy")                     # has the keyword "test"
        v = m.graph_view({uid(m, "Welcome"), uid(m, "Profile"), copy}, no_starts={copy})
        self.assertNotIn(copy, v.trigger_flows)
        self.assertNotIn(copy, v.no_start)
        self.assertNotIn(f"k-{copy}", {n for e in v.edges(m) for n in e[:2]})


class NoFalseNoStart(unittest.TestCase):
    def test_neighbour_started_elsewhere_has_no_no_start_box(self):
        m = model(project="Demo")
        v = m.graph_view({U(3), U(2)})       # Weekly tip and Profile; Welcome (which starts Profile) is off the graph
        self.assertNotIn(U(2), v.no_start)


class OnlyStartedByHiddenFlow(unittest.TestCase):
    def test_flow_started_only_by_hidden_flow_gets_a_box(self):
        m = model()
        save, start = U(7), U(6)                     # Survey start enters Survey save
        v = m.graph_view({save}, ignore_callers={start})
        self.assertIn(save, v.no_start)
        svg, _ = gsvg.graph_svg(m, v, [])
        self.assertIn("Only test flows start it", svg)


class CallersAcrossExport(unittest.TestCase):
    def test_filler_with_real_caller_is_not_no_start(self):
        m = model()
        profile = next(u for u in m.flows if m.name(u) == "Profile")
        self.assertIn(profile, m.view.on_map)
        self.assertNotIn(profile, m.view.no_start)


class SettingFlows(unittest.TestCase):
    ORG = {"outOfOffice": {"defaultFlowId": "008"}}

    def test_default_flow_on_graph_without_tag(self):
        m = model(org=self.ORG)
        old = next(u for u in m.flows if m.name(u) == "Old draft")
        self.assertIn(old, m.view.on_map)
        self.assertIn(old, m.view.setting_flows)

    def test_tagged_setting_flow_on_graph(self):
        flows, triggers = load()
        by_name(flows, "Old draft")["tag"] = {"label": "Demo"}
        m = model(flows, triggers, org=self.ORG)
        old = next(u for u in m.flows if m.name(u) == "Old draft")
        self.assertIn(old, m.view.setting_flows)


class CapKeepsEntryFlows(unittest.TestCase):
    def test_entry_flows_survive_the_cap(self):
        import model as model_module
        saved = model_module.GRAPH_CAP
        model_module.GRAPH_CAP = 4
        try:
            m = model()
        finally:
            model_module.GRAPH_CAP = saved
        self.assertLessEqual(len(m.view.on_map), 6)        # the cap is really applied (plus group fillers)
        for name in ("Weekly tip", "Welcome", "Survey start"):
            self.assertIn(next(u for u in m.flows if m.name(u) == name), m.view.on_map, name)


class NoDuplicateGroupEdges(unittest.TestCase):
    def test_two_triggers_one_group_edge(self):
        flows, triggers = load()
        extra = copy.deepcopy(next(t for t in triggers if t["isActive"]))
        extra["id"] = "599"
        m = model(flows, triggers + [extra])
        gt = [e for e in m.view.edges(m) if e[2] == "gt"]
        self.assertEqual(len(gt), len(set(map(tuple, gt))))


class SettingsModelTest(unittest.TestCase):
    def test_setting_starts_mapped_by_flow_id(self):
        m = model(org=SETTINGS)
        self.assertIn("default flow", m.setting_starts[U(8)][0][1].lower())
        self.assertIn("new contact", m.setting_starts[U(1)][0][1].lower())

    def test_setting_flow_is_not_no_start(self):
        m = model(org=SETTINGS)
        v = m.graph_view({U(8)})
        self.assertNotIn(U(8), v.no_start)
        self.assertIn([f"s-{U(8)}", f"f-{U(8)}", "s"], v.edges(m))

    def test_graph_page_shows_setting_box(self):
        page = groups_page(org=SETTINGS)
        self.assertIn("Glific setting", page)
        self.assertNotIn("No start found for Old draft", page)

    def test_without_settings_nothing_changes(self):
        m = model(org=None)
        self.assertEqual(m.setting_starts, {})


class StartColumnTest(unittest.TestCase):
    def test_all_start_boxes_share_one_column(self):
        flows, triggers = load()
        m = md.Model(flows, triggers, md.Settings(today=date(2026, 11, 13)))
        svg, _ = gsvg.graph_svg(m, m.graph_view(set(m.flows)), [])
        xs = {float(x) for x in re.findall(r'data-id="[tkxs]-[^"]+"[^>]*><rect x="([\d.]+)"', svg)}
        self.assertGreaterEqual(len(re.findall(r'data-id="[tkxs]-', svg)), 3)
        self.assertEqual(len(xs), 1, xs)


if __name__ == "__main__":
    unittest.main()


class ViewConsistency(unittest.TestCase):
    def test_card_describes_the_graph_it_is_drawn_in(self):
        import cards
        m = model()
        tip = uid(m, "Weekly tip")
        rows = cards.flow_rows(m, tip, m.graph_view({tip}))      # Profile, which sets stage, is not on this graph
        self.assertIn("Reads stage set by Profile", rows)

    def test_edges_computed_once_per_view(self):
        m = model()
        self.assertIs(m.view.edges(m), m.view.edges(m))

    def test_build_view_needs_the_cap(self):
        import inspect
        import graph_view
        self.assertIs(inspect.signature(graph_view.build_view).parameters["cap"].default, inspect.Parameter.empty)
