#!/usr/bin/env python3
"""Fetch all triggers (scheduled flow starts: nudges, API data pulls, broadcasts) from Glific.

Uses the same settings as glific_get_flows.py (the Glific client is in glific_common/api.py):
  python3 glific_get_triggers.py   # writes output/org_programme_architecture/<YYYY-MM-DD_HH-MM-SS>/triggers.json

Times (startAt, nextTriggerAt) are in UTC.
"""
import sys

from glific_get_flows import login, save_json
from glific_common.api import GlificError, paged
from glific_common.org_facts.schedules import WEEKDAYS as FULL_WEEKDAYS

TRIGGERS_QUERY = """
query triggers($filter: TriggerFilter, $opts: Opts) {
  triggers(filter: $filter, opts: $opts) {
    id
    name
    isActive
    isRepeating
    frequency
    days
    hours
    startAt
    nextTriggerAt
    endDate
    groupType
    groups
    waGroups
    flow { id uuid name isActive tag { label } }
  }
}
"""

WEEKDAYS = {k: v[:3] for k, v in FULL_WEEKDAYS.items()}  # one shared weekday map


def describe(t):
    """Human-readable schedule, e.g. 'weekly on Mon, Thu from 2025-06-01T04:30:00Z'."""
    freq = (t.get("frequency") or "none") if t.get("isRepeating") else "once"
    days, hours = t.get("days") or [], t.get("hours") or []
    if freq == "weekly" and days:
        freq += " on " + ", ".join(WEEKDAYS.get(d, str(d)) for d in days)
    elif freq == "monthly" and days:
        freq += " on day(s) " + ", ".join(map(str, days))
    elif freq == "hourly" and hours:
        freq += " at hour(s) " + ", ".join(map(str, hours)) + " UTC"
    when = f"{freq} from {t.get('startAt')}"
    if t.get("endDate"):
        when += f" until {t['endDate']}"
    return when


def get_all_triggers(token):
    try:
        return paged(TRIGGERS_QUERY, "triggers", token)
    except GlificError as e:
        sys.exit(str(e))


def fetch_triggers(token):
    """Fetch every trigger and add a readable `schedule` string to each."""
    triggers = get_all_triggers(token)
    for t in triggers:
        t["schedule"] = describe(t)
        flow = (t.get("flow") or {}).get("name") or "<no flow>"
        status = "ACTIVE  " if t.get("isActive") else "inactive"
        print(f"{status} {t['name']} -> {flow} | {t['schedule']} | groups: {t.get('groups')}", file=sys.stderr)
    return triggers


if __name__ == "__main__":
    triggers = fetch_triggers(login())
    path = save_json(triggers, "triggers.json")
    active = sum(1 for t in triggers if t.get("isActive"))
    print(f"Fetched {len(triggers)} triggers ({active} active) -> {path}", file=sys.stderr)
