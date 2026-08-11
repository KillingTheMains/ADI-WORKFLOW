from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, abort
from extensions import db
from models import (Show, Client, Venue, ProductionPhase, SHOW_STATUS, PHASE_TYPES,
                    ScheduleDay, ScheduleActivity, CrewRow)
from datetime import date, timedelta
from werkzeug.utils import secure_filename
import os

shows_bp = Blueprint("shows", __name__)

# ── #48 show artwork: upload/serve show key-art used as a paperwork header ──
ART_ROOT = os.path.expanduser("~/adi_workflow_uploads/show_artwork")
ART_MAX_BYTES = 5 * 1024 * 1024
ART_EXT_TO_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".gif": "image/gif", ".webp": "image/webp"}


def _art_path(show):
    if not show.artwork_filename:
        return None
    return os.path.join(ART_ROOT, str(show.id), show.artwork_filename)


@shows_bp.route("/<int:show_id>/artwork/upload", methods=["POST"])
def artwork_upload(show_id):
    show = Show.query.get_or_404(show_id)
    f = request.files.get("artwork")
    if not f or not f.filename:
        flash("Choose an image file to upload.", "warning")
        return redirect(url_for("shows.detail", show_id=show_id))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ART_EXT_TO_MIME:
        flash("Artwork must be a PNG, JPG, GIF, or WEBP image.", "danger")
        return redirect(url_for("shows.detail", show_id=show_id))
    f.seek(0, os.SEEK_END)
    if f.tell() > ART_MAX_BYTES:
        flash("Artwork must be under 5 MB.", "danger")
        return redirect(url_for("shows.detail", show_id=show_id))
    f.seek(0)
    d = os.path.join(ART_ROOT, str(show_id))
    os.makedirs(d, exist_ok=True)
    # clear any previous file so we don't leave orphans
    if show.artwork_filename:
        old = os.path.join(d, show.artwork_filename)
        if os.path.exists(old):
            try: os.remove(old)
            except OSError: pass
    name = (secure_filename(f.filename) or "artwork")[:300]
    if os.path.splitext(name)[1].lower() not in ART_EXT_TO_MIME:
        name += ext
    f.save(os.path.join(d, name))
    show.artwork_filename = name
    db.session.commit()
    flash("Show artwork updated — it now appears on all generated paperwork.", "success")
    return redirect(url_for("shows.detail", show_id=show_id))


@shows_bp.route("/<int:show_id>/artwork/delete", methods=["POST"])
def artwork_delete(show_id):
    show = Show.query.get_or_404(show_id)
    p = _art_path(show)
    if p and os.path.exists(p):
        try: os.remove(p)
        except OSError: pass
    show.artwork_filename = None
    db.session.commit()
    flash("Show artwork removed.", "success")
    return redirect(url_for("shows.detail", show_id=show_id))


@shows_bp.route("/<int:show_id>/artwork")
def artwork(show_id):
    show = Show.query.get_or_404(show_id)
    p = _art_path(show)
    if not p or not os.path.exists(p):
        abort(404)
    # Re-derive mimetype from extension (never trust stored content-type) and
    # serve inline so it can render in an <img> on the paperwork header.
    ext = os.path.splitext(show.artwork_filename)[1].lower()
    return send_file(p, mimetype=ART_EXT_TO_MIME.get(ext, "application/octet-stream"))



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
    phases = ProductionPhase.query.filter_by(show_id=show.id)\
               .order_by(ProductionPhase.start_date).all()
    return render_template("shows/detail.html", show=show, phases=phases)


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
    #
    # deep=1 also carries the roster, the crew LINKS, the OSS entries and the
    # F&B services. The default (structure only, crew wiped to TBD) is right
    # for "next year's version of this show"; deep is right for a working copy
    # of a live show — testing a change against real crew, real headcounts and
    # real meal services, which structure alone cannot exercise.
    deep = form.get("deep") == "1"
    day_map = {}
    act_map = {}
    for day in src.days:
        new_day = ScheduleDay(
            show_id    = new_show.id,
            date       = _shift(day.date),
            label      = day.label,
            call_time  = day.call_time,
            wrap_time  = day.wrap_time,
            sod        = day.sod,
            eod        = day.eod,
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
        day_map[day.id] = new_day.id

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
            act_map[act.id] = new_act.id

            for row in act.crew_rows:
                db.session.add(CrewRow(
                    activity_id     = new_act.id,
                    sort_order      = row.sort_order,
                    is_group_header = row.is_group_header,
                    group_label     = row.group_label,
                    header_level    = row.header_level,
                    company_id      = row.company_id,
                    qty             = row.qty,
                    hours           = row.hours,          # estimated carries over
                    actual_hours    = None,               # actual doesn't
                    position        = row.position,
                    position_id     = row.position_id,
                    # Structure-only wipes the person; deep keeps them, which
                    # is the whole point of a working copy.
                    crew_member_id  = row.crew_member_id if deep else None,
                    name_override   = row.name_override if deep else None,
                    crew_type       = row.crew_type,
                    notes           = row.notes,
                ))

    if deep:
        from routes._deep_clone import clone_show_crew_and_fnb
        clone_show_crew_and_fnb(src, new_show, day_map, act_map, _shift)

    db.session.commit()
    if deep:
        flash(
            f"Show deep-cloned. '{new_name}' has {len(src.days)} days, "
            f"{sum(len(d.activities) for d in src.days)} activities, and "
            "carries the crew roster, OSS entries and F&B services. It is a "
            "working copy of real data — check the name before Larry sees it.",
            "success",
        )
    else:
        flash(
            f"Show cloned. '{new_name}' has {len(src.days)} days and "
            f"{sum(len(d.activities) for d in src.days)} activities. Crew slots "
            "are TBD — assign them on the new show.",
            "success",
        )
    return redirect(url_for("shows.detail", show_id=new_show.id))
