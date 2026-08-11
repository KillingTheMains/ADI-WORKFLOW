"""Editing a crew break: time, duration, provided, meal-service link."""
from flask import Blueprint, flash, redirect, request, url_for

from breaks import break_export_text, guess_meal_kind
from extensions import db
from models import (CATERED_STATES, CATERED_UNCONFIRMED, CATERED_YES,
                    CrewBreak, MealService, MealServiceLocation,
                    ScheduleActivity, ScheduleDay, Show)
# parse_minutes, NOT sort_minutes: sort_minutes returns a 1,000,000
# sentinel for an unreadable time so an `is None` guard never fires,
# which would place a break at a nonsense hour off an untimed crew call.
from time_utils import from_minutes, hhmm_or_blank, parse_minutes

break_edit_bp = Blueprint("break_edit", __name__)

# Jason's set. A break is one of these; anything else is a meal service with
# its own window, not a break length.
DURATION_CHOICES = (15, 30, 60)


def _ensure_meal_service(cb):
    """Marking a break 'provided' creates the service F&B will work to.

    Without this, saying a meal is provided changes a dropdown and nothing
    else — F&B never hears about it. One service per break, per the 1:1 rule.

    The location is created with **no headcount typed in**, so it follows the
    crew call and keeps following it. That is the whole point of the derived
    figure: a number frozen at the moment the break was created is a number
    that is wrong by the time it matters.
    """
    if cb.meal_service_id or cb.activity is None:
        return None
    label = (cb.label or "MEAL").strip() or "MEAL"
    day_id = cb.activity.day_id
    svc = MealService(
        show_id=cb.show_id,
        schedule_day_id=day_id,
        activity_id=cb.activity_id,
        name=label.title(),
        kind=guess_meal_kind(label),
        is_recurring=False,
        sort_order=MealService.query.filter_by(schedule_day_id=day_id).count() * 10,
    )
    db.session.add(svc)
    db.session.flush()

    # The location carries the BREAK window — when the crew actually stops.
    # F&B's own window (setup, holdover) is derived from it, so the two can
    # never drift apart the way two stored copies of a time would.
    start = parse_minutes(cb.activity.time)
    db.session.add(MealServiceLocation(
        meal_service_id=svc.id,
        start_time=hhmm_or_blank(cb.activity.time) or None,
        end_time=(from_minutes(start + (cb.duration_minutes or 60))
                  if start is not None else None),
        headcount=None,          # follow the crew
        sort_order=0,
    ))
    cb.meal_service_id = svc.id
    return svc


def _back(show_id, day_id):
    return redirect(url_for("schedule.day_detail", show_id=show_id,
                            day_id=day_id))


@break_edit_bp.route("/<int:show_id>/schedule/<int:day_id>/breaks/"
                     "<int:break_id>/edit", methods=["POST"])
