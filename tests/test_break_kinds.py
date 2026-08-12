"""Meal vs coffee, and the second meal (2026-08-12).

Jason: "coffee breaks are the ones that are around 2.5 hours either after the
start of the call or coming back from a meal break. So in a standard day,
there would be 3 breaks: COFFEE, MEAL, COFFEE." And: coffee breaks are always
15 minutes and "they just are what they are" — no catering question.

Also: the first meal is not always lunch, so it is a MEAL BREAK. Which meal it
IS lives on the MealService, which is where the crew timeline and the F&B
timeline were always meant to separate.

The rule that must not bend: when in doubt, it is a MEAL. Guessing wrong that
way asks a question nobody needed; guessing wrong the other way silently
removes one, and a missing meal on site is far worse than an extra line.
"""
import datetime as dt

import breaks
from breaks import KIND_COFFEE, KIND_MEAL, break_options_for, kind_for_offset


def test_the_house_offsets_are_coffee_meal_coffee():
    assert kind_for_offset(150) == KIND_COFFEE
    assert kind_for_offset(300) == KIND_MEAL
    assert kind_for_offset(510) == KIND_COFFEE
    assert kind_for_offset(660) == KIND_MEAL


def test_an_unrecognised_offset_is_a_meal():
    """The safe direction. An extra question costs a click."""
    for offset in (0, 90, 200, 480, 1000, None, "banana"):
        assert kind_for_offset(offset) == KIND_MEAL


class _Row:
    def __init__(self, hours, header=False):
        self.hours = hours
        self.is_group_header = header


class _Call:
    def __init__(self, *rows):
        self.crew_rows = list(rows)


def test_the_second_meal_is_offered_only_past_fourteen_hours():
    assert len(break_options_for(_Call(_Row(10.0)))) == 3
    assert len(break_options_for(_Call(_Row(14.0)))) == 3     # not MORE than 14
    long = break_options_for(_Call(_Row(10.0), _Row(14.5)))
    assert len(long) == 4
    assert long[-1]["offset"] == 660
    assert long[-1]["kind"] == KIND_MEAL
    assert long[-1]["duration"] == 60


def test_unknown_hours_do_not_offer_a_second_meal():
    """None is not a short day, but the second meal is OFFERED rather than
    created — so a silent no costs a dropdown entry, not a meal."""
    assert len(break_options_for(_Call(_Row(None)))) == 3
    assert len(break_options_for(_Call())) == 3
    assert len(break_options_for(None)) == 3


def test_a_section_header_row_is_not_a_shift():
    assert breaks.longest_shift_hours(_Call(_Row(99.0, header=True))) is None


def test_the_offered_meal_is_called_MEAL_BREAK_not_lunch():
    """The first break may not always be lunch."""
    meal = [o for o in break_options_for(_Call()) if o["kind"] == KIND_MEAL]
    assert meal and all(o["label"] == "MEAL BREAK" for o in meal)


# ── grouping: the rename must not merge two different meals ─────────────────

class _B:
    _n = 0

    def __init__(self, label, minute, call_id, catered="no"):
        _B._n += 1
        self.id = _B._n
        self.label = label
        self.start_minute = minute
        self.crew_call_id = call_id
        self.duration_minutes = 60
        self.catered = catered
        self.derived_headcount = 10


def test_two_meals_six_hours_apart_are_two_periods(app):
    """The regression the rename would otherwise have caused. LUNCH and DINNER
    kept them apart by label; once both read MEAL BREAK and they hang off
    DIFFERENT crew calls, nothing did — they collapsed into one period timed
    at the first, with the evening meal hidden inside it."""
    periods = breaks.group_breaks([
        _B("MEAL BREAK", 12 * 60, 1),
        _B("MEAL BREAK", 18 * 60 + 30, 2),
    ])
    assert len(periods) == 2
    assert [p["time"] for p in periods] == ["12:00", "18:30"]


def test_two_sittings_an_hour_apart_are_still_one_period(app):
    """The case the grouping exists FOR: an 08:00 and an 09:00 crew eating an
    hour apart is one meal with two sittings."""
    periods = breaks.group_breaks([
        _B("MEAL BREAK", 13 * 60, 1),
        _B("MEAL BREAK", 14 * 60, 2),
    ])
    assert len(periods) == 1
    assert len(periods[0]["sittings"]) == 2


def test_the_same_crew_call_still_splits(app):
    periods = breaks.group_breaks([
        _B("MEAL BREAK", 13 * 60, 1),
        _B("MEAL BREAK", 13 * 60 + 30, 1),
    ])
    assert len(periods) == 2


# ── the migration ───────────────────────────────────────────────────────────

def _show(db, code):
    from models import ScheduleActivity, ScheduleDay, Show
    show = Show(name="Kind", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8),
                      sod="07:00", eod="23:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.flush()
    return show, day, call


def _brk(db, show, day, call, label, dur, catered="unconfirmed", svc=None):
    from models import CrewBreak, ScheduleActivity
    act = ScheduleActivity(day_id=day.id, time="12:00", description=label)
    db.session.add(act); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label=label, duration_minutes=dur, catered=catered,
                   meal_service_id=svc.id if svc else None)
    db.session.add(cb); db.session.flush()
    return cb


