"""Masking of personal data and secrets, in one place.

    mask(text, staff)            phone numbers, emails, links, secrets and staff names, no cut
    clean_text(text, staff, n)   mask, then cut to n characters without splitting a letter
    staff_names(flows)           staff contact names from staff alerts and ticket assignees

The model masks every name and label it reads from the export with mask(), so the page and
the facts sent to Claude both get masked text; excerpts of messages and notes go through
clean_text() as well.
"""
import re
import unicodedata
from urllib.parse import urlsplit

EXCERPT_CHARS = 200
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"(?:https?://|\bwww\.)[^\s\"'<>)]+", re.I)
BARE_LINK = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}/[^\s\"'<>)]*")      # host.tld/path without a scheme
# 8 or more digits with at most one separator between them (space, dot, dash, or a closing bracket
# and a space), so "+91 98765 43210" and "(022) 2345 6789" match but a range like "2501 - 4000" does not
PHONE = re.compile(r"\+?\(?\d(?:(?:[\s.\-]|\)\s?)?\d){7,}")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
HOSTNAME = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
SECRET = re.compile(
    r"(?<=Bearer )\S+"                                      # bearer tokens
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"   # JWTs
    r"|\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]+"              # Stripe-style keys
    r"|\bxox[abprs]-[A-Za-z0-9-]+"                          # Slack tokens
    r"|\bAIza[0-9A-Za-z_-]{20,}"                           # Google API keys
    r"|(?<![\w.-])(?=[A-Za-z0-9_]*\d)(?=[A-Za-z0-9_]*[A-Za-z])[A-Za-z0-9_]{32,}(?![\w.-])")
# The long-token rule leaves out hyphens and dots, so hostnames such as
# volunteer-digital-onboarding-123456789012.europe-west1.run.app are not taken for keys
VIRAMA_ETC = {"\u094d", "\u09cd", "\u0a4d", "\u0acd", "\u0b4d", "\u0bcd", "\u0c4d", "\u0ccd", "\u0d4d", "\u200c", "\u200d"}


def host_of(url):
    text = url if "://" in url else "http://" + url
    try:
        return urlsplit(text).hostname or "[link]"
    except ValueError:
        return "[link]"


def _name_pattern(name):
    return re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I)


def _cut(text, limit):
    """Cut at `limit` characters without splitting a letter from its vowel sign or virama."""
    if len(text) <= limit:
        return text
    cut = limit
    while cut > 0 and (unicodedata.category(text[cut]).startswith("M") or text[cut - 1] in VIRAMA_ETC or text[cut] in VIRAMA_ETC):
        cut -= 1
    return text[:cut].rstrip() + "\u2026"


def mask(text, staff=()):
    """Personal data and secrets out of one piece of text; nothing is cut."""
    out = str(text or "")
    out = SECRET.sub("[secret]", out)                         # before links, so tokens in paths go too
    out = URL.sub(lambda mm: host_of(mm.group(0)), out)         # before emails, so user:pw@host links go whole
    out = BARE_LINK.sub(lambda mm: host_of(mm.group(0)), out)
    out = EMAIL.sub("[email]", out)
    names = set()
    for n in staff:
        if n and len(n) > 2:
            names.add(n)
            names.update(p for p in re.split(r"[\s.]+", n) if len(p) > 2)
    for name in sorted(names, key=len, reverse=True):
        out = _name_pattern(name).sub("a staff contact", out)
    # Dates and hostnames (a Cloud Run host carries a long project number) are kept out of the
    # phone rule, then put back
    kept = []

    def keep(mm):
        kept.append(mm.group(0))
        return f"\x00{len(kept) - 1}\x00"
    out = ISO_DATE.sub(keep, out)
    out = HOSTNAME.sub(keep, out)
    out = PHONE.sub("[number]", out)
    return re.sub(r"\x00(\d+)\x00", lambda mm: kept[int(mm.group(1))], out)


def clean_text(text, staff_names, limit=EXCERPT_CHARS):
    """Strip personal data and long links from one piece of text, then cut it to `limit` characters."""
    return _cut(re.sub(r"\s+", " ", mask(text, staff_names)).strip(), limit)


def staff_names(flows):
    """Names of staff contacts in staff alerts and ticket assignees, anywhere in the export.

    A contact named like a flow (an org or team account such as a helpline) is not a person,
    and masking it would garble the messages that mention the org. When only part of a name
    appears as a word in flow names, the other parts are returned on their own instead."""
    found = set()
    for f in flows.values():
        for n in f.get("nodes") or []:
            for a in n.get("actions") or []:
                if a.get("type") == "send_broadcast":
                    found.update(c.get("name") for c in a.get("contacts") or [] if isinstance(c, dict))
                elif a.get("type") == "open_ticket" and isinstance(a.get("assignee"), dict):
                    found.add(a["assignee"].get("name"))
    flow_names = " ".join(str(f.get("name") or "") for f in flows.values())
    in_flow_names = lambda w: bool(_name_pattern(w).search(flow_names))
    out = set()
    for name in (n for n in found if n):
        if in_flow_names(name):
            continue
        parts = [p for p in re.split(r"[\s.]+", name) if len(p) > 2]
        if any(in_flow_names(p) for p in parts):
            out.update(p for p in parts if not in_flow_names(p))
        else:
            out.add(name)
    return out
