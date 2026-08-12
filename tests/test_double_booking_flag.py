"""
The Create Crew Call picker flags somebody already on a call that day.

Jason, 2026-08-12: **named people from a company only.** Local labour — an
Encore-style row — is a called POSITION rather than a person, often several of
them and often the same position twice, so seeing it on two calls is normal
work and flagging it would cry wolf on most of the list. The test is
`is_unnamed_slot` (the strict one that already drives name substitution) plus
a company.

A real double booking matters: the person gets two sets of breaks and is
counted on two calls, and `MealServiceLocation.effective_headcount` derives
from those calls — so it inflates what the caterer is told.
"""
import datetime as dt


def _fixture(db):
    from models import (Company, CrewMember, ScheduleDay, Show,
                        ShowCrewAssignment)
    show = Show(name="Double Show", code="DBL26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 6),
                      sod="07:00", eod="19:00")
    co = Company(name="Sparks AV")
    db.session.add_all([day, co])
    db.session.flush()
    return show, day, co


def _person(db, show, co, first="Dana", last="Reyes"):
    from models import CrewMember, ShowCrewAssignment
    cm = CrewMember(first_name=first, last_name=last, active=True,
                    company_id=co.id if co else None)
    db.session.add(cm)
    db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.commit()
    return cm


def _call_with(db, day, time, cm, desc="CREW START"):
    from models import CrewRow, ScheduleActivity
    act = ScheduleActivity(day_id=day.id, time=time, description=desc,
                           sort_order=10)
    db.session.add(act)
    db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id,
                           qty=1, crew_type="Lead Crew", sort_order=10))
    db.session.commit()
    return act


def _modal(client, show, day):
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    return html.split('id="createCrewCallModal"')[1]


def test_a_named_person_already_on_a_call_is_flagged(app, client, db):
    show, day, co = _fixture(db)
    cm = _person(db, show, co)
    _call_with(db, day, "08:00", cm)
    assert "already on 8:00 AM" in _modal(client, show, day)


def test_somebody_on_no_call_is_not_flagged(app, client, db):
    show, day, co = _fixture(db)
    _person(db, show, co)
    assert "already on" not in _modal(client, show, day)


def test_an_unnamed_slot_is_never_flagged(app, client, db):
    """Local labour. A called position, not a person — and the same position
    appearing on two calls is the normal way a show is staffed.
    """
    show, day, co = _fixture(db)
    cm = _person(db, show, co, first="First", last="Last")
    assert cm.is_unnamed_slot          # guard: the fixture is what we think
    _call_with(db, day, "08:00", cm)
    assert "already on" not in _modal(client, show, day)


def test_somebody_with_no_company_is_not_flagged(app, client, db):
    """"Names AND companies" — both halves of Jason's rule."""
    show, day, co = _fixture(db)
    cm = _person(db, show, None, first="Casual", last="Hand")
    _call_with(db, day, "08:00", cm)
    assert "already on" not in _modal(client, show, day)


def test_only_crew_starts_count(app, client, db):
    """Being on a non-crew-call activity is not a double booking."""
    show, day, co = _fixture(db)
    cm = _person(db, show, co)
    _call_with(db, day, "08:00", cm, desc="SOUND CHECK")
    assert "already on" not in _modal(client, show, day)


def test_two_calls_are_both_named(app, client, db):
    show, day, co = _fixture(db)
    cm = _person(db, show, co)
    _call_with(db, day, "08:00", cm)
    _call_with(db, day, "14:00", cm, desc="CREW START — AUDIO")
    body = _modal(client, show, day)
    assert "8:00 AM" in body and "2:00 PM" in body


def test_the_flag_does_not_stop_you_adding_them(app, client, db):
    """A warning, never a block. Jason has real reasons to call somebody
    twice; the point is that it is a decision rather than an accident.
    """
    from models import CrewRow
    show, day, co = _fixture(db)
    cm = _person(db, show, co)
    _call_with(db, day, "08:00", cm)
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "14:00", "crew_member_ids": [str(cm.id)]})
    assert CrewRow.query.filter_by(crew_member_id=cm.id).count() == 2