def test_fifteen_minutes_is_a_coffee_break_and_stops_asking(app, db):
    from migrations import _classify_break_kinds
    show, day, call = _show(db, "KD01")
    cb = _brk(db, show, day, call, "MORNING BREAK", 15)
    _classify_break_kinds(db.session); db.session.commit()
    assert cb.kind == KIND_COFFEE
    assert cb.asks_catering is False
    assert cb.visible_to_fnb is False


def test_lunch_and_dinner_both_become_MEAL_BREAK(app, db):
    from migrations import _classify_break_kinds
    show, day, call = _show(db, "KD02")
    a = _brk(db, show, day, call, "LUNCH BREAK — 07:00 CREW", 60)
    b = _brk(db, show, day, call, "DINNER BREAK", 60)
    c = _brk(db, show, day, call, "BREAKFAST", 30)
    _classify_break_kinds(db.session); db.session.commit()
    assert a.label == "MEAL BREAK — 07:00 CREW"   # trailing text preserved
    assert b.label == "MEAL BREAK"
    assert c.label == "MEAL BREAK"
    assert all(x.kind == KIND_MEAL for x in (a, b, c))


def test_a_coffee_named_break_stuck_at_60_stays_a_meal(app, db):
    """The 18 on MCDC26 whose labels had no readable length. Their duration is
    wrong, and until somebody fixes it they keep their catering question —
    which is the safe way to be wrong."""
    from migrations import _classify_break_kinds
    show, day, call = _show(db, "KD03")
    cb = _brk(db, show, day, call, "COFFEE BREAK — 08:00 CREW", 60)
    _classify_break_kinds(db.session); db.session.commit()
    assert cb.kind == KIND_MEAL
    assert cb.asks_catering is True
    assert cb.label == "COFFEE BREAK — 08:00 CREW"   # not a meal name


def test_a_break_with_a_service_is_never_called_coffee(app, db):
    """Something is demonstrably feeding it, whatever its length says."""
    from migrations import _classify_break_kinds
    from models import MealService
    show, day, call = _show(db, "KD04")
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Crew Lunch", kind="lunch")
    db.session.add(svc); db.session.flush()
    cb = _brk(db, show, day, call, "LUNCH BREAK", 15, catered="yes", svc=svc)
    _classify_break_kinds(db.session); db.session.commit()
    assert cb.kind == KIND_MEAL
    assert cb.catered == "yes"


def test_the_migration_is_repeatable(app, db):
    from migrations import _classify_break_kinds
    show, day, call = _show(db, "KD05")
    cb = _brk(db, show, day, call, "LUNCH BREAK — 07:00 CREW", 60)
    for _ in range(2):
        _classify_break_kinds(db.session); db.session.commit()
    assert cb.label == "MEAL BREAK — 07:00 CREW"


def test_coffee_breaks_leave_the_coverage_panel(app, db):
    import break_coverage
    from migrations import _classify_break_kinds
    show, day, call = _show(db, "KD06")
    _brk(db, show, day, call, "MORNING BREAK", 15)
    _brk(db, show, day, call, "AFTERNOON BREAK", 15)
    meal = _brk(db, show, day, call, "LUNCH BREAK", 60)
    db.session.commit()
    assert break_coverage.survey(show)["counts"]["undecided"] == 3
    _classify_break_kinds(db.session); db.session.commit()
    c = break_coverage.survey(show)["counts"]
    assert c["undecided"] == 1 and c["total"] == 1
    assert meal.asks_catering is True


# ── the editor ──────────────────────────────────────────────────────────────

def test_adding_a_coffee_slot_creates_a_coffee_break(app, db, client):
    from models import CrewBreak
    show, day, call = _show(db, "KD07")
    db.session.commit()
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/{call.id}/"
                "breaks/add", data={"offset_minutes": "150"})
    cb = CrewBreak.query.filter_by(show_id=show.id).one()
    assert cb.kind == KIND_COFFEE
    assert cb.duration_minutes == 15
    assert cb.label == "COFFEE BREAK"
    # Not left sitting on TBD waiting for an answer nobody will give.
    assert cb.catered == "no"


def test_adding_a_meal_slot_names_it_MEAL_BREAK_and_asks(app, db, client):
    from models import CrewBreak
    show, day, call = _show(db, "KD08")
    db.session.commit()
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/{call.id}/"
                "breaks/add", data={"offset_minutes": "300"})
    cb = CrewBreak.query.filter_by(show_id=show.id).one()
    assert (cb.kind, cb.label, cb.duration_minutes) == (
        KIND_MEAL, "MEAL BREAK", 60)
    assert cb.catered == "unconfirmed"


def test_a_posted_catering_answer_cannot_stick_to_a_coffee_break(app, db, client):
    """Hiding the control is not enough — a stale form or a hand-rolled POST
    would put the question back on a break that has none."""
    show, day, call = _show(db, "KD09")
    cb = _brk(db, show, day, call, "COFFEE BREAK", 15, catered="no")
    cb.kind = KIND_COFFEE
    db.session.commit()
    client.post(f"/shows/{show.id}/schedule/{day.id}/breaks/{cb.id}/edit",
                data={"catered": "yes"})
    assert cb.catered == "no"
    assert cb.meal_service_id is None
