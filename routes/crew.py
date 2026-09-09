from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import CompanyPositionRate, CrewMember, Company, Position, find_normalised
from crew_duplicates import find_duplicates

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
    # 2026-09-09 — report only, never a merge. Seven names existed twice on
    # production and it costs real overtime: the 6th-day and short-turnaround
    # rules both resolve per crew_member_id, so a person split across two
    # records can never trip either. See crew_duplicates for the whole story.
    duplicates = find_duplicates(members)
    return render_template("crew/index.html", members=members,
                           companies=companies, positions=positions,
                           duplicates=duplicates)


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

    # Duplicate detection under the ONE rule — normalise_type_name, not
    # lower(). "Load-In" and "Load In" are the same position.
    existing = find_normalised(Position.query.all(), title, attr="title")
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


@crew_bp.route("/companies/create", methods=["POST"])
def companies_create():
    """Create a new Company on the fly from a company dropdown's inline modal.
    Returns JSON so the modal JS can slot the new option into every company
    dropdown on the page and preselect it."""
    from flask import jsonify
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, error="Company name is required"), 400
    if len(name) > 200:
        name = name[:200]

    existing = Company.query.filter(
        db.func.lower(Company.name) == name.lower()
    ).first()
    if existing:
        return jsonify(ok=True, id=existing.id, name=existing.name, duplicate=True)

    code = (f.get("code") or "").strip() or None
    if code and len(code) > 20:
        code = code[:20]
    c = Company(name=name, code=code)
    db.session.add(c)
    db.session.commit()
    return jsonify(ok=True, id=c.id, name=c.name, duplicate=False)


@crew_bp.route("/companies")
def companies():
    """Every company with its overtime terms (2026-09-05).

    Companies were created from a modal and never had a page of their own,
    which was fine while the only thing on one was a name. Thresholds gave
    them a second field with nowhere to be edited. This page is that surface,
    and nothing more: contact details still live where they always have."""
    from billing import OT_AFTER_HOURS, DT_AFTER_HOURS, SHORT_TURN_HOURS
    rows = Company.query.order_by(Company.name).all()
    rated = {}
    for co_id, n in (db.session.query(CompanyPositionRate.company_id,
                                      db.func.count(CompanyPositionRate.id))
                     .filter(CompanyPositionRate.rate_standard.isnot(None))
                     .group_by(CompanyPositionRate.company_id).all()):
        rated[co_id] = n
    headcount = {}
    for co_id, n in (db.session.query(CrewMember.company_id,
                                      db.func.count(CrewMember.id))
                     .group_by(CrewMember.company_id).all()):
        headcount[co_id] = n
    return render_template("crew/companies.html", companies=rows,
                           headcount=headcount, rated=rated,
                           default_ot=OT_AFTER_HOURS, default_dt=DT_AFTER_HOURS,
                           default_short=SHORT_TURN_HOURS)


@crew_bp.route("/companies/<int:company_id>/rates")
def company_rates(company_id):
    """A company's rate card: one standard hourly rate per local labor
    position (Jason, 2026-09-06). Every catalogue position is listed so the
    card can be filled in before a show, not only once a line exists;
    positions with a rate sort first. Autosaves per cell."""
    co = Company.query.get_or_404(company_id)
    positions = (Position.query.filter_by(is_local_labor=True)
                 .order_by(Position.department, Position.title).all())
    have = {r.position_id: r for r in co.rate_card}
    return render_template("crew/company_rates.html", company=co,
                           positions=positions, have=have)


@crew_bp.route("/companies/<int:company_id>/rates/<int:position_id>", methods=["POST"])
def company_rate_save(company_id, position_id):
    """Save one cell of the rate card. Blank clears the rate (the row stays,
    which is harmless and keeps the id stable for the autosave)."""
    co = Company.query.get_or_404(company_id)
    pos = Position.query.get_or_404(position_id)
    rate = _money(request.form, "rate_standard")
    entry = CompanyPositionRate.query.filter_by(company_id=co.id,
                                                position_id=pos.id).first()
    if entry is None:
        entry = CompanyPositionRate(company_id=co.id, position_id=pos.id)
        db.session.add(entry)
    entry.rate_standard = rate if rate and rate > 0 else None
    db.session.commit()
    if request.headers.get("X-Autosave"):
        return ("", 204)
    flash(f"{co.name}: rate for {pos.title} saved.", "success")
    return redirect(url_for("crew.company_rates", company_id=co.id))


