"""Recurring events sit in the timeline by time, not in a block at the top.

Note 6, 2026-08-11: "All hard-coded events should be inserted chronologically
into the daily schedules where they belong and should not be in a group of
their own at the top."
"""
import datetime as dt

from hardcoded_service import place_in_day as _place_recurring


class _Act:
    def __init__(self, id, time):
        self.id, self.time = id, time


class _Day:
    def __init__(self, activities):
        self.activities = activities


def _item(name, mins):
    return {"id": hash(name) % 1000, "name": name, "sort_min": mins}


def test_event_lands_before_the_first_later_activity():
    day = _Day([_Act(1, "07:00"), _Act(2, "12:00"), _Act(3, "18:00")])
    before, after = _place_recurring(day, [_item("Beverage", 6 * 60 + 30)])
    assert before == {1: [_item("Beverage", 390)]} or list(before) == [1]
    assert after == []


def test_midday_event_lands_before_the_afternoon_activity():
    day = _Day([_Act(1, "07:00"), _Act(2, "12:00"), _Act(3, "18:00")])
    before, after = _place_recurring(day, [_item("Coffee", 9 * 60 + 30)])
    assert list(before) == [2]
    assert after == []


def test_event_after_every_activity_falls_to_the_end():
    """Shown rather than silently dropped."""
    day = _Day([_Act(1, "07:00"), _Act(2, "12:00")])
    before, after = _place_recurring(day, [_item("Lockup", 23 * 60)])
    assert before == {}
    assert [i["name"] for i in after] == ["Lockup"]


def test_several_events_keep_chronological_order_within_a_slot():
    day = _Day([_Act(1, "12:00")])
    before, _ = _place_recurring(
        day, [_item("Late", 11 * 60), _item("Early", 7 * 60)])
    assert [i["name"] for i in before[1]] == ["Early", "Late"]


def test_activities_with_unreadable_times_do_not_capture_events():
    day = _Day([_Act(1, ""), _Act(2, "09:00")])
    before, after = _place_recurring(day, [_item("Sweep", 8 * 60)])
    assert list(before) == [2]
    assert after == []


def test_no_activities_means_everything_falls_to_the_end():
    before, after = _place_recurring(_Day([]), [_item("Sweep", 8 * 60)])
    assert before == {}
    assert len(after) == 1


def test_day_page_places_events_inline_not_in_a_top_block(app, client, db):
    from models import Show, ScheduleDay, ScheduleActivity, HardCodedEvent
    show = Show(name="Place", code="PLC26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 12),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="12:00", description="LUNCH")
    db.session.add(act)
    db.session.add(HardCodedEvent(name="Gate Sweep", start_anchor="SOD",
                                  start_offset=0, active=True))
    db.session.commit()

    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "Gate Sweep" in html
    # It renders in the timeline, immediately above the activity card it
    # precedes. Anchor on the card id — "LUNCH" also appears in the quick-add
    # pills much earlier in the page.
    assert html.index("Gate Sweep") < html.index('id="act-%d"' % act.id)
    # And the old standalone list is gone — the panel only summarises now.
    assert "placed in the schedule below by time" in html
