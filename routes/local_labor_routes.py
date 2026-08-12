"""The Local Labor Database — a catalogue of positions hired in multiples.

Not a roster. There are no people here: a local labour position is a title and
a department, and the number of them is decided per crew call. That is the
whole difference from the Crew Database next to it in the nav.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from extensions import db
from local_labor import SEED_TASKS, group_by_department
from models import CrewRow, Position

local_labor_bp = Blueprint("local_labor", __name__)

DEPARTMENTS = ["General", "Rigging", "Lighting", "LED", "Video", "Audio",
               "Scenic", "Power", "Production", "Specialty"]
# 'lead' runs the crew, 'hand' is the one you hire N of. The 2026 workbook's
# unfilled rate blocks were headed Leads and Hands, so this is most likely
# what a rate eventually attaches to.
TYPES = ["lead", "hand"]


@local_labor_bp.route("/local-labor")
def index():
    positions = Position.query.filter_by(is_local_labor=True).all()
    # How often each is actually used, so a catalogue that has drifted from
    # practice says so rather than just growing.
    usage = {}
    for row in (CrewRow.query
                .filter(CrewRow.position_id.isnot(None),
                        CrewRow.is_group_header == False).all()):  # noqa: E712
        usage[row.position_id] = usage.get(row.position_id, 0) + (row.qty or 1)
    return render_template("local_labor/index.html",
                           grouped=group_by_department(positions),
                           total=len(positions),
                           usage=usage,
                           tasks=SEED_TASKS,
                           departments=DEPARTMENTS, types=TYPES)


@local_labor_bp.route("/local-labor/add", methods=["POST"])
def add():
    f = request.form
    title = (f.get("title") or "").strip()
    if not title:
        flash("A position needs a title.", "warning")
        return redirect(url_for("local_labor.index"))

    # Case-insensitive, across the WHOLE table — not just local labour. Two
    # positions called "Rigger" would split every count that matters, and the
    # second one would be invisible to whoever created the first.
    clash = Position.query.filter(
        db.func.lower(Position.title) == title.lower()).first()
    if clash is not None:
        if clash.is_local_labor:
            flash(f"“{clash.title}” is already in the local labour "
                  "catalogue.", "info")
        else:
            clash.is_local_labor = True
            db.session.commit()
            flash(f"“{clash.title}” already existed as a crew position — "
                  "marked it as local labour rather than making a second one.",
                  "success")
        return redirect(url_for("local_labor.index"))

    db.session.add(Position(
        title=title,
        department=(f.get("department") or "").strip() or None,
        type=(f.get("type") or "hand").strip(),
        union_eligible=f.get("union_eligible") == "1",
        notes=(f.get("notes") or "").strip() or None,
        is_local_labor=True,
    ))
    db.session.commit()
    flash(f"Added {title}.", "success")
    return redirect(url_for("local_labor.index"))


@local_labor_bp.route("/local-labor/<int:pos_id>/edit", methods=["POST"])
def edit(pos_id):
    p = Position.query.get_or_404(pos_id)
    f = request.form
    title = (f.get("title") or "").strip()
    if title:
        p.title = title
    p.department = (f.get("department") or "").strip() or None
    p.type = (f.get("type") or "").strip() or None
    p.union_eligible = f.get("union_eligible") == "1"
    p.notes = (f.get("notes") or "").strip() or None
    db.session.commit()
    flash(f"Saved {p.title}.", "success")
    return redirect(url_for("local_labor.index"))


@local_labor_bp.route("/local-labor/<int:pos_id>/remove", methods=["POST"])
def remove(pos_id):
    """Take a position OUT of the catalogue. Deletes nothing.

    Crew rows point at positions, and a show from last year is entitled to
    keep saying it called fourteen riggers. So this clears the flag and leaves
    the Position row alone — the catalogue is a view of the table, not the
    table itself.
    """
    p = Position.query.get_or_404(pos_id)
    used = CrewRow.query.filter_by(position_id=p.id).count()
    p.is_local_labor = False
    db.session.commit()
    msg = f"Removed {p.title} from the local labour catalogue."
    if used:
        msg += (f" It stays on {used} existing crew row"
                f"{'' if used == 1 else 's'} — nothing was deleted.")
    flash(msg, "info")
    return redirect(url_for("local_labor.index"))
