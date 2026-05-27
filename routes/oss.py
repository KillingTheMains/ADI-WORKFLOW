"""
OSS (On-Site Schedule) blueprint.

One OSS page per show. Tabs:
  * Master Schedule  — all entries across departments, sorted chronologically
  * One tab per department in SUB_SCHEDULE_TYPES (Dock, Haze, F&B, etc.)
  * Show Book        — the printable production book (moved from schedule.py)

URL space (registered with url_prefix="/shows"):
  GET   /<show_id>/oss                  → hub (default tab = master)
  GET   /<show_id>/oss?tab=<key>        → hub with a specific tab active
  POST  /<show_id>/oss/add              → create entry, redirect back to its tab
  POST  /<show_id>/oss/<entry_id>/edit  → update entry
  POST  /<show_id>/oss/<entry_id>/delete→ delete entry
  GET   /<show_id>/oss/show-book        → printable show book
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import (
    Show, ScheduleDay, ScheduleActivity, SubScheduleEntry,
    SUB_SCHEDULE_TYPES, SUB_SCHEDULE_META, is_meal_break,
    ShowCommChannel, CrewCommAssignment, ShowCrewAssignment,
    CrewMember, COM_PACK_TYPES, COM_PACK_BRANDS,
    RadioChannel, COM_PACK_BRAND_LIMITS, COM_PACK_HARD_CAP, RADIO_CHANNEL_SLOTS,
)

oss_bp = Blueprint("oss", __name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _redirect_after_change(show_id, entry_type=None, prefer_next=True):
    """
    Return a redirect target. If the form (or query) supplied a ?next=, use
    that — this lets the day editor send users back to where they were.
    Otherwise fall back to the OSS hub on the right tab.
    """
    if prefer_next:
        nxt = request.form.get("next") or request.args.get("next")
        if nxt and nxt.startswith("/"):  # cheap open-redirect guard
            return redirect(nxt)
    return redirect(url_for("oss.oss_hub", show_id=show_id,
                            tab=_tab_safe(entry_type)))

def _ordered_types():
    """SUB_SCHEDULE_TYPES sorted by the `sort` field in SUB_SCHEDULE_META."""
    return sorted(SUB_SCHEDULE_TYPES, key=lambda t: SUB_SCHEDULE_META.get(t, {}).get("sort", 99))


def _tab_safe(tab_key):
    """Validate a tab key, falling back to 'master'."""
    if tab_key == "master" or tab_key in SUB_SCHEDULE_TYPES:
        return tab_key
    return "master"


def _entries_by_type(show_id):
    """
    Return ({type: [entries]}, [entries_in_master_order]).
    Sorted by day date, then effective_time (which respects linked activities),
    then sort_order. The effective_time sort is done in Python because it's a
    @property that can come from either entry.time or entry.linked_activity.time.
    """
    entries = (
        SubScheduleEntry.query
        .filter_by(show_id=show_id)
        .join(ScheduleDay, SubScheduleEntry.schedule_day_id == ScheduleDay.id)
        .all()
    )
    # Python sort: empty/missing times sort last within their day.
    def _sort_key(e):
        date_key = e.schedule_day.date if e.schedule_day else None
        t        = e.effective_time or "99:99"
        return (date_key, t, e.sort_order or 0)
    entries.sort(key=_sort_key)

    grouped = {t: [] for t in SUB_SCHEDULE_TYPES}
    for e in entries:
        grouped.setdefault(e.type, []).append(e)
    return grouped, entries


# ── Main hub page ────────────────────────────────────────────────────────────

@oss_bp.route("/<int:show_id>/oss")
def oss_hub(show_id):
    show = Show.query.get_or_404(show_id)
    tab  = _tab_safe(request.args.get("tab", "master"))

    grouped, all_entries = _entries_by_type(show_id)

    # Map of day_id -> list of activity dicts, for the JS-driven activity
    # dropdown in the templates. Built server-side so we don't need AJAX.
    activities_by_day = {}
    for d in show.days:
        activities_by_day[d.id] = [
            {
                "id":          a.id,
                "time":        a.time or "",
                "description": a.description or "",
                # The label shown in the dropdown
                "label":       (f"{a.time}  ·  " if a.time else "") + (a.description or ""),
            }
            for a in d.activities
        ]

    # Meal-break activities across the whole show that don't have an F&B
    # linked. We surface the count as a badge on the F&B tab and a short
    # list of missing items on the F&B tab body.
    fb_linked_activity_ids = {
        e.activity_id for e in all_entries if e.type == "F&B" and e.activity_id
    }
    missing_fb = []
    for d in show.days:
        for act in d.activities:
            if is_meal_break(act) and act.id not in fb_linked_activity_ids:
                missing_fb.append({
                    "day":         d,
                    "activity":    act,
                    "day_url":     url_for("schedule.day_detail",
                                           show_id=show.id, day_id=d.id),
                })

    # ── Wristbands tab data ─────────────────────────────────────────────
    # Simple: just pass show.days. The ScheduleDay model has the helpers
    # (computed_crew_count / effective_crew_count / total_wristbands).
    wristband_grand_total = sum(d.total_wristbands for d in show.days) if show.days else 0

    # ── COMS tab data ───────────────────────────────────────────────────
    coms_channels    = (ShowCommChannel.query
                        .filter_by(show_id=show_id)
                        .order_by(ShowCommChannel.sort_order, ShowCommChannel.id)
                        .all())
    radio_channels   = _ensure_radio_channels(show_id)
    coms_assignments = _build_coms_assignments(show)

    # Summary counts for the COMS header
    coms_summary = {
        "radios":    sum(1 for a in coms_assignments if a["assignment"].radio),
        "wireless":  sum(1 for a in coms_assignments if a["assignment"].headset
                         and a["assignment"].pack_type == "Wireless"),
        "wired":     sum(1 for a in coms_assignments if a["assignment"].headset
                         and a["assignment"].pack_type == "Wired"),
        "no_comms":  sum(1 for a in coms_assignments if not a["assignment"].radio
                         and not a["assignment"].headset),
    }

    return render_template(
        "oss/index.html",
        show                  = show,
        active_tab            = tab,
        ordered_types         = _ordered_types(),
        meta                  = SUB_SCHEDULE_META,
        grouped               = grouped,
        all_entries           = all_entries,
        days                  = show.days,
        activities_by_day     = activities_by_day,
        missing_fb            = missing_fb,
        wristband_grand_total = wristband_grand_total,
        coms_channels         = coms_channels,
        radio_channels        = radio_channels,
        coms_assignments      = coms_assignments,
        coms_summary          = coms_summary,
        com_pack_types        = COM_PACK_TYPES,
        com_pack_brands       = COM_PACK_BRANDS,
        com_pack_brand_limits = COM_PACK_BRAND_LIMITS,
        com_pack_hard_cap     = COM_PACK_HARD_CAP,
    )


def _ensure_radio_channels(show_id):
    """Return the show's 16 radio channels (creating them if missing)."""
    existing = (RadioChannel.query
                .filter_by(show_id=show_id)
                .order_by(RadioChannel.slot)
                .all())
    have_slots = {c.slot for c in existing}
    if len(have_slots) < RADIO_CHANNEL_SLOTS:
        for slot in range(1, RADIO_CHANNEL_SLOTS + 1):
            if slot not in have_slots:
                db.session.add(RadioChannel(show_id=show_id, slot=slot))
        db.session.commit()
        existing = (RadioChannel.query
                    .filter_by(show_id=show_id)
                    .order_by(RadioChannel.slot)
                    .all())
    return existing


