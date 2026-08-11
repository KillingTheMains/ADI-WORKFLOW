"""Recurring events appear in the show book (reported by Jason, 2026-08-11).

The show book rendered day.activities directly, so recurring events never
appeared in it — they existed on the day editor and in the master exports
only. Pre-existing gap, surfaced once the day editor started showing them
inline.
"""
import datetime as dt


def _show_with_recurring(db, code="SB26"):
    from models import Show, ScheduleDay, ScheduleActivity, HardCodedEvent
    show = Show(name="Book", code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 15),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="12:00", description="LUNCH")
    db.session.add(act)
    ev = HardCodedEvent(name="Gate Sweep", start_anchor="SOD",
                        start_offset=0, active=True)
    db.session.add(ev)
    db.session.commit()
    return show, day, act, ev


def test_show_book_includes_recurring_events(app, client, db):
    show, day, act, ev = _show_with_recurring(db)
    html = client.get("/shows/%d/oss/show-book" % show.id).get_data(as_text=True)
    assert "Gate Sweep" in html


def test_show_book_places_them_chronologically(app, client, db):
    show, day, act, ev = _show_with_recurring(db)
    html = client.get("/shows/%d/oss/show-book" % show.id).get_data(as_text=True)
    # 07:00 sweep renders above the 12:00 activity.
    assert html.index("Gate Sweep") < html.index("LUNCH")


def test_a_removed_occurrence_is_absent_from_the_show_book(app, client, db):
    """The show book must respect per-day removals like everything else."""
    show, day, act, ev = _show_with_recurring(db, "SB27")
    client.post("/shows/%d/schedule/%d/recurring/%d/remove"
                % (show.id, day.id, ev.id))
    html = client.get("/shows/%d/oss/show-book" % show.id).get_data(as_text=True)
    assert "Gate Sweep" not in html


def test_day_with_only_recurring_events_is_not_called_empty(app, client, db):
    """A day whose only content is recurring events must not print
    'No activities scheduled' with the events sitting right there."""
    from models import Show, ScheduleDay, HardCodedEvent
    show = Show(name="Book3", code="SB28")
    db.session.add(show); db.session.flush()
    db.session.add(ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 16),
                               sod="07:00", eod="22:00"))
    db.session.add(HardCodedEvent(name="Night Lockup", start_anchor="EOD",
                                  start_offset=30, active=True))
    db.session.commit()

    html = client.get("/shows/%d/oss/show-book" % show.id).get_data(as_text=True)
    assert "Night Lockup" in html
    assert "No activities scheduled for this day" not in html
