"""The Glific API: settings from .env, login, GraphQL calls and paging.

Settings (repo-root .env or the shell; the shell wins):
  GLIFIC_URL        the API host, e.g. https://api.yourorg.glific.com (no trailing /api)
  GLIFIC_PHONE      a staff login phone number, with country code
  GLIFIC_PASSWORD   its password
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 100


class GlificError(RuntimeError):
    """Glific refused a call or returned GraphQL errors."""


def load_env(path=ROOT / ".env"):
    """Load KEY=VALUE lines from the repo-root .env, if present. Shell variables win; empty values
    are skipped; GLIFIC_NO_DOTENV turns this off (the tests use it)."""
    path = Path(path)
    if not path.is_file() or os.environ.get("GLIFIC_NO_DOTENV"):
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]  # drop one pair of matching surrounding quotes only
        if value:   # an empty line in .env must not mask credentials set elsewhere
            os.environ.setdefault(key, value)


load_env()


def missing_settings():
    """The required settings that are not set, in order."""
    return [k for k in ("GLIFIC_URL", "GLIFIC_PHONE", "GLIFIC_PASSWORD") if not os.environ.get(k)]


def post(path, payload, token=None):
    """POST JSON to the Glific host and return the decoded reply."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(
        os.environ["GLIFIC_URL"].rstrip("/") + path, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def login(post=post):
    """A fresh access token for the staff account in the settings."""
    body = {"user": {"phone": os.environ["GLIFIC_PHONE"], "password": os.environ["GLIFIC_PASSWORD"]}}
    return post("/api/v1/session", body)["data"]["access_token"]


def graphql(query, variables=None, token=None, post=post):
    """Run one GraphQL query and return its data; GraphQL errors raise GlificError."""
    result = post("/api", {"query": query, "variables": variables or {}}, token)
    if result.get("errors"):
        raise GlificError(f"GraphQL error: {result['errors']}")
    return result.get("data") or {}


def paged(query, field, token, filter=None, page_size=PAGE_SIZE, post=post):
    """Every item of a list query that takes (filter, opts), fetched page by page."""
    items, offset = [], 0
    while True:
        variables = {"filter": filter or {}, "opts": {"order": "ASC", "limit": page_size, "offset": offset}}
        page = graphql(query, variables, token, post=post)[field]
        items.extend(page)
        if len(page) < page_size:
            return items
        offset += page_size


class Session:
    """A logged-in connection for long-running callers (the MCP server): logs in on first use and
    once more if Glific rejects the token."""

    def __init__(self, post=post):
        self._post, self._token = post, None

    def query(self, query, variables=None):
        for attempt in (1, 2):
            if self._token is None:
                self._token = login(post=self._post)
            try:
                return graphql(query, variables, self._token, post=self._post)
            except (urllib.error.HTTPError, GlificError) as e:
                expired = getattr(e, "code", None) == 401 or "unauthor" in str(e).lower()
                if not expired or attempt == 2:
                    raise
                self._token = None
