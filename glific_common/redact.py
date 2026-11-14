"""Blanking credentials in Glific flow definitions before anything is saved or shown.

Glific keeps webhook credentials in flow definitions in plain text. redact_definition blanks
every webhook header value except Content-Type and Accept, user:password@ and query values in
webhook URLs, literal values of body fields named like keys or tokens, and anything shaped like
a JWT or Bearer token anywhere, including the editor's sticky notes.
"""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[redacted]"
# Headers that never carry secrets; every other header value is blanked.
SAFE_HEADERS = {"content-type", "accept"}
# Webhook body fields whose literal values are blanked ("@..." expressions are kept).
SECRET_FIELD = re.compile(
    r'("[^"]*(?:key|token|secret|passw|auth|credential|userid|user_id)[^"]*"\s*:\s*)'
    r'(?:"(?!@|\[redacted\]")(?:[^"\\]|\\.)*"|-?\d[\d.eE+-]*)', re.I)
# Credential-shaped strings anywhere in a definition: JWTs and Bearer tokens.
SECRET_VALUE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?<=Bearer )(?!\[redacted\])[^\s\"'\\]+", re.I)


def _scrub(value):
    """Apply SECRET_VALUE to every string inside value. Returns (new value, count)."""
    if isinstance(value, str):
        return SECRET_VALUE.subn(REDACTED, value)
    if isinstance(value, list):
        out, total = [], 0
        for item in value:
            item, n = _scrub(item)
            out.append(item)
            total += n
        return out, total
    if isinstance(value, dict):
        out, total = {}, 0
        for k, item in value.items():
            out[k], n = _scrub(item)
            total += n
        return out, total
    return value, 0


def redact_url(url):
    """Blank user:pass@ credentials and query-string values in a webhook URL.

    Returns (new url, count). A URL that cannot be parsed (e.g. a malformed
    password containing '/' or a bad port) is left unchanged rather than crashing
    the export. IPv6 hosts keep their brackets.
    """
    if "@" not in url.split("?")[0] and "?" not in url:
        return url, 0
    try:
        parts = urlsplit(url)
        username, password, port = parts.username, parts.password, parts.port
    except ValueError:
        return url, 0  # malformed URL; leave it as-is
    count = 0
    if "://" in url and (password or (username and username != "redacted")):
        host = parts.hostname or ""
        if ":" in host:          # IPv6 literal; urlsplit strips the brackets
            host = f"[{host}]"
        host += f":{port}" if port else ""
        parts = parts._replace(netloc=f"redacted@{host}")
        count += 1
    if parts.query:
        original = parse_qsl(parts.query, keep_blank_values=True)
        query = [(k, v if v.startswith("@") else REDACTED) for k, v in original]
        parts = parts._replace(query=urlencode(query, safe="@[]"))
        count += sum(1 for (_, old), (_, new) in zip(original, query) if old != new)
    return urlunsplit(parts), count


def redact_nodes(nodes):
    """Blank webhook credentials in place before anything is saved. Returns the count."""
    count = 0
    for node in nodes:
        for action in node.get("actions") or []:
            if action.get("type") != "call_webhook":
                continue
            headers = action.get("headers")
            if isinstance(headers, dict):
                for name in headers:
                    if name.lower() not in SAFE_HEADERS and headers[name] != REDACTED:
                        headers[name] = REDACTED
                        count += 1
            url = action.get("url")
            if isinstance(url, str):
                action["url"], n = redact_url(url)
                count += n
            body = action.get("body")
            if isinstance(body, str):
                action["body"], n = SECRET_FIELD.subn(lambda m: f'{m.group(1)}"{REDACTED}"', body)
                count += n
    # Safety net for tokens anywhere else in the definition, string by string
    cleaned, n = _scrub(nodes)
    if n:
        nodes[:] = cleaned
    return count + n


def redact_definition(definition):
    """Blank credentials in a flow definition: webhook details in its nodes, and tokens anywhere,
    including the editor's sticky notes in _ui. Returns the count."""
    count = redact_nodes(definition.get("nodes") or [])
    if isinstance(definition.get("_ui"), dict):
        definition["_ui"], n = _scrub(definition["_ui"])
        count += n
    return count
