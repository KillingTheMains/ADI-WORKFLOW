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
