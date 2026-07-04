from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models import Show, ScheduleDay, ScheduleActivity, CrewRow, Position, CrewMember, \
                   PHASES, CREW_TYPES, DayTemplate, PHASE_TYPES, ShowCrewAssignment, Company, \
                   SubScheduleEntry, SUB_SCHEDULE_TYPES, SUB_SCHEDULE_META, is_meal_break
from datetime import date, timedelta
import re, json

schedule_bp = Blueprint("schedule", __name__)


# ── Time helpers ─────────────────────────────────────────────────────────────

def _parse_time_to_minutes(t_str):
    """Parse '8:00 AM', '19:00', '7:30 PM' → minutes since midnight. Returns None on failure."""
    if not t_str or not t_str.strip():
        return None
    t = t_str.strip().upper()
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', t)
    if not m:
        return None
    h, mn, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm == 'PM' and h != 12:
        h += 12
    elif ampm == 'AM' and h == 12:
        h = 0
    return h * 60 + mn


def _minutes_to_time_str(mins):
    """Convert minutes since midnight → '8:00 AM' format."""
    mins = int(mins) % (24 * 60)
    h, mn = divmod(mins, 60)
    ampm = 'AM' if h < 12 else 'PM'
    display_h = h if h <= 12 else h - 12
    if display_h == 0:
        display_h = 12
    return f"{display_h}:{mn:02d} {ampm}"


# ── Day Templates (loaded from DB) ───────────────────────────────────────────

def _get_templates_dict():
    """Return all DayTemplates as a key→dict mapping (replaces old DAY_TEMPLATES constant)."""
    return {t.key: t.to_dict() for t in DayTemplate.query.order_by(DayTemplate.sort_order).all()}


def _get_template_by_phase(phase_type):
    """Return the DayTemplate whose phase_hint matches the given production phase type, or None."""
    return DayTemplate.query.filter_by(phase_hint=phase_type).first()


# ── Schedule overview for a show ─────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule")
def overview(show_id):
    show = Show.query.get_or_404(show_id)
    return render_template("schedule/overview.html", show=show, phases=PHASES)


# ── Add / generate days ──────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/add-day", methods=["GET", "POST"])
def add_day(show_id):
    show      = Show.query.get_or_404(show_id)
    positions = Position.query.order_by(Position.department, Position.title).all()

    if request.method == "POST":
        f = request.form
        try:
            day_date = date.fromisoformat(f["date"])
        except (ValueError, KeyError):
            flash("Invalid date.", "danger")
            return redirect(url_for("schedule.add_day", show_id=show_id))

        day = ScheduleDay(
            show_id    = show_id,
            date       = day_date,
            label      = f.get("label", ""),
            call_time  = f.get("call_time", ""),
            wrap_time  = f.get("wrap_time", ""),
            phase      = f.get("phase", ""),
            milestones = f.get("milestones", ""),
            notes      = f.get("notes", ""),
        )
        db.session.add(day)
        db.session.commit()
        flash(f"Day added: {day.day_header}", "success")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day.id))

    existing = [d.date for d in show.days]
    if existing:
        suggested = max(existing) + timedelta(days=1)
    elif show.load_in_date:
        suggested = show.load_in_date
    else:
        suggested = date.today()

    return render_template("schedule/add_day.html", show=show, phases=PHASES,
                           suggested_date=suggested)


