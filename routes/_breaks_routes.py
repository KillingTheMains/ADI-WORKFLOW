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
        f"{counts['provided']} provided, {counts['not_provided']} not "
        f"provided, {counts['unconfirmed']} unconfirmed. "
        "Nothing was deleted or edited; the activities are untouched.",
        "success")
    return redirect(url_for("breaks.backfill_preview", show_id=show.id))


@breaks_bp.route("/<int:show_id>/breaks/reset", methods=["POST"])
def backfill_reset(show_id):
    """Delete this show's break records so the backfill can be re-run.

    Idempotent is not the same as repeatable: `apply` skips activities that
    already have a record, which protects against double-running but also
    means a verdict decided by an OLD rule can never be corrected by re-
    running. The classification has already changed once after meeting real
    data, so a clean re-run has to be possible.

    Safe in a way that deleting activities would not be: a CrewBreak is
    additive metadata that nothing else points at. The break activities, their
    crew rows, their OSS entries and their meal services are untouched.
    """
    show = Show.query.get_or_404(show_id)
    n = CrewBreak.query.filter_by(show_id=show.id).delete()
    db.session.commit()
    flash(
        f"Cleared {n} break record{'' if n == 1 else 's'} for {show.name}. "
        "The break activities themselves are untouched — re-run the backfill "
        "when you are ready.", "success")
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
