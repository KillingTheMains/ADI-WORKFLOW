from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response, abort
from extensions import db
from crew_ordering import (apply_partial_order, crew_order_by, crew_sort_key,
                           roster_index)
from crew_sections import insert_index_for, renumber
from models import Show, ScheduleDay, ScheduleActivity, CrewRow, Position, CrewMember, \
                   PHASES, CREW_TYPES, DayTemplate, PHASE_TYPES, ShowCrewAssignment, Company, \
                   SubScheduleEntry, SUB_SCHEDULE_TYPES, SUB_SCHEDULE_META, is_meal_break, DayPhase, \
                   MealService, MealServiceLocation, HardCodedEventDayOff
from datetime import date, timedelta
from time_utils import sort_minutes, parse_minutes, hhmm_or_blank
import re, json

schedule_bp = Blueprint("schedule", __name__)


# Placement lives in hardcoded_service so the day editor and the show book
# cannot drift apart on where a recurring event belongs.
from hardcoded_service import place_in_day as _place_recurring
from breaks import (DEFAULT_MEAL_MINUTES, MEAL_MINUTES_CHOICES,
                    break_options_for, is_crew_start, meal_minutes_from_breaks)


def _break_options_resolver(breaks_by_crew_call):
    """The template asks per crew call, so the answer is per crew call.

    The afternoon coffee follows the END of the meal, so a call with a
    30-minute meal on it offers +8:00 and a call with an hour-long one offers
    +8:30 — on the same day, from the same dropdown. Reading the length off
    the breaks already loaded keeps it self-correcting and costs no query.
    """
    def resolve(crew_call):
        rows = breaks_by_crew_call.get(getattr(crew_call, "id", None), [])
        meal = meal_minutes_from_breaks(rows) or DEFAULT_MEAL_MINUTES
        return break_options_for(crew_call, meal)
    return resolve


# ── Time helpers ─────────────────────────────────────────────────────────────

def _parse_time_to_minutes(t_str):
    """Parse '8:00 AM', '19:00', '7:30 PM' → minutes since midnight. None on failure.

    Thin alias for time_utils.parse_minutes — kept so existing callers and
    tests keep working, but there is now ONE parser behind every time compare.
    """
    return parse_minutes(t_str)


def _minutes_to_time_str(mins):
    """Convert minutes since midnight → 24-hour 'HH:MM'.

    Was '8:00 AM'. Every generated activity written in that format rendered
    as a BLANK <input type="time"> on the day page, and sorted lexically
    below every 24-hour time. Display still shows 12-hour via |to_12hr.
    """
    return "%02d:%02d" % divmod(int(mins) % (24 * 60), 60)


