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

# What each offset is FOR. +2:30 and +8:30 are the morning and afternoon
# coffee; +5:00 is lunch. Jason, 2026-08-11 — picking the offset should pick
# the length, because nobody takes an hour for a coffee.
DEFAULT_DURATION_FOR_OFFSET = {150: 15, 300: 60, 510: 15}


def default_duration_for(offset_minutes):
    """The house length for a break at this offset. ONE definition — the add
    form's JS and the route that receives it both read it, so a browser with
    JS off cannot save a different answer from one with it on."""
    try:
        return DEFAULT_DURATION_FOR_OFFSET.get(int(offset_minutes),
                                               DEFAULT_SERVICE_MINUTES)
    except (TypeError, ValueError):
        return DEFAULT_SERVICE_MINUTES


def duration_text(minutes):
    """'15 Minutes'. Jason's wording, one definition, so the day page and any
    document that later wants it cannot disagree."""
    if not minutes:
        return ""
    return f"{int(minutes)} Minutes"


def window_end(start_minute, duration_minutes):
    """When the crew is back. None when the start is unreadable."""
    if start_minute is None:
        return None
    return int(start_minute) + int(duration_minutes or 0)


# Standing beverage service. The offset is from the day's SOD and is NEGATIVE
# for "before SOD" — it is a per-service setting, and these are only the values
# the create form opens with.
BEVERAGE_SETUP_BEFORE_SOD = -30
BEVERAGE_REFRESH_INTERVAL = 150      # 2h30. Longer than the food-out cap on
                                     # purpose — beverages are not hot food.
# How close to EOD a refresh may fall. Jason, 2026-08-11: 1h30, and NOT tied
# to the refresh interval — a shop that tops up every four hours should not
# stop four hours early. It is about how long the last pot is worth drinking,
# which does not change with how often you make one.
BEVERAGE_EOD_THRESHOLD = 90
# What the generated refresh events are called on the schedule.
BEVERAGE_SETUP_LABEL = "Beverage Service Set"
BEVERAGE_REFRESH_LABEL = "Beverage Service Refresh"


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


def beverage_touchpoints(sod, eod, offset=BEVERAGE_SETUP_BEFORE_SOD,
                         interval=BEVERAGE_REFRESH_INTERVAL,
                         eod_threshold=BEVERAGE_EOD_THRESHOLD):
    """Standing beverage service: ``[setup_minute, refresh, refresh, ...]``.

    Jason's spec, 2026-08-11:

    * set up at **SOD plus an offset chosen when the service is created** —
      negative for "before SOD";
    * refresh every ``interval`` after that;
    * **no refresh within ``eod_threshold`` of EOD** — 1h30 by default.
      Setting out a fresh service shortly before wrap is waste; it would be
      cleared away almost immediately. So the last refresh lands at or before
      ``eod - eod_threshold``.

    The threshold is deliberately NOT the refresh interval (it was, briefly):
    a service topped up every four hours should not stop four hours early.
    How long the last pot is worth drinking does not change with how often
    you make one.

    Returns ``[]`` when either anchor is missing. A day with no EOD cannot have
    refreshes generated, and guessing an end to the day would put F&B on site
    for a shift nobody scheduled — the caller must surface the reason instead,
    the way overlay_for_day reports a missing anchor.
    """
    if sod is None or eod is None:
        return []
    setup_at = int(sod) + int(offset or 0)
    if setup_at > int(eod):
        return []
    points = [setup_at]
    step = int(interval or 0)
    if step <= 0:
        return points
    # The setup itself is allowed to sit inside the final window — it is the
    # service starting, not a top-up nobody will drink.
    last_allowed = int(eod) - int(eod_threshold or 0)
    t = setup_at + step
    while t <= last_allowed:
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
        # The crew wants to know when it is back, not just when it stops.
        "end_time": from_minutes(window_end(first.start_minute,
                                            first.duration_minutes)),
        "duration_minutes": first.duration_minutes,
        "duration_text": duration_text(first.duration_minutes),
        "sittings": sittings,
        "catered": states.pop() if len(states) == 1 else "mixed",
        "crew": sum(known) if known else None,
        "crew_partial": len(known) != len(counts),
    }


def break_export_text(label, duration_minutes):
    """How a break reads on a document. ONE definition, matching the screen.

    ``LUNCH — 60 Minutes``.

    It used to carry a trailing ``— 07:00 CREW`` stamp, because the master
    export's only way to tell two sittings of the same break apart was to
    regex it back out of the description. That made a presentation string
    load-bearing, and it printed the break builder talking to itself on a
    document that goes to a client. Break items now carry ``break_label`` and
    ``break_call_id`` instead, so the text can just be the text.
    """
    name = (label or "BREAK").strip() or "BREAK"
    suffix = duration_text(duration_minutes)
    return f"{name} — {suffix}" if suffix else name


# A service is a standing beverage setup if ANY of these say so. The explicit
# flag is the modern answer; the kind and the name catch the legacy services
# Larry created before the model had anywhere to put a beverage table.
BEVERAGE_WORDS = ("BEVERAGE", "REFRESH", "COFFEE", "WATER", "CREW BREAK")


def is_beverage_service(service):
    """Is this service a standing beverage setup rather than a meal?

    ONE definition. The break backfill, the linking rules and the repair
    migration all need it, and they did NOT agree: the repair tested only
    `is_recurring` while the backfill also read the kind and the name, so it
    silently missed every legacy service — which is all of them on MCDC26.

    Duck-typed on ``is_recurring``, ``kind`` and ``name``.
    """
    if service is None:
        return False
    if getattr(service, "is_recurring", False):
        return True
    if (getattr(service, "kind", "") or "").lower() == "beverages":
        return True
    name = (getattr(service, "name", "") or "").upper()
    return any(word in name for word in BEVERAGE_WORDS)


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
