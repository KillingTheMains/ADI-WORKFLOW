"""
Canonical time parsing and sort keys.

Times across ADI Workflow are stored as free-form display strings: mostly
12-hour ("1:00 PM"), sometimes 24-hour ("13:00"), occasionally unpadded
("8:00"). Ordering those as raw strings is what pushed afternoon items to
the bottom of the OSS master — lexically "1:00 PM" sorts AFTER "18:00",
because ':' (0x3A) is greater than '8' (0x38).

Anything that orders by time-of-day must go through here so every surface
agrees on what "chronological" means.
"""
import re

# Sorts after any real time-of-day, so blank / unparseable values land last
# instead of silently jumping to the top.
UNKNOWN = 10 ** 6

# "8", "8:00", "08:00", "13:00", "8AM", "1:00 PM", "7:30 p.m."
_STRICT_RE = re.compile(
    r'^\s*(\d{1,2})(?::(\d{2}))?\s*(?:([AP])\.?M\.?)?\s*$',
    re.I,
)

# Legacy-tolerant fallback: same shape but allows trailing text, e.g.
# "6:00 PM (doors)". Preserves the behaviour of the old hardcoded_service
# parser, which was unanchored.
_LOOSE_RE = re.compile(r'(\d{1,2}):(\d{2})\s*(?:([AP])\.?M\.?)?', re.I)


def _from_match(m):
    """Shared hour/minute/meridiem resolution for both patterns."""
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").upper()
    if minute > 59:
        return None
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        if meridiem == "P" and hour != 12:
            hour += 12
        elif meridiem == "A" and hour == 12:
            hour = 0
    elif hour > 23:
        return None
    return hour * 60 + minute


def parse_minutes(value):
    """'1:00 PM' / '13:00' / '8:00' -> minutes since midnight. None if unreadable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    m = _STRICT_RE.match(text)
    if m:
        return _from_match(m)
    m = _LOOSE_RE.search(text)
    return _from_match(m) if m else None


def sort_minutes(value, default=UNKNOWN):
    """Integer sort key for a time string. Blank/unreadable sorts last."""
    minutes = parse_minutes(value)
    return default if minutes is None else minutes


def hhmm(value):
    """Normalise to zero-padded 24-hour 'HH:MM'; '99:99' when unreadable."""
    minutes = parse_minutes(value)
    return "99:99" if minutes is None else "%02d:%02d" % divmod(minutes, 60)


def hhmm_or_blank(value):
    """Normalise to 24-hour 'HH:MM' for storage and for <input type="time">.

    Returns "" when the value is missing or unreadable — an HTML time input
    accepts ONLY 24-hour HH:MM and silently renders anything else as an empty
    box, which then posts back as blank and destroys the stored time.
    """
    minutes = parse_minutes(value)
    return "" if minutes is None else "%02d:%02d" % divmod(minutes, 60)


def from_minutes(minutes):
    """Minutes since midnight -> canonical 'HH:MM'. The inverse of parse_minutes.

    Anything that works out a time by arithmetic — a break offset off a crew
    call, a service window, a beverage refresh — comes back through here, so
    nothing ever invents a '25:30' that then renders as an empty time input.
    """
    if minutes is None:
        return ""
    return "%02d:%02d" % divmod(int(minutes) % (24 * 60), 60)


def earliest(values):
    """The chronologically earliest of several time strings (None if none parse)."""
    readable = [(parse_minutes(v), v) for v in values]
    readable = [pair for pair in readable if pair[0] is not None]
    return min(readable)[1] if readable else None
