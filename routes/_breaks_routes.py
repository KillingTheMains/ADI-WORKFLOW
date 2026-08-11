"""Break backfill: preview, apply, and the per-show rollout switch."""
from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

import break_backfill
from extensions import db
from models import CrewBreak, Show

breaks_bp = Blueprint("breaks", __name__)


@breaks_bp.route("/<int:show_id>/breaks/backfill")
def backfill_preview(show_id):
    """Read-only. Shows exactly what a backfill would create."""
    show = Show.query.get_or_404(show_id)
    result = break_backfill.plan(show)
    return render_template("shows/break_backfill.html", show=show,
                           rows=result["rows"], counts=result["counts"])


@breaks_bp.route("/<int:show_id>/breaks/backfill", methods=["POST"])
def backfill_apply(show_id):
    show = Show.query.get_or_404(show_id)
    counts = break_backfill.apply(show)
    flash(
        f"Created {counts['created']} crew break record"
        f"{'' if counts['created'] == 1 else 's'} — "
        f"{counts['catered']} catered, {counts['unconfirmed']} unconfirmed. "
        "Nothing was deleted or edited; the activities are untouched.",
        "success")
    return redirect(url_for("breaks.backfill_preview", show_id=show.id))


@breaks_bp.route("/<int:show_id>/breaks/toggle", methods=["POST"])
def toggle_new_breaks(show_id):
    """Roll the overhaul on or off for one show, without touching data."""
    show = Show.query.get_or_404(show_id)
    show.uses_new_breaks = not bool(show.uses_new_breaks)
    db.session.commit()
    flash(
        f"New breaks model {'ON' if show.uses_new_breaks else 'OFF'} for "
        f"{show.name}. " + ("Break records stay in place either way — turning "
                            "it off only changes what is read."),
        "success")
    return redirect(url_for("breaks.backfill_preview", show_id=show.id))