@schedule_bp.route("/<int:show_id>/schedule/generate-days", methods=["POST"])
def generate_days(show_id):
    """Auto-generate a skeleton day for every date between load_in and strike."""
    show = Show.query.get_or_404(show_id)
    if not (show.load_in_date and show.strike_date):
        flash("Set Load-In and Strike dates on the show first.", "warning")
        return redirect(url_for("schedule.overview", show_id=show_id))

    existing_dates = {d.date for d in show.days}
    with_templates = request.form.get("with_templates") == "1"

    # Build a date→phase_type lookup from ProductionPhase table
    phase_lookup = {}
    for phase in show.phases:
        if phase.start_date and phase.end_date:
            cur = phase.start_date
            while cur <= phase.end_date:
                phase_lookup[cur] = phase.phase_type
                cur += timedelta(days=1)

    # Map ProductionPhase types → schedule phase label
    PHASE_LABEL_MAP = {
        "Prep":    "Setup",
        "Load In": "Load In",
        "Show":    "Show Day",
        "Strike":  "Strike",
        "Custom":  "Setup",
    }

    current = show.load_in_date
    added = 0
    while current <= show.strike_date:
        if current not in existing_dates:
            raw = phase_lookup.get(current)
            if raw and raw in PHASE_LABEL_MAP:
                phase_label = PHASE_LABEL_MAP[raw]
                phase_type  = raw
            elif current == show.load_in_date:
                phase_label, phase_type = "Load In", "Load In"
            elif current == show.strike_date:
                phase_label, phase_type = "Strike", "Strike"
            elif show.show_start and show.show_end and show.show_start <= current <= show.show_end:
                phase_label, phase_type = "Show Day", "Show"
            else:
                phase_label, phase_type = "Setup", "Load In"

            day = ScheduleDay(show_id=show_id, date=current, phase=phase_label)
            db.session.add(day)
            db.session.flush()

            if with_templates:
                tpl = _get_template_by_phase(phase_type)
                if tpl:
                    for i, (t, desc) in enumerate(tpl.activities):
                        db.session.add(ScheduleActivity(
                            day_id=day.id, time=t, description=desc,
                            sort_order=(i + 1) * 10))

            added += 1
        current += timedelta(days=1)

    db.session.commit()
    flash(f"{added} days generated.", "success")
    return redirect(url_for("schedule.overview", show_id=show_id))


# ── Day detail / editor ──────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>", methods=["GET"])
def day_detail(show_id, day_id):
    show      = Show.query.get_or_404(show_id)
    day       = ScheduleDay.query.get_or_404(day_id)
    positions = Position.query.order_by(Position.department, Position.title).all()

    # Crew assigned to this show only; fall back to full roster if none assigned yet
    assigned_ids = [a.crew_member_id for a in show.crew_assignments]
    if assigned_ids:
        crew_members = (
            db.session.query(CrewMember)
            .filter(CrewMember.id.in_(assigned_ids), CrewMember.active == True)
            .outerjoin(Position, CrewMember.position_id == Position.id)
            .order_by(Position.department, CrewMember.last_name)
            .all()
        )
    else:
        # No assignments yet — show everyone so the day editor still works
        crew_members = (
            db.session.query(CrewMember).filter_by(active=True)
            .outerjoin(Position, CrewMember.position_id == Position.id)
            .order_by(Position.department, CrewMember.last_name)
            .all()
        )

    # Companies that have at least one crew member assigned to this show
    # (used by the "Add all company" bulk button in the day editor)
    if assigned_ids:
        company_ids = db.session.query(CrewMember.company_id)\
            .filter(CrewMember.id.in_(assigned_ids))\
            .distinct().all()
        company_ids = [c[0] for c in company_ids if c[0]]
        show_companies = Company.query.filter(Company.id.in_(company_ids))\
            .order_by(Company.name).all()
    else:
        show_companies = Company.query.order_by(Company.name).all()

    # OSS items that fall on this day, grouped by linked activity.
    # Linked entries hang under their activity card; unlinked ones become
    # their own row in the timeline.
    oss_for_day = (
        SubScheduleEntry.query
        .filter_by(show_id=show_id, schedule_day_id=day_id)
        .order_by(SubScheduleEntry.sort_order)
        .all()
    )
    oss_by_activity = {}     # activity_id -> [entries]
    oss_unlinked    = []     # entries with no activity_id
    for e in oss_for_day:
        if e.activity_id:
            oss_by_activity.setdefault(e.activity_id, []).append(e)
        else:
            oss_unlinked.append(e)
    # Sort unlinked by effective_time (string compare on HH:MM works fine)
    oss_unlinked.sort(key=lambda e: (e.effective_time or "99:99", e.sort_order or 0))

    # Ordered tab keys for the per-activity "+ OSS" department picker
    ordered_oss_types = sorted(
        SUB_SCHEDULE_TYPES,
        key=lambda t: SUB_SCHEDULE_META.get(t, {}).get("sort", 99),
    )

    # Meal-break F&B warnings: set of activity IDs that look like meal breaks
    # but have no linked F&B OSS entry. Templates can check `act.id in
    # meal_breaks_missing_fb` to render the warning.
    meal_breaks_missing_fb = set()
    for act in day.activities:
        if not is_meal_break(act):
            continue
        has_fb = any(e.activity_id == act.id and e.type == "F&B"
                     for e in oss_for_day)
        if not has_fb:
            meal_breaks_missing_fb.add(act.id)

    return render_template("schedule/day.html", show=show, day=day,
                           positions=positions, crew_members=crew_members,
                           show_companies=show_companies,
                           phases=PHASES, crew_types=CREW_TYPES,
                           day_templates=_get_templates_dict(),
                           oss_by_activity=oss_by_activity,
                           oss_unlinked=oss_unlinked,
                           oss_types=ordered_oss_types,
                           oss_meta=SUB_SCHEDULE_META,
                           meal_breaks_missing_fb=meal_breaks_missing_fb)


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/edit", methods=["POST"])
def edit_day(show_id, day_id):
    day = ScheduleDay.query.get_or_404(day_id)
    f   = request.form

    # Server-side rename detection — the second layer of the 9/9 protection.
    # The JS `confirmDayDateChange` is the first layer, but if it ever gets
    # bypassed (autosave misconfiguration, a scripted client), the server
    # still shows an obvious flash telling the user the date changed. Compare
    # the form's _original_date hidden input against the incoming date.
    old_date = day.date
    original_iso = (f.get("_original_date") or "").strip()
    try:
        new_date = date.fromisoformat(f["date"])
        day.date = new_date
    except (ValueError, KeyError):
        new_date = day.date

    date_changed = False
    if original_iso and new_date and new_date.isoformat() != original_iso:
        date_changed = True
    elif old_date and new_date and new_date != old_date:
        date_changed = True

    day.label      = f.get("label", "")
    day.call_time  = f.get("call_time", "")
    day.wrap_time  = f.get("wrap_time", "")
    day.phase      = f.get("phase", "")
    day.milestones = f.get("milestones", "")
    day.notes      = f.get("notes", "")
    # Travel fields
    day.travel_flight_number  = f.get("travel_flight_number", "")
    day.travel_airline        = f.get("travel_airline", "")
    day.travel_depart_airport = f.get("travel_depart_airport", "").upper()
    day.travel_arrive_airport = f.get("travel_arrive_airport", "").upper()
    day.travel_depart_time    = f.get("travel_depart_time", "")
    day.travel_arrive_time    = f.get("travel_arrive_time", "")
    day.travel_hotel_name     = f.get("travel_hotel_name", "")
    day.travel_hotel_confirm  = f.get("travel_hotel_confirm", "")
    db.session.commit()

    if date_changed:
        # Loud, non-dismissible-feeling notice so a silent rename is impossible.
        flash(
            f"⚠ Day RENAMED from {original_iso or old_date} to {new_date}. "
            f"If this was not intended, use Recent Activity to undo.",
            "warning",
        )
    else:
        flash("Day updated.", "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/delete", methods=["POST"])
