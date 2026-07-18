from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import CrewMember, Company, Position

crew_bp = Blueprint("crew", __name__)


def _ensure_sort_order():
    """
    Backfill sort_order for any crew rows that don't have one, so up/down
    arrows always have a stable starting point. Uses alphabetical
    (last_name, first_name) order — matches the pre-Wishlist#3 display.
    """
    unset = CrewMember.query.filter(CrewMember.sort_order.is_(None)).count()
    if unset == 0:
        return
    all_crew = (CrewMember.query
                .order_by(CrewMember.sort_order,
                          CrewMember.last_name, CrewMember.first_name)
                .all())
    for idx, cm in enumerate(all_crew):
        if cm.sort_order is None:
            cm.sort_order = idx * 10
    db.session.commit()


@crew_bp.route("/")
def index():
    _ensure_sort_order()
    members   = (CrewMember.query
                 .order_by(CrewMember.sort_order.asc().nullslast(),
                           CrewMember.last_name)
                 .all())
    companies = Company.query.order_by(Company.name).all()
    positions = Position.query.order_by(Position.department, Position.title).all()
    return render_template("crew/index.html", members=members,
                           companies=companies, positions=positions)


# ── Wishlist #3: reorder + inline edit ───────────────────────────────────────

@crew_bp.route("/<int:member_id>/move-up", methods=["POST"])
def move_up(member_id):
    _ensure_sort_order()
    m = CrewMember.query.get_or_404(member_id)
    # Find the crew member immediately above this one in current order
    prev = (CrewMember.query
            .filter(CrewMember.sort_order < m.sort_order)
            .order_by(CrewMember.sort_order.desc())
            .first())
    if prev:
        m.sort_order, prev.sort_order = prev.sort_order, m.sort_order
        db.session.commit()
    return redirect(url_for("crew.index"))


@crew_bp.route("/<int:member_id>/move-down", methods=["POST"])
def move_down(member_id):
    _ensure_sort_order()
    m = CrewMember.query.get_or_404(member_id)
    nxt = (CrewMember.query
           .filter(CrewMember.sort_order > m.sort_order)
           .order_by(CrewMember.sort_order.asc())
           .first())
    if nxt:
        m.sort_order, nxt.sort_order = nxt.sort_order, m.sort_order
        db.session.commit()
    return redirect(url_for("crew.index"))


@crew_bp.route("/reorder", methods=["POST"])
def reorder():
    """
    Bulk-update sort_order from a drag-and-drop reorder. Accepts JSON:
       { "order": [id1, id2, id3, ...] }
    Assigns sort_order = idx * 10 to each id in the order given. IDs not in
    the payload are left as-is (they'll be pushed below the reordered ones
    by the next _ensure_sort_order pass if they had a NULL, otherwise their
    numeric order stays).
    """
    data = request.get_json(silent=True) or {}
    order = data.get("order") or []
    if not isinstance(order, list):
        return {"ok": False, "error": "order must be a list"}, 400
    for idx, cm_id in enumerate(order):
        try:
            cm_id = int(cm_id)
        except (TypeError, ValueError):
            continue
        cm = CrewMember.query.get(cm_id)
        if cm:
            cm.sort_order = idx * 10
    db.session.commit()
    return {"ok": True, "count": len(order)}


