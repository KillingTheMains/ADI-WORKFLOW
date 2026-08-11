"""The backfill must be repeatable, not merely idempotent (2026-08-11).

`apply` skips activities that already have a record — good against double
running, bad when a verdict was decided by a rule that has since changed. The
classification changed once already after meeting real data.
"""
import datetime as dt

import break_backfill


def _show_with_break(db, code="RST26"):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Reset", code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 5), sod="07:00")
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="07:00",
                                    description="CREW START"))
    brk = ScheduleActivity(day_id=day.id, time="13:00",
                           description="LUNCH BREAK")
    db.session.add(brk); db.session.flush()
    db.session.commit()
    return show, day, brk


def test_reset_clears_records_so_the_backfill_can_run_again(app, client, db):
    from models import CrewBreak
    show, day, brk = _show_with_break(db)
    break_backfill.apply(show)
    assert CrewBreak.query.filter_by(show_id=show.id).count() == 1

    client.post("/shows/%d/breaks/reset" % show.id)
    assert CrewBreak.query.filter_by(show_id=show.id).count() == 0

    break_backfill.apply(show)
    assert CrewBreak.query.filter_by(show_id=show.id).count() == 1


def test_reset_leaves_the_break_activities_alone(app, client, db):
    """The distinction that makes this safe: a CrewBreak is additive metadata
    nothing points at. Deleting activities would cascade to crew rows."""
    from models import ScheduleActivity
    show, day, brk = _show_with_break(db, "RST27")
    before = (brk.description, brk.time, brk.day_id)
    break_backfill.apply(show)
    client.post("/shows/%d/breaks/reset" % show.id)

    again = ScheduleActivity.query.get(brk.id)
    assert again is not None
    assert (again.description, again.time, again.day_id) == before


def test_reset_does_not_touch_another_show(app, client, db):
    from models import CrewBreak
    a, _, _ = _show_with_break(db, "RST28")
    b, _, _ = _show_with_break(db, "RST29")
    break_backfill.apply(a)
    break_backfill.apply(b)

    client.post("/shows/%d/breaks/reset" % a.id)
    assert CrewBreak.query.filter_by(show_id=a.id).count() == 0
    assert CrewBreak.query.filter_by(show_id=b.id).count() == 1


def test_reset_on_a_show_with_nothing_is_harmless(app, client, db):
    show, day, brk = _show_with_break(db, "RST30")
    r = client.post("/shows/%d/breaks/reset" % show.id, follow_redirects=True)
    assert r.status_code == 200
