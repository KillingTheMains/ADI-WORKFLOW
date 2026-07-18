"""Travel window (#31): crew Travel In/Out auto-fill from the show's window."""
import datetime as dt


def _show(db, start=None, end=None):
    from models import Show
    show = Show(name="TW Show", code="TW26",
                travel_window_start=start, travel_window_end=end)
    db.session.add(show); db.session.commit()
    return show


def test_autofill_on_assign(app, client, db):
    from models import CrewMember, ShowCrewAssignment
    show = _show(db, dt.date(2026, 7, 10), dt.date(2026, 7, 15))
    cm = CrewMember(first_name="Ann", last_name="Lee")
    db.session.add(cm); db.session.commit()
    client.post("/shows/%d/crew/assign" % show.id,
                data={"crew_member_id": cm.id, "action": "assign"})
    a = ShowCrewAssignment.query.filter_by(show_id=show.id, crew_member_id=cm.id).first()
    assert a.travel_in_date == dt.date(2026, 7, 10)
    assert a.travel_out_date == dt.date(2026, 7, 15)


def test_no_window_leaves_blank(app, client, db):
    from models import CrewMember, ShowCrewAssignment
    show = _show(db, None, None)
    cm = CrewMember(first_name="Bo", last_name="Kim")
    db.session.add(cm); db.session.commit()
    client.post("/shows/%d/crew/assign" % show.id,
                data={"crew_member_id": cm.id, "action": "assign"})
    a = ShowCrewAssignment.query.filter_by(show_id=show.id, crew_member_id=cm.id).first()
    assert a.travel_in_date is None and a.travel_out_date is None


def test_set_and_clear_travel_window_route(app, client, db):
    from models import Show, ScheduleDay
    show = Show(name="S", code="S1"); db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 8, 1))
    db.session.add(day); db.session.commit()
    client.post("/shows/%d/travel-window" % show.id,
                data={"marker": "start", "day_id": day.id})
    db.session.refresh(show)
    assert show.travel_window_start == dt.date(2026, 8, 1)
    # click again → clear
    client.post("/shows/%d/travel-window" % show.id,
                data={"marker": "start", "day_id": ""})
    db.session.refresh(show)
    assert show.travel_window_start is None