def delete_day(show_id, day_id):
    day = ScheduleDay.query.get_or_404(day_id)
    db.session.delete(day)
    db.session.commit()
    flash("Day deleted.", "info")
    return redirect(url_for("schedule.overview", show_id=show_id))


# ── Clone day ────────────────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/clone", methods=["POST"])
def clone_day(show_id, day_id):
    src = ScheduleDay.query.get_or_404(day_id)
    new_day = ScheduleDay(
        show_id    = show_id,
        date       = src.date + timedelta(days=1),
        label      = src.label,
        call_time  = src.call_time,
        wrap_time  = src.wrap_time,
        phase      = src.phase,
        milestones = src.milestones,
        notes      = src.notes,
    )
    db.session.add(new_day)
    db.session.flush()
    for act in src.activities:
        new_act = ScheduleActivity(
            day_id=new_day.id, time=act.time,
            description=act.description, notes=act.notes,
            sort_order=act.sort_order,
        )
        db.session.add(new_act)
        db.session.flush()
        for row in act.crew_rows:
            db.session.add(CrewRow(
                activity_id=new_act.id, sort_order=row.sort_order,
                is_group_header=row.is_group_header, group_label=row.group_label,
                qty=row.qty, hours=row.hours, position=row.position,
                position_id=row.position_id, crew_member_id=row.crew_member_id,
                name_override=row.name_override, crew_type=row.crew_type,
                notes=row.notes,
            ))
    db.session.commit()
    flash(f"Day cloned to {new_day.day_header}.", "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=new_day.id))


# ── Apply day template ───────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/apply-template", methods=["POST"])
def apply_template(show_id, day_id):
    day = ScheduleDay.query.get_or_404(day_id)
    tpl_key = request.form.get("template")
    replace = request.form.get("replace") == "1"
    tpl = DayTemplate.query.filter_by(key=tpl_key).first()
    if not tpl:
        flash("Unknown template.", "warning")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))
    if replace:
        ScheduleActivity.query.filter_by(day_id=day_id).delete()
    last = db.session.query(db.func.max(ScheduleActivity.sort_order)).filter_by(day_id=day_id).scalar() or 0
    if not day.label:
        day.label = tpl.label
    for i, (t, desc) in enumerate(tpl.activities):
        db.session.add(ScheduleActivity(
            day_id=day_id, time=t, description=desc,
            sort_order=last + (i + 1) * 10))
    db.session.commit()
    flash(f'Template "{tpl.label}" applied.', "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Build Day Schedule (break schedule from call/wrap times) ─────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/build-schedule", methods=["POST"])