def _display_time(mins):
    """Minutes since midnight → human-readable 12-hour text, e.g. '8:00 AM'.

    For labels shown to people. Storage is always 24-hour HH:MM."""
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
    from models import HardCodedEvent, ShowHardCodedEvent
    hc_events = (HardCodedEvent.query.filter_by(active=True)
                 .order_by(HardCodedEvent.sort_order, HardCodedEvent.id).all())
    hc_disabled = {r.hce_id for r in
                   ShowHardCodedEvent.query.filter_by(show_id=show_id, enabled=False).all()}
    return render_template("schedule/overview.html", show=show, phases=PHASES,
                           hc_events=hc_events, hc_disabled=hc_disabled)


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
            sod        = f.get("sod", ""),
            eod        = f.get("eod", ""),
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
    """#32 — auto-generate a skeleton day for every date spanned by the show's
    production phases (falling back to Load-In..Strike), and attach a DayPhase
    membership for every phase covering each date, so overlapping phases both
    show (e.g. 'Lighting Prep D2' + 'Video Prep D1'). Non-destructive: adds
    missing days + missing memberships only — never wipes or duplicates."""
    show = Show.query.get_or_404(show_id)

    dated_phases = [p for p in show.phases if p.start_date and p.end_date]

    # Full span = union of every phase range + any Load-In / Strike.
    starts = [p.start_date for p in dated_phases]
    ends   = [p.end_date for p in dated_phases]
    if show.load_in_date:
        starts.append(show.load_in_date)
    if show.strike_date:
        ends.append(show.strike_date)
    if not starts or not ends:
        flash("Set production-phase date ranges (or Load-In and Strike) first.", "warning")
        return redirect(url_for("schedule.overview", show_id=show_id))
    span_start, span_end = min(starts), max(ends)

    existing = {d.date: d for d in show.days}
    with_templates = request.form.get("with_templates") == "1"

    PHASE_LABEL_MAP = {"Prep": "Setup", "Load In": "Load In", "Show": "Show Day",
                       "Strike": "Strike", "Custom": "Setup"}
    # date → phase_type for the single-string backward-compat `phase` label
    phase_lookup = {}
    for p in dated_phases:
        cur = p.start_date
        while cur <= p.end_date:
            phase_lookup.setdefault(cur, p.phase_type)
            cur += timedelta(days=1)

    added = 0
    current = span_start
    while current <= span_end:
        if current not in existing:
            raw = phase_lookup.get(current)
            if raw and raw in PHASE_LABEL_MAP:
                phase_label, phase_type = PHASE_LABEL_MAP[raw], raw
            elif show.load_in_date and current == show.load_in_date:
                phase_label, phase_type = "Load In", "Load In"
            elif show.strike_date and current == show.strike_date:
                phase_label, phase_type = "Strike", "Strike"
            elif show.show_start and show.show_end and show.show_start <= current <= show.show_end:
                phase_label, phase_type = "Show Day", "Show"
            else:
                phase_label, phase_type = "Setup", "Load In"

            day = ScheduleDay(show_id=show_id, date=current, phase=phase_label)
            db.session.add(day)
            db.session.flush()
            existing[current] = day

            if with_templates:
                tpl = _get_template_by_phase(phase_type)
                if tpl:
                    for i, (t, desc) in enumerate(tpl.activities):
                        db.session.add(ScheduleActivity(
                            day_id=day.id, time=t, description=desc,
                            sort_order=(i + 1) * 10))
            added += 1
        current += timedelta(days=1)

    db.session.flush()

    # #32 — attach DayPhase memberships for every phase covering each date,
    # numbering each phase's own days from 1 (so a date can be Lighting Prep
    # Day 2 AND Video Prep Day 1 at once). Skips memberships already present.
    memberships = 0
    for p in dated_phases:
        idx = 0
        cur = p.start_date
        while cur <= p.end_date:
            idx += 1
            day = existing.get(cur)
            if day is not None and not DayPhase.query.filter_by(
                    day_id=day.id, phase_id=p.id).first():
                db.session.add(DayPhase(day_id=day.id, phase_id=p.id, day_index=idx))
                memberships += 1
            cur += timedelta(days=1)

    db.session.commit()
    msg = f"{added} day(s) generated."
    if memberships:
        msg += f" {memberships} phase membership(s) attached."
    flash(msg, "success")
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
            .order_by(*crew_order_by())
            .all()
        )
        # The dropdown lists people in ROSTER order, same as the crew calls
        # themselves — two different orders for the same show reads as a bug.
        _idx = roster_index(show.id)
        crew_members.sort(key=lambda cm: _idx.get(cm.id, 10 ** 9))
    else:
        # No assignments yet — show everyone so the day editor still works
        crew_members = (
            db.session.query(CrewMember).filter_by(active=True)
            .outerjoin(Position, CrewMember.position_id == Position.id)
            .order_by(*crew_order_by())
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
    # Sort unlinked chronologically. NOT a string compare: times are free-form
    # display text, so "1:00 PM" would sort after "18:00".
    oss_unlinked.sort(key=lambda e: (sort_minutes(e.effective_time),
                                     e.sort_order or 0))

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

    # Who is ALREADY on a crew call today, for the wizard's double-booking
    # flag. Jason, 2026-08-12: flag only a NAMED person from a COMPANY.
    #
    # Local labour is the reason for the rule. An Encore-style row is a called
    # POSITION rather than a person — often several of them, often the same
    # position twice — so seeing it on two calls is normal work, not a
    # mistake, and flagging it would cry wolf on the majority of rows. The
    # test is `is_unnamed_slot`, the strict one that already drives name
    # substitution, plus a company: exactly "names and companies".
    #
    # When the LOCAL CREW section lands this is the one place to repoint.
    already_called = {}
    for act in day.activities:
        if not is_crew_start(act.description):
            continue
        for row in act.crew_rows:
            if row.is_group_header or not row.crew_member_id:
                continue
            cm_row = row.crew_member
            if cm_row is None or cm_row.is_unnamed_slot or not cm_row.company_id:
                continue
            already_called.setdefault(row.crew_member_id, []).append(
                act.time or "an untimed call")

    # Show crew grouped by company for the Create Crew Call wizard.
    #
    # ROSTER ORDER THROUGHOUT — Jason, 2026-08-12. `crew_members` above is
    # already sorted by `roster_index`, so iterating it keeps each company's
    # people in roster order. The GROUPS are then ordered by where their first
    # person sits in the roster rather than alphabetically, so the whole list
    # reads top to bottom in exactly the order the crew call itself renders.
    # Alphabetical companies would have interleaved against the roster and
    # given the same names two different orders on one page, which is the
    # thing `crew_ordering` exists to prevent.
    _roster_idx = roster_index(show.id)
    crew_by_company, _first_seen = {}, {}
    for pos, cm in enumerate(crew_members):
        key = cm.company.name if cm.company else "No Company"
        crew_by_company.setdefault(key, []).append(cm)
        _first_seen.setdefault(key, _roster_idx.get(cm.id, 10 ** 9 + pos))
    crew_by_company = sorted(crew_by_company.items(),
                             key=lambda kv: (_first_seen[kv[0]], kv[0]))

    from hardcoded_service import overlay_for_day, hidden_for_day
    hc_overlay, hc_missing_anchor = overlay_for_day(day)
    hc_hidden = hidden_for_day(day)

    # Breaks overhaul: only read for shows switched over, so every other show
    # renders exactly as it did before.
    # Breaks are EDITED on their crew call and READ as one row per period
    # (Jason, 2026-08-11), so the page needs both shapes:
    #   breaks_by_crew_call — the editor, folded into the CREW START card
    #   break_periods       — the timeline rows, grouped across crew groups
    # breaks_by_activity stays only so a break's own activity can be skipped
    # where it would otherwise render as an ordinary event.
    breaks_by_activity, day_meal_services = {}, []
    breaks_by_crew_call, break_periods = {}, []
    break_link_choices = {}
    if show.uses_new_breaks:
        from models import CrewBreak
        from breaks import group_breaks  # noqa: F811
        day_act_ids = {a.id for a in day.activities}
        on_this_day = []
        for cb in CrewBreak.query.filter_by(show_id=show.id).all():
            breaks_by_activity[cb.activity_id] = cb
            if cb.activity_id in day_act_ids:
                on_this_day.append(cb)
                breaks_by_crew_call.setdefault(cb.crew_call_id, []).append(cb)
        for rows in breaks_by_crew_call.values():
            rows.sort(key=lambda b: (b.start_minute if b.start_minute is not None
                                     else 10 ** 6, b.id or 0))
        break_periods = group_breaks(on_this_day)
        # Services on this day that nothing feeds yet. Offered ONLY where
        # there is a choice — a permanently mounted service picker is what
        # made this page unusable the first time round.
        import break_linking
        for cb in on_this_day:
            if cb.meal_service_id:
                continue
            choices = [{"svc": svc,
                        "suggested": break_linking.is_suggested(cb, svc)}
                       for svc in break_linking.candidates_for_break(cb)]
            if choices:
                break_link_choices[cb.id] = choices
    # Outside the switch: a standing beverage service only reads a day and
    # computes, changes no stored value, and belongs on every show's schedule.
    day_meal_services = (MealService.query
                         .filter_by(show_id=show.id, schedule_day_id=day.id)
                         .order_by(MealService.sort_order, MealService.id)
                         .all())

    # A break activity is drawn inside its period row, so it is not a timeline
    # row of its own — and not an anchor for anything either.
    visible_acts = [a for a in day.ordered_activities
                    if a.id not in breaks_by_activity]
    # Standing beverage touchpoints are real events on the schedule and are
    # computed on every read, so they follow SOD and EOD instead of going
    # stale. Placed the same way recurring events are.
    from beverage_service import overlay_for_day as _beverage_overlay
    bev_overlay = _beverage_overlay(day, day_meal_services)

    # ONE stream, placed once. Recurring events, beverage touchpoints and
    # break periods used to be placed and rendered as three separate lists, so
    # everything landing in the same gap came out grouped by TYPE — a 12:00
    # lunch drawing after a 15:00 beverage refresh, because breaks came after
    # beverages in the markup. A day is one timeline; it sorts by the clock.
    # SOD and EOD are rows on this stream too, derived from Day Settings on
    # every read. They replaced the hand-typed EOD WRAP activity, which was
    # a second copy of a number the day already held and drifted from it.
    from day_anchors import overlay_for_day as _anchor_overlay
    anchor_overlay = _anchor_overlay(day)

    timeline = (
        [{"kind": "recurring", "sort_min": hc.get("sort_min") or 0, "item": hc}
         for hc in hc_overlay]
        + [{"kind": "beverage", "sort_min": b["sort_min"], "item": b}
           for b in bev_overlay]
        + [{"kind": "break", "sort_min": p["minute"] or 0, "item": p}
           for p in break_periods]
        + [{"kind": "anchor", "sort_min": a["sort_min"], "item": a}
           for a in anchor_overlay]
    )
    extras_before, extras_after = _place_recurring(day, timeline, visible_acts)

    # Note 4: people in the Crew Database who are NOT yet on this show, offered
    # in the add-to-roster modal so the common case is one click, not retyping
    # someone who already exists.
    off_roster_crew = (db.session.query(CrewMember)
                       .filter(CrewMember.active == True,
                               ~CrewMember.id.in_(assigned_ids or [-1]))
                       .order_by(*crew_order_by()).all())

    return render_template("schedule/day.html", show=show, day=day,
                           positions=positions, crew_members=crew_members,
                           off_roster_crew=off_roster_crew,
                           all_companies=Company.query.order_by(Company.name).all(),
                           show_companies=show_companies,
                           phases=PHASES, crew_types=CREW_TYPES,
                           day_templates=_get_templates_dict(),
                           oss_by_activity=oss_by_activity,
                           oss_unlinked=oss_unlinked,
                           oss_types=ordered_oss_types,
                           oss_meta=SUB_SCHEDULE_META,
                           hardcoded_overlay=hc_overlay,
                           hardcoded_missing_anchor=hc_missing_anchor,
                           hardcoded_hidden=hc_hidden,
                           extras_before=extras_before, extras_after=extras_after,
                           breaks_by_activity=breaks_by_activity,
                           breaks_by_crew_call=breaks_by_crew_call,
                           break_periods=break_periods,
                           # The add-break choices for a crew call. Passed as
                           # the function so the template asks per call — the
                           # second meal only appears where somebody on THAT
                           # call is over 14 hours.
                           break_options=_break_options_resolver(
                               breaks_by_crew_call),
                           break_link_choices=break_link_choices,
                           day_meal_services=day_meal_services,
                           crew_by_company=crew_by_company,
                           already_called=already_called,
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
    # SOD/EOD replaced Call/Wrap in Day Settings. Only touch the legacy
    # call/wrap columns if the form still carries them, so saving day settings
    # never wipes the values Smart Breaks still reads (until it's re-anchored).
    if "call_time" in f:
        day.call_time = f.get("call_time", "")
    if "wrap_time" in f:
        day.wrap_time = f.get("wrap_time", "")
    # Field-present semantics (like call/wrap above): the Travel-info form
    # autosaves without SOD/EOD inputs, so only write them when the submitting
    # form actually carries them — never wipe on an unrelated partial save.
    if "sod" in f:
        day.sod = hhmm_or_blank(f.get("sod", ""))
    if "eod" in f:
        day.eod = hhmm_or_blank(f.get("eod", ""))
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
        sod        = src.sod,
        eod        = src.eod,
        phase      = src.phase,
        milestones = src.milestones,
        notes      = src.notes,
    )
    db.session.add(new_day)
    db.session.flush()
    act_map = {}   # #45 — src activity id -> cloned activity id, to re-link OSS/meals
    for act in src.activities:
        new_act = ScheduleActivity(
            day_id=new_day.id, time=act.time,
            description=act.description, notes=act.notes,
            sort_order=act.sort_order,
        )
        db.session.add(new_act)
        db.session.flush()
        act_map[act.id] = new_act.id
        for row in act.crew_rows:
            db.session.add(CrewRow(
                activity_id=new_act.id, sort_order=row.sort_order,
                is_group_header=row.is_group_header, group_label=row.group_label,
                qty=row.qty, hours=row.hours, position=row.position,
                position_id=row.position_id, crew_member_id=row.crew_member_id,
                name_override=row.name_override, crew_type=row.crew_type,
                notes=row.notes,
            ))

    # #45 — also clone the day's OSS department entries (Dock, F&B, venue lights,
    # etc.) and meal services, re-linking any activity reference to the clone.
    for e in SubScheduleEntry.query.filter_by(schedule_day_id=src.id).all():
        if e.type == "F&B":
            continue   # legacy F&B lives as meal services now — don't propagate
        db.session.add(SubScheduleEntry(
            show_id=show_id, schedule_day_id=new_day.id,
            activity_id=act_map.get(e.activity_id),
            type=e.type, time=e.time, activity=e.activity,
            duration_hrs=e.duration_hrs, count=e.count,
            notes=e.notes, sort_order=e.sort_order,
        ))
    for ms in MealService.query.filter_by(schedule_day_id=src.id).all():
        new_ms = MealService(
            show_id=show_id, schedule_day_id=new_day.id,
            activity_id=act_map.get(ms.activity_id),
            name=ms.name, kind=ms.kind, is_recurring=ms.is_recurring,
            notes=ms.notes, sort_order=ms.sort_order,
        )
        db.session.add(new_ms)
        db.session.flush()
        for loc in ms.locations:
            db.session.add(MealServiceLocation(
                meal_service_id=new_ms.id, location_name=loc.location_name,
                start_time=loc.start_time, end_time=loc.end_time,
                headcount=loc.headcount, notes=loc.notes, sort_order=loc.sort_order,
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


# ── Break generation — REMOVED 2026-08-12 ────────────────────────────────────
#
# `build_day_schedule` and `smart_breaks` both wrote breaks as ordinary
# ACTIVITIES labelled 'LUNCH BREAK — 30 min' / 'EOD WRAP'. That is the shape
# the 08-12 repair migrations spent the day undoing: a label is not a
# duration, and a break that is not attached to a crew call has no offset to
# mean anything against. Breaks are created on the crew call now, through
# `breaks.break_options_for` — one door, one definition of the add list.
#
# Jason's call, 2026-08-12: close BOTH doors rather than keep a legacy one.
# The old sidebar builder and the Smart Breaks quick tool are gone with them.


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

    row = CrewRow(
        activity_id=act_id, sort_order=last + 10,
        is_group_header=is_header,
        group_label=f.get("group_label", "") if is_header else "",
        header_level=int(f.get("header_level") or 1) if is_header else 1,
        company_id=int(f["header_company_id"]) if (is_header and
                                                   f.get("header_company_id")) else None,
        qty=int(f.get("qty", 1)) if not is_header else 0,
        hours=float(f.get("hours", 0)) if not is_header and f.get("hours") else None,
        position=f.get("position", "") if not is_header else "",
        position_id=int(f["position_id"]) if f.get("position_id") and not is_header else None,
        crew_member_id=crew_member_id,
        name_override=f.get("name_override", "") if not is_header else "",
        crew_type=f.get("crew_type", "Lead Crew") if not is_header else "",
        notes=f.get("notes", ""),
    )
    db.session.add(row)
    db.session.flush()

    # Note 3: a new person goes into the section that matches their company
    # (and department), not under whatever header happened to be last. Headers
    # themselves are always appended — the user placed them deliberately.
    if not is_header and crew_member_id:
        act = ScheduleActivity.query.get(act_id)
        others = [r for r in act.crew_rows if r.id != row.id]
        idx = insert_index_for(others, row.crew_member)
        others.insert(idx, row)
        renumber(others)

    db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/recurring/"
                   "<int:hce_id>/remove", methods=["POST"])
def remove_recurring_from_day(show_id, day_id, hce_id):
    """Hide one occurrence of a recurring event on one day of one show.

    Nothing is deleted — the definition is a series and this is a
    per-occurrence exception, so it can be restored. Keyed on the day's DATE
    because #32 regenerates ScheduleDay rows and an id-keyed suppression would
    evaporate or reattach to the wrong day.
    """
    day = ScheduleDay.query.get_or_404(day_id)
    if day.show_id != show_id or not day.date:
        abort(404)
    exists = HardCodedEventDayOff.query.filter_by(
        show_id=show_id, hce_id=hce_id, date=day.date).first()
    if exists is None:
        db.session.add(HardCodedEventDayOff(show_id=show_id, hce_id=hce_id,
                                            date=day.date))
        db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id,
                            day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/recurring/"
                   "<int:hce_id>/restore", methods=["POST"])
def restore_recurring_to_day(show_id, day_id, hce_id):
    """Put a removed occurrence back on this day."""
    day = ScheduleDay.query.get_or_404(day_id)
    if day.show_id != show_id or not day.date:
        abort(404)
    row = HardCodedEventDayOff.query.filter_by(
        show_id=show_id, hce_id=hce_id, date=day.date).first()
    if row is not None:
        db.session.delete(row)
        db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id,
                            day_id=day_id))


