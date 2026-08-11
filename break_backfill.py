"""Backfill CrewBreak rows from existing break activities.

Additive and idempotent. Creates a CrewBreak describing each break activity;
never edits or deletes the activity itself, so every existing link (crew rows,
OSS entries, meal services) is untouched.

The catering decision is the whole point, so it is made conservatively:

    a MealService already links to the activity  ->  catered = yes
    anything else                                ->  catered = UNCONFIRMED

Never "no". Nothing about a break's NAME is evidence of whether food was
ordered — that inference is the bug this overhaul exists to remove, and
applying it here would bake today's wrong answers into tomorrow's data.
"""
import re

from extensions import db
from models import (CATERED_UNCONFIRMED, CATERED_YES, CrewBreak, MealService,
                    ScheduleActivity)
from time_utils import sort_minutes

# Anything that reads as a break in the wild, including the builder's output.
BREAK_KEYWORDS = ("BREAK", "LUNCH", "DINNER", "BREAKFAST", "MEAL")

# "LUNCH BREAK — 7:00 AM CREW" — the builder stamps the crew start into the
# label, which is better evidence of the anchor than proximity guessing.
_CREW_SUFFIX = re.compile(r"[—-]\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM)?)\s*CREW\s*$",
                          re.IGNORECASE)


def looks_like_break(activity):
    desc = (activity.description or "").upper()
    if "CREW START" in desc:
        return False
    return any(k in desc for k in BREAK_KEYWORDS)


def crew_starts_for_day(day):
    """``[(minutes, activity), ...]`` for every timed CREW START on the day."""
    out = []
    for a in day.activities:
        if "CREW START" in (a.description or "").upper():
            m = sort_minutes(a.time)
            if m is not None:
                out.append((m, a))
    return sorted(out, key=lambda p: p[0])


def infer_crew_call(day, activity):
    """Which crew start this break hangs off, and by how many minutes.

    Prefers the crew time stamped into the label by the break builder; falls
    back to the latest crew start at or before the break. Returns
    ``(crew_call, offset_minutes)`` — either may be None when the day has no
    timed crew start, which is left for a human rather than guessed.
    """
    starts = crew_starts_for_day(day)
    if not starts:
        return (None, None)
    break_m = sort_minutes(activity.time)

    match = _CREW_SUFFIX.search(activity.description or "")
    if match:
        labelled = sort_minutes(match.group(1))
        if labelled is not None:
            for m, act in starts:
                if m == labelled:
                    return (act, None if break_m is None else break_m - m)

    if break_m is None:
        return (None, None)
    candidate = None
    for m, act in starts:
        if m <= break_m:
            candidate = (m, act)
    if candidate is None:
        return (None, None)
    return (candidate[1], break_m - candidate[0])


def plan(show):
    """What a backfill WOULD do. Reads only — nothing is written.

    Returns ``{"rows": [...], "counts": {...}}``. Every row carries the day,
    the activity, the inferred anchor and the catering verdict, so the whole
    thing can be read before anyone commits to it.
    """
    existing = {cb.activity_id for cb in
                CrewBreak.query.filter_by(show_id=show.id).all()}
    linked = {ms.activity_id: ms for ms in
              MealService.query.filter_by(show_id=show.id).all()
              if ms.activity_id}

    rows = []
    counts = {"total": 0, "catered": 0, "unconfirmed": 0,
              "already_done": 0, "no_anchor": 0}

    for day in show.days:
        for act in day.activities:
            if not looks_like_break(act):
                continue
            counts["total"] += 1
            if act.id in existing:
                counts["already_done"] += 1
                continue
            crew_call, offset = infer_crew_call(day, act)
            ms = linked.get(act.id)
            catered = CATERED_YES if ms else CATERED_UNCONFIRMED
            if crew_call is None:
                counts["no_anchor"] += 1
            counts["catered" if ms else "unconfirmed"] += 1
            rows.append({
                "day": day, "activity": act, "crew_call": crew_call,
                "offset": offset, "catered": catered, "meal_service": ms,
            })
    return {"rows": rows, "counts": counts}


def apply(show):
    """Write the plan. Idempotent — re-running adds nothing.

    Duration is NOT inferred from anything: existing break activities carry a
    start time and no end, so any duration would be invented. Everything gets
    the house default and Larry adjusts what is wrong, which is honest about
    what the old data actually knew.
    """
    from breaks import DEFAULT_SERVICE_MINUTES

    result = plan(show)
    made = 0
    for row in result["rows"]:
        db.session.add(CrewBreak(
            show_id=show.id,
            activity_id=row["activity"].id,
            crew_call_id=row["crew_call"].id if row["crew_call"] else None,
            offset_minutes=row["offset"],
            duration_minutes=DEFAULT_SERVICE_MINUTES,
            label=(row["activity"].description or "")[:120],
            catered=row["catered"],
            meal_service_id=row["meal_service"].id if row["meal_service"] else None,
        ))
        made += 1
    db.session.commit()
    result["counts"]["created"] = made
    return result["counts"]