def build_day_schedule(show_id, day_id):
    """
    Add a full break schedule to the day derived from call time, wrap time,
    and lunch duration.  Optionally replace existing break/start/wrap activities.
    Schedule:
        call        → CREW START
        call + 2:30 → MORNING BREAK — 15 min
        call + 5:00 → LUNCH BREAK
        lunch_end + 2:30 → AFTERNOON BREAK — 15 min
        wrap        → EOD WRAP
    """
    day = ScheduleDay.query.get_or_404(day_id)
    f = request.form

    call_time  = (f.get("call_time") or day.call_time or "").strip()
    wrap_time  = (f.get("wrap_time") or day.wrap_time or "").strip()
    lunch_mins = int(f.get("lunch_minutes") or 30)
    replace    = f.get("replace") == "1"

    call_m = _parse_time_to_minutes(call_time)
    if call_m is None:
        flash("Set a call time on this day first.", "warning")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))

    wrap_m = _parse_time_to_minutes(wrap_time)

    # Optionally purge existing break / start / wrap activities
    if replace:
        BREAK_KEYWORDS = ("break", "lunch", "dinner", "crew start", "eod wrap", "eod")
        for act in list(day.activities):
            if any(kw in act.description.lower() for kw in BREAK_KEYWORDS):
                db.session.delete(act)
        db.session.flush()

    coffee1   = call_m + 150           # +2h 30m
    lunch_s   = call_m + 300           # +5h 00m
    lunch_end = lunch_s + lunch_mins
    coffee2   = lunch_end + 150        # +2h 30m after lunch ends

    to_add = [
        (call_m,   "CREW START"),
        (coffee1,  "MORNING BREAK — 15 min"),
        (lunch_s,  f"LUNCH BREAK — {lunch_mins} min"),
        (coffee2,  "AFTERNOON BREAK — 15 min"),
    ]

    # Dinner break required when total elapsed time exceeds 10 hours
    # AND the calculated dinner time actually falls before the wrap
    if wrap_m is not None and ((wrap_m - call_m) % (24 * 60)) > 600:
        dinner_s = lunch_end + 300     # 5h of work after lunch ends
        if dinner_s < wrap_m:
            to_add.append((dinner_s, f"DINNER BREAK — {lunch_mins} min"))

    if wrap_m is not None:
        to_add.append((wrap_m, "EOD WRAP"))

    to_add.sort(key=lambda x: x[0])

    last = db.session.query(
        db.func.max(ScheduleActivity.sort_order)
    ).filter_by(day_id=day_id).scalar() or 0

    for i, (t, desc) in enumerate(to_add):
        db.session.add(ScheduleActivity(
            day_id=day_id,
            time=_minutes_to_time_str(t),
            description=desc,
            sort_order=last + (i + 1) * 10,
        ))

    db.session.commit()
    flash(
        f"Day schedule built — {len(to_add)} activities added "
        f"({call_time} – {wrap_time or 'no wrap set'}).",
        "success"
    )
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Smart breaks ─────────────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/smart-breaks", methods=["POST"])
def smart_breaks(show_id, day_id):
    day = ScheduleDay.query.get_or_404(day_id)
    call_mins = _parse_time_to_minutes(day.call_time)
    if call_mins is None:
        flash("Set a call time on this day first.", "warning")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))

    existing = " ".join(a.description.upper() for a in day.activities)
    last = db.session.query(db.func.max(ScheduleActivity.sort_order)).filter_by(day_id=day_id).scalar() or 0
    to_add = []

    # Lunch: call + 5h30, clamped 11:30–13:30
    if "LUNCH" not in existing:
        lunch = max(11 * 60 + 30, min(13 * 60 + 30, call_mins + 5 * 60 + 30))
        to_add.append((lunch, "LUNCH BREAK — 30 min"))
    else:
        lunch = 12 * 60 + 30  # fallback for pm-break calc

    # Afternoon break: lunch + 2h30
    if "AFTERNOON BREAK" not in existing and "PM BREAK" not in existing:
        to_add.append((lunch + 2 * 60 + 30, "AFTERNOON BREAK — 15 min"))

    # EOD Wrap from wrap_time
    wrap_mins = _parse_time_to_minutes(day.wrap_time)
    if wrap_mins and "EOD WRAP" not in existing and "EOD" not in existing:
        to_add.append((wrap_mins, "EOD WRAP"))

    to_add.sort(key=lambda x: x[0])
    for i, (t, desc) in enumerate(to_add):
        db.session.add(ScheduleActivity(
            day_id=day_id, time=_minutes_to_time_str(t),
            description=desc, sort_order=last + (i + 1) * 10))

    db.session.commit()
    if to_add:
        flash(f"{len(to_add)} break{'s' if len(to_add) != 1 else ''} added.", "success")
    else:
        flash("Breaks already exist on this day — nothing added.", "info")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Bulk time shift ───────────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/bulk-shift", methods=["POST"])
