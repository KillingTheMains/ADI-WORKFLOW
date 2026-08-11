"""Crew breaks, meal service windows, and the food-out rule.

See the project doc ADI_Breaks_And_Meals_Design.md. Pure arithmetic — no ORM,
no Flask — so the rules can be tested without a database and cannot drift
between the day page, the F&B tab and the exports. The one import is
time_utils, itself the single time parser; the two helpers that walk a day are
duck-typed on attributes rather than reaching for a model.

The central idea: a catered meal is ONE event with TWO times.

    setup 30m │ break (crew stops) 60m │ holdover 30m
    ──────────┼────────────────────────┼──────────────
    12:30     │  13:00 ────── 14:00    │ 14:30
    └──────────────── food out: 2h ─────────────────┘

Crew surfaces show the break window. F&B surfaces show the service window.
"""
from time_utils import from_minutes, parse_minutes

# House defaults, confirmed by Jason 2026-08-11.
DEFAULT_SETUP_MINUTES = 30
DEFAULT_SERVICE_MINUTES = 60
DEFAULT_HOLDOVER_MINUTES = 30

# Health and safety: total time food is out. Warned about, never blocked —
# real shows break this knowingly and a hard block just gets worked around.
FOOD_OUT_MAX_MINUTES = 120

# Standing beverage service.
BEVERAGE_SETUP_BEFORE_FIRST_CALL = 30
BEVERAGE_REFRESH_INTERVAL = 150      # 2h30. Longer than the food-out cap on
                                     # purpose — beverages are not hot food.


def service_window(break_start, duration=DEFAULT_SERVICE_MINUTES,
                   setup=DEFAULT_SETUP_MINUTES,
                   holdover=DEFAULT_HOLDOVER_MINUTES):
    """Break start (minutes since midnight) -> ``(set_at, teardown_at)``.

    This is what F&B works to. The crew never sees either number.
    """
    start = int(break_start)
    return (start - int(setup or 0),
            start + int(duration or 0) + int(holdover or 0))


def food_out_minutes(duration=DEFAULT_SERVICE_MINUTES,
                     setup=DEFAULT_SETUP_MINUTES,
                     holdover=DEFAULT_HOLDOVER_MINUTES):
    """Total time food is out: setup + service + holdover."""
    return int(setup or 0) + int(duration or 0) + int(holdover or 0)


def breaches_food_out_rule(duration=DEFAULT_SERVICE_MINUTES,
                           setup=DEFAULT_SETUP_MINUTES,
                           holdover=DEFAULT_HOLDOVER_MINUTES,
                           limit=FOOD_OUT_MAX_MINUTES):
    """True when food would be out longer than the limit.

    The house default of 30 + 60 + 30 lands exactly ON the limit, which is the
    point — the rule is what sets the defaults, so anything longer than a
    one-hour service is a deliberate choice someone should see.
    """
    return food_out_minutes(duration, setup, holdover) > limit


def beverage_touchpoints(first_crew_call, eod,
                         setup_before=BEVERAGE_SETUP_BEFORE_FIRST_CALL,
                         interval=BEVERAGE_REFRESH_INTERVAL):
    """Standing beverage service: ``[setup_minute, refresh, refresh, ...]``.

    Jason's spec: set up 30 minutes before the first crew call, then refresh
    every 2h30 — and **never past the day's EOD**. A refresh landing exactly on
    EOD is fine; past it is not.

    Returns ``[]`` when either anchor is missing. A day with no EOD cannot have
    refreshes generated, and guessing an end to the day would put F&B on site
    for a shift nobody scheduled — the caller must surface the reason instead,
    the way overlay_for_day reports a missing anchor.
    """
    if first_crew_call is None or eod is None:
        return []
    setup_at = int(first_crew_call) - int(setup_before or 0)
    if setup_at > int(eod):
        return []
    points = [setup_at]
    step = int(interval or 0)
    if step <= 0:
        return points
    t = setup_at + step
    while t <= int(eod):
        points.append(t)
        t += step
    return points


