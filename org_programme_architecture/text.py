"""Small text helpers shared by the pages: escaping, joining, plurals, dates and time zones."""
import html
import re
from datetime import datetime, timedelta, timezone

from privacy import mask

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None


ROW_WORDS = 25        # word cap per card row


def parse_tz(spec):
    """Return (tzinfo, label). Accepts 'IST, UTC+5:30', 'UTC+05:30' or 'Asia/Kolkata'."""
    spec = (spec or "UTC").strip()
    m = re.search(r"UTC\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", spec, re.I)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        offset = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)) * sign
        label = spec.split(",")[0].strip() if "," in spec else spec
        return timezone(offset), label
    if ZoneInfo and spec.upper() != "UTC":
        try:
            tz = ZoneInfo(spec)
            return tz, datetime.now(tz).tzname() or spec
        except Exception:
            pass
    return timezone.utc, "UTC"


def esc(value):
    """HTML-escape for text and attributes. Em dashes (banned on the page) become hyphens."""
    return html.escape(str(value).replace("\u2014", "-"), quote=True)


def typo(text):
    """Typographic apostrophes and quotes for visible text; no em dashes."""
    text = re.sub(r"(\w)'(\w)", "\\1\u2019\\2", str(text))
    text = re.sub(r'"([^"]*)"', "\u201c\\1\u201d", text)
    return text.replace("\u2014", ",")


def split_top(text, sep):
    """Split on sep, but not inside brackets."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and text.startswith(sep, i):
            parts.append(cur)
            cur, i = "", i + len(sep)
            continue
        cur += ch
        i += 1
    return parts + [cur]


def cap_words(text, limit=ROW_WORDS):
    """Keep rows under the word limit, cutting at clause or list boundaries where possible."""
    text = str(text)
    if len(text.split()) <= limit:
        return text
    for sep in ("; ", ". ", ", "):
        parts = split_top(text, sep)
        if len(parts) < 2:
            continue
        kept = []
        for part in parts:
            if len(" ".join(kept + [part]).split()) + 2 > limit:
                break
            kept.append(part)
        if kept:
            return sep.join(kept).rstrip(",;. ") + (", and more" if sep == ", " else f"{sep.strip()} And more" if sep == ". " else "; and more")
    return " ".join(text.split()[:limit]).rstrip(",;:") + " and more"


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def join(items, limit=6, last="and"):
    items = [str(i) for i in dict.fromkeys(items) if str(i)]
    extra = len(items) - limit
    if extra > 0:
        items = items[:limit] + [f"{extra} more"]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def names(items):
    """Groups and labels arrive as strings or as {name|label: ...} objects."""
    out = []
    for item in items or []:
        if isinstance(item, dict):
            item = item.get("name") or item.get("label")
        if item:
            out.append(mask(str(item)))   # group and label names can hold phone numbers or emails
    return out


def times(n):
    return "" if n == 1 else (" twice" if n == 2 else f" {n} times")


def sentence(text):
    text = str(text).strip()
    return (text[0].upper() + text[1:]) if text else ""


def parse_utc(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_day(dt):
    return f"{dt.day} {dt:%b %Y}" if dt else ""


def wrap(text, width, lines=2):
    """Split text into at most `lines` lines of about `width` characters, with an ellipsis when cut."""
    words, out, cur = re.split(r"(?<=[ _])", text), [], ""
    for w in words:
        if len(cur) + len(w) > width and cur:
            out.append(cur.rstrip())
            cur = ""
        while len(w) > width:
            out.append(w[:width])
            w = w[width:]
        cur += w
    if cur:
        out.append(cur.rstrip())
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][:width - 1].rstrip() + "\u2026"
    return out
