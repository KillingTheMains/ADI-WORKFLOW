"""The model and the rules must agree about what a beverage service is.

`breaks.is_beverage_service` became THE predicate on 2026-08-11, after a
repair migration written against `is_recurring` alone matched none of the rows
it was written for and had to be re-run under a new key. Every RULE was
switched over then — can_link, candidates_for_break, candidates_for_service,
break_coverage.is_orphan.

`MealService.is_standing` was missed, and stayed `bool(self.is_recurring)`.

⚠️ WHY THAT MATTERED IN PRODUCTION. Every beverage service on MCDC26 came
through `_migrate_fb_entries_to_meal_services`, which hard-codes
`is_recurring=False` (migrations.py:161). So `is_standing` was False for every
beverage table the show actually had, and three things silently did the wrong
thing:

  · `beverage_plan` returned None — no set or refresh touchpoints computed
    for any real beverage service, which is the whole feature;
  · `fb_service_save` skipped the offset and interval fields, so they could
    not be edited;
  · the F&B tab offered a "Feeds" link picker that `can_link` would refuse,
    because the rules already knew better than the model did.

And a fourth, found while fixing it: `fb_standing_add`'s "one per day" guard
was a SQL `filter_by(is_recurring=True)`, so it never fired either — the day
that was supposed to hold exactly one beverage table would take a second and
a third without complaint.
"""
import datetime as dt

import pytest

from breaks import is_beverage_service


def _service(db, **kw):
    from models import MealService, ScheduleDay, Show
    show = Show.query.filter_by(code="BEV26").first()
    if show is None:
        show = Show(name="Bev", code="BEV26")
        show.uses_new_breaks = True
        db.session.add(show)
        db.session.flush()
        db.session.add(ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 8),
                                   sod="7:00 AM", eod="11:00 PM"))
        db.session.flush()
    day = show.days[0]
    kw.setdefault("name", "Crew Beverages")
    kw.setdefault("kind", "beverages")
    kw.setdefault("is_recurring", False)
    svc = MealService(show_id=show.id, schedule_day_id=day.id, **kw)
    db.session.add(svc)
    db.session.commit()
    return show, day, svc


# ── The property and the predicate are the same answer ───────────────────

@pytest.mark.parametrize("name,kind,recurring", [
    ("Crew Beverages", "beverages", False),   # legacy: kind says it
    ("CREW BEVERAGE SET", "other", False),    # legacy: name says it
    ("Coffee Station", "other", False),       # legacy: name says it
    ("All-day beverages", "beverages", True), # modern: flag says it
    ("Crew Lunch", "meal", False),            # a meal is not standing
    ("Dinner", "dinner", False),
])
def test_is_standing_agrees_with_the_predicate(app, db, name, kind, recurring):
    _show, _day, svc = _service(db, name=name, kind=kind, is_recurring=recurring)
    assert svc.is_standing == is_beverage_service(svc)


def test_a_legacy_beverage_service_is_standing(app, db):
    """The production shape: converted from the old F&B model, so the flag is
    False and the kind is the only evidence."""
    _show, _day, svc = _service(db, name="Crew Beverages", kind="beverages",
                                is_recurring=False)
    assert svc.is_recurring is False
    assert svc.is_standing is True


def test_a_meal_service_is_not_standing(app, db):
    _show, _day, svc = _service(db, name="Crew Lunch", kind="meal")
    assert svc.is_standing is False


def test_crew_breakfast_is_still_a_meal(app, db):
    """The word-boundary regression. "CREW BREAK" is a prefix of "CREW
    BREAKFAST", which is a real service on MCDC26; six consumers of the
    predicate misread it before the \\b was added. is_standing depends on the
    predicate now, so it inherits the trap and needs the guard."""
    _show, _day, svc = _service(db, name="CREW BREAKFAST", kind="other")
    assert svc.is_standing is False


# ── What was silently broken ─────────────────────────────────────────────

def test_a_legacy_beverage_service_gets_a_beverage_plan(app, db):
    """It returned None for every real service. No set time, no refreshes —
    the entire point of a standing service."""
    from models import ScheduleActivity, CrewRow, CrewMember
    show, day, svc = _service(db, name="Crew Beverages", kind="beverages",
                              is_recurring=False)
    call = ScheduleActivity(day_id=day.id, time="8:00 AM",
                            description="CREW START", sort_order=10)
    db.session.add(call)
    db.session.flush()
    cm = CrewMember(first_name="Ann", last_name="One", active=True)
    db.session.add(cm)
    db.session.flush()
    db.session.add(CrewRow(activity_id=call.id, crew_member_id=cm.id,
                           qty=1, hours=10))
    db.session.commit()

    plan = svc.beverage_plan
    assert plan is not None, "a standing service must compute its touchpoints"


def test_an_ordinary_meal_still_has_no_beverage_plan(app, db):
    _show, _day, svc = _service(db, name="Crew Lunch", kind="meal")
    assert svc.beverage_plan is None


# ── One beverage table per day, actually enforced ────────────────────────

def test_a_second_beverage_service_is_refused_even_when_the_first_is_legacy(
        app, client, db):
    """The guard was `filter_by(is_recurring=True)`, so on a show whose
    beverage services are all legacy it never fired."""
    from models import MealService
    show, day, existing = _service(db, name="Crew Beverages", kind="beverages",
                                   is_recurring=False)
    before = MealService.query.filter_by(schedule_day_id=day.id).count()

    r = client.post("/shows/%d/oss/fb/standing/add" % show.id,
                    data={"schedule_day_id": day.id,
                          "name": "A second beverage table"},
                    follow_redirects=True)
    assert r.status_code == 200
    after = MealService.query.filter_by(schedule_day_id=day.id).count()
    assert after == before, "a second beverage table was created"
    assert "already the standing service" in r.get_data(as_text=True)


def test_a_meal_service_does_not_block_the_beverage_table(app, client, db):
    """The guard must not over-fire either — a lunch is not a beverage
    table, and a day should still be able to have one of each."""
    from models import MealService
    show, day, _lunch = _service(db, name="Crew Lunch", kind="meal")
    before = MealService.query.filter_by(schedule_day_id=day.id).count()

    client.post("/shows/%d/oss/fb/standing/add" % show.id,
                data={"schedule_day_id": day.id, "name": "Crew Beverages"},
                follow_redirects=True)
    assert MealService.query.filter_by(schedule_day_id=day.id).count() == before + 1


# ── The one definition ───────────────────────────────────────────────────

def test_the_model_holds_no_second_copy_of_the_rule(app):
    """This is the bug: two spellings of one question. Same guard as the one
    on beverage_service.crew_windows_for_day after the headcount rule grew a
    second copy."""
    import inspect
    import re
    from models import MealService
    src = inspect.getsource(MealService.is_standing.fget)
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert "is_beverage_service" in code
    assert "is_recurring" not in code, \
        "the beverage rule belongs in breaks.is_beverage_service, not here"