@crew_bp.route("/companies/<int:company_id>/terms", methods=["POST"])
def company_terms(company_id):
    """Save a company's OT/DT thresholds. Field-present semantics; blank or
    zero means 'same as the default'."""
    co = Company.query.get_or_404(company_id)
    f = request.form
    if "ot_after_hours" in f:
        co.ot_after_hours = _threshold(f, "ot_after_hours")
    if "dt_after_hours" in f:
        co.dt_after_hours = _threshold(f, "dt_after_hours")
    if "short_turn_hours" in f:
        co.short_turn_hours = _threshold(f, "short_turn_hours")
    if "code" in f:
        co.code = (f.get("code") or "").strip()[:20] or None
    db.session.commit()
    if request.headers.get("X-Autosave"):
        return ("", 204)
    flash(f"{co.name}: overtime terms saved.", "success")
    return redirect(url_for("crew.companies"))


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

    # Optional return path (e.g. the per-show roster), validated to a local URL.
    nxt = request.form.get("next") or ""
    dest = nxt if (nxt.startswith("/") and not nxt.startswith("//")) else url_for("crew.index")

    if not ids or not (pos_raw or co_raw):
        flash("Nothing to update — select crew and choose a field to change.", "warning")
        return redirect(dest)

    members = CrewMember.query.filter(CrewMember.id.in_(ids)).all()
    for m in members:
        if pos_raw.isdigit():
            m.position_id = int(pos_raw)
        if co_raw.isdigit():
            m.company_id = int(co_raw)
    db.session.commit()
    flash(f"Updated {len(members)} crew member{'s' if len(members) != 1 else ''}.", "success")
    return redirect(dest)


def _money(f, key):
    """A blank money/number field is NULL, never 0. Tolerates "$" and ",",
    which is how rates arrive when pasted from a rate card."""
    raw = (f.get(key) or "").strip().replace("$", "").replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _threshold(f, key):
    """OT/DT thresholds: blank or 0 means inherit (see billing.thresholds_for)."""
    v = _money(f, key)
    return v if v and v > 0 else None


def _rate_unit(f):
    """"hourly" unless the form says "day". Never anything else."""
    from billing import RATE_UNITS, RATE_UNIT_HOURLY
    v = (f.get("rate_unit") or "").strip().lower()
    return v if v in RATE_UNITS else RATE_UNIT_HOURLY


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
            rate_standard = _money(f, "rate_standard"),
            rate_unit     = _rate_unit(f),
            rate_ot       = _money(f, "rate_ot"),
            rate_dt       = _money(f, "rate_dt"),
            meal_penalty  = _money(f, "meal_penalty"),
            per_diem      = _money(f, "per_diem"),
            ot_after_hours = _threshold(f, "ot_after_hours"),
            dt_after_hours = _threshold(f, "dt_after_hours"),
            short_turn_hours = _threshold(f, "short_turn_hours"),
            notes         = f.get("notes", ""),
        )
        db.session.add(member)
        db.session.commit()
        flash(f"{member.full_name} added to roster.", "success")
        if member.looks_like_placeholder:
            flash(f"Heads up — \u201c{member.full_name}\u201d looks like a "
                  "placeholder rather than a person. Placeholder crew are "
                  "counted in call headcounts on schedules and client "
                  "exports. Rename them once you know who is filling the slot.",
                  "warning")
        return redirect(url_for("crew.index"))

    from billing import OT_AFTER_HOURS, DT_AFTER_HOURS, SHORT_TURN_HOURS
    return render_template("crew/add.html", companies=companies, positions=positions,
                           default_ot=OT_AFTER_HOURS, default_dt=DT_AFTER_HOURS,
                           default_short=SHORT_TURN_HOURS)


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
        member.rate_standard = _money(f, "rate_standard")
        member.rate_unit     = _rate_unit(f)
        member.rate_ot       = _money(f, "rate_ot")
        member.rate_dt       = _money(f, "rate_dt")
        member.meal_penalty  = _money(f, "meal_penalty")
        member.per_diem      = _money(f, "per_diem")
        member.ot_after_hours = _threshold(f, "ot_after_hours")
        member.dt_after_hours = _threshold(f, "dt_after_hours")
        member.short_turn_hours = _threshold(f, "short_turn_hours")
        member.active        = f.get("active") == "1"
        member.notes         = f.get("notes", "")
        db.session.commit()
        flash(f"{member.full_name} updated.", "success")
        if member.looks_like_placeholder:
            flash(f"Heads up — \u201c{member.full_name}\u201d looks like a "
                  "placeholder rather than a person. Placeholder crew are "
                  "counted in call headcounts on schedules and client "
                  "exports. Rename them once you know who is filling the slot.",
                  "warning")
        return redirect(url_for("crew.index"))

    from billing import (rates_for, thresholds_for, short_turn_for,
                         OT_AFTER_HOURS, DT_AFTER_HOURS, SHORT_TURN_HOURS)
    _std, auto_ot, auto_dt = rates_for(member)
    # What this person would inherit if their own thresholds were blank —
    # shown as the placeholder so a blank field says what it means.
    inherit_ot, inherit_dt = thresholds_for(None, member.company)
    inherit_short = short_turn_for(None, member.company)
    return render_template("crew/edit.html", member=member,
                           companies=companies, positions=positions,
                           auto_ot=auto_ot, auto_dt=auto_dt,
                           inherit_ot=inherit_ot, inherit_dt=inherit_dt,
                           inherit_short=inherit_short,
                           default_ot=OT_AFTER_HOURS, default_dt=DT_AFTER_HOURS,
                           default_short=SHORT_TURN_HOURS)


@crew_bp.route("/<int:member_id>/delete", methods=["POST"])
def delete(member_id):
    member = CrewMember.query.get_or_404(member_id)
    name = member.full_name
    db.session.delete(member)
    db.session.commit()
    flash(f"{name} removed from roster.", "info")
    return redirect(url_for("crew.index"))
