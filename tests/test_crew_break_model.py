"""CrewBreak wraps an activity; it never replaces one (2026-08-11, step 1).

Three tables point at schedule_activities — CrewRow (not-null),
SubScheduleEntry and MealService — so replacing a break activity would
cascade-delete its crew rows and orphan anything already linked to it.
"""
import datetime as dt

from models import CATERED_NO, CATERED_UNCONFIRMED, CATERED_YES


def _day_with_break(db, code="BRK26"):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Breaks", code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 20),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    brk = ScheduleActivity(day_id=day.id, time="12:00",
                           description="LUNCH BREAK — 7:00 AM CREW")
    db.session.add_all([call, brk]); db.session.flush()
    db.session.commit()
    return show, day, call, brk


def test_a_break_wraps_the_existing_activity(app, db):
    from models import CrewBreak
    show, day, call, brk = _day_with_break(db)
    cb = CrewBreak(show_id=show.id, activity_id=brk.id, crew_call_id=call.id,
                   offset_minutes=300, duration_minutes=60, label="LUNCH")
    db.session.add(cb); db.session.commit()

    assert cb.activity.id == brk.id
    assert cb.crew_call.description == "CREW START"
    # The activity still exists in its own right.
    from models import ScheduleActivity
    assert ScheduleActivity.query.get(brk.id) is not None


def test_catering_defaults_to_unconfirmed(app, db):
    from models import CrewBreak
    show, day, call, brk = _day_with_break(db, "BRK27")
    cb = CrewBreak(show_id=show.id, activity_id=brk.id)
    db.session.add(cb); db.session.commit()
    assert cb.catered == CATERED_UNCONFIRMED


def test_unconfirmed_is_not_catered_and_not_uncatered(app, db):
    """The whole reason the flag is three-state. Reading unconfirmed as 'no'
    is how a meal quietly stops reaching the F&B manager."""
    from models import CrewBreak
    show, day, call, brk = _day_with_break(db, "BRK28")
    cb = CrewBreak(show_id=show.id, activity_id=brk.id)
    db.session.add(cb); db.session.commit()

    assert cb.is_catered is False           # not treated as catered
    assert cb.needs_confirmation is True
    assert cb.visible_to_fnb is True        # but F&B still sees it, flagged


def test_a_confirmed_uncatered_break_is_invisible_to_fnb(app, db):
    from models import CrewBreak
    show, day, call, brk = _day_with_break(db, "BRK29")
    cb = CrewBreak(show_id=show.id, activity_id=brk.id, catered=CATERED_NO)
    db.session.add(cb); db.session.commit()
    assert cb.visible_to_fnb is False
    assert cb.is_catered is False


def test_a_catered_break_is_visible_to_fnb(app, db):
    from models import CrewBreak
    show, day, call, brk = _day_with_break(db, "BRK30")
    cb = CrewBreak(show_id=show.id, activity_id=brk.id, catered=CATERED_YES)
    db.session.add(cb); db.session.commit()
    assert cb.is_catered is True
    assert cb.visible_to_fnb is True


def test_one_break_per_activity(app, db):
    """An activity cannot be described by two competing break records."""
    import pytest
    from sqlalchemy.exc import IntegrityError
    from models import CrewBreak
    show, day, call, brk = _day_with_break(db, "BRK31")
    db.session.add(CrewBreak(show_id=show.id, activity_id=brk.id))
    db.session.commit()
    db.session.add(CrewBreak(show_id=show.id, activity_id=brk.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_shows_default_to_the_old_behaviour(app, db):
    """Nothing changes on deploy until a show is switched over."""
    from models import Show
    show = Show(name="Untouched", code="OLD26")
    db.session.add(show); db.session.commit()
    assert not show.uses_new_breaks


def test_meal_service_window_defaults(app, db):
    from models import MealService, Show, ScheduleDay
    show = Show(name="Svc", code="SVC26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 21))
    db.session.add(day); db.session.flush()
    ms = MealService(show_id=show.id, schedule_day_id=day.id, name="Lunch")
    db.session.add(ms); db.session.commit()
    assert ms.setup_minutes == 30
    assert ms.holdover_minutes == 30
