"""
OSS surfaces must be chronological regardless of creation order.

Two distinct defects are covered here:

1. FORMAT — the master built sort keys from raw display strings for OSS
   entries and meals, but normalised 24-hour keys for activities/crew/
   hard-coded events. Lexically "1:00 PM" > "18:00", so afternoon OSS rows
   sank to the bottom of the day.

2. CREATION ORDER — meal services and their locations were ordered by
   sort_order, which is assigned at creation, so a meal added later sat at
   the bottom of its day no matter what time it was set to.

Note: the OSS page renders EVERY tab pane into the DOM, so assertions must
be scoped to the pane under test or they silently measure the master table.
"""
import datetime as dt

import pytest

# The master pane is rendered first; department panes start at id="tab-1".
_DEPT_MARKER = 'id="tab-1"'


def _master_pane(body):
    return body[:body.index(_DEPT_MARKER)]


def _dept_panes(body):
    return body[body.index(_DEPT_MARKER):]


def _show_with_day(db, name, code, when=dt.date(2026, 9, 14)):
    from models import Show, ScheduleDay
    show = Show(name=name, code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=when)
    db.session.add(day); db.session.flush()
    return show, day


def test_afternoon_oss_entry_sorts_between_morning_and_evening(app, client, db):
    """A 1:00 PM Dock entry belongs between the 8 AM and 6 PM activities."""
    from models import ScheduleActivity, SubScheduleEntry
    show, day = _show_with_day(db, "Chrono Show", "CH26")
    db.session.add_all([
        ScheduleActivity(day_id=day.id, time="8:00 AM",
                         description="MORNING LOAD IN", sort_order=10),
        ScheduleActivity(day_id=day.id, time="6:00 PM",
                         description="EVENING DOORS", sort_order=20),
    ])
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Dock",
        time="1:00 PM", activity="AFTERNOON DOCK PUSH", sort_order=0))
    db.session.commit()

    pane = _master_pane(
        client.get("/shows/%d/oss?tab=master" % show.id).get_data(as_text=True))
    assert (pane.index("MORNING LOAD IN")
            < pane.index("AFTERNOON DOCK PUSH")
            < pane.index("EVENING DOORS")), "1 PM entry not in chronological position"


def test_master_places_meal_service_by_clock(app, client, db):
    """A noon meal sits between the 8 AM and 6 PM activities in the master."""
    from models import ScheduleActivity, MealService, MealServiceLocation
    show, day = _show_with_day(db, "Meal Master", "MM26")
    db.session.add_all([
        ScheduleActivity(day_id=day.id, time="8:00 AM",
                         description="MORNING LOAD IN", sort_order=10),
        ScheduleActivity(day_id=day.id, time="6:00 PM",
                         description="EVENING DOORS", sort_order=20),
    ])
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="MIDDAY CREW MEAL", kind="lunch", sort_order=0)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       location_name="Backstage",
                                       start_time="12:30 PM", sort_order=0))
    db.session.commit()

    pane = _master_pane(
        client.get("/shows/%d/oss?tab=master" % show.id).get_data(as_text=True))
    assert (pane.index("MORNING LOAD IN")
            < pane.index("MIDDAY CREW MEAL")
            < pane.index("EVENING DOORS"))


def test_department_tab_orders_am_before_pm(app, client, db):
    """Lexically '10:00 AM' < '8:00 AM'; chronologically it is not."""
    from models import SubScheduleEntry
    show, day = _show_with_day(db, "Tab Show", "TB26")
    # Created late-first so creation order can't accidentally pass the test.
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Dock",
        time="10:00 AM", activity="LATE DOCK CALL", sort_order=0))
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Dock",
        time="8:00 AM", activity="EARLY DOCK CALL", sort_order=1))
    db.session.commit()

    pane = _dept_panes(
        client.get("/shows/%d/oss?tab=Dock" % show.id).get_data(as_text=True))
    assert pane.index("EARLY DOCK CALL") < pane.index("LATE DOCK CALL")