def bulk_shift(show_id, day_id):
    day = ScheduleDay.query.get_or_404(day_id)
    try:
        shift_mins = int(request.form.get("shift_minutes", 0))
    except ValueError:
        flash("Invalid shift amount.", "danger")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))

    act_ids = request.form.getlist("act_ids[]")
    acts = [ScheduleActivity.query.get(int(i)) for i in act_ids if i] if act_ids else list(day.activities)

    shifted = 0
    for act in acts:
        if not act or not act.time:
            continue
        mins = _parse_time_to_minutes(act.time)
        if mins is not None:
            act.time = _minutes_to_time_str(mins + shift_mins)
            shifted += 1

    db.session.commit()
    direction = f"+{shift_mins}" if shift_mins > 0 else str(shift_mins)
    flash(f"{shifted} activit{'ies' if shifted != 1 else 'y'} shifted {direction} minutes.", "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Copy activity to other days ───────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/activities/<int:act_id>/copy-to-days",
                   methods=["POST"])
def copy_activity_to_days(show_id, day_id, act_id):
    act = ScheduleActivity.query.get_or_404(act_id)
    target_ids = request.form.getlist("target_day_ids[]")
    copy_crew  = request.form.get("copy_crew") == "1"
    count = 0
    for tid in target_ids:
        try:
            target = ScheduleDay.query.get(int(tid))
        except ValueError:
            continue
        if not target or target.show_id != show_id:
            continue
        last = db.session.query(db.func.max(ScheduleActivity.sort_order)).filter_by(day_id=target.id).scalar() or 0
        new_act = ScheduleActivity(
            day_id=target.id, time=act.time,
            description=act.description, notes=act.notes,
            sort_order=last + 10,
        )
        db.session.add(new_act)
        db.session.flush()
        if copy_crew:
            for row in act.crew_rows:
                db.session.add(CrewRow(
                    activity_id=new_act.id, sort_order=row.sort_order,
                    is_group_header=row.is_group_header, group_label=row.group_label,
                    qty=row.qty, hours=row.hours, position=row.position,
                    position_id=row.position_id, crew_member_id=row.crew_member_id,
                    name_override=row.name_override, crew_type=row.crew_type,
                    notes=row.notes,
                ))
        count += 1
    db.session.commit()
    flash(f'"{act.description}" copied to {count} day{"s" if count != 1 else ""}.', "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Stamp activity to all days in same phase ──────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/activities/<int:act_id>/stamp-phase",
                   methods=["POST"])
