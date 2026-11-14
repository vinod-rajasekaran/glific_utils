"""Trigger schedules in plain words, in the display time zone with UTC in brackets."""
from collections import Counter
from datetime import datetime, timedelta, timezone

from text import fmt_day, join, names, parse_utc, plural


WEEKDAYS = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}


def trigger_days(t):
    """Weekday numbers from the structured days field (1 = Monday ... 7 = Sunday)."""
    return [d for d in (t.get("days") or []) if isinstance(d, int)]


def clock(tz, start, hour_utc=None):
    """'06:00 (00:30 UTC)' in the display zone, or just UTC when the zone is UTC."""
    base = start or datetime.now(timezone.utc)
    utc = base.replace(hour=hour_utc, minute=0) if hour_utc is not None else base
    local = utc.astimezone(tz)
    if local.utcoffset() == timedelta(0):
        return f"{utc:%H:%M} UTC"
    return f"{local:%H:%M} ({utc:%H:%M} UTC)"


def schedule_text(t, tz, findings):
    start = parse_utc(t.get("startAt"))
    at = clock(tz, start) if start else "a time that could not be read"
    freq = (t.get("frequency") or "").lower() if t.get("isRepeating") else "once"
    if freq == "daily":
        return f"Every day at {at}"
    if freq == "weekly":
        days = trigger_days(t)
        return f"Every {join([WEEKDAYS.get(d, str(d)) for d in days], 7) or 'week, day not set,'} at {at}"
    if freq == "monthly":
        return f"Every month on day {join(map(str, t.get('days') or []), 31) or 'not set'} at {at}"
    if freq == "hourly":
        hours = [h for h in (t.get("hours") or []) if isinstance(h, int) and 0 <= h < 24]
        return f"Every day at {join([clock(tz, start, h) for h in hours], 24) or 'hours not set'}"
    if start:
        return f"Once on {fmt_day(start.astimezone(tz))} at {at}"
    return "Once, at a time that could not be read"


def window_text(t, tz):
    if not t.get("isRepeating"):
        return ""
    start, end = parse_utc(t.get("startAt")), parse_utc(t.get("endDate"))
    if start and end:
        return f"{fmt_day(start.astimezone(tz))} to {fmt_day(end)}"
    return f"From {fmt_day(start.astimezone(tz))}, with no end date" if start else ""


def schedule_title(ts):
    if len(ts) > 1:
        return f"{len(ts)} schedules"
    t = ts[0]
    if not t.get("isRepeating"):
        return "One-off run"
    return f"{(t.get('frequency') or 'Repeating').capitalize()} schedule"


def earlier_runs(ts, tz):
    starts = [d for d in (parse_utc(t.get("startAt")) for t in ts) if d]
    ends = [d for d in ((parse_utc(t.get("endDate")) if t.get("isRepeating") else None) or parse_utc(t.get("startAt")) for t in ts) if d]
    one_off = sum(1 for t in ts if not t.get("isRepeating"))
    freq = Counter((t.get("frequency") or "repeating").lower() for t in ts if t.get("isRepeating"))
    kinds = join(([f"{one_off} one-off"] if one_off else []) + [f"{n} {k}" for k, n in freq.most_common()])
    span = ""
    if starts:
        a, b = min(starts).astimezone(tz), max(ends + starts).astimezone(tz)
        span = f" on {fmt_day(a)}" if fmt_day(a) == fmt_day(b) else f" between {fmt_day(a)} and {fmt_day(b)}"
    groups = join([g for t in ts for g in names(t.get("groups")) + names(t.get("waGroups"))], 5)
    text = f"{plural(len(ts), 'earlier trigger')}{span}: {kinds}."
    return text + (f" Groups: {groups}." if groups else "")
