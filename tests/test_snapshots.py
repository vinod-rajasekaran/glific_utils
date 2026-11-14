"""Byte-for-byte snapshots of the pages for the made-up org, so refactoring cannot change output
unnoticed. After an intended change, regenerate with:  UPDATE_SNAPSHOTS=1 python3 -m unittest tests.test_snapshots
"""
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "org_programme_architecture"))

import programme_claude as uc  # noqa: E402
import programme_facts as uf  # noqa: E402
import render_graph as ra  # noqa: E402
import render_programmes as ru  # noqa: E402
from tests.test_review3 import hostile  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SNAP = ROOT / "tests" / "snapshots"
TODAY = date(2026, 11, 13)
ORG = {"newcontactFlowId": "001", "outOfOffice": {"defaultFlowId": "008"}}


def pages():
    flows = json.loads((FIX / "flows.json").read_text())
    triggers = json.loads((FIX / "triggers.json").read_text())
    out = {}
    out["graph.html"] = ra.render_html(flows, triggers, ra.Settings(project="Demo", tag="Demo", today=TODAY), org=ORG)[0]
    out["graph_notag.html"] = ra.render_html(flows, triggers, ra.Settings(project="Demo", today=TODAY), org=ORG)[0]
    st = ra.Settings(project="Demo", tag="Demo", scope_all=True, today=TODAY, notes="journey Field: f:Visit | c:Welcome")
    m = ra.Model(flows, triggers, st, org=ORG)
    facts = uf.build_facts(m)
    v, p = uc.validate(json.loads((FIX / "claude_output_programmes.json").read_text()), facts)
    gm = ra.Model(flows, triggers, ra.Settings(project="Demo", tag="Demo", today=TODAY), org=ORG)
    out["programmes.html"] = ru.render_programme_page(m, facts, v, p, st, graph_model=gm)
    out["facts.json"] = json.dumps(facts, indent=1, ensure_ascii=False, sort_keys=True)
    hf, ht = hostile()
    out["hostile_graph.html"] = ra.render_html(hf, ht, ra.Settings(project="Demo", today=TODAY))[0]
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
