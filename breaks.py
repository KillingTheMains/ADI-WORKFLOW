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
import re

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
DEFAULT_DURATION_FOR_OFFSET = {150: 15, 300: 60, 510: 15, 660: 60}

# ── What KIND of break it is, and what that changes ─────────────────────────
#
# Jason, 2026-08-12: "coffee breaks are the ones that are around 2.5 hours
# either after the start of the call or coming back from a meal break. So in a
# standard day, there would be 3 breaks: COFFEE, MEAL, COFFEE."
#
# That is why the house offsets are what they are, and it is worth writing
# down because they look arbitrary otherwise: +2:30 is 2.5h after the call;
# +5:00 is the meal; +8:30 is 2.5h after an hour-long meal ends. A show whose
# meal is 30 minutes puts its second coffee at +8:00 for the same reason.
#
# The difference the kind makes is ONE thing: a meal break asks whether F&B
# provides it, and a coffee break does not. Jason: "those are always 15
# minutes and they just are what they are." A crew helping itself from the
# standing beverage table is not a catering question, and asking it 54 times
# is how a real question stops being read.
KIND_MEAL = "meal"
KIND_COFFEE = "coffee"
BREAK_KINDS = (KIND_MEAL, KIND_COFFEE)

COFFEE_AFTER_MINUTES = 150       # "around 2.5 hours"
COFFEE_DURATION_MINUTES = 15     # "those are always 15 minutes"
MEAL_BREAK_LABEL = "MEAL BREAK"  # not LUNCH: the first meal is not always one
COFFEE_BREAK_LABEL = "COFFEE BREAK"

# The second meal. Jason, 2026-08-12: offered when any crew on the call is
# scheduled beyond 14 hours, and it sits at the 11th hour.
SECOND_MEAL_OFFSET = 660
LONG_CALL_HOURS = 14


def kind_for_offset(offset_minutes):
    """Which kind the house schedule puts at this offset.

    Unknown offsets are a MEAL, deliberately. Getting it wrong that way asks a
    catering question nobody needed; getting it wrong the other way silently
    removes one, and a missing meal on site is far worse than an extra line.
    """
    try:
        offset = int(offset_minutes)
    except (TypeError, ValueError):
        return KIND_MEAL
    if DEFAULT_DURATION_FOR_OFFSET.get(offset) == COFFEE_DURATION_MINUTES:
        return KIND_COFFEE
    return KIND_MEAL


def longest_shift_hours(crew_call):
    """The longest shift on this crew call, in hours. ``None`` when nobody has
    said — which is not zero, and must not be read as a short day.

    Duck-typed on ``crew_call.crew_rows`` and each row's ``hours``.
    """
    if crew_call is None:
        return None
    hours = [r.hours for r in getattr(crew_call, "crew_rows", [])
             if not getattr(r, "is_group_header", False) and r.hours]
    return max(hours) if hours else None


def needs_second_meal(crew_call):
    """Is anybody on this call working past ``LONG_CALL_HOURS``?

    False when the hours are unknown. The second meal is OFFERED, never
    created, so a silent False costs an option in a dropdown rather than a
    meal nobody ordered.
    """
    longest = longest_shift_hours(crew_call)
    return longest is not None and longest > LONG_CALL_HOURS


def break_options_for(crew_call):
    """The add-a-break choices for one crew call, in clock order.

    ONE definition, so the dropdown and the route that receives it cannot
    offer different things — the same reason ``default_duration_for`` exists.
    """
    out = [
        {"offset": 150, "kind": KIND_COFFEE, "label": COFFEE_BREAK_LABEL,
         "duration": 15, "text": "+2:30  Coffee"},
        {"offset": 300, "kind": KIND_MEAL, "label": MEAL_BREAK_LABEL,
         "duration": 60, "text": "+5:00  Meal"},
        {"offset": 510, "kind": KIND_COFFEE, "label": COFFEE_BREAK_LABEL,
         "duration": 15, "text": "+8:30  Coffee"},
    ]
    if needs_second_meal(crew_call):
        out.append({"offset": SECOND_MEAL_OFFSET, "kind": KIND_MEAL,
                    "label": MEAL_BREAK_LABEL, "duration": 60,
                    "text": "+11:00  Second meal"})
    return out


def default_duration_for(offset_minutes):
    """The house length for a break at this offset. ONE definition — the add
    form's JS and the route that receives it both read it, so a browser with
    JS off cannot save a different answer from one with it on."""
    try:
        return DEFAULT_DURATION_FOR_OFFSET.get(int(offset_minutes),
                                               DEFAULT_SERVICE_MINUTES)
    except (TypeError, ValueError):
        return DEFAULT_SERVICE_MINUTES


