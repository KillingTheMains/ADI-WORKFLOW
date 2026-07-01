from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models import (Show, Client, Venue, ProductionPhase, SHOW_STATUS, PHASE_TYPES,
                    ScheduleDay, ScheduleActivity, CrewRow)
from datetime import date, timedelta

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



# ── Duplicate / Clone a Show ─────────────────────────────────────────────────

@shows_bp.route("/<int:show_id>/duplicate", methods=["POST"])
def duplicate(show_id):
    """
    Deep-copy a show's schedule STRUCTURE into a new show. What we copy:
      * Show basic info (client, venue, room, version=1, status='Planning')
      * ProductionPhase records (dates shifted by offset)
      * ScheduleDay records (date shifted by offset)
      * ScheduleActivity records under each day (all fields kept)
      * CrewRow records under each activity — position, qty, hours (est),
        crew_type, sort_order, is_group_header/group_label all copied,
        but crew_member_id gets WIPED so each row shows as TBD. The
        user then fills in the crew for the new show.
    What we DO NOT copy:
      * ShowCrewAssignment (booking sheet is empty on the new show)
      * ShowOpenSlot
      * OSS SubScheduleEntry rows, MealServices, MealServiceLocations,
        ShowCommChannel, RadioChannel, CrewCommAssignment, dietary notes
      * Any actual_hours (only estimates carry over)
      * Wristband override/extras/notes on days
    """
    src = Show.query.get_or_404(show_id)
    form = request.form
    new_name  = (form.get("new_name") or f"Copy of {src.name}").strip()
    new_code  = (form.get("new_code") or "").strip() or None
    try:
        offset_days = int((form.get("date_offset_days") or "0").strip())
    except ValueError:
        offset_days = 0
    offset = timedelta(days=offset_days)

    def _shift(d):
        return (d + offset) if d else None

    # 1. Show basic info
    new_show = Show(
        code         = new_code,
        name         = new_name,
        client_id    = src.client_id,
        venue_id     = src.venue_id,
        room_name    = src.room_name,
        load_in_date = _shift(src.load_in_date),
        show_start   = _shift(src.show_start),
        show_end     = _shift(src.show_end),
        strike_date  = _shift(src.strike_date),
        version      = 1,
        status       = "Planning",
        notes        = src.notes,
    )
    db.session.add(new_show)
    db.session.flush()

    # 2. Production phases
    for ph in src.phases:
        db.session.add(ProductionPhase(
            show_id    = new_show.id,
            name       = ph.name,
            phase_type = ph.phase_type,
            start_date = _shift(ph.start_date),
            end_date   = _shift(ph.end_date),
            notes      = ph.notes,
        ))

    # 3. Days + activities + crew rows
    for day in src.days:
        new_day = ScheduleDay(
            show_id    = new_show.id,
            date       = _shift(day.date),
            label      = day.label,
            call_time  = day.call_time,
            wrap_time  = day.wrap_time,
            phase      = day.phase,
            milestones = day.milestones,
            notes      = day.notes,
            # travel fields carry over — dates get shifted
            travel_flight_number  = day.travel_flight_number,
            travel_airline        = day.travel_airline,
            travel_depart_airport = day.travel_depart_airport,
            travel_arrive_airport = day.travel_arrive_airport,
            travel_depart_time    = day.travel_depart_time,
            travel_arrive_time    = day.travel_arrive_time,
            travel_hotel_name     = day.travel_hotel_name,
            travel_hotel_confirm  = day.travel_hotel_confirm,
        )
        db.session.add(new_day)
        db.session.flush()

        for act in day.activities:
            new_act = ScheduleActivity(
                day_id      = new_day.id,
                time        = act.time,
                description = act.description,
                notes       = act.notes,
                sort_order  = act.sort_order,
            )
            db.session.add(new_act)
            db.session.flush()

            for row in act.crew_rows:
                db.session.add(CrewRow(
                    activity_id     = new_act.id,
                    sort_order      = row.sort_order,
                    is_group_header = row.is_group_header,
                    group_label     = row.group_label,
                    qty             = row.qty,
                    hours           = row.hours,          # estimated carries over
                    actual_hours    = None,               # actual doesn't
                    position        = row.position,
                    position_id     = row.position_id,
                    crew_member_id  = None,               # WIPED — becomes TBD
                    name_override   = None,               # so it renders as TBD
                    crew_type       = row.crew_type,
                    notes           = row.notes,
                ))

    db.session.commit()
    flash(
        f"Show cloned. '{new_name}' has {len(src.days)} days and "
        f"{sum(len(d.activities) for d in src.days)} activities. Crew slots "
        "are TBD — assign them on the new show.",
        "success",
    )
    return redirect(url_for("shows.detail", show_id=new_show.id))