@schedule_bp.route("/<int:show_id>/travel-window", methods=["POST"])
def set_travel_window(show_id):
    """#31 — set the show's designated travel window from the Schedule Overview
    markers. marker='start'|'end'; day_id=<day> to set, or empty to clear."""
    show = Show.query.get_or_404(show_id)
    marker = request.form.get("marker")
    raw_day = (request.form.get("day_id") or "").strip()
    the_date = None
    if raw_day.isdigit():
        day = ScheduleDay.query.get(int(raw_day))
        if day and day.show_id == show_id:
            the_date = day.date
    if marker == "start":
        show.travel_window_start = the_date
    elif marker == "end":
        show.travel_window_end = the_date
    else:
        return jsonify({"ok": False, "error": "bad marker"}), 400
    db.session.commit()
    return jsonify({"ok": True, "marker": marker,
                    "date": the_date.isoformat() if the_date else None})


def _assign_crew_to_activity(activity, crew_ids, hours=None):
    """Put crew onto an activity. STRICTLY ADDITIVE. ONE definition.

    Returns ``(added, skipped)``. Somebody already on the call is skipped, not
    duplicated and not overwritten. The caller commits.

    Shared by the Create Crew Call wizard and the older bulk-assign pop-up so
    the two cannot drift on what "assign" means — a second copy of this is how
    one door starts overwriting rows the other leaves alone.
    """
    sort_order = db.session.query(
        db.func.max(CrewRow.sort_order)).filter_by(
            activity_id=activity.id).scalar() or 0
    added = skipped = 0
    for cm in CrewMember.query.filter(CrewMember.id.in_(crew_ids)).all():
        if CrewRow.query.filter_by(activity_id=activity.id,
                                   crew_member_id=cm.id).first():
            skipped += 1
            continue
        sort_order += 10
        db.session.add(CrewRow(
            activity_id=activity.id,
            crew_member_id=cm.id,
            position=cm.position.title if cm.position else "",
            position_id=cm.position_id,
            crew_type="Lead Crew",
            qty=1,
            hours=hours,
            sort_order=sort_order,
        ))
        added += 1
    return added, skipped


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/crew-call/create",
                   methods=["POST"])
