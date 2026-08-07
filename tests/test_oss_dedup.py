"""
One event, one row.

A real 11-day export had 18% of its rows involved in a duplicate pair — 33 of
them character-identical — because the #39 rollup listed both the day activity
and the OSS entry linked to it. A linked entry IS that activity with
departmental detail attached, so they merge.

Also covers the crew-break collapse: the break builder emits one activity per
crew start ("COFFEE BREAK — 07:00 CREW" at 09:30, "— 08:00 CREW" at 10:30),
which quadrupled every break period on a two-crew-start show.
"""
import datetime as dt


def _items(db, show):
    from models import SubScheduleEntry, MealService
    from oss_export import build_master_items
    entries = SubScheduleEntry.query.filter_by(show_id=show.id).all()
    meals = MealService.query.filter_by(show_id=show.id).all()
    items, _hc = build_master_items(show, entries, meals)
    return items


def _base(db):
    from models import Show, ScheduleDay
    show = Show(name="Dedup Show", code="DD26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8))
    db.session.add(day); db.session.flush()
    return show, day


def test_linked_entry_and_activity_become_one_row(app, db):
    """The real case: an identical-text pair at the same minute."""
    from models import ScheduleActivity, SubScheduleEntry
    show, day = _base(db)
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="OVERNIGHT SECURITY RELEASED",
                           sort_order=10)
    db.session.add(act); db.session.flush()
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Security",
        activity_id=act.id, activity="OVERNIGHT SECURITY RELEASED",
        sort_order=0))
    db.session.commit()

    rows = [i for i in _items(db, show)
            if "OVERNIGHT SECURITY RELEASED" in i["activity"]]
    assert len(rows) == 1, f"expected one merged row, got {len(rows)}"
    assert rows[0]["dept"] == "Security", "should belong to the department"


def test_merge_keeps_the_richer_description_and_both_notes(app, db):
    """The Dock case: same truck, different wording, detail split in two."""
    from models import ScheduleActivity, SubScheduleEntry
    show, day = _base(db)
    act = ScheduleActivity(day_id=day.id, time="07:45",
                           description="CL Truss/LX Truck 1&2 at Dock 00 - Two (2) 53' Semi",
                           notes="WEST LOADING DOCK", sort_order=10)
    db.session.add(act); db.session.flush()
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Dock",
        activity_id=act.id, activity="CL Truss/LX Truck 1&2 - 53' Semi -- LOCAL",
        notes="WEST DOCK", count=2, duration_hrs=0.5, sort_order=0))
    db.session.commit()

    rows = [i for i in _items(db, show) if "Truck 1&2" in i["activity"]]
    assert len(rows) == 1
    assert "at Dock 00" in rows[0]["activity"]      # the longer wording won
    assert "WEST DOCK" in rows[0]["notes"] and "WEST LOADING DOCK" in rows[0]["notes"]
    assert rows[0]["count"] == 2 and rows[0]["duration_hrs"] == 0.5


def test_unlinked_activity_still_gets_its_own_row(app, db):
    """Merging must not swallow activities that stand alone."""
    from models import ScheduleActivity, SubScheduleEntry
    show, day = _base(db)
    db.session.add(ScheduleActivity(day_id=day.id, time="06:00",
                                    description="HEAVY EQUIPMENT DELIVERED",
                                    sort_order=10))
    db.session.add(SubScheduleEntry(
        show_id=show.id, schedule_day_id=day.id, type="Dock",
        time="09:00", activity="UNRELATED DOCK ITEM", sort_order=0))
    db.session.commit()
    labels = [i["activity"] for i in _items(db, show)]
    assert "HEAVY EQUIPMENT DELIVERED" in labels
    assert "UNRELATED DOCK ITEM" in labels


def test_crew_breaks_collapse_to_one_row_per_period(app, db):
    from models import ScheduleActivity
    show, day = _base(db)
    db.session.add_all([
        ScheduleActivity(day_id=day.id, time="09:30",
                         description="COFFEE BREAK — 07:00 CREW", sort_order=10),
        ScheduleActivity(day_id=day.id, time="10:30",
                         description="COFFEE BREAK — 08:00 CREW", sort_order=20),
        ScheduleActivity(day_id=day.id, time="12:00",
                         description="LUNCH BREAK — 07:00 CREW", sort_order=30),
    ])
    db.session.commit()

    items = _items(db, show)
    coffee = [i for i in items if "COFFEE BREAK" in i["activity"]]
    assert len(coffee) == 1, f"coffee break did not collapse: {coffee}"
    assert coffee[0]["time"] == "09:30", "should sit at the earliest call"
    assert "07:00" in coffee[0]["notes"] and "08:00" in coffee[0]["notes"], \
        "both call times must survive in the notes"
    assert len([i for i in items if "LUNCH BREAK" in i["activity"]]) == 1


def test_handwritten_breaks_are_left_alone(app, db):
    """Only the generated '<name> — <time> CREW' pattern collapses."""
    from models import ScheduleActivity
    show, day = _base(db)
    db.session.add_all([
        ScheduleActivity(day_id=day.id, time="08:30",
                         description="MORNING BREAK — 15 min", sort_order=10),
        ScheduleActivity(day_id=day.id, time="14:00",
                         description="MORNING BREAK — 15 min", sort_order=20),
    ])
    db.session.commit()
    rows = [i for i in _items(db, show) if "MORNING BREAK" in i["activity"]]
    assert len(rows) == 2, "hand-written activities must not be merged"


def test_crew_names_move_to_the_crew_sheet(app, db):
    """Master shows a headcount; the Crew sheet carries the names."""
    from models import (ScheduleActivity, CrewMember, CrewRow,
                        ShowCrewAssignment, Company, AgencySetting,
                        SubScheduleEntry, MealService)
    from oss_xlsx import build_workbook
    show, day = _base(db)
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="CREW START", sort_order=10)
    co = Company(name="Acme")
    db.session.add_all([act, co]); db.session.flush()
    for first in ("Ryan", "Rick", "Vince"):
        cm = CrewMember(first_name=first, last_name="Crew", company_id=co.id)
        db.session.add(cm); db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
        db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id,
                               sort_order=1))
    db.session.commit()

    wb = build_workbook(show, [], [], agency=AgencySetting.get())
    master = wb["Master Schedule"]
    labels = [master.cell(row=r, column=3).value
              for r in range(3, master.max_row + 1)]
    assert "3 crew called" in labels, labels
    assert not any(l and "Ryan Crew," in str(l) for l in labels), \
        "the Master sheet should not carry the name list"
    crew_sheet = [wb["Crew"].cell(row=r, column=4).value
                  for r in range(3, wb["Crew"].max_row + 1)]
    assert any(c and "Ryan Crew" in str(c) for c in crew_sheet), crew_sheet
