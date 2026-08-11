"""No per-company "Add all" pills on activity cards (Jason, 2026-08-11).

A row of company buttons on every activity was clutter. Companies are only
ever bulk-added at a crew call, and Bulk Assign Crew (#38) covers that with
checkboxes.
"""
import datetime as dt


def _day_with_company_crew(db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewMember,
                        ShowCrewAssignment, Company)
    co = Company(name="Encore", code="ENCORE")
    db.session.add(co); db.session.flush()
    show = Show(name="Pills", code="PIL26")
    db.session.add(show); db.session.flush()
    cm = CrewMember(first_name="A", last_name="B", company_id=co.id)
    db.session.add(cm); db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 12), sod="07:00")
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="07:00",
                                    description="CREW START"))
    db.session.add(ScheduleActivity(day_id=day.id, time="10:00",
                                    description="LOAD IN"))
    db.session.commit()
    return show, day, co


def test_add_all_pills_are_gone(app, client, db):
    show, day, co = _day_with_company_crew(db)
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "Add all:" not in html
    # No CALL SITES. The openShiftModal function itself is kept on purpose so
    # the behaviour can be re-attached to crew calls alone in one line.
    assert 'onclick="openShiftModal(' not in html


def test_the_rest_of_the_crew_controls_still_work(app, client, db):
    """Removing the pills must not take the add-crew form with it."""
    show, day, co = _day_with_company_crew(db)
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "+ Add crew row" in html
    assert "Bulk Assign Crew" in html