def group_breaks(breaks):
    """Breaks -> reading order: one period per meal, sittings underneath.

    Jason, 2026-08-11: breaks are EDITED on the crew call they hang off, and
    READ as one row per break period. So the day's timeline shows "LUNCH,
    3 sittings, 12:00 / 13:00 / 14:00" rather than three separate lunches
    interleaved with everything else.

    This is a DISPLAY grouping and nothing else. Each break stays its own
    record with its own service, because the 2-hour food-out rule means an
    08:00 and an 09:00 crew genuinely cannot share one sitting. It is also
    the same collapse ``oss_export._collapse_crew_breaks`` already does, so
    the screen and the printout finally describe the day the same way.

    Grouped by label, and a label group is SPLIT when two of its breaks come
    off the SAME crew call — one crew taking a morning and an afternoon break
    both typed "BREAK" is two periods, not one period the same crew attends
    twice. Breaks with no crew-call anchor never conflict, since there is
    nothing to tell them apart by.

    Duck-typed on ``label``, ``crew_call_id``, ``start_minute`` and
    ``duration_minutes``.
    """
    ordered = sorted(
        breaks,
        key=lambda b: (b.start_minute if b.start_minute is not None else 10 ** 6,
                       b.id or 0),
    )
    buckets = {}
    order = []
    for b in ordered:
        key = (b.label or "BREAK").strip().upper() or "BREAK"
        if key not in buckets:
            buckets[key] = []
        home = None
        for group in buckets[key]:
            clash = (b.crew_call_id is not None
                     and any(x.crew_call_id == b.crew_call_id for x in group))
            if not clash:
                home = group
                break
        if home is None:
            home = []
            buckets[key].append(home)
            order.append((key, home))
        home.append(b)
    return [_period(key, group) for key, group in order]


def _period(label, sittings):
    """One grouped row. ``catered`` is 'mixed' when the sittings disagree —
    never silently one of them, because 'the LX crew is fed and the riggers
    are not' is exactly the thing somebody needs to see."""
    states = {b.catered for b in sittings}
    first = sittings[0]
    counts = [b.derived_headcount for b in sittings]
    known = [c for c in counts if c is not None]
    return {
        "label": label,
        "minute": first.start_minute,
        "time": from_minutes(first.start_minute),
        "duration_minutes": first.duration_minutes,
        "sittings": sittings,
        "catered": states.pop() if len(states) == 1 else "mixed",
        "crew": sum(known) if known else None,
        "crew_partial": len(known) != len(counts),
    }


def is_crew_start(description):
    """Is this activity the moment a crew group arrives? ONE definition.

    Five copies of this test had formed — the break builder, the backfill, the
    master export, the day template and the beverage plan all need it, and a
    day where they disagree is a day where a break hangs off one activity and
    its headcount is read off another.
    """
    return "CREW START" in (description or "").upper()


def crew_starts_for_day(day):
    """``[(minutes, activity), ...]`` for every timed CREW START on the day.

    Duck-typed on purpose (``day.activities``, ``a.description``, ``a.time``) so
    this module still imports nothing.
    """
    out = []
    for a in day.activities:
        if is_crew_start(a.description):
            m = parse_minutes(a.time)
            if m is not None:
                out.append((m, a))
    return sorted(out, key=lambda p: p[0])


def guess_meal_kind(name):
    """Best guess at a MEAL_KINDS value from a label. ONE definition.

    Nothing here is authoritative — it only picks the opening value for a
    dropdown the user can change. It lives in one place because a label and
    the kind derived from it disagreeing across two copies is precisely how
    the XLSX and the PDF ended up describing the same row differently.
    """
    n = (name or "").upper()
    if "BREAKFAST" in n:
        return "breakfast"
    if "LUNCH" in n:
        return "lunch"
    if "DINNER" in n:
        return "dinner"
    if "BEVERAGE" in n or "COFFEE" in n:
        return "beverages"
    if "SNACK" in n:
        return "snack"
    return "other"


def on_site_at(crew_windows, minute):
    """How many crew are on site at ``minute``.

    ``crew_windows`` is an iterable of ``(start, end, qty)`` in minutes. Used
    for beverage refresh headcounts: Jason's rule is the total crew on site at
    each refresh time.

    A window with no end (hours not filled in) counts as still on site — a
    caterer under-catering because someone left ``hours`` blank is worse than
    over-catering. Callers should mark such figures as estimates.
    """
    total = 0
    for start, end, qty in crew_windows:
        if start is None or minute < start:
            continue
        if end is not None and minute >= end:
            continue
        total += int(qty or 0)
    return total


def called_before(crew_windows, minute):
    """Crew whose call begins before ``minute``.

    Jason's rule for the beverage SETUP headcount: the crew calls that begin
    before the first refresh.
    """
    return sum(int(qty or 0) for start, _end, qty in crew_windows
               if start is not None and start < minute)
