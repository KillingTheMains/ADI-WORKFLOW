"""#37 Phase 2b: dept-tagged hard-coded events surface on their OSS tab + master.

The event is virtual (computed from the day's SOD/EOD) — the same event shown
on the day page, the department tab, and the master, never a stored copy.
"""
import datetime as dt


def test_hardcoded_event_on_dept_tab_and_master(app, client, db):
    from models import Show, ScheduleDay, HardCodedEvent
    show = Show(name="HC Show", code="HC26")
    db.session.add(show); db.session.flush()
    db.session.add(ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 25),
                               sod="8:00 AM", eod="10:00 PM"))
    db.session.add(HardCodedEvent(name="Gate Sweep", department="Security",
                                  start_anchor="SOD", start_offset=0, active=True))
    db.session.commit()

    r = client.get("/shows/%d/oss?tab=Security" % show.id)
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Gate Sweep" in body
    assert "Hard-Coded Events" in body

    rm = client.get("/shows/%d/oss?tab=master" % show.id)
    assert "Gate Sweep" in rm.get_data(as_text=True)


def test_inactive_hardcoded_event_not_surfaced(app, client, db):
    from models import Show, ScheduleDay, HardCodedEvent
    show = Show(name="HC2", code="HC27")
    db.session.add(show); db.session.flush()
    db.session.add(ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 26),
                               sod="8:00 AM", eod="10:00 PM"))
    db.session.add(HardCodedEvent(name="Ghost Event", department="Dock",
                                  start_anchor="SOD", start_offset=0, active=False))
    db.session.commit()
    r = client.get("/shows/%d/oss?tab=Dock" % show.id)
    assert "Ghost Event" not in r.get_data(as_text=True)
