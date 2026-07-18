"""Master Schedule rollup includes day activities + crew call times (#39)."""
import datetime as dt


def test_master_rolls_up_activities_and_crew(app, client, db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewMember,
                        CrewRow, ShowCrewAssignment, Company)
    show = Show(name="Master Show", code="MS26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 22))
    db.session.add(day); db.session.flush()
    cs = ScheduleActivity(day_id=day.id, time="7:00 AM",
                          description="CREW START", sort_order=10)
    doors = ScheduleActivity(day_id=day.id, time="6:00 PM",
                             description="DOORS OPEN", sort_order=20)
    db.session.add_all([cs, doors]); db.session.flush()
    co = Company(name="Beta"); db.session.add(co); db.session.flush()
    cm = CrewMember(first_name="Dana", last_name="Reed", company_id=co.id)
    db.session.add(cm); db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.add(CrewRow(activity_id=cs.id, crew_member_id=cm.id, sort_order=1))
    db.session.commit()

    r = client.get("/shows/%d/oss?tab=master" % show.id)
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "DOORS OPEN" in body        # a plain day activity rolled up
    assert "CREW START" in body        # the crew-start activity rolled up
    assert "Dana Reed" in body         # crew member with call time rolled up
    assert "Schedule" in body          # new dept label for activities
    assert "Crew" in body              # new dept label for crew call times
