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
import render_org_map as ru  # noqa: E402
from grouping import group_answer  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SNAP = ROOT / "tests" / "snapshots"
ORG = {"newcontactFlowId": "001", "outOfOffice": {"defaultFlowId": "008"}}
NO_CLAUDE = "it was run with --no-claude"


def _groups(flows, triggers, org=None):
    m = md.Model(flows, triggers, md.Settings(project="Demo", today=TODAY), org=org)
    return ru.render_org_map(m, uf.build_facts(m), group_answer(m, NO_CLAUDE))


def pages():
    flows, triggers = load()
    out = {"org_map_groups.html": _groups(flows, triggers, ORG)}
    st = md.Settings(project="Demo", today=TODAY, notes="journey Field: f:Visit | c:Welcome")
    m = md.Model(flows, triggers, st, org=ORG)
    facts = uf.build_facts(m)
    v, p = uc.validate(json.loads((FIX / "claude_output_programmes.json").read_text()), facts)
    out["org_map_claude.html"] = ru.render_org_map(m, facts, v, p)
    out["facts.json"] = json.dumps(facts, indent=1, ensure_ascii=False, sort_keys=True)
    out["hostile_groups.html"] = _groups(*hostile())
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
