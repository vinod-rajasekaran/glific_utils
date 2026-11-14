"""Byte-for-byte snapshots of the pages for the made-up org, so refactoring cannot change output
unnoticed. After an intended change, regenerate with:  UPDATE_SNAPSHOTS=1 python3 -m unittest tests.test_snapshots
"""
import json
import os
import unittest

from tests.helpers import ROOT, TODAY, hostile, load  # also puts org_programme_architecture on sys.path

import model as md  # noqa: E402
import programme_claude as uc  # noqa: E402
import programme_facts as uf  # noqa: E402
import render_graph as ra  # noqa: E402
import render_programmes as ru  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SNAP = ROOT / "tests" / "snapshots"
ORG = {"newcontactFlowId": "001", "outOfOffice": {"defaultFlowId": "008"}}


def pages():
    flows, triggers = load()
    out = {}
    out["graph.html"] = ra.render_html(flows, triggers, md.Settings(project="Demo", tag="Demo", today=TODAY), org=ORG)[0]
    out["graph_notag.html"] = ra.render_html(flows, triggers, md.Settings(project="Demo", today=TODAY), org=ORG)[0]
    st = md.Settings(project="Demo", tag="Demo", scope_all=True, today=TODAY, notes="journey Field: f:Visit | c:Welcome")
    m = md.Model(flows, triggers, st, org=ORG)
    facts = uf.build_facts(m)
    v, p = uc.validate(json.loads((FIX / "claude_output_programmes.json").read_text()), facts)
    gm = md.Model(flows, triggers, md.Settings(project="Demo", tag="Demo", today=TODAY), org=ORG)
    out["programmes.html"] = ru.render_programme_page(m, facts, v, p, st, graph_model=gm)
    out["facts.json"] = json.dumps(facts, indent=1, ensure_ascii=False, sort_keys=True)
    hf, ht = hostile()
    out["hostile_graph.html"] = ra.render_html(hf, ht, md.Settings(project="Demo", today=TODAY))[0]
    return out


class SnapshotTest(unittest.TestCase):
    def test_pages_unchanged(self):
        got = pages()
        if os.environ.get("UPDATE_SNAPSHOTS"):
            for name, text in got.items():
                (SNAP / name).write_text(text, encoding="utf-8")
        for name, text in got.items():
            self.assertEqual(text, (SNAP / name).read_text(encoding="utf-8"), f"{name} changed; see the docstring")


if __name__ == "__main__":
    unittest.main()