# "MORNING BREAK — 15 min" — the length, written into the name, by whoever
# built the schedule before the app had a field for it. Anchored to the END of
# the string and requiring the dash, so "LUNCH BREAK — 60 minute NOT PROVIDED"
# and "COFFEE BREAK — 08:00 CREW" do NOT match: a fragment in the middle of a
# label is not reliably its duration, and half-reading one is worse than not.
_DURATION_IN_LABEL = re.compile(
    r"\s*[—–-]\s*(\d{1,3})\s*(?:mins?|minutes?)\.?\s*$", re.IGNORECASE)


def duration_from_label(label):
    """``'MORNING BREAK — 15 min'`` -> ``(15, 'MORNING BREAK')``.

    Returns ``(None, label)`` unchanged when there is nothing to read.

    This exists because the old schedules wrote the length into the break's
    NAME, and the backfill only ever recovered a duration from a matching
    `RETURN FROM` row. Shows without those rows took the 60-minute house
    default for every break — so a fifteen-minute coffee printed as an hour on
    the day page, the call sheet and the client master, while its own label
    said fifteen. The answer was in the string the whole time.

    Reading the number out is NOT the same as guessing from a keyword. The
    length is stated; that a break is called COFFEE says nothing about how
    long it is, and this deliberately will not infer one.
    """
    text = (label or "").strip()
    m = _DURATION_IN_LABEL.search(text)
    if not m:
        return None, label
    minutes = int(m.group(1))
    if minutes <= 0 or minutes > 480:
        return None, label
    cleaned = text[:m.start()].strip().rstrip("—–-").strip()
    return minutes, (cleaned or label)


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
            # ...and a group cannot span more than one sitting's worth of
            # clock. Necessary from 2026-08-12, when LUNCH and DINNER both
            # became MEAL BREAK: two meals six hours apart off DIFFERENT crew
            # calls share a label and do not clash, so without this they
            # collapsed into one period row timed at the first of them, with
            # the evening meal hidden inside it as a sitting.
            #
            # FOOD_OUT_MAX_MINUTES is the right limit and not a new number:
            # it is already the app's statement of how long one service can
            # be out, so sittings further apart than that cannot be one meal.
            if not clash and group and b.start_minute is not None:
                first = group[0].start_minute
                if (first is not None
                        and abs(b.start_minute - first) > FOOD_OUT_MAX_MINUTES):
                    clash = True
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
    # A period asks the catering question only if its sittings do. A coffee
    # period showed a "TBD" pill on the day's timeline otherwise — putting the
    # question back on the one surface everybody reads, after the editor had
    # stopped offering any way to answer it.
    asks = any(getattr(b, "asks_catering", True) for b in sittings)
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
        "asks_catering": asks,
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

# Matched on WORD BOUNDARIES, which the plain substring test was not.
#
# 2026-08-12: "CREW BREAK" is a prefix of "CREW BREAKFAST", so a service named
# CREW BREAKFAST — one exists on MCDC26 — was read as a standing beverage
# service by all six consumers of this predicate. `can_link` refused to attach
# it to any break; `classify` marked a break it fed as NOT PROVIDED without
# ever reaching the meal-name branch three lines below, which was written to
# catch exactly that name; and the 08-11 repair migration would have unlinked
# it. Found by an ordering test, not by any of them.
#
# The plural forms are spelled out rather than left to a prefix match, because
# a prefix match is what caused this.
_BEVERAGE_RE = re.compile(
    r"\b(?:BEVERAGES?|REFRESH(?:ES|MENTS?)?|COFFEE|WATERS?|CREW BREAKS?)\b")

# NOT changed here: beverage wording still beats a stray meal word, so
# "Crew Break - Lunch Refresh" stays a beverage service. That is a deliberate
# earlier decision with a test on it — the failure it prevents is a standing
# beverage table being read as a catered meal. A meal word was tried as an
# override on 2026-08-12 and reverted when that test caught it; the bug was
# only ever the missing word boundary.


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
    return bool(_BEVERAGE_RE.search(name))


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
    # After the specific ones, so "LUNCH MEAL" is still lunch. Before the
    # rest, because since 2026-08-12 a break is a MEAL BREAK and a service
    # created from one was landing in "other" — which tells a caterer nothing
    # and reads on the F&B tab as though somebody forgot to pick.
    if "MEAL" in n:
        return "meal"
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
