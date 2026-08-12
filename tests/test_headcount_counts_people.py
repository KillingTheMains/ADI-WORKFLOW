"""
A line of 7 is 7 people. Everywhere.

⚠️ THIS WAS WRONG IN PRODUCTION UNTIL 2026-08-12 and it under-fed crews.

`crew_headcount` did `if row.crew_member_id: named_ids.add(...)`, counting one
person and discarding `qty`. Correct for a real person — one human however
many rows they hold. But an UNFILLED SLOT also carries a `crew_member_id`,
pointing at a placeholder record like "Sparks Lighting Hand". So `7 × Lighting
Hand` counted as 1, and several rows sharing one placeholder collapsed into
each other.

Measured on production the day it was found — show 3 (MCDC26), day 26:
**43 people on the crew calls, every break telling F&B 18.**

Jason: "Even though 'Lighting Hand' is 1 line item in the crew call, there are
7 humans that make up that line item. They all incur hours and they all need
to be accounted for when meals and beverages are taken into account."
"""
import datetime as dt


def _fixture(db):
    from models import Company, ScheduleActivity, ScheduleDay, Show
    show = Show(name="Count Show", code="CNT26")
    show.uses_new_breaks = True
    co = Company(name="Sparks")
    db.session.add_all([show, co])
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 25),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="CREW START", sort_order=10)
    db.session.add(act)
    db.session.commit()
    return show, day, act, co


def _slot(db, co, position="Lighting Hand"):
    """An UNFILLED SLOT — a placeholder crew record, exactly as production has.

    `display_label` renders these as "Sparks Lighting Hand", which is why they
    read like a person and were counted like one.
    """
    from models import CrewMember, Position
    pos = Position.query.filter_by(title=position).first() or Position(
        title=position, department="Lighting", type="hand")
    db.session.add(pos)
    cm = CrewMember(first_name="First", last_name="Last", active=True,
                    company_id=co.id, position_id=pos.id)
    db.session.add(cm)
    db.session.commit()
    assert cm.is_unnamed_slot, "fixture must be an unfilled slot"
    return cm, pos


def _row(db, act, **kw):
    from models import CrewRow
    kw.setdefault("crew_type", "Local Crew")
    r = CrewRow(activity_id=act.id, sort_order=10, **kw)
    db.session.add(r)
    db.session.commit()
    return r


def test_an_unfilled_slot_of_seven_is_seven_people(app, db):
    """The bug, as one assertion. This returned 1."""
    show, day, act, co = _fixture(db)
    cm, pos = _slot(db, co)
    _row(db, act, qty=7, crew_member_id=cm.id, position_id=pos.id,
         position="Lighting Hand")
    db.session.expire_all()
    assert act.crew_headcount == 7


def test_two_lines_sharing_one_placeholder_do_not_collapse(app, db):
    """Production reuses one "Sparks Lighting Hand" record across rows. The
    old `set()` of crew_member_ids merged them into a single person.
    """
    show, day, act, co = _fixture(db)
    cm, pos = _slot(db, co)
    _row(db, act, qty=7, crew_member_id=cm.id, position_id=pos.id)
    _row(db, act, qty=4, crew_member_id=cm.id, position_id=pos.id)
    db.session.expire_all()
    assert act.crew_headcount == 11


def test_a_real_person_still_counts_once_across_rows(app, db):
    """The behaviour the old code got RIGHT, which the fix must not break."""
    from models import CrewMember
    show, day, act, co = _fixture(db)
    person = CrewMember(first_name="Dana", last_name="Reyes", active=True,
                        company_id=co.id)
    db.session.add(person)
    db.session.commit()
    _row(db, act, qty=1, crew_member_id=person.id, crew_type="Lead Crew")
    _row(db, act, qty=1, crew_member_id=person.id, crew_type="Lead Crew")
    db.session.expire_all()
    assert act.crew_headcount == 1


def test_leads_and_local_add_up(app, db):
    from models import CrewMember
    show, day, act, co = _fixture(db)
    cm, pos = _slot(db, co)
    person = CrewMember(first_name="Dana", last_name="Reyes", active=True)
    db.session.add(person)
    db.session.commit()
    _row(db, act, qty=1, crew_member_id=person.id, crew_type="Lead Crew")
    _row(db, act, qty=7, crew_member_id=cm.id, position_id=pos.id)
    db.session.expire_all()
    assert act.crew_headcount == 8


def test_a_section_header_is_nobody(app, db):
    show, day, act, co = _fixture(db)
    cm, pos = _slot(db, co)
    _row(db, act, qty=7, crew_member_id=cm.id, position_id=pos.id)
    _row(db, act, qty=0, is_group_header=True, group_label="SPARKS")
    db.session.expire_all()
    assert act.crew_headcount == 7


def test_the_day_count_agrees_with_the_calls(app, db):
    show, day, act, co = _fixture(db)
    cm, pos = _slot(db, co)
    _row(db, act, qty=7, crew_member_id=cm.id, position_id=pos.id)
    db.session.expire_all()
    assert day.computed_crew_count == 7


def test_the_meal_is_ordered_for_all_of_them(app, client, db):
    """The whole point. F&B reads this number.

    Reproduces the production shape: a crew call, a real break on it, and a
    seven-person line. The break used to say 1.
    """
    from models import CrewBreak, ScheduleActivity
    show, day, act, co = _fixture(db)
    db.session.delete(act)
    db.session.commit()
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "08:00", "add_breaks": "1"})
    call = ScheduleActivity.query.filter_by(day_id=day.id,
                                            description="CREW START").one()
    cm, pos = _slot(db, co)
    _row(db, call, qty=7, crew_member_id=cm.id, position_id=pos.id)
    db.session.expire_all()

    meal = CrewBreak.query.filter_by(offset_minutes=300).one()
    assert meal.derived_headcount == 7


def test_hours_are_per_person_and_multiply_out(app, client, db):
    """"They all incur hours." Seven hands at 10 hours is 70 man-hours."""
    show, day, act, co = _fixture(db)
    cm, pos = _slot(db, co)
    _row(db, act, qty=7, hours=10.0, crew_member_id=cm.id, position_id=pos.id)
    db.session.expire_all()
    html = client.get(f"/shows/{show.id}/crew/hours").get_data(as_text=True)
    assert "70" in html


def test_the_count_can_only_have_gone_up(app, db):
    """A headcount that shrinks silently tells a caterer to bring less food
    than last week for the same crew. Every shape here must be >= the old
    rule's answer.
    """
    from models import CrewMember, count_people
    show, day, act, co = _fixture(db)
    person = CrewMember(first_name="Dana", last_name="Reyes", active=True)
    db.session.add(person)
    db.session.commit()
    cm, pos = _slot(db, co)
    rows = [
        _row(db, act, qty=1, crew_member_id=person.id, crew_type="Lead Crew"),
        _row(db, act, qty=7, crew_member_id=cm.id, position_id=pos.id),
        _row(db, act, qty=3),
        _row(db, act, qty=1),
    ]
    # The old rule: named ids deduped to 1 each, qty only for rows with no
    # crew member at all.
    old_named = {r.crew_member_id for r in rows if r.crew_member_id}
    old = len(old_named) + sum((r.qty or 1) for r in rows if not r.crew_member_id)
    assert count_people(rows) >= old
    assert count_people(rows) == 12
