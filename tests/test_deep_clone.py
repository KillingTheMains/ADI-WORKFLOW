"""Deep clone: a working copy of a live show (2026-08-11).

Structure-only cloning wipes crew and drops F&B, which is right for "next
year's version" and useless for rehearsing a change against real data.
"""
import datetime as dt


def _rich_show(db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        CrewMember, ShowCrewAssignment, MealService,
                        MealServiceLocation, SubScheduleEntry, Company)
    co = Company(name="Encore", code="ENCORE")
    db.session.add(co); db.session.flush()
    show = Show(name="Rich", code="RCH26")
    db.session.add(show); db.session.flush()
    cm = CrewMember(first_name="Real", last_name="Person", company_id=co.id)
    db.session.add(cm); db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id,
                                      booking_task="PREP", sort_order=10))
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 25),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:00",
                           description="CREW START")
    db.session.add(act); db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id, qty=1,
                           hours=10))
    db.session.add(CrewRow(activity_id=act.id, is_group_header=True,
                           group_label="ENCORE", header_level=1,
                           company_id=co.id, sort_order=1))
    ms = MealService(show_id=show.id, schedule_day_id=day.id,
                     activity_id=act.id, name="Lunch", kind="lunch")
    db.session.add(ms); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=ms.id,
                                       location_name="Ballroom",
                                       start_time="12:00", headcount=11))
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    activity_id=act.id, type="Dock",
                                    time="06:00", activity="Truck 1"))
    db.session.commit()
    return show, cm, co


def _clone(client, show, deep):
    data = {"new_name": "Clone", "new_code": "CLN26", "date_offset_days": "0"}
    if deep:
        data["deep"] = "1"
    client.post("/shows/%d/duplicate" % show.id, data=data,
                follow_redirects=True)
    from models import Show
    return Show.query.filter_by(code="CLN26").one()


def test_structure_clone_still_wipes_crew(app, client, db):
    """The existing behaviour must not change."""
    from models import CrewRow
    show, cm, co = _rich_show(db)
    new = _clone(client, show, deep=False)
    rows = [r for d in new.days for a in d.activities for r in a.crew_rows]
    assert rows, "activities should still be copied"
    assert all(r.crew_member_id is None for r in rows if not r.is_group_header)


def test_deep_clone_keeps_the_crew_links(app, client, db):
    show, cm, co = _rich_show(db)
    new = _clone(client, show, deep=True)
    rows = [r for d in new.days for a in d.activities for r in a.crew_rows
            if not r.is_group_header]
    assert [r.crew_member_id for r in rows] == [cm.id]


def test_deep_clone_copies_the_roster(app, client, db):
    from models import ShowCrewAssignment
    show, cm, co = _rich_show(db)
    new = _clone(client, show, deep=True)
    assignments = ShowCrewAssignment.query.filter_by(show_id=new.id).all()
    assert [a.crew_member_id for a in assignments] == [cm.id]
    assert assignments[0].booking_task == "PREP"


def test_deep_clone_copies_meal_services_and_locations(app, client, db):
    from models import MealService
    show, cm, co = _rich_show(db)
    new = _clone(client, show, deep=True)
    services = MealService.query.filter_by(show_id=new.id).all()
    assert len(services) == 1
    assert services[0].name == "Lunch"
    assert [(l.location_name, l.headcount) for l in services[0].locations] == \
        [("Ballroom", 11)]


def test_deep_clone_copies_oss_entries(app, client, db):
    from models import SubScheduleEntry
    show, cm, co = _rich_show(db)
    new = _clone(client, show, deep=True)
    entries = SubScheduleEntry.query.filter_by(show_id=new.id).all()
    assert [(e.type, e.activity) for e in entries] == [("Dock", "Truck 1")]


def test_cloned_links_point_at_the_clone_not_the_original(app, client, db):
    """A mis-mapped id is worse than a missing row — it looks correct."""
    from models import MealService, SubScheduleEntry
    show, cm, co = _rich_show(db)
    new = _clone(client, show, deep=True)
    new_act_ids = {a.id for d in new.days for a in d.activities}
    new_day_ids = {d.id for d in new.days}

    for ms in MealService.query.filter_by(show_id=new.id).all():
        assert ms.schedule_day_id in new_day_ids
        assert ms.activity_id in new_act_ids
    for e in SubScheduleEntry.query.filter_by(show_id=new.id).all():
        assert e.schedule_day_id in new_day_ids
        assert e.activity_id in new_act_ids


def test_deep_clone_carries_section_headers(app, client, db):
    show, cm, co = _rich_show(db)
    new = _clone(client, show, deep=True)
    headers = [r for d in new.days for a in d.activities
               for r in a.crew_rows if r.is_group_header]
    assert [(h.group_label, h.header_level, h.company_id) for h in headers] == \
        [("ENCORE", 1, co.id)]


def test_clone_does_not_inherit_the_new_breaks_flag(app, client, db):
    """A copy of a switched-over show starts on the old behaviour until
    someone deliberately switches it too."""
    show, cm, co = _rich_show(db)
    show.uses_new_breaks = True
    db.session.commit()
    new = _clone(client, show, deep=True)
    assert not new.uses_new_breaks
