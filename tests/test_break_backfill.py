"""Backfilling CrewBreak records from existing break activities.

Additive and idempotent: the activities are never edited or deleted, and
catering is only ever asserted when a MealService already proves it.
"""
import datetime as dt

import break_backfill
from models import CATERED_UNCONFIRMED, CATERED_YES


def _show(db, code="BF26"):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Backfill", code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 28),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.flush()
    return show, day, call


def _act(db, day, time, desc):
    from models import ScheduleActivity
    a = ScheduleActivity(day_id=day.id, time=time, description=desc)
    db.session.add(a); db.session.flush()
    return a


def test_unlinked_break_is_unconfirmed_never_uncatered(app, db):
    """The core rule. A name is not evidence that food was ordered."""
    show, day, call = _show(db)
    _act(db, day, "12:00", "LUNCH BREAK — 7:00 AM CREW")
    db.session.commit()
    rows = break_backfill.plan(show)["rows"]
    assert [r["catered"] for r in rows] == [CATERED_UNCONFIRMED]


def test_break_with_a_meal_service_is_catered(app, db):
    from models import MealService
    show, day, call = _show(db, "BF27")
    brk = _act(db, day, "12:00", "LUNCH BREAK")
    db.session.add(MealService(show_id=show.id, schedule_day_id=day.id,
                               activity_id=brk.id, name="Lunch"))
    db.session.commit()
    rows = break_backfill.plan(show)["rows"]
    assert [r["catered"] for r in rows] == [CATERED_YES]
    assert rows[0]["meal_service"].name == "Lunch"


def test_anchor_comes_from_the_label_when_present(app, db):
    """The builder stamps the crew time into the label; better evidence than
    guessing by proximity."""
    show, day, call = _show(db, "BF28")
    late = _act(db, day, "09:00", "CREW START")
    _act(db, day, "14:00", "LUNCH BREAK — 7:00 AM CREW")
    db.session.commit()
    row = break_backfill.plan(show)["rows"][0]
    assert row["crew_call"].id == call.id      # 07:00, not the nearer 09:00
    assert row["offset"] == 420                # 07:00 -> 14:00


def test_anchor_falls_back_to_the_latest_earlier_crew_start(app, db):
    show, day, call = _show(db, "BF29")
    late = _act(db, day, "09:00", "CREW START")
    _act(db, day, "12:00", "COFFEE BREAK")
    db.session.commit()
    row = break_backfill.plan(show)["rows"][0]
    assert row["crew_call"].id == late.id
    assert row["offset"] == 180


def test_break_with_no_crew_start_is_reported_not_guessed(app, db):
    from models import Show, ScheduleDay
    show = Show(name="NoCall", code="BF30")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 29))
    db.session.add(day); db.session.flush()
    _act(db, day, "12:00", "LUNCH BREAK")
    db.session.commit()
    result = break_backfill.plan(show)
    assert result["counts"]["no_anchor"] == 1
    assert result["rows"][0]["crew_call"] is None


def test_crew_starts_are_not_treated_as_breaks(app, db):
    show, day, call = _show(db, "BF31")
    db.session.commit()
    assert break_backfill.plan(show)["counts"]["total"] == 0


def test_apply_creates_records_without_touching_activities(app, db):
    from models import CrewBreak, ScheduleActivity
    show, day, call = _show(db, "BF32")
    brk = _act(db, day, "12:00", "LUNCH BREAK — 7:00 AM CREW")
    db.session.commit()
    before = (brk.description, brk.time, brk.day_id)

    counts = break_backfill.apply(show)
    assert counts["created"] == 1
    again = ScheduleActivity.query.get(brk.id)
    assert (again.description, again.time, again.day_id) == before
    assert CrewBreak.query.filter_by(activity_id=brk.id).count() == 1


def test_apply_is_idempotent(app, db):
    from models import CrewBreak
    show, day, call = _show(db, "BF33")
    _act(db, day, "12:00", "LUNCH BREAK")
    db.session.commit()
    break_backfill.apply(show)
    second = break_backfill.apply(show)
    assert second["created"] == 0
    assert CrewBreak.query.filter_by(show_id=show.id).count() == 1


def test_preview_route_writes_nothing(app, client, db):
    from models import CrewBreak
    show, day, call = _show(db, "BF34")
    _act(db, day, "12:00", "LUNCH BREAK")
    db.session.commit()
    r = client.get("/shows/%d/breaks/backfill" % show.id)
    assert r.status_code == 200
    assert CrewBreak.query.count() == 0


def test_toggle_flips_the_rollout_flag(app, client, db):
    show, day, call = _show(db, "BF35")
    db.session.commit()
    client.post("/shows/%d/breaks/toggle" % show.id)
    assert show.uses_new_breaks is True
    client.post("/shows/%d/breaks/toggle" % show.id)
    assert show.uses_new_breaks is False
