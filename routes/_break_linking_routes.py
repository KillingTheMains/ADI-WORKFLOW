"""Linking a break to its F&B service, from either side.

Two doors, one transaction — see break_linking. The F&B tab links a service to
a break; the day page links a break to a service; both land here.
"""
from flask import Blueprint, flash, redirect, request, url_for

import break_linking
from extensions import db
from models import CrewBreak, MealService, Show

break_link_bp = Blueprint("break_link", __name__)


def _back_to_fb(show_id):
    """Back where the question was asked.

    The Feeds question is now asked in two places — the F&B tab and the
    coverage panel — and answering it on the panel used to dump you on the
    other page mid-list. A `next` of "coverage" comes back to the panel;
    anything else, including nothing, keeps the old behaviour.
    """
    if (request.form.get("next") or "").strip() == "coverage":
        return redirect(url_for("break_coverage.coverage", show_id=show_id))
    return redirect(url_for("oss.oss_hub", show_id=show_id, tab="F&B"))


def _offer_crew_figure(svc):
    """Linking brings a live headcount with it. Say so when hand-typed figures
    are now sitting on top of it — never overwrite them."""
    typed = break_linking.typed_headcounts(svc)
    if typed and svc.derived_headcount is not None:
        flash(f"'{svc.name}' still has {len(typed)} hand-typed headcount"
              f"{'' if len(typed) == 1 else 's'}. The crew call says "
              f"{svc.derived_headcount} — clear a Count box to follow it.",
              "warning")


@break_link_bp.route("/<int:show_id>/oss/fb/service/<int:svc_id>/feeds",
                     methods=["POST"])
def service_feeds(show_id, svc_id):
    """From the F&B tab: which break does this service feed?

    A blank break_id is 'standalone' — a client lunch or a green room feeds no
    crew break, and that is a legitimate answer rather than a missing one.
    """
    Show.query.get_or_404(show_id)
    svc = MealService.query.get_or_404(svc_id)
    if svc.show_id != show_id:
        flash("Service doesn't belong to this show.", "danger")
        return _back_to_fb(show_id)

    raw = (request.form.get("break_id") or "").strip()
    if not raw:
        existing = getattr(svc, "crew_break", None)
        if existing is not None:
            flash(f"'{svc.name}' still feeds a break — use Unlink, which asks "
                  "what that break should say instead.", "warning")
        else:
            # Standalone is an ANSWER, so record it. It was always offered
            # here and never stored, which left it indistinguishable from a
            # question nobody had asked — and that is precisely the difference
            # the coverage panel has to be able to see.
            svc.standalone_confirmed = True
            db.session.commit()
            flash(f"'{svc.name}' feeds no crew break. Noted — it will not be "
                  "chased on the coverage panel.", "success")
        return _back_to_fb(show_id)

    cb = CrewBreak.query.get(int(raw))
    ok, message = break_linking.link(cb, svc)
    if ok:
        db.session.commit()
        flash(message, "success")
        _offer_crew_figure(svc)
    else:
        flash(message, "danger")
    return _back_to_fb(show_id)


@break_link_bp.route("/<int:show_id>/oss/fb/service/<int:svc_id>/unlink",
                     methods=["POST"])
def service_unlink(show_id, svc_id):
    """Detach, and set the break to whatever the dialog asked for."""
    Show.query.get_or_404(show_id)
    svc = MealService.query.get_or_404(svc_id)
    if svc.show_id != show_id:
        flash("Service doesn't belong to this show.", "danger")
        return _back_to_fb(show_id)
    cb = getattr(svc, "crew_break", None)
    ok, message = break_linking.unlink(
        cb, (request.form.get("then_status") or "").strip())
    if ok:
        db.session.commit()
    flash(message, "success" if ok else "danger")
    return _back_to_fb(show_id)


@break_link_bp.route("/<int:show_id>/schedule/<int:day_id>/breaks/"
                     "<int:break_id>/link", methods=["POST"])
def break_link(show_id, day_id, break_id):
    """From the day page: attach this break to a service that already exists.

    Only offered when there is something to choose, so the single catering
    control stays the whole story for anyone not in the F&B-first workflow.
    """
    cb = CrewBreak.query.get_or_404(break_id)
    raw = (request.form.get("service_id") or "").strip()
    if not raw:
        flash("Pick a service to link.", "warning")
    else:
        svc = MealService.query.get(int(raw))
        ok, message = break_linking.link(cb, svc)
        if ok:
            db.session.commit()
            flash(message, "success")
            _offer_crew_figure(svc)
        else:
            flash(message, "danger")
    return redirect(url_for("schedule.day_detail", show_id=show_id,
                            day_id=day_id))
