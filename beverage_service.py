"""Standing beverage service — the day's setup and refresh touchpoints.

See ADI_Breaks_And_Meals_Design.md §4. A standing service is not a break and
not a point-in-time meal: F&B sets up before the first crew arrives and tops
up through the day, and the crew never stops working for it.

    setup at (first crew call − 30m), then a refresh every 2h30, never past EOD

**Touchpoints are COMPUTED, never stored.** They depend on the first crew call,
on the day's EOD and on who is on site — all three of which move during
planning. A stored copy would be a set of times that were right on the day
somebody pressed a button, which is exactly the staleness this whole overhaul
exists to remove.

The arithmetic lives in breaks.py and is tested without a database. This module
only walks the day and hands it the numbers.
"""
from breaks import (BEVERAGE_REFRESH_INTERVAL, BEVERAGE_REFRESH_LABEL,
                    BEVERAGE_SETUP_BEFORE_SOD, BEVERAGE_SETUP_LABEL,
                    beverage_touchpoints, called_before, crew_starts_for_day,
                    on_site_at)
from time_utils import from_minutes, parse_minutes

SETUP = "setup"
REFRESH = "refresh"

# Why a day cannot have touchpoints. Surfaced verbatim — a plan that silently
# comes back empty reads as "no beverages needed", which is not what it means.
NO_SOD = ("This day has no SOD set, so there is nothing to anchor the "
          "beverage service to. Set the day's start time.")
NO_EOD = ("This day has no EOD set, so there is no end to stop refreshing at. "
          "Set the day's EOD and the touchpoints appear.")
SETUP_AFTER_EOD = ("The day ends before the beverage service would be set. "
                   "Check the SOD, the offset and the EOD.")


def crew_windows_for_day(day):
    """``([(start, end, qty), ...], estimated)`` in minutes, per crew group.

    Read from CREW START activities only. Crew rows hang off other activities
    too, and counting those would bill the same rigger three times over: a
    crew group arrives once, at its call.

    ``end`` is the call plus ``CrewRow.hours``. Where hours are blank there is
    no end, which ``on_site_at`` treats as still on site — over-catering beats
    a caterer who under-ordered because a planner left a box empty. The second
    return value says whether any row was missing hours, so the figure can be
    shown as the estimate it is.
    """
    from models import iter_people

    windows = []
    estimated = False
    for minute, act in crew_starts_for_day(day):
        # ⚠️ This loop used to carry its own copy of the headcount rule, and
        # its copy was the OLD one — `if row.crew_member_id: qty = 1`, which
        # throws `qty` away. That is the bug fixed in count_people on
        # 2026-08-12, which survived here in a second file because nothing
        # pointed the two at each other.
        #
        # An UNFILLED SLOT carries a crew_member_id (it points at a
        # placeholder record like "Sparks Lighting Hand"), so every local
        # labour line counted as ONE body: a crew call of three leads and
        # 14 + 7 + 6 local reported SIX people on site instead of thirty, and
        # that number is what a beverage refresh is ordered against.
        #
        # `iter_people` is now the only definition, shared with count_people.
        # Do not reintroduce a local rule here.
        for row, qty in iter_people(act.crew_rows):
            if not qty:
                continue            # a named person already counted
            hours = row.hours
            if hours:
                windows.append((minute, minute + int(round(float(hours) * 60)), qty))
            else:
                windows.append((minute, None, qty))
                estimated = True
    return windows, estimated


def plan_for_day(day, offset=None, interval=None):
    """The day's beverage touchpoints, or the reason there are none.

    Returns ``{"points": [...], "reason": str|None, "estimated": bool,
    "sod": str, "eod": str}``. Each point is ``{"minute", "time", "kind",
    "label", "headcount"}`` — enough to render as a row on the schedule.

    Anchored to the day's **SOD** plus a per-service offset (Jason,
    2026-08-11), not to the first crew call. A day with no EOD gets no
    refreshes and a reason, never a guessed end — inventing one would put F&B
    on site for a shift nobody scheduled.
    """
    empty = {"points": [], "estimated": False, "sod": "", "eod": ""}
    sod = parse_minutes(getattr(day, "sod", None))
    if sod is None:
        return dict(empty, reason=NO_SOD)
    eod = parse_minutes(getattr(day, "eod", None))
    if eod is None:
        return dict(empty, reason=NO_EOD, sod=from_minutes(sod))

    step = int(interval or BEVERAGE_REFRESH_INTERVAL)
    minutes = beverage_touchpoints(
        sod, eod,
        offset if offset is not None else BEVERAGE_SETUP_BEFORE_SOD,
        step)
    if not minutes:
        return dict(empty, reason=SETUP_AFTER_EOD,
                    sod=from_minutes(sod), eod=from_minutes(eod))

    windows, estimated = crew_windows_for_day(day)
    points = []
    for i, m in enumerate(minutes):
        if i == 0:
            # The set headcount is the crew arriving before the first top-up —
            # measured against setup + interval whether or not that refresh
            # survives the EOD rule, so a short day still reports the crew it
            # is setting up for rather than the nobody on site beforehand.
            head = called_before(windows, m + step)
            kind, label = SETUP, BEVERAGE_SETUP_LABEL
        else:
            head = on_site_at(windows, m)
            kind, label = REFRESH, BEVERAGE_REFRESH_LABEL
        points.append({"minute": m, "time": from_minutes(m), "kind": kind,
                       "label": label, "headcount": head})
    return {"points": points, "reason": None, "estimated": estimated,
            "sod": from_minutes(sod), "eod": from_minutes(eod)}


def plan_for_service(svc, **kwargs):
    """The plan for a standing service, using ITS offset and interval."""
    day = getattr(svc, "schedule_day", None)
    if day is None:
        return None
    kwargs.setdefault("offset", svc.beverage_offset_minutes)
    kwargs.setdefault("interval", svc.beverage_interval_minutes)
    return plan_for_day(day, **kwargs)


def overlay_for_day(day, services):
    """Every standing service's touchpoints on this day, as placeable rows.

    Shaped for ``hardcoded_service.place_in_day`` — a ``sort_min`` key and
    nothing else required — so beverage refreshes land in the day's timeline,
    the show book and the exports exactly the way recurring events do.

    **Computed on every read, never stored.** Jason wanted them to appear as
    schedule events; storing them would also mean they stop moving when SOD or
    EOD does, which is the staleness that retired the old break builder.
    """
    rows = []
    for svc in services:
        if not svc.is_recurring:
            continue
        plan = plan_for_day(day, svc.beverage_offset_minutes,
                            svc.beverage_interval_minutes)
        for p in plan["points"]:
            rows.append(dict(p, sort_min=p["minute"], service=svc,
                             estimated=plan["estimated"]))
    return sorted(rows, key=lambda r: r["sort_min"])
