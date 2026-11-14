"""The model's scope and the graph views built from it: starts, groups, links, the cap and boxes."""
import copy
import json
import re
import sys
import unittest
from datetime import date

from tests.helpers import ROOT, FIX, U, SETTINGS, load, model, uid, by_name  # also puts org_programme_architecture on sys.path
import graph_svg as gsvg  # noqa: E402
import model as md  # noqa: E402
import render_graph as ra  # noqa: E402


class GraphSubsetTest(unittest.TestCase):
    def test_scope_all_includes_unlinked(self):
        m = model(scope_all=True)
        self.assertIn(uid(m, "Old draft"), m.scope)

    def test_graph_view_limits_nodes(self):
        m = model(scope_all=True)
        keep = {uid(m, "Welcome"), uid(m, "Profile")}
        v = m.graph_view(keep)
        self.assertEqual(v.on_map, keep)
        ids = {n for e in v.edges(m) for n in e[:2]}
        self.assertNotIn(f"f-{uid(m, 'Weekly tip')}", ids)

    def test_graph_svg_namespaces_ids(self):
        m = model(scope_all=True)
        a, ta = gsvg.graph_svg(m, m.graph_view({uid(m, "Welcome"), uid(m, "Profile")}), [], ns="u1-")
        b, tb = gsvg.graph_svg(m, m.graph_view({uid(m, "Weekly tip"), uid(m, "Ask AI")}), [], ns="u2-")
        ids = lambda s: set(re.findall(r'(?:\bid|data-id)="([^"]+)"', s))
        self.assertTrue(ids(a + "".join(ta)))
        self.assertFalse(ids(a + "".join(ta)) & ids(b + "".join(tb)))

    def test_faded_class(self):
        m = model(scope_all=True)
        welcome, profile = uid(m, "Welcome"), uid(m, "Profile")
        svg, _ = gsvg.graph_svg(m, m.graph_view({welcome, profile}), [], ns="u1-", faded={profile})
        self.assertRegex(svg, rf'<g class="node flow[^"]*faded[^"]*" data-id="u1-f-{profile}"')


    def test_render_is_deterministic(self):
        import subprocess
        code = ("import sys,json;sys.path.insert(0,'org_programme_architecture');import render_graph as r;"
                "from datetime import date;f=json.load(open('tests/fixtures/flows.json'));t=json.load(open('tests/fixtures/triggers.json'));"
                "print(r.render_html(f,t,r.Settings(today=date(2026,11,13)))[0])")
        outs = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                               env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}).stdout for seed in ("1", "2", "3")}
        self.assertEqual(len(outs), 1)


    def test_no_start_boxes_for_neighbours(self):
        m = model(scope_all=True)
        copy = uid(m, "Ask AI copy")                     # has the keyword "test"
        v = m.graph_view({uid(m, "Welcome"), uid(m, "Profile"), copy}, no_starts={copy})
        self.assertNotIn(copy, v.trigger_flows)
        self.assertNotIn(copy, v.no_start)
        self.assertNotIn(f"k-{copy}", {n for e in v.edges(m) for n in e[:2]})


class NoFalseNoStart(unittest.TestCase):
    def test_neighbour_started_elsewhere_has_no_no_start_box(self):
        m = model(project="Demo", scope_all=True)
        v = m.graph_view({U(3), U(2)})       # Weekly tip and Profile; Welcome (which starts Profile) is off the graph
        self.assertNotIn(U(2), v.no_start)


class OnlyStartedByHiddenFlow(unittest.TestCase):
    def test_flow_started_only_by_hidden_flow_gets_a_box(self):
        m = model(scope_all=True)
        save, start = U(7), U(6)                     # Survey start enters Survey save
        v = m.graph_view({save}, ignore_callers={start})
        self.assertIn(save, v.no_start)
        svg, _ = gsvg.graph_svg(m, v, [])
        self.assertIn("Only test flows start it", svg)


class CallersAcrossExport(unittest.TestCase):
    def test_filler_with_real_caller_is_not_no_start(self):
        flows, triggers = load()
        for f in flows:
            f["tag"] = {"label": "Only"} if f["name"] == "Weekly tip" else None
        m = model(flows, triggers, tag="Only")
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
        m = model(flows, triggers, org=self.ORG, tag="Demo")
        old = next(u for u in m.flows if m.name(u) == "Old draft")
        self.assertIn(old, m.view.setting_flows)


class CapKeepsEntryFlows(unittest.TestCase):
    def test_entry_flows_survive_the_cap(self):
        import model as model_module
        saved = model_module.GRAPH_CAP
        model_module.GRAPH_CAP = 4
        try:
            m = model(scope_all=True)
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
        m = model(flows, triggers + [extra], scope_all=True)
        gt = [e for e in m.view.edges(m) if e[2] == "gt"]
        self.assertEqual(len(gt), len(set(map(tuple, gt))))


class SettingsModelTest(unittest.TestCase):
    def test_setting_starts_mapped_by_flow_id(self):
        m = model(org=SETTINGS, scope_all=True)
        self.assertIn("default flow", m.setting_starts[U(8)][0][1].lower())
        self.assertIn("new contact", m.setting_starts[U(1)][0][1].lower())

    def test_setting_flow_is_not_no_start(self):
        m = model(org=SETTINGS, scope_all=True)
        v = m.graph_view({U(8)})
        self.assertNotIn(U(8), v.no_start)
        self.assertIn([f"s-{U(8)}", f"f-{U(8)}", "s"], v.edges(m))

    def test_graph_page_shows_setting_box(self):
        flows = json.loads((FIX / "flows.json").read_text())
        triggers = json.loads((FIX / "triggers.json").read_text())
        page, _ = ra.render_html(flows, triggers, md.Settings(today=date(2026, 11, 13)), org=SETTINGS)
        self.assertIn("Glific setting", page)
        self.assertNotIn("No start found for Old draft", page)

    def test_without_settings_nothing_changes(self):
        m = model(org=None, scope_all=True)
        self.assertEqual(m.setting_starts, {})


class StartColumnTest(unittest.TestCase):
    def test_all_start_boxes_share_one_column(self):
        flows, triggers = load()
        m = md.Model(flows, triggers, md.Settings(scope_all=True, today=date(2026, 11, 13)))
        svg, _ = gsvg.graph_svg(m, m.graph_view(set(m.flows)), [])
        xs = {float(x) for x in re.findall(r'data-id="[tkxs]-[^"]+"[^>]*><rect x="([\d.]+)"', svg)}
        self.assertGreaterEqual(len(re.findall(r'data-id="[tkxs]-', svg)), 3)
        self.assertEqual(len(xs), 1, xs)


if __name__ == "__main__":
    unittest.main()
