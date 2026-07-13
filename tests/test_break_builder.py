"""
Tests for the crew-start-anchored break builder (board #44).

Breaks hang off each CREW START activity (not a day-level call time), each
labelled with that crew start's time, on a 10-hour default. Crew starts are
the INPUT and are never created or deleted by the builder. No EOD WRAP.
"""
import datetime as dt

DASH = "\u2014"  # em dash used in generated break labels


def _make_day(db):
    from models import Show, ScheduleDay
    show = Show(name="Break Show", code="BS26")
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 16))
    db.session.add(day)
    db.session.commit()
    return show.id, day.id


def _add_activity(db, day_id, time, desc, sort_order=10):
    from models import ScheduleActivity
    a = ScheduleActivity(day_id=day_id, time=time, description=desc, sort_order=sort_order)
    db.session.add(a)
    db.session.commit()


def _acts(day_id):
    from models import ScheduleActivity
    return {a.description: a.time
            for a in ScheduleActivity.query.filter_by(day_id=day_id).all()}


def _descs(day_id):
    from models import ScheduleActivity
    return [a.description for a in ScheduleActivity.query.filter_by(day_id=day_id).all()]


def _build_url(app, show_id, day_id):
    from flask import url_for
    with app.test_request_context():
        return url_for("schedule.build_day_schedule", show_id=show_id, day_id=day_id)


def test_build_breaks_off_single_crew_start(app, client, db):
    show_id, day_id = _make_day(db)
    _add_activity(db, day_id, "8:00 AM", "CREW START")

    r = client.post(_build_url(app, show_id, day_id), data={})
    assert r.status_code in (200, 302)

    acts = _acts(day_id)
    assert acts["COFFEE BREAK " + DASH + " 8:00 AM CREW"] == "10:30 AM"
    assert acts["LUNCH BREAK " + DASH + " 8:00 AM CREW"] == "1:00 PM"
    assert "AFTERNOON BREAK " + DASH + " 8:00 AM CREW" in acts
    # Crew start preserved; no EOD WRAP generated
    assert "CREW START" in acts
    assert not any("EOD" in d for d in acts)


def test_build_breaks_per_crew_start_are_offset(app, client, db):
    show_id, day_id = _make_day(db)
    _add_activity(db, day_id, "8:00 AM", "CREW START", 10)
    _add_activity(db, day_id, "9:00 AM", "CREW START", 20)

    client.post(_build_url(app, show_id, day_id), data={})

    acts = _acts(day_id)
    assert acts["COFFEE BREAK " + DASH + " 8:00 AM CREW"] == "10:30 AM"
    assert acts["COFFEE BREAK " + DASH + " 9:00 AM CREW"] == "11:30 AM"  # one hour later
    assert acts["LUNCH BREAK " + DASH + " 8:00 AM CREW"] == "1:00 PM"
    assert acts["LUNCH BREAK " + DASH + " 9:00 AM CREW"] == "2:00 PM"


def test_build_breaks_no_crew_start_adds_nothing(app, client, db):
    show_id, day_id = _make_day(db)
    _add_activity(db, day_id, "10:00 AM", "DOORS OPEN")

    client.post(_build_url(app, show_id, day_id), data={})

    assert _descs(day_id) == ["DOORS OPEN"]  # nothing generated without a crew start


def test_replace_regenerates_without_touching_crew_start_or_user_rows(app, client, db):
    show_id, day_id = _make_day(db)
    _add_activity(db, day_id, "8:00 AM", "CREW START", 10)
    _add_activity(db, day_id, "9:00 AM", "DOORS OPEN", 20)

    client.post(_build_url(app, show_id, day_id), data={})            # first build
    client.post(_build_url(app, show_id, day_id), data={"replace": "1"})  # regenerate

    descs = _descs(day_id)
    assert descs.count("CREW START") == 1          # input preserved
    assert descs.count("DOORS OPEN") == 1          # unrelated activity preserved
    assert descs.count("COFFEE BREAK " + DASH + " 8:00 AM CREW") == 1  # no duplicates
    assert descs.count("LUNCH BREAK " + DASH + " 8:00 AM CREW") == 1
