"""
Tests for the Start of Day / End of Day anchors (board #36).

SOD/EOD are standalone per-day fields that replace Call/Wrap in Day Settings.
The legacy call_time/wrap_time columns are retained (Smart Breaks still reads
them until it's re-anchored to crew starts in #44), so the edit path must never
wipe them, and a partial save must never wipe SOD/EOD.
"""
import datetime as dt


def _make_show_day(db, **day_kwargs):
    from models import Show, ScheduleDay
    show = Show(name="Test Show", code="TS26")
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 16), **day_kwargs)
    db.session.add(day)
    db.session.commit()
    return show.id, day.id


# --- Backfill migration ---

def test_backfill_seeds_sod_eod_from_call_wrap(db):
    from migrations import _backfill_sod_eod_from_call_wrap
    from models import ScheduleDay
    _, day_id = _make_show_day(db, call_time="6:00 AM", wrap_time="10:00 PM")
    assert ScheduleDay.query.get(day_id).sod is None

    _backfill_sod_eod_from_call_wrap(db.session)

    day = ScheduleDay.query.get(day_id)
    assert day.sod == "6:00 AM"
    assert day.eod == "10:00 PM"


def test_backfill_never_overwrites_existing_sod_eod(db):
    from migrations import _backfill_sod_eod_from_call_wrap
    from models import ScheduleDay
    _, day_id = _make_show_day(db, call_time="6:00 AM", wrap_time="10:00 PM",
                               sod="5:00 AM", eod="11:00 PM")

    _backfill_sod_eod_from_call_wrap(db.session)

    day = ScheduleDay.query.get(day_id)
    assert day.sod == "5:00 AM"   # pre-existing value untouched
    assert day.eod == "11:00 PM"


# --- Display ---

def test_time_window_uses_sod_eod(db):
    from models import ScheduleDay
    _, day_id = _make_show_day(db, sod="6:00 AM", eod="10:00 PM")
    assert ScheduleDay.query.get(day_id).time_window == "6:00 AM \u2013 10:00 PM"


def test_time_window_falls_back_to_call_wrap(db):
    from models import ScheduleDay
    _, day_id = _make_show_day(db, call_time="7:00 AM", wrap_time="9:00 PM")
    assert ScheduleDay.query.get(day_id).time_window == "7:00 AM \u2013 9:00 PM"


# --- Non-destructive edit path ---

def test_edit_day_sets_sod_eod_and_preserves_call_time(app, client, db):
    from flask import url_for
    from models import ScheduleDay
    show_id, day_id = _make_show_day(db, call_time="6:00 AM", wrap_time="10:00 PM",
                                     sod="6:00 AM", eod="10:00 PM")
    with app.test_request_context():
        url = url_for("schedule.edit_day", show_id=show_id, day_id=day_id)

    # Day Settings save: carries sod/eod + date, but NOT call_time/wrap_time.
    r = client.post(url, data={"date": "2026-07-16", "sod": "7:00 AM", "eod": "11:00 PM"})
    assert r.status_code in (200, 302)

    day = ScheduleDay.query.get(day_id)
    assert day.sod == "7:00 AM"
    assert day.eod == "11:00 PM"
    # Legacy call_time must survive -- Smart Breaks still reads it.
    assert day.call_time == "6:00 AM"


def test_edit_day_partial_save_preserves_sod_eod(app, client, db):
    from flask import url_for
    from models import ScheduleDay
    show_id, day_id = _make_show_day(db, sod="6:00 AM", eod="10:00 PM")
    with app.test_request_context():
        url = url_for("schedule.edit_day", show_id=show_id, day_id=day_id)

    # Travel-info autosave style: no sod/eod fields present in the form.
    r = client.post(url, data={"date": "2026-07-16", "travel_airline": "United"})
    assert r.status_code in (200, 302)

    day = ScheduleDay.query.get(day_id)
    assert day.sod == "6:00 AM"    # not wiped by an unrelated partial save
    assert day.eod == "10:00 PM"
