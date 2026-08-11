"""How a break reads on a document (2026-08-11).

It used to print the break builder's internal label — "LUNCH BREAK — 7:00 AM
CREW" — on call sheets, the show book and the client PDF. A machine talking to
itself on a document that goes to a client.
"""
import datetime as dt

from breaks import break_export_text


def test_the_printed_text_matches_the_screen(app):
    """Jason: paper should read the way the day page does."""
    assert break_export_text("LUNCH", 60) == "LUNCH — 60 Minutes"
    assert break_export_text("COFFEE", 15) == "COFFEE — 15 Minutes"


def test_a_break_with_no_duration_is_just_its_name(app):
    assert break_export_text("LUNCH", None) == "LUNCH"


def test_the_crew_stamp_is_gone_from_the_text(app):
    """It was only ever there so the export could regex the sittings apart.
    Break rows now carry break_label / break_call_id instead, so a display
    string is no longer load-bearing."""
    assert "CREW" not in break_export_text("LUNCH", 60)


def _show_with_two_sittings(db, code):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, CrewBreak)
    show = Show(name="Paper", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    for time, qty, lunch in [("07:00", 11, "12:00"), ("08:00", 6, "13:00")]:
        call = ScheduleActivity(day_id=day.id, time=time,
                                description="CREW START")
        db.session.add(call); db.session.flush()
        db.session.add(CrewRow(activity_id=call.id, qty=qty, hours=10.0))
        act = ScheduleActivity(
            day_id=day.id, time=lunch,
            description=break_export_text("LUNCH", 60))
        db.session.add(act); db.session.flush()
        db.session.add(CrewBreak(show_id=show.id, activity_id=act.id,
                                 crew_call_id=call.id, label="LUNCH",
                                 duration_minutes=60))
    db.session.commit()
    return show, day


def _lunch_rows(show):
    from oss_export import build_master_items
    items, _hc = build_master_items(show, [], [])
    return [i for i in items if "LUNCH" in (i["activity"] or "")]


def test_the_sittings_collapse_to_one_printed_row(app, db):
    """Same shape as the day page: one row per period, not one per crew."""
    show, day = _show_with_two_sittings(db, "PP01")
    rows = _lunch_rows(show)
    assert len(rows) == 1
    assert rows[0]["activity"] == "LUNCH — 60 Minutes"
    assert rows[0]["time"] == "12:00"


def test_the_printed_count_is_the_whole_period(app, db):
    """It took the earliest sitting's count wholesale, so a lunch that stops
    21 crew printed 11."""
    show, day = _show_with_two_sittings(db, "PP02")
    assert _lunch_rows(show)[0]["count"] == 17      # 11 + 6


def test_both_call_times_stay_legible(app, db):
    show, day = _show_with_two_sittings(db, "PP03")
    notes = _lunch_rows(show)[0]["notes"]
    assert "07:00 crew" in notes and "08:00 crew" in notes


def test_the_builders_internal_label_is_gone(app, db):
    show, day = _show_with_two_sittings(db, "PP04")
    from oss_export import build_master_items
    items, _hc = build_master_items(show, [], [])
    assert not any("LUNCH BREAK" in (i["activity"] or "") for i in items)


def test_adding_a_break_writes_the_printable_text(app, client, db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewBreak)
    show = Show(name="Paper", code="PP05", uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10), sod="07:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.commit()
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/add"
                % (show.id, day.id, call.id),
                data={"label": "LUNCH", "offset_minutes": "300",
                      "duration_minutes": "60"})
    cb = CrewBreak.query.filter_by(show_id=show.id).one()
    assert cb.activity.description == "LUNCH — 60 Minutes"


def test_the_printed_row_carries_the_window(app, db):
    """Paper matches the screen: start, end, and the duration in words."""
    from oss_export import time_range_text
    show, day = _show_with_two_sittings(db, "PP06")
    row = _lunch_rows(show)[0]
    assert row["time"] == "12:00"
    assert row["end_time"] == "13:00"
    assert time_range_text(row) == "12:00 – 13:00"
    assert row["activity"] == "LUNCH — 60 Minutes"


def test_the_time_column_still_sorts_by_the_start(app, db):
    """A range in `time` would fail sort_minutes and sink the row."""
    show, day = _show_with_two_sittings(db, "PP07")
    row = _lunch_rows(show)[0]
    assert row["sort_time"] == 12 * 60


def test_a_row_with_no_end_prints_just_its_start(app):
    from oss_export import time_range_text
    assert time_range_text({"time": "09:00", "end_time": None}) == "09:00"


def test_sittings_split_when_one_crew_takes_two_of_the_same_name(app, db):
    """Same rule the day page uses, so screen and paper agree."""
    from models import ScheduleActivity, CrewBreak
    from oss_export import build_master_items
    show, day = _show_with_two_sittings(db, "PP08")
    call = ScheduleActivity.query.filter_by(day_id=day.id,
                                            description="CREW START").first()
    act = ScheduleActivity(day_id=day.id, time="17:00",
                           description=break_export_text("LUNCH", 60))
    db.session.add(act); db.session.flush()
    db.session.add(CrewBreak(show_id=show.id, activity_id=act.id,
                             crew_call_id=call.id, label="LUNCH",
                             duration_minutes=60))
    db.session.commit()
    items, _hc = build_master_items(show, [], [])
    lunches = [i for i in items if "LUNCH" in (i["activity"] or "")]
    assert len(lunches) == 2          # the 12:00 pair, and the second sitting
