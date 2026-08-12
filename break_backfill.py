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

from breaks import (crew_starts_for_day, duration_from_label,
                    is_beverage_service, is_crew_start)
from extensions import db
from models import (CATERED_NO, CATERED_UNCONFIRMED, CATERED_YES, CrewBreak,
                    MealService)
# parse_minutes returns None for an unreadable time; sort_minutes returns
# a 1,000,000 sentinel, so `is None` checks against it never fire.
from time_utils import parse_minutes

# Anything that reads as a break in the wild, including the builder's output.
BREAK_KEYWORDS = ("BREAK", "LUNCH", "DINNER", "BREAKFAST", "MEAL")

# "LUNCH BREAK — 7:00 AM CREW" — the builder stamps the crew start into the
# label, which is better evidence of the anchor than proximity guessing.
_CREW_SUFFIX = re.compile(r"[—-]\s*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM)?)\s*CREW\s*$",
                          re.IGNORECASE)


# "RETURN FROM LUNCH" is not a break — it is the break ENDING, which is how
# the old schedules recorded a duration before breaks had one. It becomes the
# break's duration rather than a break of its own.
_RETURN = re.compile(r"^\s*RETURN\s+FROM\s+(.*)$", re.IGNORECASE)


def is_return_marker(activity):
    return bool(_RETURN.match(activity.description or ""))


def looks_like_break(activity):
    desc = (activity.description or "").upper()
    if is_crew_start(desc):
        return False
    if is_return_marker(activity):
        return False
    return any(k in desc for k in BREAK_KEYWORDS)


def _base_label(desc):
    """'LUNCH BREAK — 7:00 AM CREW' -> 'LUNCH'. Used to pair a break with its
    RETURN FROM marker."""
    text = re.sub(r"[—-]\s*[0-9].*$", "", desc or "")
    text = re.sub(r"\bBREAK\b", "", text, flags=re.IGNORECASE)
    return " ".join(text.split()).upper()


def recover_duration(day, activity):
    """Minutes, from the day's own evidence. None when there is none, and the
    caller falls back to the house default rather than inventing a number.

    TWO sources, in order of how much they know:

    1. A matching `RETURN FROM` marker later the same day — an actual
       scheduled return time, so it beats anything merely stated.
    2. The length written into the break's own NAME: "MORNING BREAK — 15 min".

    (2) was missing until 2026-08-12 and it cost 91 wrong durations across
    three live shows. MCDC26, AWS and Grace Hopper have no RETURN FROM rows at
    all, so every break took the 60-minute house default — a fifteen-minute
    coffee printing as an hour on the day page, the call sheet and the client
    master, while its own label said fifteen. `_base_label` was even STRIPPING
    that text, to pair breaks with return markers, and nothing ever read it.
    """
    start = parse_minutes(activity.time)
    if start is None:
        return None
    from_label, _cleaned = duration_from_label(activity.description)
    want = _base_label(activity.description)
    if not want:
        return from_label
    best = None
    for other in day.activities:
        m = _RETURN.match(other.description or "")
        if not m:
            continue
        if _base_label(m.group(1)) != want and want not in (m.group(1) or "").upper():
            continue
        end = parse_minutes(other.time)
        if end is None or end <= start:
            continue
        if best is None or end < best:
            best = end
    return from_label if best is None else best - start


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
    break_m = parse_minutes(activity.time)

    match = _CREW_SUFFIX.search(activity.description or "")
    if match:
        labelled = parse_minutes(match.group(1))
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


MEAL_KINDS_REAL = ("breakfast", "lunch", "dinner", "snack")
_BEVERAGE_WORDS = ("BEVERAGE", "REFRESH", "COFFEE", "WATER", "CREW BREAK")