def test_entry_with_no_time_sorts_last_not_first(app, client, db):
    """Untimed rows park at the end of the day rather than jumping the queue."""
    from models import SubScheduleEntry
    show, day = _show_with_day(db, "Blank Show", "BL26")
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Dock",
        time="", activity="BLANK DOCK ITEM", sort_order=0))
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Dock",
        time="9:00 AM", activity="CLOCKED DOCK ITEM", sort_order=1))
    db.session.commit()

    pane = _dept_panes(
        client.get("/shows/%d/oss?tab=Dock" % show.id).get_data(as_text=True))
    assert pane.index("CLOCKED DOCK ITEM") < pane.index("BLANK DOCK ITEM")


def test_fb_meal_added_later_still_sorts_by_time(app, client, db):
    """Dinner created first, lunch second — lunch must still render first."""
    from models import MealService, MealServiceLocation
    show, day = _show_with_day(db, "Meal Show", "ML26")
    dinner = MealService(show_id=show.id, schedule_day_id=day.id,
                         name="CREW DINNER SERVICE", kind="dinner", sort_order=0)
    db.session.add(dinner); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=dinner.id,
                                       location_name="Backstage",
                                       start_time="5:00 PM", sort_order=0))
    lunch = MealService(show_id=show.id, schedule_day_id=day.id,
                        name="CREW LUNCH SERVICE", kind="lunch", sort_order=1)
    db.session.add(lunch); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=lunch.id,
                                       location_name="Backstage",
                                       start_time="12:00 PM", sort_order=0))
    db.session.commit()

    pane = _dept_panes(
        client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True))
    assert pane.index("CREW LUNCH SERVICE") < pane.index("CREW DINNER SERVICE")


def test_meal_locations_render_in_time_order(app, client, db):
    """Locations within one service follow the clock, not insertion order."""
    from models import MealService, MealServiceLocation
    show, day = _show_with_day(db, "Loc Show", "LC26")
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Staggered Lunch", kind="lunch", sort_order=0)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       location_name="LATE ROOM",
                                       start_time="2:00 PM", sort_order=0))
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       location_name="EARLY ROOM",
                                       start_time="11:30 AM", sort_order=1))
    db.session.commit()

    pane = _dept_panes(
        client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True))
    assert pane.index("EARLY ROOM") < pane.index("LATE ROOM")


def test_earliest_time_is_chronological_not_lexical(app, db):
    """'9:00 AM' beats '10:00 AM' on the clock but loses a string compare."""
    from models import MealService, MealServiceLocation
    show, day = _show_with_day(db, "Early Show", "ER26")
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Breakfast", kind="breakfast", sort_order=0)
    db.session.add(svc); db.session.flush()
    db.session.add_all([
        MealServiceLocation(meal_service_id=svc.id, location_name="A",
                            start_time="10:00 AM", sort_order=0),
        MealServiceLocation(meal_service_id=svc.id, location_name="B",
                            start_time="9:00 AM", sort_order=1),
    ])
    db.session.commit()
    assert svc.earliest_time == "9:00 AM"


@pytest.mark.parametrize("value,expected", [
    ("1:00 PM", 780), ("13:00", 780), ("8:00", 480), ("8:00 AM", 480),
    ("08:00", 480), ("12:00 AM", 0), ("12:00 PM", 720), ("7:30 p.m.", 1170),
    ("9AM", 540), ("6:00 PM (doors)", 1080),
    ("", None), (None, None), ("lunch", None), ("25:00", None), ("8:99", None),
])
def test_parse_minutes(value, expected):
    from time_utils import parse_minutes
    assert parse_minutes(value) == expected


def test_unreadable_times_sort_after_real_ones():
    from time_utils import sort_minutes
    assert sort_minutes("11:59 PM") < sort_minutes("")
    assert sort_minutes("11:59 PM") < sort_minutes("TBD")
