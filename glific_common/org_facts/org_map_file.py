"""org_map.json: what an org map run concluded, saved next to org_map.html for the MCP server.

It holds only cleaned data: Claude's validated answer (written from the cleaned facts) or the
groups by links, what validation dropped, and the masked flow names the answer refers to."""
import json
from datetime import datetime

FILENAME = "org_map.json"


def record(m, answer, dropped):
    """The org_map.json content for a model and its answer (Claude's, or grouping.group_answer's)."""
    source = answer.get("source") or "claude"
    return {
        "built": datetime.now().isoformat(timespec="seconds"),
        "project": m.st.project,
        "source": source,
        "reason": answer.get("reason", ""),
        "model": answer.get("model", ""),
        "answer": answer,
        "dropped": list(dropped),
        "flow_names": {u: m.name(u) for u in sorted(m.flows, key=m.name_key)},
    }


def latest(root):
    """(path, data) of the newest org_map.json under root built with Claude, else of the newest one
    (grouped by links), else (None, None). A later run without Claude does not hide Claude's reading."""
    if not root.is_dir():
        return None, None
    fallback = (None, None)
    for run in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        path = run / FILENAME
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("source") == "claude":
                return path, data
            fallback = fallback if fallback[0] else (path, data)
    return fallback
