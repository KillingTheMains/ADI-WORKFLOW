"""What counts as a standing beverage service. ONE definition.

The repair migration shipped testing `is_recurring` alone and found NOTHING on
production, because every beverage service on MCDC26 is a legacy row converted
from the old F&B model — `is_recurring` is False and the only evidence is the
kind or the name. `classify()` had always read all three. The predicate and its
consumers drifted, and this file is the guard against it happening again.
"""
import datetime as dt

from breaks import is_beverage_service


class _Svc:
    def __init__(self, name="Lunch", kind="lunch", is_recurring=False):
        self.name = name
        self.kind = kind
        self.is_recurring = is_recurring


def test_the_explicit_flag_says_so():
    assert is_beverage_service(_Svc(is_recurring=True)) is True


def test_the_kind_says_so():
    assert is_beverage_service(_Svc(kind="beverages")) is True


def test_the_legacy_names_say_so():
    """These are the real MCDC26 names, and the only evidence those rows have."""
    for name in ("Beverage Break", "Crew Break - Refresh as Needed",
                 "COFFEE SETUP", "Water Station"):
        assert is_beverage_service(_Svc(name=name, kind="other")) is True, name


def test_a_real_meal_is_not_one():
    for name in ("Crew Lunch", "LUNCH BREAK — 08:00 CREW", "Dinner", "Breakfast"):
        assert is_beverage_service(_Svc(name=name, kind="lunch")) is False, name


def test_nothing_is_not_one():
    assert is_beverage_service(None) is False


# ── every consumer uses it ──────────────────────────────────────────────────

def _legacy_beverage_show(db, code):
    """A show shaped like MCDC26: the beverage service is a LEGACY row, so
    is_recurring is False and only the name gives it away."""
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        MealService, MealServiceLocation)
    show = Show(name="Legacy", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="20:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.flush()
    db.session.add(CrewRow(activity_id=call.id, qty=11, hours=10.0))
    act = ScheduleActivity(day_id=day.id, time="09:30",
                           description="COFFEE BREAK — 07:00 CREW")
    db.session.add(act); db.session.flush()
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Beverage Break", kind="other",
                      is_recurring=False, activity_id=act.id)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id, sort_order=0))
    db.session.commit()
    return show, day, call, act, svc


def test_the_backfill_leaves_a_legacy_beverage_break_unlinked(app, db):
    import break_backfill
    from models import CrewBreak
    show, day, call, act, svc = _legacy_beverage_show(db, "BP01")
    break_backfill.apply(show)
    cb = CrewBreak.query.filter_by(show_id=show.id).one()
    assert cb.catered == "no"
    assert cb.meal_service_id is None


def test_a_legacy_beverage_service_cannot_be_linked(app, db):
    import break_linking
    from models import CrewBreak
    show, day, call, act, svc = _legacy_beverage_show(db, "BP02")
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label="COFFEE", duration_minutes=15)
    db.session.add(cb); db.session.commit()
    ok, msg = break_linking.link(cb, svc)
    assert ok is False
    assert "standing beverage service" in msg


def test_a_legacy_beverage_service_is_not_offered_as_a_candidate(app, db):
    import break_linking
    from models import CrewBreak
    show, day, call, act, svc = _legacy_beverage_show(db, "BP03")
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label="COFFEE", duration_minutes=15)
    db.session.add(cb); db.session.commit()
    assert svc not in break_linking.candidates_for_break(cb)
    assert break_linking.candidates_for_service(svc) == []


def test_the_repair_migration_catches_a_legacy_link(app, db):
    """The case the first version missed entirely."""
    from migrations import _unlink_breaks_from_standing_services
    from models import CrewBreak
    show, day, call, act, svc = _legacy_beverage_show(db, "BP04")
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label="COFFEE", duration_minutes=15, catered="no",
                   meal_service_id=svc.id)
    db.session.add(cb); db.session.commit()
    _unlink_breaks_from_standing_services(db.session)
    db.session.commit()
    assert cb.meal_service_id is None


def test_the_repair_leaves_a_real_meal_link_alone(app, db):
    from migrations import _unlink_breaks_from_standing_services
    from models import CrewBreak, MealService
    show, day, call, act, svc = _legacy_beverage_show(db, "BP05")
    meal = MealService(show_id=show.id, schedule_day_id=day.id,
                       name="Crew Lunch", kind="lunch")
    db.session.add(meal); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label="LUNCH", duration_minutes=60, catered="yes",
                   meal_service_id=meal.id)
    db.session.add(cb); db.session.commit()
    _unlink_breaks_from_standing_services(db.session)
    db.session.commit()
    assert cb.meal_service_id == meal.id
