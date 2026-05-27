from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models import Show, Client, Venue, ProductionPhase, SHOW_STATUS, PHASE_TYPES
from datetime import date

shows_bp = Blueprint("shows", __name__)


def _parse_date(val):
    try:
        return date.fromisoformat(val) if val and val.strip() else None
    except ValueError:
        return None


# ── Show list ────────────────────────────────────────────────────────────────

@shows_bp.route("/")
def index():
    shows = Show.query.order_by(Show.show_start.desc()).all()
    return render_template("shows/index.html", shows=shows)


# ── New show ─────────────────────────────────────────────────────────────────

@shows_bp.route("/new", methods=["GET", "POST"])
def new():
    clients = Client.query.order_by(Client.name).all()
    venues  = Venue.query.order_by(Venue.name).all()

    if request.method == "POST":
        f = request.form

        client_id = f.get("client_id") or None
        if f.get("new_client_name"):
            client = Client(name=f["new_client_name"],
                            contact=f.get("new_client_contact",""),
                            email=f.get("new_client_email",""))
            db.session.add(client); db.session.flush()
            client_id = client.id

        venue_id = f.get("venue_id") or None
        if f.get("new_venue_name"):
            venue = Venue(name=f["new_venue_name"],
                          city=f.get("new_venue_city",""),
                          state=f.get("new_venue_state",""),
                          address=f.get("new_venue_address",""))
            db.session.add(venue); db.session.flush()
            venue_id = venue.id

        show = Show(
            code      = f.get("code","").upper(),
            name      = f["name"],
            client_id = client_id,
            venue_id  = venue_id,
            room_name = f.get("room_name",""),
            status    = f.get("status","Planning"),
            notes     = f.get("notes",""),
        )
        db.session.add(show); db.session.flush()

        # Save default phases from the new form
        _save_phases(show.id, f)

        # Keep legacy date columns in sync for schedule generator
        _sync_legacy_dates(show)

        db.session.commit()
        flash(f'Show "{show.name}" created.', "success")
        return redirect(url_for("shows.detail", show_id=show.id))

    return render_template("shows/new.html", clients=clients, venues=venues,
                           statuses=SHOW_STATUS, phase_types=PHASE_TYPES)


# ── Show detail ───────────────────────────────────────────────────────────────

@shows_bp.route("/<int:show_id>")
def detail(show_id):
    show = Show.query.get_or_404(show_id)
    return render_template("shows/detail.html", show=show)


# ── Edit show ─────────────────────────────────────────────────────────────────

@shows_bp.route("/<int:show_id>/edit", methods=["GET", "POST"])
def edit(show_id):
    show    = Show.query.get_or_404(show_id)
    clients = Client.query.order_by(Client.name).all()
    venues  = Venue.query.order_by(Venue.name).all()

    if request.method == "POST":
        f = request.form
        show.code      = f.get("code","").upper()
        show.name      = f["name"]
        show.client_id = f.get("client_id") or None
        show.venue_id  = f.get("venue_id") or None
        show.room_name = f.get("room_name","")
        show.status    = f.get("status","Planning")
        show.notes     = f.get("notes","")

        # Delete existing phases and rebuild from form
        ProductionPhase.query.filter_by(show_id=show.id).delete()
        _save_phases(show.id, f)
        _sync_legacy_dates(show)

        db.session.commit()
        flash("Show updated.", "success")
        return redirect(url_for("shows.detail", show_id=show.id))

    return render_template("shows/edit.html", show=show, clients=clients,
                           venues=venues, statuses=SHOW_STATUS, phase_types=PHASE_TYPES)


# ── Phases API (add/delete via AJAX) ─────────────────────────────────────────

@shows_bp.route("/<int:show_id>/phases/add", methods=["POST"])
def add_phase(show_id):
    Show.query.get_or_404(show_id)
    data = request.get_json()
    phase = ProductionPhase(
        show_id    = show_id,
        name       = data.get("name","Custom Range"),
        phase_type = data.get("phase_type","Custom"),
        start_date = _parse_date(data.get("start_date")),
        end_date   = _parse_date(data.get("end_date")),
        notes      = data.get("notes",""),
    )
    db.session.add(phase)
    db.session.commit()
    return jsonify({"id": phase.id, "name": phase.name})


@shows_bp.route("/<int:show_id>/phases/<int:phase_id>/delete", methods=["POST"])
def delete_phase(show_id, phase_id):
    phase = ProductionPhase.query.get_or_404(phase_id)
    db.session.delete(phase)
    db.session.commit()
    return jsonify({"status": "ok"})


# ── Delete show ───────────────────────────────────────────────────────────────

@shows_bp.route("/<int:show_id>/delete", methods=["POST"])
def delete(show_id):
    show = Show.query.get_or_404(show_id)
    name = show.name
    db.session.delete(show)
    db.session.commit()
    flash(f'Show "{name}" deleted.', "info")
    return redirect(url_for("main.dashboard"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_phases(show_id, f):
    """Parse phase rows out of a submitted form and write to DB."""
    names       = f.getlist("phase_name[]")
    types       = f.getlist("phase_type[]")
    starts      = f.getlist("phase_start[]")
    ends        = f.getlist("phase_end[]")
    notes_list  = f.getlist("phase_notes[]")

    for i in range(len(names)):
        name = names[i].strip() if i < len(names) else ""
        if not name:
            continue
        phase = ProductionPhase(
            show_id    = show_id,
            name       = name,
            phase_type = types[i]       if i < len(types)      else "Custom",
            start_date = _parse_date(starts[i]) if i < len(starts) else None,
            end_date   = _parse_date(ends[i])   if i < len(ends)   else None,
            notes      = notes_list[i]  if i < len(notes_list) else "",
        )
        db.session.add(phase)


def _sync_legacy_dates(show):
    """Keep the legacy date columns (used by schedule generator) in sync with phases."""
    phases = ProductionPhase.query.filter_by(show_id=show.id)\
               .order_by(ProductionPhase.start_date).all()
    if not phases:
        return
    all_starts = [p.start_date for p in phases if p.start_date]
    all_ends   = [p.end_date   for p in phases if p.end_date]
    if all_starts:
        show.load_in_date = min(all_starts)
    if all_ends:
        show.strike_date = max(all_ends)
    # Show start/end from "Show" phase specifically
    for p in phases:
        if p.phase_type == "Show":
            show.show_start = p.start_date
            show.show_end   = p.end_date
            break
