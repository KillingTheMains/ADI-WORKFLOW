"""#47 — crew sharing a call time are grouped into ONE master crew call.

Updated 2026-08-11 (note 5): the grouping is unchanged — one crew call per
distinct call time — but it now renders as a headcount row with the names
listed one per row beneath it, instead of one comma-joined cell. Larry asked
for the show book's tall list everywhere.
"""
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
    # ONE crew call for the shared 7:00 call time, shown as a headcount...
    assert "2 crew called" in body
    # ...with each person on their own row beneath it (note 5).
    assert "Ann Lee" in body and "Bob Kim" in body
    assert "Ann Lee, Bob Kim" not in body
    assert body.count("oss-master-name-row") == 2
