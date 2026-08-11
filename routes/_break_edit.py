"""Editing a crew break: time, duration, provided, meal-service link."""
from flask import Blueprint, flash, redirect, request, url_for

from extensions import db
from models import (CATERED_STATES, CATERED_YES, CrewBreak, MealService,
                    ScheduleActivity, ScheduleDay, Show)
# parse_minutes, NOT sort_minutes: sort_minutes returns a 1,000,000
# sentinel for an unreadable time so an `is None` guard never fires,
# which would place a break at a nonsense hour off an untimed crew call.
from time_utils import hhmm_or_blank, parse_minutes

break_edit_bp = Blueprint("break_edit", __name__)

# Jason's set. A break is one of these; anything else is a meal service with
# its own window, not a break length.
DURATION_CHOICES = (15, 30, 60)


def _back(show_id, day_id):
    return redirect(url_for("schedule.day_detail", show_id=show_id,
                            day_id=day_id))


@break_edit_bp.route("/<int:show_id>/schedule/<int:day_id>/breaks/"
                     "<int:break_id>/edit", methods=["POST"])
def edit_break(show_id, day_id, break_id):
    """Update one break. Time lives on the activity — that is still the event."""
    cb = CrewBreak.query.get_or_404(break_id)
    f = request.form

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
        cb.meal_service_id = int(raw) if raw else None
        # Linking a service is a statement that something IS provided; leaving
        # it unconfirmed alongside a real link would be contradictory.
        if cb.meal_service_id and cb.catered != CATERED_YES:
            cb.catered = CATERED_YES

    if "label" in f:
        cb.label = (f.get("label") or "").strip() or None

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
        time="%02d:%02d" % (at // 60 % 24, at % 60),
        description=f"{label} — {call.time} CREW",
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