def stamp_activity_to_phase(show_id, day_id, act_id):
    act        = ScheduleActivity.query.get_or_404(act_id)
    source_day = ScheduleDay.query.get_or_404(day_id)
    show       = Show.query.get_or_404(show_id)

    if not source_day.phase:
        flash("This day has no phase set — can't stamp to phase.", "warning")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))

    count = 0
    for target in show.days:
        if target.phase != source_day.phase or target.id == day_id:
            continue
        if act.description in [a.description for a in target.activities]:
            continue  # skip if already present
        last = db.session.query(db.func.max(ScheduleActivity.sort_order)).filter_by(day_id=target.id).scalar() or 0
        db.session.add(ScheduleActivity(
            day_id=target.id, time=act.time,
            description=act.description, notes=act.notes,
            sort_order=last + 10,
        ))
        count += 1

    db.session.commit()
    flash(f'"{act.description}" stamped to {count} "{source_day.phase}" day{"s" if count != 1 else ""}.', "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Activities ───────────────────────────────────────────────────────────────

def _resort_day_by_time(day_id):
    """
    Re-number sort_order on all activities in a day so they appear in
    time order. Activities without a parseable time get pushed to the
    bottom (their relative order among themselves is preserved).
    """
    acts = ScheduleActivity.query.filter_by(day_id=day_id).all()
    def _key(a):
        m = _parse_time_to_minutes(a.time)
        # Timed activities first (0), untimed second (1). Ties broken by
        # existing sort_order so manual reordering of untimed rows sticks.
        return (0, m) if m is not None else (1, a.sort_order or 0)
    acts.sort(key=_key)
    for idx, a in enumerate(acts):
        a.sort_order = idx * 10


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/activities/add", methods=["POST"])
def add_activity(show_id, day_id):
    day  = ScheduleDay.query.get_or_404(day_id)
    f    = request.form
    # Insert with a temp sort_order at the end, then re-sort the whole day.
    last = db.session.query(db.func.max(ScheduleActivity.sort_order)).filter_by(day_id=day_id).scalar() or 0
    db.session.add(ScheduleActivity(
        day_id=day_id, time=f.get("time", ""),
        description=f.get("description", ""),
        notes=f.get("notes", ""), sort_order=last + 10,
    ))
    db.session.flush()
    _resort_day_by_time(day_id)
    db.session.commit()
    flash("Activity added.", "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/activities/<int:act_id>/edit",
                   methods=["POST"])
def edit_activity(show_id, day_id, act_id):
    act = ScheduleActivity.query.get_or_404(act_id)
    f   = request.form
    old_time = act.time
    act.time        = f.get("time", "")
    act.description = f.get("description", "")
    act.notes       = f.get("notes", "")
    # Re-sort only when the time actually changed, so a description-only
    # edit doesn't blow away any manual reordering the user did.
    if (act.time or "") != (old_time or ""):
        _resort_day_by_time(day_id)
    db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/activities/<int:act_id>/delete",
                   methods=["POST"])
def delete_activity(show_id, day_id, act_id):
    act = ScheduleActivity.query.get_or_404(act_id)
    # Unlink any OSS entries that pointed at this activity before deleting,
    # so they survive as unlinked entries on the day rather than getting
    # cascaded into oblivion or left with a dangling activity_id.
    linked_oss = SubScheduleEntry.query.filter_by(activity_id=act_id).all()
    unlinked_count = 0
    for e in linked_oss:
        # Preserve the entry's last known time so it still has chronology
        # in the day editor after the activity goes away.
        if not e.time and act.time:
            e.time = act.time
        e.activity_id = None
        unlinked_count += 1
    db.session.delete(act)
    db.session.commit()
    if unlinked_count:
        flash(f"Activity deleted. {unlinked_count} OSS "
              f"entr{'y' if unlinked_count == 1 else 'ies'} now show "
              f"as unlinked operational items.", "info")
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Crew Rows ────────────────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/activities/<int:act_id>/crew/add",
                   methods=["POST"])