def _build_coms_assignments(show):
    """
    Return a list of {crew_member, assignment} dicts, one per crew member
    assigned to the show. Auto-create CrewCommAssignment rows on demand so
    the table always shows every assigned crew member.
    """
    rows = (
        db.session.query(CrewMember, ShowCrewAssignment)
        .join(ShowCrewAssignment, ShowCrewAssignment.crew_member_id == CrewMember.id)
        .filter(ShowCrewAssignment.show_id == show.id)
        .order_by(CrewMember.last_name, CrewMember.first_name)
        .all()
    )
    # Existing comm assignments for this show, keyed by crew_member_id
    existing = {a.crew_member_id: a
                for a in CrewCommAssignment.query.filter_by(show_id=show.id).all()}

    out = []
    created = False
    for crew, _show_assign in rows:
        a = existing.get(crew.id)
        if a is None:
            a = CrewCommAssignment(show_id=show.id, crew_member_id=crew.id)
            db.session.add(a)
            created = True
        out.append({"crew_member": crew, "assignment": a})
    if created:
        db.session.commit()
    return out


# ── Create / update / delete entries ─────────────────────────────────────────

def _apply_form_to_entry(entry, form):
    """Common write path for both add and edit. Returns (ok, error_message_or_None)."""
    type_key = form.get("type", "").strip()
    if type_key not in SUB_SCHEDULE_TYPES:
        return False, "Unknown OSS section."

    try:
        schedule_day_id = int(form.get("schedule_day_id"))
    except (TypeError, ValueError):
        return False, "A schedule day is required."

    day = ScheduleDay.query.get(schedule_day_id)
    if not day or day.show_id != entry.show_id:
        return False, "Selected day does not belong to this show."

    # Optional activity link — must belong to the chosen day
    activity_id = None
    raw_act = (form.get("activity_id") or "").strip()
    if raw_act:
        try:
            activity_id = int(raw_act)
        except ValueError:
            return False, "Invalid activity selection."
        act = ScheduleActivity.query.get(activity_id)
        if not act or act.day_id != schedule_day_id:
            return False, "Selected activity does not belong to the chosen day."

    entry.type            = type_key
    entry.schedule_day_id = schedule_day_id
    entry.activity_id     = activity_id
    # When linked to an activity, clear the freeform time — single source
    # of truth lives on the activity. When unlinked, use the form value.
    entry.time            = None if activity_id else (form.get("time", "").strip() or None)
    entry.activity        = form.get("activity", "").strip() or None
    entry.notes           = form.get("notes", "").strip() or None

    # numeric fields — accept blanks
    dur = form.get("duration_hrs", "").strip()
    try:
        entry.duration_hrs = float(dur) if dur else None
    except ValueError:
        return False, "Duration must be a number."

    cnt = form.get("count", "").strip()
    try:
        entry.count = int(cnt) if cnt else None
    except ValueError:
        return False, "Count must be a whole number."

    return True, None


