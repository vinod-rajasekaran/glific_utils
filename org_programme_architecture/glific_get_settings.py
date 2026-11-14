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
import sys

from glific_get_flows import login, post as glific_post, save_json

SETTINGS_QUERY = """
query organization {
  organization {
    organization {
      name
      newcontactFlowId
      optinFlowId
      outOfOffice { enabled flowId defaultFlowId }
      regxFlow { flowId regx }
    }
    errors { key message }
  }
}
"""


def fetch_settings(token, post=glific_post):
    """The organisation's flow settings, or {} (with a warning) when they cannot be read."""
    try:
        result = post("/api", {"query": SETTINGS_QUERY}, token)
    except Exception as e:   # noqa: BLE001 - settings are optional; the flow map works without them
        print(f"Warning: could not read the organisation settings ({type(e).__name__}); "
              "flows started by Glific settings will show as 'No start found'.", file=sys.stderr)
        return {}
    org = ((result.get("data") or {}).get("organization") or {}).get("organization")
    if result.get("errors") or not org:
        print("Warning: the organisation settings were not returned; "
              "flows started by Glific settings will show as 'No start found'.", file=sys.stderr)
        return {}
    return org


if __name__ == "__main__":
    print(f"Saved {save_json(fetch_settings(login()), 'settings.json')}")