def add_crew_row(show_id, day_id, act_id):
    f    = request.form
    last = db.session.query(db.func.max(CrewRow.sort_order)).filter_by(activity_id=act_id).scalar() or 0
    is_header = f.get("is_group_header") == "1"

    # ── Double-booking detection ──────────────────────────────────────────────
    crew_member_id = int(f["crew_member_id"]) if f.get("crew_member_id") and not is_header else None
    if crew_member_id:
        # Find all activity IDs on this day (excluding the current activity)
        day = ScheduleDay.query.get(day_id)
        day_act_ids = [a.id for a in day.activities if a.id != act_id]
        if day_act_ids:
            existing = CrewRow.query.filter(
                CrewRow.crew_member_id == crew_member_id,
                CrewRow.activity_id.in_(day_act_ids),
                CrewRow.is_group_header == False,
            ).first()
            if existing:
                cm = CrewMember.query.get(crew_member_id)
                name = cm.full_name if cm else "That crew member"
                conflict_act = ScheduleActivity.query.get(existing.activity_id)
                conflict_time = conflict_act.time or "another activity"
                flash(
                    f"⚠ Double-booking: {name} is already on this day "
                    f"({conflict_time} — {conflict_act.description[:40]}). "
                    f"Row added anyway — review the call sheet.",
                    "warning"
                )

    db.session.add(CrewRow(
        activity_id=act_id, sort_order=last + 10,
        is_group_header=is_header,
        group_label=f.get("group_label", "") if is_header else "",
        qty=int(f.get("qty", 1)) if not is_header else 0,
        hours=float(f.get("hours", 0)) if not is_header and f.get("hours") else None,
        position=f.get("position", "") if not is_header else "",
        position_id=int(f["position_id"]) if f.get("position_id") and not is_header else None,
        crew_member_id=crew_member_id,
        name_override=f.get("name_override", "") if not is_header else "",
        crew_type=f.get("crew_type", "Lead Crew") if not is_header else "",
        notes=f.get("notes", ""),
    ))
    db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/crew/<int:row_id>/edit",
                   methods=["POST"])
def edit_crew_row(show_id, day_id, row_id):
    """Wishlist #7 — inline edit for a crew row within an activity."""
    row = CrewRow.query.get_or_404(row_id)
    f = request.form

    if "qty" in f:
        raw = (f.get("qty") or "").strip()
        try:
            row.qty = int(raw) if raw else 1
        except ValueError:
            pass
    if "hours" in f:
        raw = (f.get("hours") or "").strip()
        try:
            row.hours = float(raw) if raw else None
        except ValueError:
            row.hours = None
    if "actual_hours" in f:
        raw = (f.get("actual_hours") or "").strip()
        try:
            row.actual_hours = float(raw) if raw else None
        except ValueError:
            row.actual_hours = None
    if "position" in f:
        v = (f.get("position") or "").strip()
        row.position = v or None
        # If the free-text position exactly matches a Position title,
        # also update position_id so hours reports + reports pick it up.
        if v:
            match = Position.query.filter(
                db.func.lower(Position.title) == v.lower()).first()
            row.position_id = match.id if match else None
        else:
            row.position_id = None
    if "name_override" in f:
        v = (f.get("name_override") or "").strip()
        row.name_override = v or None
    if "crew_type" in f:
        v = (f.get("crew_type") or "").strip()
        if v in CREW_TYPES:
            row.crew_type = v
    db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/crew/<int:row_id>/delete",
                   methods=["POST"])
def delete_crew_row(show_id, day_id, row_id):
    row = CrewRow.query.get_or_404(row_id)
    db.session.delete(row)
    db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


# ── Reorder activities (AJAX) ─────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/reorder", methods=["POST"])
def reorder_activities(show_id, day_id):
    data = request.get_json()
    for idx, act_id in enumerate(data.get("order", [])):
        act = ScheduleActivity.query.get(act_id)
        if act and act.day_id == day_id:
            act.sort_order = idx * 10
    db.session.commit()
    return jsonify({"status": "ok"})


# ── Daily Call Sheet ──────────────────────────────────────────────────────────