@crew_bp.route("/positions/create", methods=["POST"])
def positions_create():
    """Create a new Position on the fly from the roster's inline modal.
    Returns JSON so the modal JS can slot the new option into the
    dropdown that opened it and preselect it."""
    from flask import jsonify
    f = request.form
    title = (f.get("title") or "").strip()
    if not title:
        return jsonify(ok=False, error="Title is required"), 400
    if len(title) > 100:
        title = title[:100]

    # Duplicate detection (case-insensitive)
    existing = Position.query.filter(
        db.func.lower(Position.title) == title.lower()
    ).first()
    if existing:
        return jsonify(ok=True, id=existing.id, title=existing.title,
                       department=existing.department, duplicate=True)

    dept = (f.get("department") or "").strip() or None
    typ  = (f.get("type") or "").strip() or None
    union = f.get("union_eligible") == "1"

    p = Position(
        title=title,
        department=dept,
        type=typ,
        union_eligible=union,
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(ok=True, id=p.id, title=p.title,
                   department=p.department, duplicate=False)


@crew_bp.route("/<int:member_id>/edit-inline", methods=["POST"])
def edit_inline(member_id):
    """Save only the fields the inline row form sends (first/last name,
    position, company, email, phone). Uses 'field-present' semantics so
    a partial POST doesn't blank other data."""
    m = CrewMember.query.get_or_404(member_id)
    f = request.form
    if "first_name" in f:
        v = (f.get("first_name") or "").strip()
        if v: m.first_name = v
    if "last_name" in f:
        v = (f.get("last_name") or "").strip()
        if v: m.last_name = v
    if "position_id" in f:
        raw = (f.get("position_id") or "").strip()
        m.position_id = int(raw) if raw.isdigit() else None
    if "company_id" in f:
        raw = (f.get("company_id") or "").strip()
        m.company_id = int(raw) if raw.isdigit() else None
    if "email" in f:
        m.email = (f.get("email") or "").strip() or None
    if "phone" in f:
        m.phone = (f.get("phone") or "").strip() or None
    db.session.commit()
    return redirect(url_for("crew.index"))


@crew_bp.route("/bulk-edit", methods=["POST"])
def bulk_edit():
    """Bulk-set Position and/or Company on the selected crew (#42).

    Non-destructive: a field left on '— leave unchanged —' (empty) is NOT
    written, so selected members keep their existing value for that field.
    """
    ids = [int(x) for x in (request.form.get("ids") or "").split(",") if x.strip().isdigit()]
    pos_raw = (request.form.get("position_id") or "").strip()
    co_raw  = (request.form.get("company_id") or "").strip()

    if not ids or not (pos_raw or co_raw):
        flash("Nothing to update — select crew and choose a field to change.", "warning")
        return redirect(url_for("crew.index"))

    members = CrewMember.query.filter(CrewMember.id.in_(ids)).all()
    for m in members:
        if pos_raw.isdigit():
            m.position_id = int(pos_raw)
        if co_raw.isdigit():
            m.company_id = int(co_raw)
    db.session.commit()
    flash(f"Updated {len(members)} crew member{'s' if len(members) != 1 else ''}.", "success")
    return redirect(url_for("crew.index"))


@crew_bp.route("/add", methods=["GET", "POST"])
def add():
    companies = Company.query.order_by(Company.name).all()
    positions = Position.query.order_by(Position.department, Position.title).all()

    if request.method == "POST":
        f = request.form
        member = CrewMember(
            first_name    = f["first_name"],
            last_name     = f["last_name"],
            company_id    = f.get("company_id") or None,
            position_id   = f.get("position_id") or None,
            email         = f.get("email", ""),
            phone         = f.get("phone", ""),
            rate_standard = float(f["rate_standard"]) if f.get("rate_standard") else None,
            rate_ot       = float(f["rate_ot"]) if f.get("rate_ot") else None,
            rate_dt       = float(f["rate_dt"]) if f.get("rate_dt") else None,
            meal_penalty  = float(f["meal_penalty"]) if f.get("meal_penalty") else None,
            per_diem      = float(f["per_diem"]) if f.get("per_diem") else None,
            notes         = f.get("notes", ""),
        )
        db.session.add(member)
        db.session.commit()
        flash(f"{member.full_name} added to roster.", "success")
        return redirect(url_for("crew.index"))

    return render_template("crew/add.html", companies=companies, positions=positions)


@crew_bp.route("/<int:member_id>/edit", methods=["GET", "POST"])
def edit(member_id):
    member    = CrewMember.query.get_or_404(member_id)
    companies = Company.query.order_by(Company.name).all()
    positions = Position.query.order_by(Position.department, Position.title).all()

    if request.method == "POST":
        f = request.form
        member.first_name    = f["first_name"]
        member.last_name     = f["last_name"]
        member.company_id    = f.get("company_id") or None
        member.position_id   = f.get("position_id") or None
        member.email         = f.get("email", "")
        member.phone         = f.get("phone", "")
        member.rate_standard = float(f["rate_standard"]) if f.get("rate_standard") else None
        member.rate_ot       = float(f["rate_ot"]) if f.get("rate_ot") else None
        member.rate_dt       = float(f["rate_dt"]) if f.get("rate_dt") else None
        member.meal_penalty  = float(f["meal_penalty"]) if f.get("meal_penalty") else None
        member.per_diem      = float(f["per_diem"]) if f.get("per_diem") else None
        member.active        = f.get("active") == "1"
        member.notes         = f.get("notes", "")
        db.session.commit()
        flash(f"{member.full_name} updated.", "success")
        return redirect(url_for("crew.index"))

    return render_template("crew/edit.html", member=member,
                           companies=companies, positions=positions)


@crew_bp.route("/<int:member_id>/delete", methods=["POST"])
def delete(member_id):
    member = CrewMember.query.get_or_404(member_id)
    name = member.full_name
    db.session.delete(member)
    db.session.commit()
    flash(f"{name} removed from roster.", "info")
    return redirect(url_for("crew.index"))
