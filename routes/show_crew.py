"""
show_crew.py — routes for assigning crew members to a specific show.

URL prefix: /shows/<show_id>/crew
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from extensions import db
from models import Show, CrewMember, ShowCrewAssignment, Company, Position, \
    ScheduleActivity, CrewRow

show_crew_bp = Blueprint("show_crew", __name__)


# ── Helper ───────────────────────────────────────────────────────────────────

def _get_show_or_404(show_id):
    return db.session.get(Show, show_id) or \
        (_ for _ in ()).throw(Exception("404"))


# ── Show crew roster page ─────────────────────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew")
def show_crew(show_id):
    show = Show.query.get_or_404(show_id)

    # All active crew, grouped by company
    all_crew = (
        db.session.query(CrewMember)
        .filter_by(active=True)
        .outerjoin(Position, CrewMember.position_id == Position.id)
        .order_by(CrewMember.company_id, Position.department, CrewMember.last_name)
        .all()
    )

    # Set of crew_member_ids already assigned to this show
    assigned_ids = {a.crew_member_id for a in show.crew_assignments}

    # Group crew by company for display
    companies = {}
    for cm in all_crew:
        co_name = cm.company.name if cm.company else "No Company"
        co_id   = cm.company_id or 0
        if co_id not in companies:
            companies[co_id] = {"name": co_name, "crew": []}
        companies[co_id]["crew"].append(cm)

    # Sort companies alphabetically
    sorted_companies = sorted(companies.values(), key=lambda c: c["name"])

    return render_template(
        "shows/show_crew.html",
        show=show,
        sorted_companies=sorted_companies,
        assigned_ids=assigned_ids,
    )


# ── Assign / unassign a single crew member ────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/assign", methods=["POST"])
def assign_crew(show_id):
    show = Show.query.get_or_404(show_id)
    crew_member_id = int(request.form["crew_member_id"])
    action = request.form.get("action", "assign")  # "assign" or "unassign"

    if action == "assign":
        existing = ShowCrewAssignment.query.filter_by(
            show_id=show_id, crew_member_id=crew_member_id).first()
        if not existing:
            db.session.add(ShowCrewAssignment(
                show_id=show_id, crew_member_id=crew_member_id))
            db.session.commit()
    else:
        ShowCrewAssignment.query.filter_by(
            show_id=show_id, crew_member_id=crew_member_id).delete()
        db.session.commit()

    return redirect(url_for("show_crew.show_crew", show_id=show_id))


# ── Assign / unassign an entire company in one click ─────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/assign-company", methods=["POST"])
def assign_company(show_id):
    show = Show.query.get_or_404(show_id)
    company_id = int(request.form["company_id"])
    action = request.form.get("action", "assign")

    company_crew = CrewMember.query.filter_by(
        company_id=company_id, active=True).all()

    if action == "assign":
        for cm in company_crew:
            exists = ShowCrewAssignment.query.filter_by(
                show_id=show_id, crew_member_id=cm.id).first()
            if not exists:
                db.session.add(ShowCrewAssignment(
                    show_id=show_id, crew_member_id=cm.id))
        db.session.commit()
        co = Company.query.get(company_id)
        flash(f"Added all {co.name} crew to {show.name}.", "success")
    else:
        crew_ids = [cm.id for cm in company_crew]
        ShowCrewAssignment.query.filter(
            ShowCrewAssignment.show_id == show_id,
            ShowCrewAssignment.crew_member_id.in_(crew_ids)
        ).delete(synchronize_session=False)
        db.session.commit()
        co = Company.query.get(company_id)
        flash(f"Removed all {co.name} crew from {show.name}.", "info")

    return redirect(url_for("show_crew.show_crew", show_id=show_id))


# ── AJAX: Add all assigned crew from a company to a specific activity ─────────

@show_crew_bp.route(
    "/<int:show_id>/schedule/<int:day_id>/activities/<int:act_id>/add-company-crew",
    methods=["POST"])
def add_company_crew_to_activity(show_id, day_id, act_id):
    """
    Bulk-add every show-assigned crew member from a company to an activity.
    Called via AJAX from the day editor.
    """
    activity   = ScheduleActivity.query.get_or_404(act_id)
    company_id = int(request.json.get("company_id", 0))
    hours      = request.json.get("hours")          # float or None
    if hours is not None:
        try:
            hours = float(hours)
        except (TypeError, ValueError):
            hours = None

    # Crew assigned to this show AND belonging to this company
    assigned = (
        db.session.query(CrewMember)
        .join(ShowCrewAssignment,
              ShowCrewAssignment.crew_member_id == CrewMember.id)
        .filter(
            ShowCrewAssignment.show_id == show_id,
            CrewMember.company_id == company_id,
            CrewMember.active == True,
        )
        .outerjoin(Position, CrewMember.position_id == Position.id)
        .order_by(Position.department, CrewMember.last_name)
        .all()
    )

    # Current max sort_order in this activity
    existing_max = db.session.query(
        db.func.max(CrewRow.sort_order)
    ).filter_by(activity_id=act_id).scalar() or 0

    added = []
    for i, cm in enumerate(assigned):
        # Skip if already on this activity
        already = CrewRow.query.filter_by(
            activity_id=act_id, crew_member_id=cm.id).first()
        if already:
            continue
        row = CrewRow(
            activity_id=act_id,
            crew_member_id=cm.id,
            position=cm.position.title if cm.position else "",
            sort_order=existing_max + i + 1,
            hours=hours,
        )
        db.session.add(row)
        added.append({
            "id": None,  # filled after commit
            "crew_member_id": cm.id,
            "name": cm.full_name,
            "position": cm.position.title if cm.position else "",
        })

    db.session.commit()

    # Fill in the real IDs
    for item in added:
        row = CrewRow.query.filter_by(
            activity_id=act_id,
            crew_member_id=item["crew_member_id"]
        ).first()
        if row:
            item["id"] = row.id

    return jsonify({"added": len(added), "rows": added})


# ── Crew contact sheet ────────────────────────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/contact-sheet")
def contact_sheet(show_id):
    """Printable contact sheet for all crew assigned to this show."""
    show = Show.query.get_or_404(show_id)

    # Pull assigned crew with their full relationships loaded
    assignments = (
        db.session.query(ShowCrewAssignment)
        .join(CrewMember, ShowCrewAssignment.crew_member_id == CrewMember.id)
        .outerjoin(Position, CrewMember.position_id == Position.id)
        .filter(ShowCrewAssignment.show_id == show_id, CrewMember.active == True)
        .order_by(CrewMember.company_id, Position.department, CrewMember.last_name)
        .all()
    )

    # Group by company
    companies = {}
    for a in assignments:
        cm = a.crew_member
        co_name = cm.company.name if cm.company else "No Company"
        co_id   = cm.company_id or 0
        if co_id not in companies:
            companies[co_id] = {"name": co_name, "crew": []}
        companies[co_id]["crew"].append(cm)

    sorted_companies = sorted(companies.values(), key=lambda c: c["name"])

    return render_template(
        "shows/crew_contact_sheet.html",
        show=show,
        sorted_companies=sorted_companies,
        total=len(assignments),
    )


# ── Show hours report ─────────────────────────────────────────────────────────

@show_crew_bp.route("/<int:show_id>/crew/hours")
def hours_report(show_id):
    """Per-crew-member hours breakdown across all show days."""
    show = Show.query.get_or_404(show_id)

    # Build a lookup: crew_member_id → {member, days: {day_id: hours}, total}
    crew_data = {}   # keyed by crew_member_id (for named crew)
    tbd_data  = []   # list of {name, day_id, hours, position, activity} for unnamed rows

    show_days = show.days  # already ordered by date

    for day in show_days:
        for act in day.activities:
            for row in act.crew_rows:
                if row.is_group_header:
                    continue
                hrs = (row.hours or 0) * (row.qty or 1)
                if row.crew_member_id:
                    if row.crew_member_id not in crew_data:
                        cm = row.crew_member
                        crew_data[row.crew_member_id] = {
                            "member":   cm,
                            "position": row.position or (cm.position.title if cm.position else ""),
                            "dept":     (cm.position.department if cm.position else "") or "",
                            "company":  cm.company.name if cm.company else "",
                            "type":     row.crew_type or "",
                            "days":     {},
                            "total":    0.0,
                        }
                    entry = crew_data[row.crew_member_id]
                    entry["days"][day.id] = entry["days"].get(day.id, 0.0) + hrs
                    entry["total"] += hrs
                else:
                    # TBD / local unnamed row — track separately
                    tbd_data.append({
                        "name":     row.display_name,
                        "position": row.position or "",
                        "type":     row.crew_type or "",
                        "day_id":   day.id,
                        "hours":    hrs,
                        "activity": act.description,
                    })

    # Sort named crew: by company, then dept, then name
    sorted_crew = sorted(
        crew_data.values(),
        key=lambda x: (x["company"], x["dept"], x["member"].last_name)
    )

    # Day totals (sum of all named crew hours per day)
    day_totals = {}
    for entry in sorted_crew:
        for day_id, hrs in entry["days"].items():
            day_totals[day_id] = day_totals.get(day_id, 0.0) + hrs

    grand_total = sum(e["total"] for e in sorted_crew)

    return render_template(
        "shows/hours_report.html",
        show=show,
        show_days=show_days,
        sorted_crew=sorted_crew,
        tbd_data=tbd_data,
        day_totals=day_totals,
        grand_total=grand_total,
    )