@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/call-sheet")
def call_sheet(show_id, day_id):
    show = Show.query.get_or_404(show_id)
    day  = ScheduleDay.query.get_or_404(day_id)

    # Build a flat list of all crew rows with their activity context,
    # sorted by activity sort_order then crew sort_order
    # Also detect double-bookings for highlighting
    crew_lines = []
    seen_ids   = {}  # crew_member_id → first activity description
    conflicts  = set()

    for act in day.activities:
        for row in act.crew_rows:
            if row.is_group_header:
                continue
            line = {
                "act_time":    act.time or "",
                "act_desc":    act.description,
                "name":        row.display_name,
                "position":    row.position or "",
                "qty":         row.qty or 1,
                "hours":       row.hours,
                "crew_type":   row.crew_type or "",
                "notes":       row.notes or "",
                "dept":        row.position_ref.department if row.position_ref else "",
                "conflict":    False,
            }
            if row.crew_member_id:
                if row.crew_member_id in seen_ids:
                    conflicts.add(row.crew_member_id)
                    line["conflict"] = True
                else:
                    seen_ids[row.crew_member_id] = act.description
            crew_lines.append(line)

    # Mark earlier entries for the same conflicted person
    for line in crew_lines:
        if line.get("crew_member_id") in conflicts:
            line["conflict"] = True

    # Group by department for the sorted view
    from collections import defaultdict
    by_dept = defaultdict(list)
    for line in crew_lines:
        by_dept[line["dept"] or "General"].append(line)

    total_crew = sum(l["qty"] for l in crew_lines)

    return render_template("schedule/call_sheet.html",
                           show=show, day=day,
                           crew_lines=crew_lines,
                           by_dept=dict(sorted(by_dept.items())),
                           total_crew=total_crew,
                           conflicts=len(conflicts) > 0)


# ── Day Template Management ───────────────────────────────────────────────────

@schedule_bp.route("/templates")
def template_list():
    templates = DayTemplate.query.order_by(DayTemplate.sort_order, DayTemplate.label).all()
    return render_template("schedule/day_templates.html",
                           templates=templates, phase_types=PHASE_TYPES)


@schedule_bp.route("/templates/new", methods=["GET", "POST"])
def template_new():
    if request.method == "POST":
        times = request.form.getlist("activity_time[]")
        descs = request.form.getlist("activity_desc[]")
        activities = [(t.strip(), d.strip()) for t, d in zip(times, descs) if d.strip()]
        # Auto-generate a key from the label
        import re as _re
        raw_key = _re.sub(r'[^a-z0-9]+', '_', request.form.get("label", "").lower()).strip('_')
        # Make unique
        key = raw_key
        suffix = 2
        while DayTemplate.query.filter_by(key=key).first():
            key = f"{raw_key}_{suffix}"
            suffix += 1
        tpl = DayTemplate(
            key        = key,
            label      = request.form.get("label", "").strip(),
            phase_hint = request.form.get("phase_hint") or None,
            sort_order = int(request.form.get("sort_order") or 99),
        )
        tpl.activities = activities
        db.session.add(tpl)
        db.session.commit()
        flash(f'Template "{tpl.label}" created.', "success")
        return redirect(url_for("schedule.template_list"))
    return render_template("schedule/day_templates.html",
                           templates=DayTemplate.query.order_by(DayTemplate.sort_order).all(),
                           phase_types=PHASE_TYPES, editing=None, creating=True)


@schedule_bp.route("/templates/<int:tpl_id>/edit", methods=["GET", "POST"])
def template_edit(tpl_id):
    tpl = DayTemplate.query.get_or_404(tpl_id)
    if request.method == "POST":
        tpl.label      = request.form.get("label", "").strip()
        tpl.phase_hint = request.form.get("phase_hint") or None
        tpl.sort_order = int(request.form.get("sort_order") or 99)
        times = request.form.getlist("activity_time[]")
        descs = request.form.getlist("activity_desc[]")
        tpl.activities = [(t.strip(), d.strip()) for t, d in zip(times, descs) if d.strip()]
        db.session.commit()
        flash(f'Template "{tpl.label}" saved.', "success")
        return redirect(url_for("schedule.template_list"))
    return render_template("schedule/day_templates.html",
                           templates=DayTemplate.query.order_by(DayTemplate.sort_order).all(),
                           phase_types=PHASE_TYPES, editing=tpl, creating=False)


@schedule_bp.route("/templates/<int:tpl_id>/delete", methods=["POST"])
def template_delete(tpl_id):
    tpl = DayTemplate.query.get_or_404(tpl_id)
    name = tpl.label
    db.session.delete(tpl)
    db.session.commit()
    flash(f'Template "{name}" deleted.', "info")
    return redirect(url_for("schedule.template_list"))