def create_crew_call(show_id, day_id):
    """Create a crew call, put its crew on it, and hang its breaks off it.

    Replaces the Bulk Assign Crew pop-up, which could only fill a CREW START
    that already existed — so the actual job (make the call, feed the people
    on it) was three separate errands in two places.

    ORDER MATTERS and is the reason this is one route rather than three:

      1. the call, because a break's offset is meaningless without it;
      2. the crew, because `breaks.needs_second_meal` reads their hours — do
         this after the breaks and the +11:00 second meal can never appear;
      3. the breaks, through `_break_edit.create_break`, which is the same
         path the add-a-break button uses.

    Breaks come from `breaks.break_options_for` and nowhere else. Nothing here
    invents a label or a duration; that is what the removed day-level builder
    did, and it is why MCDC26 has 21 breaks stuck at 60 minutes.
    """
    # Imported here, not at module scope: _break_edit imports from breaks and
    # models at import time and schedule.py is loaded first.
    from routes._break_edit import create_break

    show = Show.query.get_or_404(show_id)
    day = ScheduleDay.query.get_or_404(day_id)
    f = request.form

    time = hhmm_or_blank(f.get("time"))
    if not time:
        flash("A crew call needs a start time.", "warning")
        return redirect(url_for("schedule.day_detail", show_id=show_id,
                                day_id=day_id))

    # The description must still READ as a crew start — `is_crew_start` is the
    # one test five other places use to find these, and a call it cannot see
    # is a call with no breaks, no headcount and no line on the master.
    desc = (f.get("description") or "").strip().upper() or "CREW START"
    if not is_crew_start(desc):
        desc = f"CREW START — {desc}"

    try:
        hours = float(f.get("hours") or 0) or None
    except (TypeError, ValueError):
        hours = None

    last = db.session.query(db.func.max(ScheduleActivity.sort_order)).filter_by(
        day_id=day_id).scalar() or 0
    call = ScheduleActivity(day_id=day.id, time=time, description=desc,
                            sort_order=last + 10)
    db.session.add(call)
    db.session.flush()

    assigned_ids = {a.crew_member_id for a in show.crew_assignments}
    wanted = [int(x) for x in f.getlist("crew_member_ids") if x.isdigit()]
    ids = [i for i in wanted if i in assigned_ids]
    added = 0
    if ids:
        added, _ = _assign_crew_to_activity(call, ids, hours=hours)
        db.session.flush()

    # The meal length moves the afternoon coffee — 30 minutes puts it at
    # +8:00, an hour at +8:30 — because Jason's rule times a coffee from the
    # END of the meal. Passed explicitly: the call has no breaks yet, so
    # there is nothing to read it off.
    try:
        meal_minutes = int(f.get("meal_minutes") or DEFAULT_MEAL_MINUTES)
    except (TypeError, ValueError):
        meal_minutes = DEFAULT_MEAL_MINUTES
    if meal_minutes not in MEAL_MINUTES_CHOICES:
        meal_minutes = DEFAULT_MEAL_MINUTES

    made = 0
    if f.get("add_breaks") and show.uses_new_breaks:
        for opt in break_options_for(call, meal_minutes):
            if create_break(show, day, call, opt["offset"],
                            duration=opt["duration"], kind=opt["kind"],
                            label=opt["label"],
                            meal_minutes=meal_minutes) is not None:
                made += 1

    db.session.commit()

    msg = f"Crew call created at {call.time}."
    if added:
        msg += f" {added} crew on it."
    if made:
        msg += (f" {made} break{'' if made == 1 else 's'} added — set whether "
                "the meal is provided.")
    elif f.get("add_breaks") and not show.uses_new_breaks:
        msg += " Breaks were not added: this show is still on the old model."
    flash(msg, "success")
    return redirect(url_for("schedule.day_detail", show_id=show_id,
                            day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/bulk-assign-crew", methods=["POST"])
def bulk_assign_crew(show_id, day_id):
    """#38 — bulk-assign show crew to a Crew Start event via the pop-up.

    STRICTLY ADDITIVE: never removes or overwrites existing crew rows. Crew
    already on the target event are skipped (no duplicate row). Only crew
    actually assigned to this show are eligible. Call time is inherited from
    the Crew Start event they're dropped into (its time), which is what feeds
    the master schedule (#39).
    """
    show = Show.query.get_or_404(show_id)
    raw_act = (request.form.get("activity_id") or "").strip()
    if not raw_act.isdigit():
        flash("Pick which Crew Start to assign the crew into.", "warning")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))

    activity = ScheduleActivity.query.get_or_404(int(raw_act))
    if activity.day_id != day_id:
        flash("That event isn't on this day.", "danger")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))

    # Eligible = selected AND actually assigned to this show.
    assigned_ids = {a.crew_member_id for a in show.crew_assignments}
    wanted = [int(x) for x in request.form.getlist("crew_member_ids") if x.isdigit()]
    ids = [i for i in wanted if i in assigned_ids]
    if not ids:
        flash("No crew selected.", "warning")
        return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))

    added, skipped = _assign_crew_to_activity(activity, ids)
    db.session.commit()

    when = activity.time or "the event"
    msg = f"Assigned {added} crew to {when}."
    if skipped:
        msg += f" ({skipped} already there — left as-is.)"
    flash(msg, "success" if added else "info")
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
    # Note 1 — section headers are editable: rename, nest, or bind to a company.
    if row.is_group_header:
        if "group_label" in f:
            row.group_label = (f.get("group_label") or "").strip() or None
        if "header_level" in f:
            try:
                row.header_level = 2 if int(f["header_level"]) == 2 else 1
            except (TypeError, ValueError):
                pass
        if "header_company_id" in f:
            v = (f.get("header_company_id") or "").strip()
            row.company_id = int(v) if v else None
    db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/crew/<int:row_id>/delete",
                   methods=["POST"])
