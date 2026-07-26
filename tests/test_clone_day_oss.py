"""#45 — Clone Day must also carry over the day's OSS entries and meal services."""
import datetime as dt


def test_clone_day_copies_oss_entries_and_meals(app, client, db):
    from models import (Show, ScheduleDay, ScheduleActivity, SubScheduleEntry,
                        MealService, MealServiceLocation)
    show = Show(name="Clone Show", code="CL26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 20))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="8:00 AM", description="LOAD IN", sort_order=10)
    db.session.add(act); db.session.flush()
    # a Dock entry linked to the activity + a standalone venue-lights entry
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    activity_id=act.id, type="Dock", activity="Truck 1", sort_order=1))
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    type="House LX", time="18:00", activity="Venue lights up", sort_order=2))
    ms = MealService(show_id=show.id, schedule_day_id=day.id, name="Crew Lunch", kind="lunch")
    db.session.add(ms); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=ms.id, location_name="Backstage", headcount=40))
    db.session.commit()

    client.post("/shows/%d/schedule/%d/clone" % (show.id, day.id), data={})

    new_day = (ScheduleDay.query.filter_by(show_id=show.id)
               .order_by(ScheduleDay.id.desc()).first())
    assert new_day.id != day.id

    entries = SubScheduleEntry.query.filter_by(schedule_day_id=new_day.id).all()
    assert {e.activity for e in entries} == {"Truck 1", "Venue lights up"}   # OSS cloned
    # the Dock entry's activity link was remapped to the CLONED activity
    dock = next(e for e in entries if e.type == "Dock")
    new_act = ScheduleActivity.query.filter_by(day_id=new_day.id).first()
    assert dock.activity_id == new_act.id

    meals = MealService.query.filter_by(schedule_day_id=new_day.id).all()
    assert len(meals) == 1 and meals[0].name == "Crew Lunch"
    assert len(meals[0].locations) == 1
    assert meals[0].locations[0].location_name == "Backstage"
