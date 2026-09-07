"""The hours report surfaces the billable split (2026-08-11)."""
import datetime as dt


def _show_with_hours(db, per_day, code="HRS26"):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        CrewMember, ShowCrewAssignment)
    show = Show(name="Hours", code=code)
    db.session.add(show); db.session.flush()
    cm = CrewMember(first_name="Long", last_name="Day")
    db.session.add(cm); db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    for i, hrs in enumerate(per_day):
        day = ScheduleDay(show_id=show.id,
                          date=dt.date(2026, 9, 1) + dt.timedelta(days=i))
        db.session.add(day); db.session.flush()
        act = ScheduleActivity(day_id=day.id, time="07:00",
                               description="CREW START")
        db.session.add(act); db.session.flush()
        db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id,
                               qty=1, hours=hrs))
    db.session.commit()
    return show, cm


def test_report_shows_the_split_when_there_is_overtime(app, client, db):
    show, cm = _show_with_hours(db, [14])
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert "Billable split" in html
    assert "10-hour day" in html


def test_no_overtime_means_no_billable_banner(app, client, db):
    """Short days should not put a billing notice in front of the user."""
    show, cm = _show_with_hours(db, [8, 8, 8], code="HRS27")
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert "Billable split" not in html


def test_split_is_per_day_not_on_the_total(app, client, db):
    """Five 8-hour days is 40 hours with NO overtime. Splitting the total
    would report a large DT figure. (Five, not eight: from the sixth
    consecutive day the whole day is OT — Jason, 2026-09-06 — which is a
    different test, below.)"""
    from billing import split_days
    show, cm = _show_with_hours(db, [8] * 5, code="HRS28")
    assert split_days([8] * 5) == (40.0, 0.0, 0.0)
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert "Billable split" not in html


def test_the_sixth_and_seventh_consecutive_days_are_all_overtime(app, client, db):
    """Jason, 2026-09-06: 6th and 7th day all day OT, within one show, any
    day off resets. Jason, 2026-09-07: and the week resets on Monday.
    The fixture starts Tuesday 2026-09-01, so eight straight 8-hour days
    run Tue..Tue: Sunday the 6th is the one flagged day, Monday is day one
    again. Seven days at ST, one at OT."""
    show, cm = _show_with_hours(db, [8] * 8, code="HRS28B")
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert "Billable split" in html
    assert "ST <strong>56.0</strong>" in html
    assert "OT <strong>8.0</strong>" in html
    assert "1 sixth-or-later day" in html and "sixth-or-later days" not in html
    assert html.count(">6+</sup>") == 1


def test_monday_to_sunday_flags_the_weekend_and_the_next_monday_is_normal(app, client, db):
    """Jason, 2026-09-07. Start on Monday 2026-09-07: Sat and Sun are the
    6th/7th day, the following Monday is normal."""
    from models import ScheduleDay
    show, cm = _show_with_hours(db, [8] * 8, code="HRS28C")
    for day in ScheduleDay.query.filter_by(show_id=show.id):
        day.date = day.date + dt.timedelta(days=6)      # 09-01 -> 09-07
    db.session.commit()
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert "ST <strong>48.0</strong>" in html
    assert "OT <strong>16.0</strong>" in html
    assert "2 sixth-or-later days" in html
    assert html.count(">6+</sup>") == 2


def test_a_single_long_day_is_split_correctly(app, client, db):
    show, cm = _show_with_hours(db, [4, 4, 14], code="HRS29")
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    # 4 + 4 + 10 straight, 2 OT, 2 DT
    assert "18.0" in html and "Billable split" in html


def test_report_still_renders_with_no_crew(app, client, db):
    from models import Show
    show = Show(name="Empty", code="HRS30")
    db.session.add(show); db.session.commit()
    r = client.get("/shows/%d/crew/hours" % show.id)
    assert r.status_code == 200
