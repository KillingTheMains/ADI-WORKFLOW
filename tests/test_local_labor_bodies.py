"""Capture log #5 (2026-09-05): actual hours per BODY on a local labor line.

The crew call keeps "Qty 6 · Lighting Hand · 10 hrs" (Jason: keep qty).
Bodies hang underneath, one per slot, holding only the actual. Identity is
per call: body #3 on Tuesday is not body #3 on Wednesday.
"""
import datetime as dt


def _show_with_local_labor(db, qty=3, est=10.0, code="LLB1", days=1):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, Position)
    show = Show(name="Bodies", code=code)
    db.session.add(show); db.session.flush()
    pos = Position.query.filter_by(title="Lighting Hand " + code).first()
    if pos is None:
        pos = Position(title="Lighting Hand " + code, department="Lighting",
                       is_local_labor=True)
        db.session.add(pos); db.session.flush()
    rows = []
    for i in range(days):
        day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 1) + dt.timedelta(days=i))
        db.session.add(day); db.session.flush()
        act = ScheduleActivity(day_id=day.id, time="07:00", description="LOAD IN",
                               sort_order=1)
        db.session.add(act); db.session.flush()
        hdr = CrewRow(activity_id=act.id, is_group_header=True, group_label="LOCAL CREW",
                      sort_order=1, qty=0)
        row = CrewRow(activity_id=act.id, position_id=pos.id, position=pos.title,
                      qty=qty, hours=est, crew_type="Local Crew", sort_order=2)
        db.session.add_all([hdr, row]); db.session.flush()
        rows.append(row)
    db.session.commit()
    return show, rows


def test_bodies_are_created_lazily_one_per_slot(app, db):
    from models import bodies_for, CrewRowBody
    show, (row,) = _show_with_local_labor(db, qty=4)
    assert CrewRowBody.query.count() == 0
    bodies = bodies_for(row)
    assert [b.index for b in bodies] == [1, 2, 3, 4]
    # asking again creates nothing new
    assert len(bodies_for(row)) == 4 and CrewRowBody.query.count() == 4


def test_a_lowered_qty_hides_bodies_but_keeps_their_hours(app, db):
    from models import bodies_for, CrewRowBody
    show, (row,) = _show_with_local_labor(db, qty=3, code="LLB2")
    bodies = bodies_for(row)
    bodies[2].actual_hours = 13
    db.session.commit()
    row.qty = 2
    db.session.commit()
    assert [b.index for b in bodies_for(row)] == [1, 2]
    assert CrewRowBody.query.filter_by(crew_row_id=row.id, index=3).one().actual_hours == 13
    row.qty = 3
    db.session.commit()
    assert bodies_for(row)[2].actual_hours == 13


def test_bodies_go_with_their_row(app, db):
    from models import bodies_for, CrewRowBody
    show, (row,) = _show_with_local_labor(db, qty=2, code="LLB3")
    bodies_for(row); db.session.commit()
    db.session.delete(row); db.session.commit()
    assert CrewRowBody.query.count() == 0


def test_the_page_lists_every_body_in_schedule_order(app, client, db):
    show, rows = _show_with_local_labor(db, qty=3, code="LLB4", days=2)
    html = client.get("/shows/%d/crew/local-labor-hours" % show.id).get_data(as_text=True)
    assert html.count('name="actual_hours"') == 6
    assert "2 lines" in html and "6 bodies" in html and "0 recorded" in html
    assert html.index("Oct 1") < html.index("Oct 2")
    assert "LOCAL CREW" in html


def test_saving_one_body_and_clearing_it(app, client, db):
    from models import bodies_for
    show, (row,) = _show_with_local_labor(db, qty=2, code="LLB5")
    b = bodies_for(row)[1]; db.session.commit()
    r = client.post("/shows/%d/crew/local-labor-hours/body/%d" % (show.id, b.id),
                    data={"actual_hours": "12.5"}, headers={"X-Autosave": "1"})
    assert r.status_code == 204
    db.session.refresh(b)
    assert b.actual_hours == 12.5
    client.post("/shows/%d/crew/local-labor-hours/body/%d" % (show.id, b.id),
                data={"actual_hours": ""})
    db.session.refresh(b)
    assert b.actual_hours is None


def test_a_body_from_another_show_is_refused(app, client, db):
    from models import bodies_for
    show_a, (row,) = _show_with_local_labor(db, qty=1, code="LLB6")
    show_b, _ = _show_with_local_labor(db, qty=1, code="LLB7")
    b = bodies_for(row)[0]; db.session.commit()
    r = client.post("/shows/%d/crew/local-labor-hours/body/%d" % (show_b.id, b.id),
                    data={"actual_hours": "9"})
    assert r.status_code == 404
    db.session.refresh(b)
    assert b.actual_hours is None


def test_use_estimate_fills_only_the_blanks(app, client, db):
    from models import bodies_for
    show, (row,) = _show_with_local_labor(db, qty=3, est=10, code="LLB8")
    bodies = bodies_for(row)
    bodies[0].actual_hours = 13       # the exception, typed on purpose
    db.session.commit()
    r = client.post("/shows/%d/crew/local-labor-hours/row/%d/fill" % (show.id, row.id))
    assert r.status_code in (302, 303)
    assert [b.actual_hours for b in bodies_for(row)] == [13, 10, 10]


def test_a_named_person_is_not_on_the_bodies_page(app, client, db):
    """Named crew already have their own actual on the crew row."""
    from models import CrewMember, CrewRow
    show, (row,) = _show_with_local_labor(db, qty=1, code="LLB9")
    cm = CrewMember(first_name="Named", last_name="Person")
    db.session.add(cm); db.session.flush()
    db.session.add(CrewRow(activity_id=row.activity_id, crew_member_id=cm.id,
                           qty=1, hours=10, sort_order=3))
    db.session.commit()
    html = client.get("/shows/%d/crew/local-labor-hours" % show.id).get_data(as_text=True)
    assert "Named" not in html
    assert html.count('name="actual_hours"') == 1


def test_a_show_with_no_local_labor_says_so(app, client, db):
    from models import Show
    show = Show(name="Nobody local", code="LLB10")
    db.session.add(show); db.session.commit()
    html = client.get("/shows/%d/crew/local-labor-hours" % show.id).get_data(as_text=True)
    assert "No local labor on this show yet" in html
