"""
Hard-Coded Events (#37) — global recurring events (Security, Crew Beverage Set,
etc.) defined once and timed as offsets from each day's Start/End of Day.

Phase 1 (this file): the definitions table — create / list / edit / delete.
Phase 2 (next): auto-populate these onto every day's schedule, timed per that
day's SOD/EOD, and surface department-tagged ones on their OSS tab (#35).

#35 folds in here: a hard-coded event's `department` is the auto-assign.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, HardCodedEvent, SUB_SCHEDULE_TYPES, SUB_SCHEDULE_META

hardcoded_bp = Blueprint("hardcoded_bp", __name__)

ANCHORS = ("SOD", "EOD")


def _parse_offset(s):
    """'-1:00' -> -60, '+0:30' -> 30, '' -> 0, '2' -> 120 (bare number = hours).
    Raises ValueError on garbage so the caller can flash a friendly message."""
    s = (s or "").strip().replace("\u2212", "-")   # accept a true minus sign
    if not s:
        return 0
    neg = s.startswith("-")
    s = s.lstrip("+-").strip()
    if ":" in s:
        h, _, m = s.partition(":")
        mins = int(h or 0) * 60 + int(m or 0)
    else:
        mins = int(s) * 60
    return -mins if neg else mins


def _apply_form(ev, f):
    ev.name = (f.get("name") or "").strip()
    if not ev.name:
        return False, "Name is required."

    dept = (f.get("department") or "").strip()
    ev.department = dept if dept in SUB_SCHEDULE_TYPES else None

    ev.start_anchor = f.get("start_anchor") if f.get("start_anchor") in ANCHORS else "SOD"
    try:
        ev.start_offset = _parse_offset(f.get("start_offset"))
    except (ValueError, TypeError):
        return False, "Start offset should look like -1:00 or +0:30."

    # End is optional -> a blank end anchor means a single point-in-time event.
    end_anchor = (f.get("end_anchor") or "").strip()
    if end_anchor in ANCHORS:
        ev.end_anchor = end_anchor
        try:
            ev.end_offset = _parse_offset(f.get("end_offset"))
        except (ValueError, TypeError):
            return False, "End offset should look like +1:00."
    else:
        ev.end_anchor = None
        ev.end_offset = None

    ev.active = f.get("active") != "0"
    return True, None


@hardcoded_bp.route("/hard-coded-events")
def index():
    events = (HardCodedEvent.query
              .order_by(HardCodedEvent.sort_order, HardCodedEvent.id).all())
    return render_template("hardcoded/index.html", events=events,
                           anchors=ANCHORS, oss_types=SUB_SCHEDULE_TYPES,
                           oss_meta=SUB_SCHEDULE_META)


@hardcoded_bp.route("/hard-coded-events/add", methods=["POST"])
def add():
    ev = HardCodedEvent()
    ok, err = _apply_form(ev, request.form)
    if not ok:
        flash(err, "danger")
        return redirect(url_for("hardcoded_bp.index"))
    ev.sort_order = HardCodedEvent.query.count() * 10
    db.session.add(ev)
    db.session.commit()
    flash(f'Added "{ev.name}".', "success")
    return redirect(url_for("hardcoded_bp.index"))


@hardcoded_bp.route("/hard-coded-events/<int:ev_id>/edit", methods=["POST"])
def edit(ev_id):
    ev = HardCodedEvent.query.get_or_404(ev_id)
    ok, err = _apply_form(ev, request.form)
    if not ok:
        flash(err, "danger")
        return redirect(url_for("hardcoded_bp.index"))
    db.session.commit()
    flash("Updated.", "success")
    return redirect(url_for("hardcoded_bp.index"))


@hardcoded_bp.route("/hard-coded-events/<int:ev_id>/delete", methods=["POST"])
def delete(ev_id):
    ev = HardCodedEvent.query.get_or_404(ev_id)
    db.session.delete(ev)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(url_for("hardcoded_bp.index"))
