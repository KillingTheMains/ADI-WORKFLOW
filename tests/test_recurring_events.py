"""Recurring Events: per-occurrence exceptions (notes 6+7, 2026-08-11).

The calendar-app model. The definition is the series; removing one occurrence
writes an exception rather than deleting anything.
"""
import datetime as dt

from hardcoded_service import hidden_for_day, overlay_for_day


def _setup(db, date=dt.date(2026, 9, 10)):
    from models import Show, ScheduleDay, HardCodedEvent
    show = Show(name="Rec", code="REC26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=date, sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    ev = HardCodedEvent(name="Crew Beverage Set", department="F&B",
                        start_anchor="SOD", start_offset=-30, active=True)
    db.session.add(ev); db.session.flush()
    db.session.commit()
    return show, day, ev


def test_event_shows_by_default(app, db):
    show, day, ev = _setup(db)
    items, _ = overlay_for_day(day)
    assert [i["name"] for i in items] == ["Crew Beverage Set"]


def test_removing_hides_it_on_that_day_only(app, client, db):
    from models import ScheduleDay
    show, day, ev = _setup(db)
    other = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 11),
                        sod="07:00", eod="22:00")
    db.session.add(other); db.session.commit()

    client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                % (show.id, day.id, ev.id))

    assert overlay_for_day(day)[0] == []
    assert [i["name"] for i in overlay_for_day(other)[0]] == ["Crew Beverage Set"]


def test_removal_does_not_leak_to_another_show(app, client, db):
    from models import Show, ScheduleDay
    show, day, ev = _setup(db)
    other_show = Show(name="Rec2", code="REC27")
    db.session.add(other_show); db.session.flush()
    same_date = ScheduleDay(show_id=other_show.id, date=day.date,
                            sod="07:00", eod="22:00")
    db.session.add(same_date); db.session.commit()

    client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                % (show.id, day.id, ev.id))

    assert [i["name"] for i in overlay_for_day(same_date)[0]] == \
        ["Crew Beverage Set"]


def test_hidden_events_are_listed_so_they_can_be_restored(app, client, db):
    """A removal with no visible trace is a trap."""
    show, day, ev = _setup(db)
    client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                % (show.id, day.id, ev.id))
    assert [e.name for e in hidden_for_day(day)] == ["Crew Beverage Set"]


def test_restore_puts_it_back(app, client, db):
    show, day, ev = _setup(db)
    client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                % (show.id, day.id, ev.id))
    client.post("/shows/%d/schedule/%d/recurring/%d/restore"
                % (show.id, day.id, ev.id))
    assert [i["name"] for i in overlay_for_day(day)[0]] == ["Crew Beverage Set"]
    assert hidden_for_day(day) == []


def test_editing_the_series_does_not_resurrect_a_hidden_occurrence(app, client, db):
    """The behaviour Jason and Larry could not resolve in their meeting.

    Editing the definition updates every occurrence still showing, but must
    NOT bring back one the user deliberately removed — otherwise fixing a typo
    silently restores an event on a dark day.
    """
    show, day, ev = _setup(db)
    client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                % (show.id, day.id, ev.id))

    ev.name = "Crew Beverage Set (AM)"
    ev.start_offset = -45
    db.session.commit()

    assert overlay_for_day(day)[0] == []
    assert [e.name for e in hidden_for_day(day)] == ["Crew Beverage Set (AM)"]


def test_removal_survives_day_rows_being_regenerated(app, client, db):
    """Keyed on the DATE, not ScheduleDay.id — #32 regenerates day rows."""
    from models import ScheduleDay
    show, day, ev = _setup(db)
    the_date = day.date
    client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                % (show.id, day.id, ev.id))

    # Simulate #32: drop the day row and recreate it for the same date.
    db.session.delete(day)
    db.session.commit()
    fresh = ScheduleDay(show_id=show.id, date=the_date, sod="07:00", eod="22:00")
    db.session.add(fresh); db.session.commit()

    assert overlay_for_day(fresh)[0] == [], \
        "suppression must follow the date, not the row id"


def test_removing_twice_is_harmless(app, client, db):
    from models import HardCodedEventDayOff
    show, day, ev = _setup(db)
    for _ in range(2):
        client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                    % (show.id, day.id, ev.id))
    assert HardCodedEventDayOff.query.filter_by(
        show_id=show.id, hce_id=ev.id, date=day.date).count() == 1


def test_overlay_items_carry_their_event_id(app, db):
    """The x button needs it to address the right occurrence."""
    show, day, ev = _setup(db)
    items, _ = overlay_for_day(day)
    assert items[0]["id"] == ev.id
