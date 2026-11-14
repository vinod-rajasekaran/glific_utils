import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import render_graph as ra  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def load():
    return json.loads((FIX / "flows.json").read_text()), json.loads((FIX / "triggers.json").read_text())


def model(**kw):
    flows, triggers = load()
    st = ra.Settings(today=date(2026, 11, 13), **kw)
    return ra.Model(flows, triggers, st)


def uid(m, name):
    return next(u for u in m.flows if m.name(u) == name)


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
        a, ta = ra.graph_svg(m, m.graph_view({uid(m, "Welcome"), uid(m, "Profile")}), [], ns="u1-")
        b, tb = ra.graph_svg(m, m.graph_view({uid(m, "Weekly tip"), uid(m, "Ask AI")}), [], ns="u2-")
        ids = lambda s: set(re.findall(r'(?:\bid|data-id)="([^"]+)"', s))
        self.assertTrue(ids(a + "".join(ta)))
        self.assertFalse(ids(a + "".join(ta)) & ids(b + "".join(tb)))

    def test_faded_class(self):
        m = model(scope_all=True)
        welcome, profile = uid(m, "Welcome"), uid(m, "Profile")
        svg, _ = ra.graph_svg(m, m.graph_view({welcome, profile}), [], ns="u1-", faded={profile})
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


if __name__ == "__main__":
    unittest.main()
