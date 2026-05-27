from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import CrewMember, Company, Position

crew_bp = Blueprint("crew", __name__)


@crew_bp.route("/")
def index():
    members   = CrewMember.query.order_by(CrewMember.last_name).all()
    companies = Company.query.order_by(Company.name).all()
    positions = Position.query.order_by(Position.department, Position.title).all()
    return render_template("crew/index.html", members=members,
                           companies=companies, positions=positions)


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
