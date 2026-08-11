"""Classification and duration recovery (rehearsed against MCDC26, 2026-08-11).

The first version treated any MealService link as proof of catering. Running
it against real data showed 30 of 41 breaks linked to services named
"Crew Break - Refresh as Needed" or "Beverage Break" — Larry using meal
services to hold a standing beverage setup. Reading those as catered meals is
the same class of error as guessing from the description.
"""
import datetime as dt

import break_backfill
from models import CATERED_NO, CATERED_UNCONFIRMED, CATERED_YES


class _MS:
    def __init__(self, name, kind="other", is_recurring=False):
        self.name, self.kind, self.is_recurring = name, kind, is_recurring


def test_no_service_is_unconfirmed():
    catered, _ = break_backfill.classify(None)
    assert catered == CATERED_UNCONFIRMED


def test_a_real_meal_service_means_provided():
    catered, why = break_backfill.classify(_MS("Crew Lunch", kind="lunch"))
    assert catered == CATERED_YES
    assert "lunch" in why


def test_the_crew_break_refresh_service_is_not_a_provided_meal():
    """24 of MCDC26's 41 breaks link to exactly this."""
    catered, why = break_backfill.classify(
        _MS("Crew Break - Refresh as Needed"))
    assert catered == CATERED_NO
    assert "standing" in why


def test_a_beverage_break_service_is_not_a_provided_meal():
    catered, _ = break_backfill.classify(_MS("Beverage Break"))
    assert catered == CATERED_NO


def test_a_recurring_service_is_a_standing_service():
    catered, _ = break_backfill.classify(_MS("All Day", is_recurring=True))
    assert catered == CATERED_NO


def test_beverages_kind_is_a_standing_service():
    catered, _ = break_backfill.classify(_MS("Anything", kind="beverages"))
    assert catered == CATERED_NO


def test_an_unclear_service_stays_unconfirmed_rather_than_guessing():
    catered, _ = break_backfill.classify(_MS("Something Else", kind="other"))
    assert catered == CATERED_UNCONFIRMED


def test_a_meal_named_service_with_no_kind_counts_as_provided():
    """MCDC26's real meals are named "LUNCH BREAK — 08:00 CREW" and carry no
    useful kind. Refusing to read the name would mark every genuine meal on
    the show unconfirmed."""
    catered, why = break_backfill.classify(_MS("LUNCH BREAK — 08:00 CREW"))
    assert catered == CATERED_YES
    assert "by name" in why


def test_beverage_wording_still_wins_over_a_meal_word():
    """"Crew Break - Refresh as Needed" must not be rescued by a stray word."""
    catered, _ = break_backfill.classify(_MS("Crew Break - Lunch Refresh"))
    assert catered == CATERED_NO


# ── RETURN FROM handling ─────────────────────────────────────────────────────

def _day(db, code="RT26"):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Return", code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 1), sod="07:00")
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="07:00",
                                    description="CREW START"))
    db.session.flush()
    return show, day


def _act(db, day, time, desc):
    from models import ScheduleActivity
    a = ScheduleActivity(day_id=day.id, time=time, description=desc)
    db.session.add(a); db.session.flush()
    return a


def test_return_row_is_not_itself_a_break(app, db):
    show, day = _day(db)
    _act(db, day, "13:00", "LUNCH BREAK")
    _act(db, day, "14:00", "RETURN FROM LUNCH")
    db.session.commit()
    result = break_backfill.plan(show)
    assert result["counts"]["total"] == 1
    assert result["counts"]["return_markers"] == 1
    assert [r["activity"].description for r in result["rows"]] == ["LUNCH BREAK"]


def test_duration_is_recovered_from_the_return_row(app, db):
    """The old data knows this; it is just written as a separate row."""
    show, day = _day(db, "RT27")
    _act(db, day, "13:00", "LUNCH BREAK")
    _act(db, day, "14:00", "RETURN FROM LUNCH")
    db.session.commit()
    row = break_backfill.plan(show)["rows"][0]
    assert row["duration"] == 60
    assert row["duration_known"] is True


def test_duration_matches_the_labelled_break(app, db):
    show, day = _day(db, "RT28")
    _act(db, day, "13:00", "LUNCH BREAK — 07:00 CREW")
    _act(db, day, "13:30", "RETURN FROM LUNCH")
    db.session.commit()
    assert break_backfill.plan(show)["rows"][0]["duration"] == 30


def test_house_default_when_there_is_no_return_row(app, db):
    show, day = _day(db, "RT29")
    _act(db, day, "13:00", "LUNCH BREAK")
    db.session.commit()
    row = break_backfill.plan(show)["rows"][0]
    assert row["duration"] == 60
    assert row["duration_known"] is False


def test_a_return_row_before_the_break_is_ignored(app, db):
    """Yesterday's marker, or a mis-ordered day, must not give a negative
    duration."""
    show, day = _day(db, "RT30")
    _act(db, day, "09:00", "RETURN FROM LUNCH")
    _act(db, day, "13:00", "LUNCH BREAK")
    db.session.commit()
    row = break_backfill.plan(show)["rows"][0]
    assert row["duration_known"] is False
    assert row["duration"] == 60
