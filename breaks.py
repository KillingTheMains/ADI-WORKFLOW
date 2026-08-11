"""Crew breaks, meal service windows, and the food-out rule.

See the project doc ADI_Breaks_And_Meals_Design.md. Pure arithmetic — no ORM,
no Flask — so the rules can be tested without a database and cannot drift
between the day page, the F&B tab and the exports.

The central idea: a catered meal is ONE event with TWO times.

    setup 30m │ break (crew stops) 60m │ holdover 30m
    ──────────┼────────────────────────┼──────────────
    12:30     │  13:00 ────── 14:00    │ 14:30
    └──────────────── food out: 2h ─────────────────┘

Crew surfaces show the break window. F&B surfaces show the service window.
"""

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
