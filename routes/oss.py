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

    return render_template(
        "oss/index.html",
        show              = show,
        active_tab        = tab,
        ordered_types     = _ordered_types(),
        meta              = SUB_SCHEDULE_META,
        grouped           = grouped,
        all_entries       = all_entries,
        days              = show.days,
        activities_by_day = activities_by_day,
        missing_fb        = missing_fb,
    )


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
