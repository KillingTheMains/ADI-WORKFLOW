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
from breaks import (BEVERAGE_REFRESH_INTERVAL, BEVERAGE_SETUP_BEFORE_FIRST_CALL,
                    beverage_touchpoints, called_before, crew_starts_for_day,
                    on_site_at)
from time_utils import from_minutes, parse_minutes

SETUP = "setup"
REFRESH = "refresh"

# Why a day cannot have touchpoints. Surfaced verbatim — a plan that silently
# comes back empty reads as "no beverages needed", which is not what it means.
NO_CREW_START = ("This day has no Crew Start with a time on it, so there is "
                 "nothing to set up ahead of.")
NO_EOD = ("This day has no EOD set, so there is no end to stop refreshing at. "
          "Set the day's EOD and the touchpoints appear.")
SETUP_AFTER_EOD = ("The day ends before the beverage setup would happen. "
                   "Check the Crew Start and EOD times.")


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
    windows = []
    estimated = False
    for minute, act in crew_starts_for_day(day):
        seen = set()
        for row in act.crew_rows:
            if row.is_group_header:
                continue
            if row.crew_member_id:
                # One person is one body however many rows they hold, the same
                # rule ScheduleActivity.crew_headcount uses.
                if row.crew_member_id in seen:
                    continue
                seen.add(row.crew_member_id)
                qty = 1
            else:
                qty = row.qty or 1
            hours = row.hours
            if hours:
                windows.append((minute, minute + int(round(float(hours) * 60)), qty))
            else:
                windows.append((minute, None, qty))
                estimated = True
    return windows, estimated


def plan_for_day(day, setup_before=BEVERAGE_SETUP_BEFORE_FIRST_CALL,
                 interval=BEVERAGE_REFRESH_INTERVAL):
    """The day's beverage touchpoints, or the reason there are none.

    Returns ``{"points": [...], "reason": str|None, "estimated": bool,
    "first_crew_call": str, "eod": str}``. Each point is
    ``{"minute", "time", "kind", "headcount"}``.

    A day with no EOD gets no refreshes and a reason, never a guessed end —
    inventing one would put F&B on site for a shift nobody scheduled.
    """
    empty = {"points": [], "estimated": False,
             "first_crew_call": "", "eod": ""}
    starts = crew_starts_for_day(day)
    if not starts:
        return dict(empty, reason=NO_CREW_START)
    first = starts[0][0]
    eod = parse_minutes(getattr(day, "eod", None))
    if eod is None:
        return dict(empty, reason=NO_EOD,
                    first_crew_call=from_minutes(first))

    minutes = beverage_touchpoints(first, eod, setup_before, interval)
    if not minutes:
        return dict(empty, reason=SETUP_AFTER_EOD,
                    first_crew_call=from_minutes(first), eod=from_minutes(eod))

    windows, estimated = crew_windows_for_day(day)
    points = []
    for i, m in enumerate(minutes):
        if i == 0:
            # Setup headcount is the crew arriving before the first top-up —
            # measured against setup + interval whether or not that refresh
            # survives the EOD cap, so a short day still reports the crew it
            # is setting up for rather than the nobody who is on site 30
            # minutes before the first call.
            head = called_before(windows, m + int(interval or 0))
            kind = SETUP
        else:
            head = on_site_at(windows, m)
            kind = REFRESH
        points.append({"minute": m, "time": from_minutes(m),
                       "kind": kind, "headcount": head})
    return {"points": points, "reason": None, "estimated": estimated,
            "first_crew_call": from_minutes(first), "eod": from_minutes(eod)}


def plan_for_service(svc, **kwargs):
    """The plan for a standing service's day. ``None`` when it has no day."""
    day = getattr(svc, "schedule_day", None)
    if day is None:
        return None
    return plan_for_day(day, **kwargs)