def edit_break(show_id, day_id, break_id):
    """Update one break. Time lives on the activity — that is still the event."""
    cb = CrewBreak.query.get_or_404(break_id)
    f = request.form
    # Captured BEFORE the form is applied. A break that already had a service
    # and comes back without one has been deliberately unlinked, and must not
    # be handed a replacement; a break that never had one and is now marked
    # provided needs one creating. The form alone cannot tell those apart —
    # the select posts blank in both cases.
    had_service = cb.meal_service_id is not None

    if "time" in f:
        # 24-hour canonical, same rule as every other time in the app.
        cleaned = hhmm_or_blank(f.get("time"))
        if cleaned:
            cb.activity.time = cleaned
            # Keep the offset honest rather than letting it go stale.
            if cb.crew_call is not None:
                start = parse_minutes(cb.crew_call.time)
                now = parse_minutes(cleaned)
                if start is not None and now is not None:
                    cb.offset_minutes = now - start

    if "duration_minutes" in f:
        try:
            mins = int(f.get("duration_minutes") or 0)
            if mins in DURATION_CHOICES:
                cb.duration_minutes = mins
        except (TypeError, ValueError):
            pass

    if "catered" in f:
        value = (f.get("catered") or "").strip()
        if value in CATERED_STATES:
            cb.catered = value

    if "meal_service_id" in f:
        raw = (f.get("meal_service_id") or "").strip()
        wanted = int(raw) if raw else None
        # One service per crew group, always. Two breaks sharing a service is
        # not a tidier version of the same thing: an 08:00 crew and an 09:00
        # crew fed from one service means food out for three hours. It would
        # also give the service two crew calls to derive a headcount from, and
        # SQLAlchemy would silently pick one of them.
        taken_by = (CrewBreak.query
                    .filter(CrewBreak.meal_service_id == wanted,
                            CrewBreak.id != cb.id).first()
                    if wanted else None)
        if taken_by is not None:
            flash("That meal service already feeds another break. One service "
                  "per crew group — add a second service for this one.",
                  "danger")
        else:
            cb.meal_service_id = wanted

    # Reconcile the two controls, which the same submit can contradict.
    #
    # A link plus "unconfirmed" is not a contradiction, it is an omission:
    # picking a service IS the statement that something is provided, so the
    # link wins. A link plus an explicit "Not provided" is a real
    # contradiction, and there the person who just said "no" wins — otherwise
    # a stale dropdown silently flips the answer back and the break can never
    # be marked uncatered at all.
    if cb.meal_service_id and cb.catered == CATERED_UNCONFIRMED:
        cb.catered = CATERED_YES

    if "label" in f:
        cb.label = (f.get("label") or "").strip() or None

    # Do this AFTER the label, so a service created here is named with what
    # the user just typed rather than what was there before.
    if cb.catered == CATERED_YES:
        svc = _ensure_meal_service(cb) if not had_service else None
        if svc is not None:
            flash(f"Added '{svc.name}' to F&B, feeding "
                  f"{cb.derived_headcount if cb.derived_headcount is not None else '?'} "
                  f"crew from the {cb.crew_call.time if cb.crew_call else ''} call.",
                  "success")
    elif cb.meal_service_id:
        # Not provided, but a service is attached. Unlink rather than delete —
        # deleting F&B's work off a dropdown change is not recoverable, and the
        # coverage panel is where a service with no break belongs.
        orphan = cb.meal_service
        cb.meal_service_id = None
        flash(f"Marked not provided. '{orphan.name if orphan else 'The service'}' "
              f"is still on the F&B tab — remove it there if it is not happening.",
              "warning")

    db.session.commit()
    return _back(show_id, day_id)


@break_edit_bp.route("/<int:show_id>/schedule/<int:day_id>/crew-call/"
                     "<int:act_id>/breaks/add", methods=["POST"])
def add_break(show_id, day_id, act_id):
    """Add a break hanging off a crew call.

    Breaks are added HERE rather than by a day-level bulk build (Jason,
    2026-08-11) because the offset only means anything relative to a specific
    crew start. The break still becomes a real ScheduleActivity — that is what
    the schedule, the call sheet and the exports render — with a CrewBreak
    describing it.
    """
    show = Show.query.get_or_404(show_id)
    day = ScheduleDay.query.get_or_404(day_id)
    call = ScheduleActivity.query.get_or_404(act_id)
    f = request.form

    try:
        offset = int(f.get("offset_minutes") or 0)
    except (TypeError, ValueError):
        offset = 0
    try:
        duration = int(f.get("duration_minutes") or 30)
    except (TypeError, ValueError):
        duration = 30
    if duration not in DURATION_CHOICES:
        duration = 30

    label = (f.get("label") or "BREAK").strip() or "BREAK"

    start = parse_minutes(call.time)
    if start is None:
        flash("That crew call has no time set, so a break cannot be placed "
              "against it.", "warning")
        return _back(show_id, day_id)

    at = start + offset
    act = ScheduleActivity(
        day_id=day.id,
        time=from_minutes(at),
        description=break_export_text(label, duration, call.time),
        sort_order=(call.sort_order or 0) + 1,
    )
    db.session.add(act)
    db.session.flush()

    db.session.add(CrewBreak(
        show_id=show.id, activity_id=act.id, crew_call_id=call.id,
        offset_minutes=offset, duration_minutes=duration, label=label,
    ))
    db.session.commit()
    flash(f"Added {label} at {act.time}. Set whether it is provided.",
          "success")
    return _back(show_id, day_id)


@break_edit_bp.route("/<int:show_id>/schedule/<int:day_id>/breaks/"
                     "<int:break_id>/delete", methods=["POST"])
def delete_break(show_id, day_id, break_id):
    """Remove a break and the activity it describes.

    Unlike the backfill's reset, this DOES delete the activity — the user is
    removing a break from the schedule, not undoing a migration.
    """
    cb = CrewBreak.query.get_or_404(break_id)
    act = cb.activity
    db.session.delete(cb)
    if act is not None:
        db.session.delete(act)
    db.session.commit()
    return _back(show_id, day_id)
