"""Production phase types — note #14, 2026-09-03.

Jason, in the meeting: "we want Larry to have the ability to add options to
that dropdown list and for everything he adds to carry over between shows in
the future and be reference for all shows in the whole workflow."

They were `PHASE_TYPES`, a five-item list in models.py, so adding a sixth
needed a developer. Now a table, shared by every show, managed here.

⚠️ SOME OF THESE NAMES ARE READ AS LITERAL STRINGS ELSEWHERE, and that is the
one thing this screen has to protect:

  · `routes.shows._sync_legacy_dates` finds the phase named "Show" to set
    show.show_start / show.show_end — which Auto-Generate Days then reads.
  · `models.Show._phase_date` looks up "Load In" and "Strike" by literal.

Rename one of those and a show silently stops knowing its own dates: no error,
no clue, just wrong dates on a schedule. So the three are marked builtin and
this screen refuses to rename or delete them. Everything else about them —
order, colour, the day label, whether they appear — is Larry's.

A type in use by real shows is never hard-deleted either. `ProductionPhase`
stores the type as a STRING, not a foreign key, so deleting the row would
leave phases pointing at a name that no longer exists in the list. Hiding
takes it out of the dropdown and leaves those shows readable.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from extensions import db
from models import (LOAD_BEARING_PHASE_TYPES, PhaseType, ProductionPhase,
                    find_normalised)

phase_types_bp = Blueprint("phase_types", __name__)


def _usage():
    """How many production phases use each type name. The type is a string, so
    this is a group-by on that string rather than a relationship count."""
    rows = (db.session.query(ProductionPhase.phase_type,
                             db.func.count(ProductionPhase.id))
            .group_by(ProductionPhase.phase_type).all())
    return {name: n for name, n in rows}


@phase_types_bp.route("/phase-types")
def index():
    types = PhaseType.query.order_by(PhaseType.sort_order, PhaseType.name).all()
    return render_template("phase_types/index.html",
                           types=types, usage=_usage())


@phase_types_bp.route("/phase-types/new", methods=["POST"])
def create():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("A phase type needs a name.", "warning")
        return redirect(url_for("phase_types.index"))

    # Case-insensitive, across the whole table including hidden rows. Without
    # it "Pre-Rig" and "pre-rig" become two types that group separately in
    # every count — the same trap positions.title still carries.
    clash = find_normalised(PhaseType.query.all(), name)
    if clash:
        tail = "" if clash.is_active else " (hidden — show it instead)"
        flash(f"“{clash.name}” is already a phase type{tail}.", "warning")
        return redirect(url_for("phase_types.index"))

    last = db.session.query(db.func.max(PhaseType.sort_order)).scalar() or 0
    db.session.add(PhaseType(
        name=name,
        day_label=(request.form.get("day_label") or "").strip() or name,
        color=(request.form.get("color") or "").strip() or None,
        sort_order=last + 10,
        is_active=True,
        is_builtin=False,
    ))
    db.session.commit()
    flash(f"“{name}” added. It is available on every show.", "success")
    return redirect(url_for("phase_types.index"))


@phase_types_bp.route("/phase-types/<int:type_id>/edit", methods=["POST"])
def edit(type_id):
    pt = PhaseType.query.get_or_404(type_id)
    new_name = (request.form.get("name") or "").strip()

    if pt.is_builtin and new_name and new_name != pt.name:
        flash(f"“{pt.name}” cannot be renamed — other parts of the app look "
              f"it up by name, and renaming it would stop shows knowing their "
              f"own dates. Its colour, order and day label are all editable.",
              "warning")
        return redirect(url_for("phase_types.index"))

    if new_name and new_name != pt.name:
        clash = find_normalised(PhaseType.query.all(), new_name,
                                exclude_id=pt.id)
        if clash:
            flash(f"“{clash.name}” is already a phase type.", "warning")
            return redirect(url_for("phase_types.index"))
        # Existing phases store the OLD string, so carry them across or they
        # are orphaned onto a name no longer in the list.
        moved = (ProductionPhase.query.filter_by(phase_type=pt.name)
                 .update({"phase_type": new_name}))
        pt.name = new_name
        if moved:
            flash(f"{moved} existing phase(s) moved to “{new_name}”.", "success")

    pt.day_label = (request.form.get("day_label") or "").strip() or pt.name
    pt.color     = (request.form.get("color") or "").strip() or None
    db.session.commit()
    flash(f"“{pt.name}” updated.", "success")
    return redirect(url_for("phase_types.index"))


@phase_types_bp.route("/phase-types/<int:type_id>/toggle", methods=["POST"])
def toggle(type_id):
    pt = PhaseType.query.get_or_404(type_id)
    pt.is_active = not pt.is_active
    db.session.commit()
    flash(f"“{pt.name}” {'is back in the list' if pt.is_active else 'hidden'}.",
          "success")
    return redirect(url_for("phase_types.index"))


@phase_types_bp.route("/phase-types/<int:type_id>/move", methods=["POST"])
def move(type_id):
    """Phase types are CHRONOLOGICAL — prep, load in, show, strike. Alphabetical
    would read wrong, so order is explicit and Larry sets it."""
    pt = PhaseType.query.get_or_404(type_id)
    direction = -1 if request.form.get("dir") == "up" else 1
    ordered = PhaseType.query.order_by(PhaseType.sort_order, PhaseType.name).all()
    i = ordered.index(pt)
    j = i + direction
    if 0 <= j < len(ordered):
        ordered[i], ordered[j] = ordered[j], ordered[i]
        for n, row in enumerate(ordered):
            row.sort_order = (n + 1) * 10
        db.session.commit()
    return redirect(url_for("phase_types.index"))


@phase_types_bp.route("/phase-types/<int:type_id>/delete", methods=["POST"])
def delete(type_id):
    pt = PhaseType.query.get_or_404(type_id)
    if pt.is_builtin:
        flash(f"“{pt.name}” cannot be deleted — other parts of the app look "
              f"it up by name. Hide it instead.", "warning")
        return redirect(url_for("phase_types.index"))
    n = _usage().get(pt.name, 0)
    if n:
        flash(f"“{pt.name}” is used by {n} phase(s), so it cannot be deleted. "
              f"Hide it instead — those shows keep their phase.", "warning")
        return redirect(url_for("phase_types.index"))
    name = pt.name
    db.session.delete(pt)
    db.session.commit()
    flash(f"“{name}” deleted. Nothing was using it.", "success")
    return redirect(url_for("phase_types.index"))
