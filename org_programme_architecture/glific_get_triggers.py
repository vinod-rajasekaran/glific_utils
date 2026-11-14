#!/usr/bin/env python3
"""Fetch all triggers (scheduled flow starts: nudges, API data pulls, broadcasts) from Glific.

Uses the same settings as glific_get_flows.py (the Glific client is in glific_common/api.py):
  python3 glific_get_triggers.py   # writes output/org_programme_architecture/<YYYY-MM-DD_HH-MM-SS>/triggers.json

Times (startAt, nextTriggerAt) are in UTC.
"""
import sys

from glific_get_flows import login, save_json
from glific_common.api import GlificError
from glific_common.org_facts import fetch


def fetch_triggers(token):
    """Every trigger with a readable `schedule`; exits if they cannot be read."""
    try:
        return fetch.fetch_triggers(token)
    except GlificError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    triggers = fetch_triggers(login())
    path = save_json(triggers, "triggers.json")
    active = sum(1 for t in triggers if t.get("isActive"))
    print(f"Fetched {len(triggers)} triggers ({active} active) -> {path}", file=sys.stderr)
