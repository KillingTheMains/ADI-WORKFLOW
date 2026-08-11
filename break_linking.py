"""Linking a crew break to the F&B service that feeds it, from either side.

See ADI_Break_Service_Linking_Plan.md. Two doors — the F&B tab asks "who am I
feeding?", the day page asks "who feeds this?" — and ONE transaction behind
both, so the two surfaces cannot drift on what linking means.

Every refusal is a real rule, not a validation nicety:

* **One service, one break.** An 08:00 and an 09:00 crew fed from one service
  means food out for three hours, which breaks the 2-hour rule. It would also
  give the service two crew calls to derive a headcount from, and SQLAlchemy
  would pick one of them silently.
* **A standing beverage service is not a break meal.** It feeds nobody *at* a
  break; it runs all day with its own refresh touchpoints.
* **Same day.** Deliberate restriction — see the plan's note on overnight
  breaks, which this would refuse.

Nothing here infers a link. Callers rank suggestions and a human clicks. A
wrong auto-link sends a caterer the wrong headcount, which is the exact failure
this whole overhaul exists to remove.
"""
from breaks import is_beverage_service
from time_utils import parse_minutes, sort_minutes

# How close a service has to start to a break before it is worth suggesting.
SUGGEST_WINDOW_MINUTES = 60


def _day_id_of(cb):
    return cb.activity.day_id if cb.activity is not None else None


def can_link(cb, svc):
    """``(True, None)`` or ``(False, why not)``. The rules, in one place."""
    if cb is None or svc is None:
        return False, "That break or service no longer exists."
    if is_beverage_service(svc):
        return False, (f"'{svc.name}' is a standing beverage service — it runs "
                       "all day rather than feeding a crew at a break, so it "
                       "cannot be linked to one.")
    taken = getattr(svc, "crew_break", None)
    if taken is not None and taken.id != cb.id:
        return False, (f"'{svc.name}' already feeds the "
                       f"{taken.activity.time if taken.activity else ''} "
                       f"{taken.label or 'break'}. One service per crew group — "
                       "add a second service for this one.")
    if cb.meal_service_id and cb.meal_service_id != svc.id:
        return False, (f"That break is already fed by "
                       f"'{cb.meal_service.name if cb.meal_service else 'a service'}'. "
                       "Unlink it first.")
    if svc.schedule_day_id != _day_id_of(cb):
        return False, ("A service can only feed a break on its own day.")
    return True, None


def link(cb, svc):
    """Attach a break to an existing service. ``(ok, message)``.

    Sets BOTH pointers. `CrewBreak.meal_service_id` is who feeds this break;
    `MealService.activity_id` is what the service is ABOUT, and the export's
    "one event, one row" merge reads that one. The old hand-link dropdown set
    only the first, so a hand-linked pair printed as two rows on the master
    timeline — the break and the meal, the exact duplication the merge exists
    to prevent.
    """
    from models import CATERED_YES
    ok, why = can_link(cb, svc)
    if not ok:
        return False, why
    cb.meal_service_id = svc.id
    # Linking IS the statement that something is provided.
    cb.catered = CATERED_YES
    svc.activity_id = cb.activity_id
    return True, (f"'{svc.name}' now feeds the {cb.label or 'break'} at "
                  f"{cb.activity.time if cb.activity else '?'}.")


def unlink(cb, new_status):
    """Detach, and say what the break becomes. ``(ok, message)``.

    The status is asked for rather than assumed: "Provided — by what?" is no
    longer answerable once the service is gone, and quietly picking an answer
    is how a crew stops being fed without anyone deciding to stop feeding it.
    """
    from models import CATERED_STATES
    if cb is None:
        return False, "That break no longer exists."
    if new_status not in CATERED_STATES:
        return False, "Pick what the break should say before unlinking."
    svc = cb.meal_service
    cb.meal_service_id = None
    if svc is not None and svc.activity_id == cb.activity_id:
        # Otherwise the export keeps merging a service into a break it no
        # longer feeds.
        svc.activity_id = None
    cb.catered = new_status
    # Built in pieces: Python 3.9 (what runs locally) cannot nest the same
    # quote inside an f-string expression.
    name = svc.name if svc is not None else ""
    whose = f" from '{name}'" if svc is not None else ""
    tail = f" '{name}' is still on the F&B tab." if svc is not None else ""
    reads = LABELS.get(new_status, new_status)
    return True, f"Unlinked{whose}. The break now reads {reads}.{tail}"


LABELS = {"yes": "Provided", "no": "Not Provided", "unconfirmed": "TBD"}


def _rank(break_minute, break_label, svc):
    """Sort key for a suggestion: same label first, then nearest start."""
    svc_min = sort_minutes(svc.earliest_time)
    gap = abs(svc_min - break_minute) if break_minute is not None else 10 ** 6
    same_label = (svc.name or "").strip().upper() != (break_label or "").strip().upper()
    return (same_label, gap, svc.id or 0)


def is_suggested(cb, svc):
    """Close enough in time to be worth marking. NEVER pre-selected — a wrong
    auto-link sends a caterer the wrong headcount."""
    start = cb.start_minute
    svc_min = sort_minutes(svc.earliest_time)
    if start is None or svc_min >= 10 ** 6:
        return False
    return abs(svc_min - start) <= SUGGEST_WINDOW_MINUTES


def candidates_for_break(cb):
    """Services on this break's day that nothing else feeds, best guess first."""
    from models import MealService
    day_id = _day_id_of(cb)
    if day_id is None:
        return []
    out = [svc for svc in MealService.query.filter_by(schedule_day_id=day_id).all()
           if not is_beverage_service(svc)
           and getattr(svc, "crew_break", None) is None]
    return sorted(out, key=lambda s: _rank(cb.start_minute, cb.label, s))


def candidates_for_service(svc):
    """Breaks on this service's day that nothing else feeds, best guess first."""
    from models import CrewBreak, ScheduleActivity
    if is_beverage_service(svc) or svc.schedule_day_id is None:
        return []
    rows = (CrewBreak.query
            .join(ScheduleActivity, CrewBreak.activity_id == ScheduleActivity.id)
            .filter(ScheduleActivity.day_id == svc.schedule_day_id,
                    CrewBreak.meal_service_id.is_(None))
            .all())
    svc_min = sort_minutes(svc.earliest_time)

    def key(cb):
        start = cb.start_minute
        gap = abs(svc_min - start) if start is not None and svc_min < 10 ** 6 else 10 ** 6
        same = (cb.label or "").strip().upper() != (svc.name or "").strip().upper()
        return (same, gap, cb.id or 0)

    return sorted(rows, key=key)


def typed_headcounts(svc):
    """Locations carrying a hand-typed figure. Linking makes the crew figure
    available; whether to hand the number back is the user's call, never a
    silent overwrite of somebody's deliberate override."""
    return [loc for loc in (svc.locations if svc else []) if loc.is_overridden]