def delete_crew_row(show_id, day_id, row_id):
    row = CrewRow.query.get_or_404(row_id)
    db.session.delete(row)
    db.session.commit()
    return redirect(url_for("schedule.day_detail", show_id=show_id, day_id=day_id))


@schedule_bp.route("/<int:show_id>/schedule/<int:day_id>/activities/"
                   "<int:act_id>/crew/reorder", methods=["POST"])
def reorder_crew_rows(show_id, day_id, act_id):
    """Body: ``{"ids": [row_id, ...]}`` in the new display order.

    Two things happen, and the second is the important one.

    The row order is stored so section MEMBERSHIP sticks — which header a row
    sits under is still a function of sort_order.

    Then, per Jason's decision on 2026-08-11, the sequence of PEOPLE is pushed
    back into the show roster. Dragging a name in one crew call reorders the
    roster, so every other crew call in the show follows. That is what keeps a
    single order in the system instead of one per call, which is what drifted
    before.
    """
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids") or []
    moved_header = bool(payload.get("moved_header"))
    rows = {r.id: r for r in CrewRow.query.filter_by(activity_id=act_id).all()}
    ordered = [rows[i] for i in ids if i in rows]
    if len(ordered) != len(rows):
        return jsonify(ok=False, error="Row list did not match the activity."), 400

    renumber(ordered)

    # A SECTION move is local to this crew call. Sections are per-activity;
    # the roster is show-wide. Writing back on a header drag reordered the
    # roster from the resulting flat sequence and scrambled the order on every
    # other crew call in the show — reported live on 2026-08-11.
    reordered = 0
    if not moved_header:
        member_ids = [r.crew_member_id for r in ordered
                      if not r.is_group_header and r.crew_member_id]
        apply_partial_order(show_id, member_ids)
        reordered = len(member_ids)

    db.session.commit()
    return jsonify(ok=True, reordered=reordered, roster_written=not moved_header)


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

    # #46 — names render live (row.display_name -> crew_member.full_name), but the
    # sheet opens in a new tab / is printed, so a cached copy showed stale names
    # after an edit. Force a fresh fetch every time so name changes always show.
    resp = make_response(render_template("schedule/call_sheet.html",
                           show=show, day=day,
                           crew_lines=crew_lines,
                           by_dept=dict(sorted(by_dept.items())),
                           total_crew=total_crew,
                           conflicts=len(conflicts) > 0))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


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
