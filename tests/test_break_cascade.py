"""
Deleting a day or a show must take its crew breaks with it.

Found 2026-08-12 by a real 500 on Create Crew Call:
`UNIQUE constraint failed: crew_breaks.activity_id`. `crew_breaks.activity_id`
is UNIQUE; deleting a day left its CrewBreak rows behind pointing at
activities that no longer existed; SQLite reuses rowids, so the next activity
created took an id a ghost still claimed and the insert died. A delete in one
show breaking a create in another, with nothing on screen to explain it.

The suite did not catch it because no test deleted a day that had breaks on
it. These do.
"""
import datetime as dt


def _show(db, code="CAS26"):
    from models import Show
    show = Show(name="Cascade Show", code=code)
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    return show


def _day_with_breaks(db, show, date, client):
    from models import ScheduleDay
    day = ScheduleDay(show_id=show.id, date=date, sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.commit()
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "08:00", "add_breaks": "1"})
    return day


def test_deleting_a_day_deletes_its_breaks(app, client, db):
    from models import CrewBreak
    show = _show(db)
    day = _day_with_breaks(db, show, dt.date(2026, 9, 7), client)
    assert CrewBreak.query.count() == 3

    db.session.delete(day)
    db.session.commit()
    assert CrewBreak.query.count() == 0


def test_deleting_a_show_deletes_its_breaks(app, client, db):
    from models import CrewBreak
    show = _show(db)
    _day_with_breaks(db, show, dt.date(2026, 9, 8), client)
    assert CrewBreak.query.count() == 3

    db.session.delete(show)
    db.session.commit()
    assert CrewBreak.query.count() == 0


def test_no_break_is_left_pointing_at_a_dead_activity(app, client, db):
    """The condition itself, stated directly."""
    from models import CrewBreak, ScheduleActivity
    show = _show(db)
    day = _day_with_breaks(db, show, dt.date(2026, 9, 9), client)
    db.session.delete(day)
    db.session.commit()

    live = {a.id for a in ScheduleActivity.query.all()}
    assert [cb.id for cb in CrewBreak.query.all()
            if cb.activity_id not in live] == []


def test_a_new_break_can_reuse_a_deleted_activity_id(app, client, db):
    """The 500, reproduced. Delete a day that had breaks, then make a new one:
    SQLite hands out the same rowids again, and before the cascade the insert
    collided with the ghost that still claimed them.
    """
    from models import CrewBreak
    show = _show(db)
    day = _day_with_breaks(db, show, dt.date(2026, 9, 10), client)
    db.session.delete(day)
    db.session.commit()

    day2 = _day_with_breaks(db, show, dt.date(2026, 9, 11), client)
    assert CrewBreak.query.count() == 3
    assert all(cb.activity is not None for cb in CrewBreak.query.all())
    assert day2 is not None


def test_deleting_one_break_leaves_the_others(app, client, db):
    """The cascade must not over-reach."""
    from models import CrewBreak
    show = _show(db)
    day = _day_with_breaks(db, show, dt.date(2026, 9, 12), client)
    cb = CrewBreak.query.filter_by(offset_minutes=150).one()
    r = client.post(
        f"/shows/{show.id}/schedule/{day.id}/breaks/{cb.id}/delete")
    assert r.status_code in (200, 302)
    assert CrewBreak.query.count() == 2


def test_the_orphan_report_changes_nothing(app, client, db):
    """It is a diagnostic. If it ever starts deleting, this fails."""
    from migrations import _report_orphaned_crew_breaks
    from models import CrewBreak
    show = _show(db)
    _day_with_breaks(db, show, dt.date(2026, 9, 13), client)
    before = CrewBreak.query.count()

    _report_orphaned_crew_breaks(db.session)
    db.session.commit()
    assert CrewBreak.query.count() == before