@oss_bp.route("/<int:show_id>/oss/add", methods=["POST"])
def add_entry(show_id):
    show = Show.query.get_or_404(show_id)
    if not show.days:
        flash("Add at least one schedule day before creating OSS entries.", "warning")
        return redirect(url_for("schedule.overview", show_id=show_id))

    entry = SubScheduleEntry(show_id=show_id)
    ok, err = _apply_form_to_entry(entry, request.form)
    if not ok:
        flash(err, "danger")
        return _redirect_after_change(show_id, entry_type=request.form.get("type"))

    # default sort_order = current count for that type
    entry.sort_order = SubScheduleEntry.query.filter_by(
        show_id=show_id, type=entry.type).count() * 10

    db.session.add(entry)
    db.session.commit()
    flash(f"Added {entry.type} entry.", "success")
    return _redirect_after_change(show_id, entry_type=entry.type)


@oss_bp.route("/<int:show_id>/oss/<int:entry_id>/edit", methods=["POST"])
def edit_entry(show_id, entry_id):
    entry = SubScheduleEntry.query.get_or_404(entry_id)
    if entry.show_id != show_id:
        flash("Entry does not belong to this show.", "danger")
        return redirect(url_for("oss.oss_hub", show_id=show_id))

    ok, err = _apply_form_to_entry(entry, request.form)
    if not ok:
        flash(err, "danger")
        return _redirect_after_change(show_id, entry_type=entry.type)

    db.session.commit()
    flash("Entry updated.", "success")
    return _redirect_after_change(show_id, entry_type=entry.type)


@oss_bp.route("/<int:show_id>/oss/<int:entry_id>/delete", methods=["POST"])
def delete_entry(show_id, entry_id):
    entry = SubScheduleEntry.query.get_or_404(entry_id)
    if entry.show_id != show_id:
        flash("Entry does not belong to this show.", "danger")
        return redirect(url_for("oss.oss_hub", show_id=show_id))

    tab = entry.type
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted.", "success")
    return _redirect_after_change(show_id, entry_type=tab)


# ── Show Book (printable) ────────────────────────────────────────────────────

@oss_bp.route("/<int:show_id>/oss/show-book")
def show_book(show_id):
    show = Show.query.get_or_404(show_id)
    return render_template("oss/show_book.html", show=show)



# ── Wristbands tab — batch save ──────────────────────────────────────────────

@oss_bp.route("/<int:show_id>/oss/wristbands/save", methods=["POST"])
def wristbands_save(show_id):
    """
    Save extras / override / notes for every day of the show in one POST.
    Form fields are keyed by day id:
        override_<day_id>, extras_<day_id>, notes_<day_id>
    Blanks clear the value (NULL for ints, empty for notes).
    """
    show = Show.query.get_or_404(show_id)
    for day in show.days:
        raw_override = (request.form.get(f"override_{day.id}") or "").strip()
        raw_extras   = (request.form.get(f"extras_{day.id}")   or "").strip()
        raw_notes    = (request.form.get(f"notes_{day.id}")    or "").strip()
        try:
            day.wristband_crew_override = int(raw_override) if raw_override else None
        except ValueError:
            flash(f"Bad override value on {day.day_header}; skipped.", "danger")
        try:
            day.wristband_extras = int(raw_extras) if raw_extras else None
        except ValueError:
            flash(f"Bad extras value on {day.day_header}; skipped.", "danger")
        day.wristband_notes = raw_notes or None
    db.session.commit()
    flash("Wristbands saved.", "success")
    return redirect(url_for("oss.oss_hub", show_id=show_id, tab="Wristbands"))


# ── COMS tab — channel CRUD ──────────────────────────────────────────────────

