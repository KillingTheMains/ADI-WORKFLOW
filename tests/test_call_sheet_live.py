"""#46 — Call Sheet reflects crew-name changes (live render + no-cache headers)."""
import datetime as dt


def test_call_sheet_shows_live_name_and_sets_no_cache(app, client, db):
    from models import Show, ScheduleDay, ScheduleActivity, CrewRow, CrewMember
    show = Show(name="CS Show", code="CS26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 21))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="8:00 AM", description="SHOW", sort_order=10)
    db.session.add(act); db.session.flush()
    cm = CrewMember(first_name="Old", last_name="Name")
    db.session.add(cm); db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id, sort_order=1))
    db.session.commit()

    r = client.get("/shows/%d/schedule/%d/call-sheet" % (show.id, day.id))
    assert r.status_code == 200
    assert "Old Name" in r.get_data(as_text=True)
    cc = r.headers.get("Cache-Control", "")
    assert "no-store" in cc or "no-cache" in cc

    # rename the crew member — the call sheet must reflect it, not a stale copy
    cm.first_name = "New"
    db.session.commit()
    r2 = client.get("/shows/%d/schedule/%d/call-sheet" % (show.id, day.id))
    body = r2.get_data(as_text=True)
    assert "New Name" in body
    assert "Old Name" not in body
