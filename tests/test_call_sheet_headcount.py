"""The call sheet's Total Crew is models.count_people, and nothing else.

Found 2026-09-09. The call sheet grew its OWN headcount on 09-05 and it was
wrong for four days:

    if line["crew_member_id"]:
        people.add(line["crew_member_id"])   # 7 × Lighting Hand → 1
    else:
        placeholders += line["qty"]

Right for a real person; wrong for local labor, because an unfilled slot also
carries a `crew_member_id` — it points at a stand-in record ("Sparks Lighting
Hand"). That is precisely the failure `count_people`'s docstring exists to
describe, and it names this very day:

    show 3 (MCDC26), day 26: 43 people on the crew calls, and every break
    told F&B 18. Twenty-five people with no meal ordered.

The printed sheet said 18. Measured across MCDC26 on the day this was found,
the sheets totalled 421 against a true 601 — one day was short by 39.

These tests pin the shape of that bug, not just today's numbers: a local
labor line of N bodies is N people even though it names a stand-in, and a
real person on three calls is still one person.
"""
import datetime as dt

import pytest


def _show_with_day(db, name="Headcount Show"):
    from models import Show, ScheduleDay
    show = Show(name=name, code="HC26")
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 9))
    db.session.add(day)
    db.session.flush()
    return show, day


def _activity(db, day, time="8:00 AM", desc="CREW START", sort=10):
    from models import ScheduleActivity
    act = ScheduleActivity(day_id=day.id, time=time, description=desc, sort_order=sort)
    db.session.add(act)
    db.session.flush()
    return act


def _local_labor_position(db, title, department):
    """The catalogue is seeded and `positions.title` is unique, so get-or-create."""
    from models import Position
    pos = Position.query.filter_by(title=title).first()
    if pos is None:
        pos = Position(title=title, department=department, is_local_labor=True)
        db.session.add(pos)
    else:
        pos.is_local_labor = True
    db.session.flush()
    return pos


def test_a_local_labor_line_counts_every_body(app, client, db):
    """`7 × Lighting Hand` is seven people, not one stand-in record."""
    from models import CrewMember, CrewRow, Position

    show, day = _show_with_day(db)
    act = _activity(db, day)

    pos = _local_labor_position(db, "Lighting Hand", "Lighting")

    # The stand-in the local-labor line hangs off — a placeholder name, so
    # `is_unnamed_slot` is True and the row reads as bodies, not a person.
    slot = CrewMember(first_name="TBD", last_name="")
    db.session.add(slot)
    db.session.flush()

    db.session.add(CrewRow(activity_id=act.id, crew_member_id=slot.id,
                           position_id=pos.id, position="Lighting Hand",
                           qty=7, hours=10, sort_order=1))
    db.session.commit()

    r = client.get("/shows/%d/schedule/%d/call-sheet" % (show.id, day.id))
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "7 people" in body, "a 7-body local labor line printed as something else"
    assert "1 person" not in body


def test_a_named_person_on_three_calls_counts_once(app, client, db):
    """The bug the 09-05 change was trying to fix must stay fixed."""
    from models import CrewMember, CrewRow

    show, day = _show_with_day(db, name="Repeat Show")
    cm = CrewMember(first_name="Larry", last_name="Kargol")
    db.session.add(cm)
    db.session.flush()

    for i, (time, desc) in enumerate(
        [("7:00 AM", "CREW START"), ("1:00 PM", "MEAL"), ("6:00 PM", "SHOW")], start=1
    ):
        act = _activity(db, day, time=time, desc=desc, sort=i * 10)
        db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id,
                               position="Technical Director", qty=1,
                               hours=12, sort_order=i))
    db.session.commit()

    r = client.get("/shows/%d/schedule/%d/call-sheet" % (show.id, day.id))
    body = r.get_data(as_text=True)
    assert "1 person" in body, "one person on three calls did not count once"
    assert "3 people" not in body


def test_the_sheet_agrees_with_count_people_on_a_mixed_day(app, client, db):
    """Named crew and local labor together — the sheet is count_people exactly.

    The general guarantee, so this cannot drift back by some new route.
    """
    import models
    from models import CrewMember, CrewRow, Position
    from routes.schedule import _call_sheet_sheet

    show, day = _show_with_day(db, name="Mixed Show")
    act = _activity(db, day)

    pos = _local_labor_position(db, "Rigger High", "Rigging")
    slot = CrewMember(first_name="TBD", last_name="")
    named_a = CrewMember(first_name="Ryan", last_name="Cruz")
    named_b = CrewMember(first_name="Vince", last_name="Suhr")
    db.session.add_all([slot, named_a, named_b])
    db.session.flush()

    db.session.add_all([
        CrewRow(activity_id=act.id, crew_member_id=named_a.id,
                position="Lead Rigger", qty=1, hours=11, sort_order=1),
        CrewRow(activity_id=act.id, crew_member_id=named_b.id,
                position="Rigging PM", qty=1, hours=11, sort_order=2),
        CrewRow(activity_id=act.id, crew_member_id=slot.id, position_id=pos.id,
                position="Rigger High", qty=4, hours=10, sort_order=3),
    ])
    db.session.commit()

    rows = [r for a in day.activities for r in a.ordered_crew_rows]
    expected = models.count_people(rows)
    assert expected == 6, "fixture drifted: 2 named + 4 bodies"

    sheet = _call_sheet_sheet(day)
    assert sheet["total_crew"] == expected

    r = client.get("/shows/%d/schedule/%d/call-sheet" % (show.id, day.id))
    assert "6 people" in r.get_data(as_text=True)
