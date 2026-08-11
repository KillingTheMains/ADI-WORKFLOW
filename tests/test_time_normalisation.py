"""
One canonical stored time format: 24-hour HH:MM.

An HTML <input type="time"> accepts ONLY 24-hour HH:MM. Given "1:00 PM" the
browser renders an EMPTY box — and because the F&B location rows autosave,
that empty box posted straight back and wiped the stored time. Same class of
bug hid activity times, SOD/EOD and travel times on the day page.
"""
import datetime as dt

import pytest


def _show_day(db, name, code):
    from models import Show, ScheduleDay
    show = Show(name=name, code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 5))
    db.session.add(day); db.session.flush()
    return show, day


@pytest.mark.parametrize("stored,expected", [
    ("1:00 PM", "13:00"), ("13:00", "13:00"), ("8:00 AM", "08:00"),
    ("8:00", "08:00"), ("12:00 AM", "00:00"), ("", ""), (None, ""),
    ("TBD", ""),
])
def test_to_24hr_filter(app, stored, expected):
    """The filter feeding every <input type='time' value=...>."""
    with app.app_context():
        rendered = app.jinja_env.filters["to_24hr"](stored)
    assert rendered == expected


def test_fb_tab_time_input_is_24h_for_12h_data(app, client, db):
    """A meal stored as '1:00 PM' must still populate its time box."""
    from models import MealService, MealServiceLocation
    show, day = _show_day(db, "Input Show", "IN26")
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Legacy Lunch", kind="lunch", sort_order=0)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       location_name="Backstage",
                                       start_time="1:00 PM", sort_order=0))
    db.session.commit()

    body = client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)
    # The F&B tab reframe (2026-08-11) namespaces location fields by id so a
    # whole service saves in one submit. The rule this guards is unchanged:
    # an <input type="time"> renders EMPTY for anything but 24-hour HH:MM, and
    # that blank posts back and wipes the stored time.
    import re
    flat = re.sub(r"\s+", " ", body)      # attributes may wrap across lines
    loc = svc.locations[0]
    assert 'name="loc_%d_start_time" value="13:00"' % loc.id in flat, \
        "12-hour meal time did not render into the time input"


def test_saving_a_meal_row_stores_24h(app, client, db):
    """Whatever the browser posts, storage is canonical."""
    from models import MealService, MealServiceLocation
    show, day = _show_day(db, "Save Show", "SV26")
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Lunch", kind="lunch", sort_order=0)
    db.session.add(svc); db.session.flush()
    loc = MealServiceLocation(meal_service_id=svc.id, location_name="BOH",
                              start_time="11:00", sort_order=0)
    db.session.add(loc); db.session.commit()
    loc_id = loc.id

    client.post("/shows/%d/oss/fb/location/%d/edit" % (show.id, loc_id),
                data={"location_name": "BOH", "start_time": "2:30 PM",
                      "end_time": "15:00", "headcount": "12", "notes": ""})
    refreshed = db.session.get(MealServiceLocation, loc_id)
    assert refreshed.start_time == "14:30"
    assert refreshed.end_time == "15:00"


def test_day_templates_yield_24h_times(app, db):
    """Seeded templates carry 12-hour text; consumers must not see it."""
    from models import DayTemplate
    tpl = DayTemplate(key="t-24h", label="T",
                      activities_json='[["8:00 AM", "CREW START"], '
                                      '["1:00 PM", "AFTERNOON SESSION"]]')
    db.session.add(tpl); db.session.commit()
    assert tpl.activities == [["08:00", "CREW START"],
                              ["13:00", "AFTERNOON SESSION"]]


def test_normalisation_migration_rewrites_stored_times(app, db):
    """The one-shot migration converts existing 12-hour data in place."""
    from migrations import _normalise_stored_times_to_24h
    from models import (ScheduleActivity, MealService, MealServiceLocation,
                        DayTemplate)
    show, day = _show_day(db, "Mig Show", "MG26")
    day.sod, day.eod = "7:00 AM", "11:00 PM"
    act = ScheduleActivity(day_id=day.id, time="1:00 PM",
                           description="AFTERNOON SESSION", sort_order=10)
    unreadable = ScheduleActivity(day_id=day.id, time="whenever",
                                  description="TBC", sort_order=20)
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Lunch", kind="lunch", sort_order=0)
    db.session.add_all([act, unreadable, svc]); db.session.flush()
    loc = MealServiceLocation(meal_service_id=svc.id, location_name="BOH",
                              start_time="12:30 PM", end_time="1:15 PM",
                              sort_order=0)
    tpl = DayTemplate(key="mig-tpl", label="T",
                      activities_json='[["8:00 AM", "CREW START"]]')
    db.session.add_all([loc, tpl]); db.session.commit()

    _normalise_stored_times_to_24h(db.session)

    assert act.time == "13:00"
    assert unreadable.time == "whenever"   # unparseable left untouched, not guessed
    assert (day.sod, day.eod) == ("07:00", "23:00")
    assert (loc.start_time, loc.end_time) == ("12:30", "13:15")
    assert '"08:00"' in tpl.activities_json
