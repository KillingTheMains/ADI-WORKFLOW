"""What is still unanswered about a show's breaks and its F&B services.

Step 6 of the breaks overhaul (ADI_Breaks_And_Meals_Design.md §9.6), and the
last of it. The backfill deliberately wrote `unconfirmed` rather than guessing
— which was right — and left 65 breaks across two shows with nowhere to be
resolved. This is that somewhere.

This module only FINDS. `break_linking` links and unlinks, `_break_edit` sets a
status and creates the service; here we point at the rows that need them and
count what is left. Nothing infers a catering decision, for the same reason
nothing else in this overhaul does: a wrong guess reaches a caterer as the
wrong headcount, which is the failure the whole thing exists to remove.

Three questions, and only three:

* **Not decided.** ``catered == unconfirmed``. Nobody has said yet, and it must
  never be read as "no".
* **Nothing feeding it.** A break that says Provided while carrying no service
  — a contradiction at any length, since saying Provided is what creates the
  service — or a meal-length break with none.
* **Feeding nobody.** A service with no break, which is what "Not Provided"
  leaves behind: it unlinks rather than deletes, deliberately, because
  deleting F&B's work off a dropdown change is not recoverable.

**A break marked Not Provided at coffee length is an ANSWER, not a gap, and is
deliberately absent.** Listing answers as problems is exactly what made
`is_meal_break`'s keyword warning unusable, and this panel replaces it. The
same reasoning is why a service confirmed standalone drops out: a client lunch
feeds no crew break and never will, and a panel that cannot reach zero is just
the next warning nobody reads.
"""
from breaks import DEFAULT_SERVICE_MINUTES, is_beverage_service
from models import (CATERED_UNCONFIRMED, CATERED_YES, CrewBreak, MealService,
                    ScheduleActivity)

# A break long enough to be a meal. The house lunch is 60 minutes and the two
# coffees are 15 (breaks.DEFAULT_DURATION_FOR_OFFSET), so this is the app's own
# figure rather than a second opinion invented here.
MEAL_LENGTH_MINUTES = DEFAULT_SERVICE_MINUTES


def is_undecided(cb):
    """Nobody has said whether F&B provides this break."""
    return cb.catered == CATERED_UNCONFIRMED


def is_unfed(cb):
    """A break with nothing feeding it that somebody should look at.

    Provided-with-no-service is a contradiction at ANY length: marking a break
    provided is what creates its service, so a break in this state had one
    deleted off the F&B tab afterwards. Meal length with no service is the
    softer case — it may be a crew walking away to eat on their own, which is
    legitimate, but at an hour long it is worth a glance.

    Undecided breaks are excluded: they are already the first question, and
    counting one break twice makes the totals lie.
    """
    if cb.meal_service_id is not None or is_undecided(cb):
        return False
    if cb.catered == CATERED_YES:
        return True
    return (cb.duration_minutes or 0) >= MEAL_LENGTH_MINUTES


def is_contradiction(cb):
    """Says Provided, has nothing providing it. Worth shouting about."""
    return cb.catered == CATERED_YES and cb.meal_service_id is None


def is_orphan(svc):
    """A service feeding nobody that anybody would want chased.

    A standing beverage service is never in here — it feeds nobody AT a break
    by definition, and `is_beverage_service` is the ONE predicate for that.
    Neither is a service somebody has confirmed standalone.
    """
    if is_beverage_service(svc):
        return False
    if getattr(svc, "standalone_confirmed", False):
        return False
    return getattr(svc, "crew_break", None) is None


def _break_sort_key(cb):
    # parse-backed minutes, never sort_minutes: the 1,000,000 sentinel would
    # sort an untimed break to the bottom silently instead of admitting it has
    # no time. Here the sentinel is applied explicitly and only for ordering.
    m = cb.start_minute
    return (m if m is not None else 10 ** 6, cb.id or 0)


def _service_sort_key(svc):
    from time_utils import sort_minutes
    return (sort_minutes(svc.earliest_time), svc.sort_order or 0, svc.id or 0)


def _day_of_service(svc, day_ids):
    """The day a service belongs to, or None.

    Same fallback the F&B tab uses: the stored day, or the day of the activity
    it is linked to. A service whose day cannot be derived is surfaced rather
    than dropped — see `survey`'s `unplaced`.
    """
    did = svc.schedule_day_id
    if did not in day_ids and svc.linked_activity is not None:
        did = svc.linked_activity.day_id
    return did if did in day_ids else None


def survey(show):
    """Everything outstanding on one show, grouped by day.

    Show-level and grouped by day rather than one or the other: Larry can work
    a show top to bottom or jump to a single day, and which of those he
    actually does is still an open question for him. Answering it later costs
    nothing from here.

    Returns ``{"days": [...], "counts": {...}, "unplaced": {...},
    "clear": bool}``. Only days with something outstanding appear in ``days``.
    """
    day_ids = {d.id for d in show.days}
    by_day = {d.id: {"day": d, "undecided": [], "unfed": [], "orphans": []}
              for d in show.days}
    unplaced = {"breaks": [], "services": []}

    breaks = (CrewBreak.query
              .join(ScheduleActivity, CrewBreak.activity_id == ScheduleActivity.id)
              .filter(CrewBreak.show_id == show.id).all())
    for cb in breaks:
        bucket = None
        if is_undecided(cb):
            bucket = "undecided"
        elif is_unfed(cb):
            bucket = "unfed"
        if bucket is None:
            continue
        did = cb.activity.day_id if cb.activity is not None else None
        if did in by_day:
            by_day[did][bucket].append(cb)
        else:
            unplaced["breaks"].append(cb)

    for svc in MealService.query.filter_by(show_id=show.id).all():
        if not is_orphan(svc):
            continue
        did = _day_of_service(svc, day_ids)
        if did in by_day:
            by_day[did]["orphans"].append(svc)
        else:
            unplaced["services"].append(svc)

    days = []
    for d in show.days:
        entry = by_day[d.id]
        entry["undecided"].sort(key=_break_sort_key)
        # Contradictions first — "says Provided with nothing providing it" is a
        # defect, where an hour-long break the crew sorts out themselves is
        # merely worth a glance.
        entry["unfed"].sort(key=lambda cb: (not is_contradiction(cb),
                                            _break_sort_key(cb)))
        entry["orphans"].sort(key=_service_sort_key)
        entry["total"] = (len(entry["undecided"]) + len(entry["unfed"])
                          + len(entry["orphans"]))
        if entry["total"]:
            days.append(entry)

    counts = {
        "undecided": sum(len(e["undecided"]) for e in days) + len(
            [cb for cb in unplaced["breaks"] if is_undecided(cb)]),
        "unfed": sum(len(e["unfed"]) for e in days) + len(
            [cb for cb in unplaced["breaks"] if not is_undecided(cb)]),
        "orphans": (sum(len(e["orphans"]) for e in days)
                    + len(unplaced["services"])),
        "days": len(days),
    }
    counts["total"] = counts["undecided"] + counts["unfed"] + counts["orphans"]
    return {"days": days, "counts": counts, "unplaced": unplaced,
            "clear": counts["total"] == 0}