@oss_bp.route("/<int:show_id>/oss/coms/channels/add", methods=["POST"])
def coms_channel_add(show_id):
    """Add a single channel to the show's channel list."""
    show = Show.query.get_or_404(show_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Channel name is required.", "danger")
        return redirect(url_for("oss.oss_hub", show_id=show_id, tab="COMS"))
    if len(name) > 50:
        name = name[:50]
    last_sort = (db.session.query(db.func.max(ShowCommChannel.sort_order))
                 .filter_by(show_id=show_id).scalar() or 0)
    ch = ShowCommChannel(show_id=show_id, name=name, sort_order=last_sort + 10)
    db.session.add(ch)
    db.session.commit()
    flash(f"Added channel '{name}'.", "success")
    return redirect(url_for("oss.oss_hub", show_id=show_id, tab="COMS"))


@oss_bp.route("/<int:show_id>/oss/coms/channels/<int:channel_id>/delete", methods=["POST"])
def coms_channel_delete(show_id, channel_id):
    """Delete a channel and strip it from any crew assignment that references it."""
    ch = ShowCommChannel.query.get_or_404(channel_id)
    if ch.show_id != show_id:
        flash("Channel does not belong to this show.", "danger")
        return redirect(url_for("oss.oss_hub", show_id=show_id, tab="COMS"))
    name = ch.name
    # Strip this channel ID out of any assignment's channel_ids CSV
    deleted_id = str(channel_id)
    for a in CrewCommAssignment.query.filter_by(show_id=show_id).all():
        if not a.channel_ids:
            continue
        ids = [s.strip() for s in a.channel_ids.split(",") if s.strip()]
        ids = [s for s in ids if s != deleted_id]
        a.channel_ids = ",".join(ids) if ids else None
    db.session.delete(ch)
    db.session.commit()
    flash(f"Removed channel '{name}'.", "success")
    return redirect(url_for("oss.oss_hub", show_id=show_id, tab="COMS"))


# ── COMS tab — batch save crew assignments ───────────────────────────────────

@oss_bp.route("/<int:show_id>/oss/coms/save", methods=["POST"])
def coms_save(show_id):
    """
    Batch-save every crew member's comm assignment. Form fields are keyed
    by assignment id:
        radio_<aid>, headset_<aid>, pack_type_<aid>, pack_brand_<aid>,
        pack_brand_other_<aid>, notes_<aid>, channels_<aid> (multi-value)
    Missing checkboxes mean False (HTML form semantics).
    """
    show = Show.query.get_or_404(show_id)
    assignments = CrewCommAssignment.query.filter_by(show_id=show_id).all()
    for a in assignments:
        aid    = str(a.id)
        a.radio   = bool(request.form.get(f"radio_{aid}"))
        a.headset = bool(request.form.get(f"headset_{aid}"))
        # Pack details only when headset is checked; clear otherwise so the
        # form state stays consistent.
        if a.headset:
            pt = (request.form.get(f"pack_type_{aid}") or "").strip()
            pb = (request.form.get(f"pack_brand_{aid}") or "").strip()
            po = (request.form.get(f"pack_brand_other_{aid}") or "").strip()
            a.pack_type        = pt if pt in COM_PACK_TYPES else None
            a.pack_brand       = pb if pb in COM_PACK_BRANDS else None
            a.pack_brand_other = po or None
            # The checkbox-grid UI submits an ordered CSV of channel ids in
            # channels_ordered_<aid> (key 1 first, then key 2, ...). We cap
            # at COM_PACK_HARD_CAP defensively in case JS is bypassed.
            raw = (request.form.get(f"channels_ordered_{aid}") or "").strip()
            picked_ids = []
            for p in raw.split(","):
                p = p.strip()
                if p.isdigit() and int(p) not in picked_ids:
                    picked_ids.append(int(p))
            picked_ids = picked_ids[:COM_PACK_HARD_CAP]
            a.channel_id_list = picked_ids
        else:
            a.pack_type = None
            a.pack_brand = None
            a.pack_brand_other = None
            a.channel_ids = None
        a.notes = (request.form.get(f"notes_{aid}") or "").strip() or None
    db.session.commit()
    flash("COMS assignments saved.", "success")
    return redirect(url_for("oss.oss_hub", show_id=show_id, tab="COMS"))



# ── COMS tab — radio channel batch save ──────────────────────────────────────

@oss_bp.route("/<int:show_id>/oss/coms/radio/save", methods=["POST"])
def coms_radio_save(show_id):
    """
    Batch-save the names of the show's 16 radio channels. Form fields are
    keyed by the channel slot:  radio_name_<slot>
    """
    show = Show.query.get_or_404(show_id)
    channels = _ensure_radio_channels(show_id)   # also creates if missing
    for ch in channels:
        raw = (request.form.get(f"radio_name_{ch.slot}") or "").strip()
        ch.name = raw[:50] if raw else None
    db.session.commit()
    flash("Radio channel names saved.", "success")
    return redirect(url_for("oss.oss_hub", show_id=show_id, tab="COMS"))
