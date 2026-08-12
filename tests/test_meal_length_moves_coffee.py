"""
The afternoon coffee follows the END of the meal, so it moves with its length.

Jason's rule, written into breaks.py since 08-12: a coffee is "around 2.5
hours ... coming back from a meal break". With an hour-long meal that lands at
+8:30; with a 30-minute meal it lands at +8:00. It was hard-coded at 510 until
2026-08-12, so a 30-minute-meal show got its afternoon coffee half an hour
late AND landed on an offset `kind_for_offset` did not recognise — which makes
it a MEAL, with a catering question and a 60-minute default. That is the exact
shape of MCDC26's stuck rows.
"""
from breaks import (KIND_COFFEE, KIND_MEAL, break_options_for,
                    default_duration_for, kind_for_offset,
                    meal_minutes_from_breaks, second_coffee_offset)


class _Row:
    def __init__(self, hours=None):
        self.hours = hours
        self.is_group_header = False


class _Call:
    def __init__(self, *rows):
        self.crew_rows = list(rows)


class _Brk:
    def __init__(self, kind, duration):
        self.kind = kind
        self.duration_minutes = duration


def test_an_hour_long_meal_puts_the_coffee_at_830():
    assert second_coffee_offset(60) == 510


def test_a_thirty_minute_meal_puts_it_at_800():
    assert second_coffee_offset(30) == 480


def test_an_unrecognised_length_falls_back_to_the_house_hour():
    """Safe direction: the house default, not arithmetic on a bad number."""
    for bad in (0, 45, None, "", "abc", -30):
        assert second_coffee_offset(bad) == 510


def test_480_is_a_coffee_not_a_meal():
    """The whole point. An offset the table does not know falls to MEAL, so a
    15-minute coffee would arrive carrying a catering question and an hour's
    duration.
    """
    assert kind_for_offset(480) == KIND_COFFEE
    assert default_duration_for(480) == 15


def test_the_options_move_with_the_meal_length():
    call = _Call(_Row(10.0))
    sixty = [o["offset"] for o in break_options_for(call, 60)]
    thirty = [o["offset"] for o in break_options_for(call, 30)]
    assert sixty == [150, 300, 510]
    assert thirty == [150, 300, 480]


def test_the_meal_option_carries_the_chosen_length():
    call = _Call(_Row(10.0))
    meal = [o for o in break_options_for(call, 30) if o["kind"] == KIND_MEAL][0]
    assert meal["duration"] == 30
    assert "30 min" in meal["text"]


def test_the_moved_coffee_is_still_fifteen_minutes():
    call = _Call(_Row(10.0))
    late = [o for o in break_options_for(call, 30) if o["offset"] == 480][0]
    assert late["kind"] == KIND_COFFEE
    assert late["duration"] == 15
    assert late["text"].startswith("+8:00")


def test_the_second_meal_does_not_move_with_the_meal_length():
    """It is anchored to the 11th hour of the shift, not to the first meal."""
    call = _Call(_Row(15.0))
    assert 660 in [o["offset"] for o in break_options_for(call, 30)]
    assert 660 in [o["offset"] for o in break_options_for(call, 60)]


def test_the_default_is_still_the_house_hour():
    call = _Call(_Row(10.0))
    assert [o["offset"] for o in break_options_for(call)] == [150, 300, 510]


def test_the_length_is_read_off_the_breaks_already_on_a_call():
    """What makes the add-a-break dropdown self-correcting."""
    assert meal_minutes_from_breaks([_Brk(KIND_COFFEE, 15),
                                     _Brk(KIND_MEAL, 30)]) == 30
    assert meal_minutes_from_breaks([_Brk(KIND_MEAL, 60)]) == 60
    assert meal_minutes_from_breaks([_Brk(KIND_COFFEE, 15)]) is None
    assert meal_minutes_from_breaks([]) is None
    # A legacy meal on some other duration is not one of the two choices, so
    # it does not get to move the coffee.
    assert meal_minutes_from_breaks([_Brk(KIND_MEAL, 45)]) is None


# ── End to end, through the wizard ───────────────────────────────────────────

def _show_day(db):
    import datetime as dt
    from models import ScheduleDay, Show
    show = Show(name="Meal Show", code="ML26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 5),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.commit()
    return show, day


def test_a_thirty_minute_meal_lands_the_coffee_at_1600(app, client, db):
    """08:00 call, 30-minute meal: 10:30, 13:00, 16:00 — not 16:30."""
    from models import CrewBreak
    show, day = _show_day(db)
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "08:00", "add_breaks": "1", "meal_minutes": "30"})
    breaks = CrewBreak.query.all()
    assert sorted(b.activity.time for b in breaks) == ["10:30", "13:00", "16:00"]
    meal = [b for b in breaks if b.kind == KIND_MEAL][0]
    assert meal.duration_minutes == 30


def test_the_moved_coffee_asks_no_catering_question(app, client, db):
    """A break at 480 must arrive as a COFFEE. If it lands as a meal it turns
    up on the coverage panel asking to be fed, which is the false signal the
    whole 08-12 clean-up was about.
    """
    from models import CATERED_NO, CrewBreak
    show, day = _show_day(db)
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "08:00", "add_breaks": "1", "meal_minutes": "30"})
    late = CrewBreak.query.filter_by(offset_minutes=480).one()
    assert late.kind == KIND_COFFEE
    assert late.duration_minutes == 15
    assert late.catered == CATERED_NO
    assert "COFFEE BREAK" in late.label


def test_an_hour_long_meal_is_unchanged(app, client, db):
    from models import CrewBreak
    show, day = _show_day(db)
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "08:00", "add_breaks": "1", "meal_minutes": "60"})
    assert sorted(b.activity.time for b in CrewBreak.query.all()) == \
        ["10:30", "13:00", "16:30"]


def test_the_add_break_dropdown_follows_the_call_it_is_on(app, client, db):
    """Self-correcting: a call with a 30-minute meal on it offers +8:00, and a
    call with an hour-long one offers +8:30 — same day, same dropdown.
    """
    show, day = _show_day(db)
    base = f"/shows/{show.id}/schedule/{day.id}/crew-call/create"
    client.post(base, data={"time": "08:00", "add_breaks": "1",
                            "meal_minutes": "30"})
    client.post(base, data={"time": "09:00", "description": "AUDIO",
                            "add_breaks": "1", "meal_minutes": "60"})

    from models import CrewBreak, ScheduleActivity
    from routes._break_edit import meal_minutes_for_call
    calls = {a.description: a for a in
             ScheduleActivity.query.filter_by(day_id=day.id).all()
             if a.description.startswith("CREW START")}
    short = calls["CREW START"]
    long_ = calls["CREW START — AUDIO"]
    assert meal_minutes_for_call(short) == 30
    assert meal_minutes_for_call(long_) == 60
    assert [o["offset"] for o in break_options_for(short, 30)][-1] == 480
    assert [o["offset"] for o in break_options_for(long_, 60)][-1] == 510
    assert CrewBreak.query.count() == 6