def classify(meal_service):
    """``(catered, reason)`` for a break, given whatever service it links to.

    A link to a MealService is NOT proof that food is provided at that break.
    Rehearsing against MCDC26 showed 30 of 41 breaks linked to services named
    "Crew Break - Refresh as Needed" or "Beverage Break" — Larry using meal
    services to represent a standing beverage setup, because the old model gave
    him nowhere else to put one. Reading those as catered meals would be the
    same class of error as guessing from the description, just pointing the
    other way.

    So: a meal-kind service is evidence of a provided meal. A beverage or
    recurring service is evidence of the OPPOSITE — the break itself is a plain
    crew break, and that service belongs in the standing-service model. No
    service at all is no evidence, and stays unconfirmed.
    """
    if meal_service is None:
        return (CATERED_UNCONFIRMED, "no meal service linked")
    name = (meal_service.name or "").upper()
    kind = (meal_service.kind or "").lower()
    if is_beverage_service(meal_service):
        return (CATERED_NO,
                f"linked to a standing/beverage service ({meal_service.name})")
    if kind in MEAL_KINDS_REAL:
        return (CATERED_YES, f"{kind} service ({meal_service.name})")
    # The name is evidence in BOTH directions, or in neither. MCDC26's real
    # meal services are named "LUNCH BREAK — 08:00 CREW" and carry no useful
    # kind, so refusing to read the name here would classify every genuine
    # meal on the show as unconfirmed.
    if any(w in name for w in ("LUNCH", "DINNER", "BREAKFAST", "MEAL")):
        return (CATERED_YES, f"meal service by name ({meal_service.name})")
    return (CATERED_UNCONFIRMED,
            f"service of unclear kind ({meal_service.name})")


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

    from breaks import DEFAULT_SERVICE_MINUTES

    rows = []
    counts = {"total": 0, "provided": 0, "not_provided": 0, "unconfirmed": 0,
              "already_done": 0, "no_anchor": 0, "duration_recovered": 0,
              "return_markers": 0}

    for day in show.days:
        for act in day.activities:
            if is_return_marker(act):
                counts["return_markers"] += 1
                continue
            if not looks_like_break(act):
                continue
            counts["total"] += 1
            if act.id in existing:
                counts["already_done"] += 1
                continue
            crew_call, offset = infer_crew_call(day, act)
            ms = linked.get(act.id)
            catered, reason = classify(ms)
            duration = recover_duration(day, act)
            if duration is not None:
                counts["duration_recovered"] += 1
            if crew_call is None:
                counts["no_anchor"] += 1
            counts[{CATERED_YES: "provided", CATERED_NO: "not_provided",
                    CATERED_UNCONFIRMED: "unconfirmed"}[catered]] += 1
            rows.append({
                "day": day, "activity": act, "crew_call": crew_call,
                "offset": offset, "catered": catered, "meal_service": ms,
                "reason": reason,
                "duration": duration if duration is not None
                            else DEFAULT_SERVICE_MINUTES,
                "duration_known": duration is not None,
            })
    return {"rows": rows, "counts": counts}


def apply(show):
    """Write the plan. Idempotent — re-running adds nothing.

    Duration comes from a matching RETURN FROM marker where one exists — the
    old schedules recorded a break's end as a separate row, so that duration is
    real data rather than a guess. Everything else takes the house default.
    """
    result = plan(show)
    made = 0
    for row in result["rows"]:
        db.session.add(CrewBreak(
            show_id=show.id,
            activity_id=row["activity"].id,
            crew_call_id=row["crew_call"].id if row["crew_call"] else None,
            offset_minutes=row["offset"],
            duration_minutes=row["duration"],
            label=(row["activity"].description or "")[:120],
            catered=row["catered"],
            # ONLY when the verdict is that food is provided. A beverage
            # service is evidence the break is NOT catered, so writing it in
            # here pointed every such break at one service and broke the 1:1
            # the model relies on.
            meal_service_id=(row["meal_service"].id
                             if row["meal_service"] and row["catered"] == CATERED_YES
                             else None),
        ))
        made += 1
    db.session.commit()
    result["counts"]["created"] = made
    return result["counts"]
