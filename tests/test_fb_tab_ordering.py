"""The F&B tab reads down the day (2026-08-12).

Jason: all-day services at the top, then meals in chronological order; a
service feeding a MEAL BREAK should say MEAL rather than OTHER.

A standing beverage service has no single time — it is set once and topped up
all day — so sorting it among the meals by its setup time is meaningless and
moves it around whenever that time is edited.
"""
import datetime as dt

from breaks import guess_meal_kind


def test_a_meal_break_service_is_a_meal_not_other():
    """Fallout from the rename: guess_meal_kind had no 'meal' to return, so
    every service created from a MEAL BREAK opened on 'other'."""
    assert guess_meal_kind("MEAL BREAK") == "meal"
    assert guess_meal_kind("Meal Break — 07:00 Crew") == "meal"


def test_the_specific_kinds_still_win():
    """A caterer told 'breakfast' knows more than one told 'meal'."""
    assert guess_meal_kind("LUNCH MEAL") == "lunch"
    assert guess_meal_kind("DINNER BREAK") == "dinner"
    assert guess_meal_kind("CREW BREAKFAST") == "breakfast"
    assert guess_meal_kind("All Day Beverages") == "beverages"


def test_meal_is_an_offerable_kind():
    from models import MEAL_KINDS
    assert "meal" in MEAL_KINDS


def test_the_backfill_reads_meal_as_a_real_meal(app, db):
    """Left out of MEAL_KINDS_REAL, the backfill would read a service created
    from a MEAL BREAK as no evidence and leave its break unconfirmed."""
    import break_backfill
    from models import MealService
    svc = MealService(show_id=1, schedule_day_id=1, name="Crew Meal",
                      kind="meal")
    catered, _why = break_backfill.classify(svc)
    assert catered == "yes"


def _fb(db, code, services):
    """services: [(name, kind, time, is_recurring), ...] on one day."""
    from models import (MealService, MealServiceLocation, ScheduleDay, Show)
    show = Show(name="Ord", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8),
                      sod="07:00", eod="18:00")
    db.session.add(day); db.session.flush()
    for i, (name, kind, time, rec) in enumerate(services):
        svc = MealService(show_id=show.id, schedule_day_id=day.id, name=name,
                          kind=kind, is_recurring=rec, sort_order=i * 10)
        db.session.add(svc); db.session.flush()
        db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                           start_time=time, sort_order=0))
    db.session.commit()
    return show, day


def _order_on_page(client, show):
    """The service names in the order the F&B tab renders them."""
    import re
    body = client.get(f"/shows/{show.id}/oss?tab=F%26B").get_data(as_text=True)
    return re.findall(r'<span class="name">\s*(.*?)\s*</span>', body)


def test_all_day_services_come_first_then_the_clock(app, db, client):
    show, day = _fb(db, "OR01", [
        ("Crew Dinner", "dinner", "18:00", False),
        ("All Day Beverages", "beverages", "06:30", True),
        ("Crew Breakfast", "breakfast", "07:30", False),
        ("Crew Meal", "meal", "12:00", False),
    ])
    assert _order_on_page(client, show) == [
        "All Day Beverages", "Crew Breakfast", "Crew Meal", "Crew Dinner"]


def test_an_all_day_service_set_late_still_sorts_to_the_top(app, db, client):
    """The point of the change. It used to ride on its setup time, so editing
    that time moved the all-day row into the middle of the meals."""
    show, day = _fb(db, "OR02", [
        ("Crew Breakfast", "breakfast", "07:30", False),
        ("All Day Beverages", "beverages", "14:00", True),
    ])
    assert _order_on_page(client, show)[0] == "All Day Beverages"


def test_a_legacy_beverage_service_floats_up_too(app, db, client):
    """is_recurring is False on every legacy row — the ONE predicate reads the
    kind and the name as well, so they do not scatter through the meals."""
    show, day = _fb(db, "OR03", [
        ("Crew Breakfast", "breakfast", "07:30", False),
        ("Crew Break - Refresh as Needed", "other", "16:30", False),
    ])
    assert _order_on_page(client, show)[0] == "Crew Break - Refresh as Needed"


def test_an_all_day_service_is_labelled_BEVERAGES_not_an_emoji(app, db, client):
    show, day = _fb(db, "OR04", [
        ("All Day Beverages", "beverages", "06:30", True),
    ])
    body = client.get(f"/shows/{show.id}/oss?tab=F%26B").get_data(as_text=True)
    assert '<span class="kind">beverages</span>' in body
    assert '<span class="kind">🥤</span>' not in body


def test_the_headcount_pill_is_just_a_number(app, db, client):
    """Jason: "I dislike the '# TO FEED'." The count is what it is read for;
    the rest is a tooltip."""
    show, day = _fb(db, "OR05", [("Crew Meal", "meal", "12:00", False)])
    body = client.get(f"/shows/{show.id}/oss?tab=F%26B").get_data(as_text=True)
    # The PILL. "to feed" still appears in the coverage banner's prose, which
    # is a sentence rather than a label.
    assert "0 to feed" not in body and "👤" in body
