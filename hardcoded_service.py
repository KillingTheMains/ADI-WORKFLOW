"""
Hard-Coded Events — virtual overlay (#37 Phase 2).

Resolves the global HardCodedEvent definitions onto a specific day using that
day's SOD/EOD anchors. Nothing is stored: this is computed at render time, so
it's always in sync — change a definition or a day's SOD/EOD and the overlay
recomputes with no drift and nothing to migrate.

Per-show scope: an event applies to a show unless ShowHardCodedEvent says
enabled=False for it (default on).
"""
from models import HardCodedEvent, HardCodedEventDayOff, ShowHardCodedEvent
from time_utils import parse_minutes


def days_off_for(show_id, day_date):
    """ids of recurring events the user removed from THIS day of THIS show."""
    if not day_date:
        return set()
    return {r.hce_id for r in HardCodedEventDayOff.query
            .filter_by(show_id=show_id, date=day_date).all()}


def _parse(t_str):
    """'8:00 AM' / '19:00' / '7:30 PM' -> minutes since midnight; None on failure.

    Thin alias for time_utils.parse_minutes so the whole app shares one
    definition of how a time string is read.
    """
    return parse_minutes(t_str)


def _fmt(mins):
    """Minutes since midnight -> '8:00 AM' (matches the rest of the schedule UI)."""
    mins = int(mins) % (24 * 60)
    h, mn = divmod(mins, 60)
    ampm = 'AM' if h < 12 else 'PM'
    disp = h if h <= 12 else h - 12
    if disp == 0:
        disp = 12
    return f"{disp}:{mn:02d} {ampm}"


def applicable_events(show_id):
    """Active hard-coded events that apply to this show (default on; a per-show
    row with enabled=False turns one off), ordered for display."""
    active = (HardCodedEvent.query
              .filter_by(active=True)
              .order_by(HardCodedEvent.sort_order, HardCodedEvent.id).all())
    disabled = {r.hce_id for r in ShowHardCodedEvent.query
                .filter_by(show_id=show_id, enabled=False).all()}
    return [e for e in active if e.id not in disabled]


def _anchor_minutes(anchor, sod_m, eod_m):
    return sod_m if (anchor or "SOD") == "SOD" else eod_m


def overlay_for_day(day):
    """Computed hard-coded items for a day. Each is a dict:
        {name, department, time, end_time, sort_min, hardcoded: True}
    Events whose anchor time isn't set on the day are skipped. Returns
    (items, missing_anchor) where missing_anchor is True if some applicable
    events couldn't place because the day has no SOD/EOD yet.
    """
    if day is None:
        return [], False
    events = applicable_events(day.show_id)
    if not events:
        return [], False

    # Per-occurrence exceptions. A removal is subtracted at render, so editing
    # the definition still updates every occurrence that is still showing.
    removed = days_off_for(day.show_id, getattr(day, "date", None))
    if removed:
        events = [e for e in events if e.id not in removed]
        if not events:
            return [], False

    sod_m = _parse(getattr(day, "sod", None))
    eod_m = _parse(getattr(day, "eod", None))

    items, missing = [], False
    for e in events:
        base = _anchor_minutes(e.start_anchor, sod_m, eod_m)
        if base is None:
            missing = True
            continue
        start_m = base + (e.start_offset or 0)
        item = {
            "id": e.id,
            "name": e.name,
            "department": e.department,
            "time": _fmt(start_m),
            "end_time": None,
            "sort_min": start_m,
            "hardcoded": True,
        }
        if e.end_anchor:
            ebase = _anchor_minutes(e.end_anchor, sod_m, eod_m)
            if ebase is not None:
                item["end_time"] = _fmt(ebase + (e.end_offset or 0))
        items.append(item)

    items.sort(key=lambda x: x["sort_min"])
    return items, missing


def hidden_for_day(day):
    """Recurring events the user removed from this day, for the restore UI.

    A removal with no visible trace is a trap — the user has no way to undo
    something they cannot see. Returns the event objects so the day page can
    offer them back.
    """
    if day is None or not getattr(day, "date", None):
        return []
    removed = days_off_for(day.show_id, day.date)
    if not removed:
        return []
    return (HardCodedEvent.query
            .filter(HardCodedEvent.id.in_(removed))
            .order_by(HardCodedEvent.sort_order, HardCodedEvent.id).all())
