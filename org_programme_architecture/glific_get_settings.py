#!/usr/bin/env python3
"""Fetch the organisation settings that start flows without a trigger or keyword.

    default flow       outOfOffice.defaultFlowId   any message that matches no keyword
    new contact flow   newcontactFlowId            the first message from a new contact
    opt-in flow        optinFlowId                 when a contact opts in
    out-of-office flow outOfOffice.flowId          messages outside working hours (when enabled)
    regex flow         regxFlow.flowId             messages matching a pattern

Only the organisation's name (for the page title), flow IDs and switches are read: no emails,
phone numbers or keys.

Usage (same env vars as the other scripts):
  python3 glific_get_settings.py      # writes settings.json to this run's folder
"""

from glific_get_flows import login, save_json
from glific_common.org_facts import fetch

fetch_settings = fetch.fetch_settings   # the organisation's flow settings, or {} with a warning


if __name__ == "__main__":
    print(f"Saved {save_json(fetch_settings(login()), 'settings.json')}")
