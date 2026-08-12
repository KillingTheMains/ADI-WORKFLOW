"""The coverage panel — step 6, and the last step of the breaks overhaul.

`break_coverage` finds; this hands the findings to a screen and routes the
repairs back through the tools that already exist. Nothing new decides anything
about catering here: marking a break Provided goes through the SAME
`_ensure_meal_service` the day page uses, and unlinking goes through the SAME
`break_linking.unlink`. A second definition of "provided" is how the F&B tab
and the day page came to disagree once already.

The one thing this screen adds is BULK. Sixty-five breaks answered one page at
a time is why they are still unanswered.
"""
from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

import break_coverage
import break_linking
from extensions import db
from models import CATERED_NO, CATERED_YES, CrewBreak, Show
# The one definition of what marking a break Provided does.
from routes._break_edit import _ensure_meal_service

break_coverage_bp = Blueprint("break_coverage", __name__)


def _back(show_id):
    return redirect(url_for("break_coverage.coverage", show_id=show_id))


@break_coverage_bp.route("/<int:show_id>/breaks/coverage")
def coverage(show_id):
    """Everything still unanswered about this show's breaks, grouped by day."""
    show = Show.query.get_or_404(show_id)
    result = break_coverage.survey(show)
    # The same ranked, MARKED-never-preselected picker the F&B tab offers, so
    # an orphan can be answered where it is found instead of sending somebody
    # to another page and back. It posts to the F&B tab's own route: one
    # transaction, two doors, which is the rule this whole area runs on.
    link_choices = {}
    for entry in result["days"]:
        for svc in entry["orphans"]:
            choices = [{"cb": cb, "suggested": break_linking.is_suggested(cb, svc)}
                       for cb in break_linking.candidates_for_service(svc)]
            if choices:
                link_choices[svc.id] = choices
    return render_template("shows/break_coverage.html", show=show,
                           days=result["days"], counts=result["counts"],
                           unplaced=result["unplaced"], clear=result["clear"],
                           link_choices=link_choices)


@break_coverage_bp.route("/<int:show_id>/breaks/coverage/resolve",
                         methods=["POST"])
def resolve(show_id):
    """Answer the catering question for however many breaks were ticked.

    One status for the whole selection, because that is the honest shape of
    the job: "these forty are the crew feeding themselves" is a single
    decision somebody makes once. Anything needing a break-by-break answer
    still belongs on the crew call, and every row here links to it.
    """
    show = Show.query.get_or_404(show_id)
    status = (request.form.get("catered") or "").strip()
    if status not in (CATERED_YES, CATERED_NO):
        flash("Pick what these breaks should say before applying.", "warning")
        return _back(show_id)

    ids = [int(x) for x in request.form.getlist("break_ids")
           if x.strip().lstrip("-").isdigit()]
    if not ids:
        flash("Nothing was ticked, so nothing changed.", "warning")
        return _back(show_id)

    # Scoped to the show, so a stale or hand-edited form cannot reach into
    # another one. The app has no authentication; this is the only guard there
    # is, and a bulk write is the worst place to leave it off.
    rows = (CrewBreak.query
            .filter(CrewBreak.show_id == show.id, CrewBreak.id.in_(ids))
            .all())
    created = unlinked = 0
    for cb in rows:
        if status == CATERED_YES:
            cb.catered = CATERED_YES
            if _ensure_meal_service(cb) is not None:
                created += 1
        else:
            if cb.meal_service_id:
                # Unlink rather than delete. Deleting F&B's work off a bulk
                # tick is not recoverable, and the orphaned service lands in
                # this panel's third list where somebody can decide about it.
                ok, _msg = break_linking.unlink(cb, CATERED_NO)
                if ok:
                    unlinked += 1
            else:
                cb.catered = CATERED_NO
    db.session.commit()

    n = len(rows)
    word = "break" if n == 1 else "breaks"
    if status == CATERED_YES:
        tail = (f" {created} meal service{'' if created == 1 else 's'} created, "
                "each following its crew call for headcount."
                if created else " They were already linked to a service.")
        flash(f"{n} {word} marked Provided.{tail}", "success")
    else:
        tail = (f" {unlinked} service{'' if unlinked == 1 else 's'} left on the "
                "F&B tab, unlinked — nothing was deleted."
                if unlinked else "")
        flash(f"{n} {word} marked Not Provided.{tail}", "success")
    if len(ids) != n:
        flash(f"{len(ids) - n} of the ticked breaks are not on this show and "
              "were skipped.", "warning")
    return _back(show_id)
