"""Breaks read as one row per period, edited on the crew call.

Jason, 2026-08-11, after seeing the day page: breaks are EDITED inside the crew
call they hang off, and READ as a single row per break period with the sittings
underneath. Six form strips became two lines.
"""
import datetime as dt

from breaks import group_breaks


class _Fake:
    """A break, without a database. group_breaks is duck-typed on purpose."""
    def __init__(self, id, label, crew_call_id, minute, duration=60,
                 catered="unconfirmed", crew=None):
        self.id = id
        self.label = label
        self.crew_call_id = crew_call_id
        self.start_minute = minute
        self.duration_minutes = duration
        self.catered = catered
        self.derived_headcount = crew


def test_the_same_break_across_crew_groups_is_one_period(app):
    periods = group_breaks([
        _Fake(1, "LUNCH", 10, 720, crew=11),
        _Fake(2, "LUNCH", 20, 780, crew=6),
        _Fake(3, "LUNCH", 30, 840, crew=4),
    ])
    assert len(periods) == 1
    p = periods[0]
    assert p["label"] == "LUNCH"
    assert p["minute"] == 720            # the earliest sitting
    assert len(p["sittings"]) == 3
    assert p["crew"] == 21


def test_different_labels_stay_apart(app):
    periods = group_breaks([
        _Fake(1, "COFFEE", 10, 570, duration=15),
        _Fake(2, "LUNCH", 10, 720),
        _Fake(3, "COFFEE", 20, 630, duration=15),
        _Fake(4, "LUNCH", 20, 780),
    ])
    assert [p["label"] for p in periods] == ["COFFEE", "LUNCH"]
    assert [len(p["sittings"]) for p in periods] == [2, 2]


def test_one_crew_taking_two_breaks_of_the_same_name_is_two_periods(app):
    """Otherwise a crew appears twice in one sitting list, which is nonsense."""
    periods = group_breaks([
        _Fake(1, "BREAK", 10, 570, crew=11),
        _Fake(2, "BREAK", 10, 900, crew=11),
        _Fake(3, "BREAK", 20, 630, crew=6),
        _Fake(4, "BREAK", 20, 960, crew=6),
    ])
    assert len(periods) == 2
    assert [p["minute"] for p in periods] == [570, 900]
    for p in periods:
        calls = [b.crew_call_id for b in p["sittings"]]
        assert len(calls) == len(set(calls))


def test_labels_are_matched_case_and_space_insensitively(app):
    periods = group_breaks([
        _Fake(1, " lunch ", 10, 720),
        _Fake(2, "LUNCH", 20, 780),
    ])
    assert len(periods) == 1


def test_periods_come_out_in_clock_order(app):
    periods = group_breaks([
        _Fake(1, "LUNCH", 10, 720),
        _Fake(2, "COFFEE", 10, 570, duration=15),
    ])
    assert [p["label"] for p in periods] == ["COFFEE", "LUNCH"]


def test_sittings_that_disagree_read_as_mixed(app):
    """'The LX crew is fed and the riggers are not' has to be visible."""
    periods = group_breaks([
        _Fake(1, "LUNCH", 10, 720, catered="yes"),
        _Fake(2, "LUNCH", 20, 780, catered="no"),
    ])
    assert periods[0]["catered"] == "mixed"


def test_sittings_that_agree_carry_that_state(app):
    periods = group_breaks([
        _Fake(1, "LUNCH", 10, 720, catered="yes"),
        _Fake(2, "LUNCH", 20, 780, catered="yes"),
    ])
    assert periods[0]["catered"] == "yes"


def test_an_unknown_headcount_is_flagged_not_swallowed(app):
    periods = group_breaks([
        _Fake(1, "LUNCH", 10, 720, crew=11),
        _Fake(2, "LUNCH", None, 780, crew=None),
    ])
    assert periods[0]["crew"] == 11
    assert periods[0]["crew_partial"] is True


def test_breaks_with_no_anchor_never_conflict(app):
    """Nothing distinguishes them, so they group rather than fragmenting."""
    periods = group_breaks([
        _Fake(1, "LUNCH", None, 720),
        _Fake(2, "LUNCH", None, 780),
    ])
    assert len(periods) == 1
    assert len(periods[0]["sittings"]) == 2


def test_an_untimed_break_still_appears(app):
    periods = group_breaks([_Fake(1, "LUNCH", 10, None)])
    assert len(periods) == 1
    assert periods[0]["minute"] is None


# ── the page itself ─────────────────────────────────────────────────────────

def _day_with_breaks(db, code):
    """Two crew groups, each with a coffee and a lunch — six strips, before."""
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, CrewBreak)
    show = Show(name="Periods", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    calls = []
    for i, (time, qty) in enumerate([("07:00", 11), ("08:00", 6)]):
        act = ScheduleActivity(day_id=day.id, time=time,
                               description="CREW START", sort_order=i * 10)
        db.session.add(act); db.session.flush()
        db.session.add(CrewRow(activity_id=act.id, qty=qty, hours=10.0))
        calls.append(act)
    for call, coffee, lunch in [(calls[0], "09:30", "12:00"),
                                (calls[1], "10:30", "13:00")]:
        for label, time, dur in [("COFFEE", coffee, 15), ("LUNCH", lunch, 60)]:
            act = ScheduleActivity(day_id=day.id, time=time,
                                   description=f"{label} BREAK")
            db.session.add(act); db.session.flush()
            db.session.add(CrewBreak(
                show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                label=label, duration_minutes=dur))
    db.session.commit()
    return show, day, calls


def test_the_day_shows_two_period_rows_not_six_strips(app, client, db):
    show, day, calls = _day_with_breaks(db, "PD01")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert html.count("2 sittings") == 2          # COFFEE and LUNCH
    assert "☕ BREAK" not in html                  # the old always-on strip


def test_the_editor_is_folded_away_until_asked_for(app, client, db):
    """The clutter was never the feature — it was rendering the form always."""
    show, day, calls = _day_with_breaks(db, "PD02")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert 'id="breaks-%d"' % calls[0].id in html
    assert 'class="collapse px-3 py-2" id="breaks-%d"' % calls[0].id in html
    assert "☕ 2 breaks" in html


def test_the_meal_service_dropdown_is_gone_from_the_day_page(app, client, db):
    """One question, one control. The service follows from the answer."""
    show, day, calls = _day_with_breaks(db, "PD03")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "No meal service" not in html
    assert ">Provided<" in html
    assert ">Not Provided<" in html


def test_a_break_does_not_also_render_as_an_ordinary_activity(app, client, db):
    """It is drawn inside its period row, so it must not get a card as well."""
    from models import CrewBreak
    show, day, calls = _day_with_breaks(db, "PD04")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    for cb in CrewBreak.query.filter_by(show_id=show.id).all():
        assert 'id="act-%d"' % cb.activity_id not in html
    # The crew calls themselves still render as cards.
    for call in calls:
        assert 'id="act-%d"' % call.id in html
