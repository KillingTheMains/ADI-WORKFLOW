"""#47 — crew sharing a call time are grouped into ONE master row, not separate ones."""
import datetime as dt


def test_master_groups_same_call_time_crew(app, client, db):
    from models import Show, ScheduleDay, ScheduleActivity, CrewMember, CrewRow
    show = Show(name="M47", code="M47")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 22))
    db.session.add(day); db.session.flush()
    cs = ScheduleActivity(day_id=day.id, time="7:00 AM", description="CREW START", sort_order=10)
    db.session.add(cs); db.session.flush()
    a = CrewMember(first_name="Ann", last_name="Lee")
    b = CrewMember(first_name="Bob", last_name="Kim")
    db.session.add_all([a, b]); db.session.flush()
    db.session.add(CrewRow(activity_id=cs.id, crew_member_id=a.id, sort_order=1))
    db.session.add(CrewRow(activity_id=cs.id, crew_member_id=b.id, sort_order=2))
    db.session.commit()

    body = client.get("/shows/%d/oss?tab=master" % show.id).get_data(as_text=True)
    # both names appear together in one grouped Crew row (comma-joined),
    # rather than as two separate rows
    assert "Ann Lee, Bob Kim" in body
