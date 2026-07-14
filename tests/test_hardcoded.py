"""
Tests for Hard-Coded Events (#37) Phase 1 — the definitions table.
Model + offset parsing + create/edit/delete routes. Department values must be
exact SUB_SCHEDULE_TYPES keys (e.g. "Security", "F&B", "Dock").
"""
from routes.hardcoded import _parse_offset


def test_parse_offset():
    assert _parse_offset("-1:00") == -60
    assert _parse_offset("+0:30") == 30
    assert _parse_offset("0:30") == 30
    assert _parse_offset("") == 0
    assert _parse_offset(None) == 0
    assert _parse_offset("2") == 120            # bare number = hours
    assert _parse_offset("\u22121:00") == -60   # accepts a true minus sign


def test_model_labels(db):
    from models import HardCodedEvent
    ev = HardCodedEvent(name="Security", department="Security",
                        start_anchor="SOD", start_offset=-60,
                        end_anchor="EOD", end_offset=60)
    db.session.add(ev); db.session.commit()
    assert ev.start_label == "SOD \u22121:00"
    assert ev.end_label == "EOD +1:00"
    assert ev.is_range is True
    assert ev.start_offset_str == "-1:00"
    assert ev.end_offset_str == "+1:00"


def test_point_event_has_no_end(db):
    from models import HardCodedEvent
    ev = HardCodedEvent(name="Crew Beverage Set", department="F&B",
                        start_anchor="SOD", start_offset=-30)
    db.session.add(ev); db.session.commit()
    assert ev.is_range is False
    assert ev.end_label == ""


def test_add_route_creates_event(app, client, db):
    from models import HardCodedEvent
    r = client.post("/hard-coded-events/add", data={
        "name": "Security", "department": "Security",
        "start_anchor": "SOD", "start_offset": "-1:00",
        "end_anchor": "EOD", "end_offset": "+1:00",
    })
    assert r.status_code in (200, 302)
    ev = HardCodedEvent.query.filter_by(name="Security").first()
    assert ev is not None
    assert ev.department == "Security"
    assert ev.start_anchor == "SOD" and ev.start_offset == -60
    assert ev.end_anchor == "EOD" and ev.end_offset == 60
    assert ev.active is True


def test_add_route_blank_end_is_point_event(app, client, db):
    from models import HardCodedEvent
    client.post("/hard-coded-events/add", data={
        "name": "Beverage", "department": "F&B",
        "start_anchor": "SOD", "start_offset": "-0:30",
        "end_anchor": "", "end_offset": "",
    })
    ev = HardCodedEvent.query.filter_by(name="Beverage").first()
    assert ev.end_anchor is None and ev.end_offset is None
    assert ev.start_offset == -30


def test_add_route_invalid_department_ignored(app, client, db):
    from models import HardCodedEvent
    client.post("/hard-coded-events/add", data={
        "name": "Mystery", "department": "not-a-dept",
        "start_anchor": "SOD", "start_offset": "0:00",
    })
    ev = HardCodedEvent.query.filter_by(name="Mystery").first()
    assert ev.department is None


def test_edit_and_delete_routes(app, client, db):
    from models import HardCodedEvent
    ev = HardCodedEvent(name="Old", start_anchor="SOD", start_offset=0)
    db.session.add(ev); db.session.commit()
    ev_id = ev.id

    client.post(f"/hard-coded-events/{ev_id}/edit", data={
        "name": "New", "department": "Dock",
        "start_anchor": "EOD", "start_offset": "+2:00",
    })
    ev = HardCodedEvent.query.get(ev_id)
    assert ev.name == "New" and ev.department == "Dock"
    assert ev.start_anchor == "EOD" and ev.start_offset == 120

    client.post(f"/hard-coded-events/{ev_id}/delete", data={})
    assert HardCodedEvent.query.get(ev_id) is None


# ── Phase 2: virtual overlay + per-show toggle ───────────────────────────────
import datetime as dt


def _show_day(db, sod="8:00 AM", eod="10:00 PM"):
    from models import Show, ScheduleDay
    show = Show(name="HCE Show", code="HC26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 16), sod=sod, eod=eod)
    db.session.add(day); db.session.commit()
    return show, day


def test_overlay_resolves_range_times(db):
    from models import HardCodedEvent
    from hardcoded_service import overlay_for_day
    show, day = _show_day(db)
    db.session.add(HardCodedEvent(name="Security", department="Security",
                   start_anchor="SOD", start_offset=-60,
                   end_anchor="EOD", end_offset=60, active=True))
    db.session.commit()
    items, missing = overlay_for_day(day)
    assert missing is False
    sec = next(i for i in items if i["name"] == "Security")
    assert sec["time"] == "7:00 AM"       # SOD 8:00 - 1:00
    assert sec["end_time"] == "11:00 PM"  # EOD 10:00 + 1:00
    assert sec["department"] == "Security"


def test_overlay_point_event_has_no_end(db):
    from models import HardCodedEvent
    from hardcoded_service import overlay_for_day
    show, day = _show_day(db)
    db.session.add(HardCodedEvent(name="Beverage", start_anchor="SOD",
                                  start_offset=-30, active=True))
    db.session.commit()
    items, _ = overlay_for_day(day)
    bev = next(i for i in items if i["name"] == "Beverage")
    assert bev["time"] == "7:30 AM"
    assert bev["end_time"] is None


def test_overlay_skips_when_anchor_missing(db):
    from models import HardCodedEvent
    from hardcoded_service import overlay_for_day
    show, day = _show_day(db, sod=None, eod=None)
    db.session.add(HardCodedEvent(name="Security", start_anchor="SOD",
                                  start_offset=-60, active=True))
    db.session.commit()
    items, missing = overlay_for_day(day)
    assert items == []
    assert missing is True


def test_overlay_respects_per_show_disable(db):
    from models import HardCodedEvent, ShowHardCodedEvent
    from hardcoded_service import overlay_for_day
    show, day = _show_day(db)
    ev = HardCodedEvent(name="Security", start_anchor="SOD", start_offset=-60, active=True)
    db.session.add(ev); db.session.commit()
    db.session.add(ShowHardCodedEvent(show_id=show.id, hce_id=ev.id, enabled=False))
    db.session.commit()
    items, _ = overlay_for_day(day)
    assert items == []


def test_overlay_excludes_inactive(db):
    from models import HardCodedEvent
    from hardcoded_service import overlay_for_day
    show, day = _show_day(db)
    db.session.add(HardCodedEvent(name="Off", start_anchor="SOD",
                                  start_offset=0, active=False))
    db.session.commit()
    items, _ = overlay_for_day(day)
    assert items == []


def test_apply_to_show_route_disables_then_reenables(app, client, db):
    from models import HardCodedEvent, ShowHardCodedEvent
    show, day = _show_day(db)
    ev = HardCodedEvent(name="Security", start_anchor="SOD", start_offset=0, active=True)
    db.session.add(ev); db.session.commit()

    # No checkbox -> turned off for this show
    client.post(f"/shows/{show.id}/hard-coded-events/apply", data={})
    row = ShowHardCodedEvent.query.filter_by(show_id=show.id, hce_id=ev.id).first()
    assert row is not None and row.enabled is False

    # Checkbox on -> back on
    client.post(f"/shows/{show.id}/hard-coded-events/apply", data={f"hce_{ev.id}": "1"})
    row = ShowHardCodedEvent.query.filter_by(show_id=show.id, hce_id=ev.id).first()
    assert row.enabled is True
