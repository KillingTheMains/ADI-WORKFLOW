"""CREW BREAKFAST is not a beverage service (2026-08-12).

`is_beverage_service` matched its words as plain substrings, and "CREW BREAK"
is a prefix of "CREW BREAKFAST". MCDC26 has a service called exactly that, and
all six consumers of the ONE predicate read it as a standing beverage setup:

* `break_linking.can_link` refused to attach it to any break, from either
  door — so a breakfast could not be linked to the break it feeds;
* `break_backfill.classify` returned NOT PROVIDED for a break it fed, and
  never reached the meal-name branch written to catch that exact name;
* the 08-11 repair migration would have unlinked it;
* `break_coverage.is_orphan` hid it from the coverage panel, so a breakfast
  service feeding nobody could never be found.

Found by an F&B ordering test. None of the six noticed.
"""
import pytest

from breaks import is_beverage_service


class _S:
    def __init__(self, name, kind="other", is_recurring=False):
        self.name = name
        self.kind = kind
        self.is_recurring = is_recurring


@pytest.mark.parametrize("name", [
    "CREW BREAKFAST",
    "Crew Breakfast",
    "MEAL BREAK — 07:00 CREW",
    "LUNCH BREAK — 08:00 CREW",
    "DINNER BREAK",
])
def test_a_meal_named_service_is_not_a_beverage_service(name):
    assert is_beverage_service(_S(name)) is False


def test_beverage_wording_still_beats_a_stray_meal_word():
    """NOT fixed here, on purpose. "Crew Break - Lunch Refresh" stays a
    beverage service — an earlier deliberate decision, guarded by
    test_break_classify.test_beverage_wording_still_wins_over_a_meal_word,
    because the failure it prevents is a standing beverage table being read as
    a catered meal. The bug was only ever the missing word boundary, and a
    meal-word override was tried on 2026-08-12 and reverted when that test
    caught it."""
    assert is_beverage_service(_S("Crew Break - Lunch Refresh")) is True
    assert is_beverage_service(_S("Coffee & Lunch")) is True


@pytest.mark.parametrize("name", [
    # The exact legacy names from MCDC26 — these must keep working.
    "Crew Break - Refresh as Needed",
    "All Day Beverages",
    "Crew Beverage Set",
    "Refresh Beverage",
    "Beverage Break",
    "COFFEE BREAK",
    "Water Station",
    "Crew Breaks",
    "Refreshments",
])
def test_the_real_beverage_services_still_match(name):
    assert is_beverage_service(_S(name)) is True


def test_the_explicit_signals_still_beat_the_name():
    """is_recurring and kind are somebody's deliberate answer. Only the NAME
    heuristic defers to a meal word."""
    assert is_beverage_service(_S("CREW BREAKFAST", is_recurring=True)) is True
    assert is_beverage_service(_S("CREW BREAKFAST", kind="beverages")) is True


def test_a_breakfast_service_can_now_be_linked_to_a_break(app, db):
    """The consequence that reached a user: can_link refused it outright."""
    import datetime as dt

    import break_linking
    from models import (CrewBreak, MealService, MealServiceLocation,
                        ScheduleActivity, ScheduleDay, Show)
    show = Show(name="BW", code="BW01", uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:30",
                           description="MEAL BREAK")
    db.session.add(act); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, label="MEAL BREAK",
                   duration_minutes=60)
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="CREW BREAKFAST", kind="breakfast")
    db.session.add_all([cb, svc]); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       start_time="07:30", sort_order=0))
    db.session.commit()
    ok, why = break_linking.link(cb, svc)
    assert ok, why
