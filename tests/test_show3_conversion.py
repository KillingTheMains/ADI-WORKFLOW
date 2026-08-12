"""
Show 3 (MCDC26) → local labour.

A one-off conversion against a mapping measured off production and approved
title by title. These tests build the production SHAPE — placeholder crew
records, multi-person rows, the mislabelled stewards — and check the migration
does the approved thing to it.

The mapping itself lives in `local_labor_show3.py`; the table with row counts
is in `ADI_Show3_Local_Labor_Mapping.md`.
"""
import datetime as dt


def _show3(db):
    """A show with id 3, because the migration is scoped to that show."""
    from models import Company, ScheduleActivity, ScheduleDay, Show
    show = Show(id=3, name="MCDC26", code="MCDC26")
    show.uses_new_breaks = True
    co = Company(name="Sparks")
    db.session.add_all([show, co])
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 28),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="CREW START", sort_order=10)
    db.session.add(act)
    db.session.commit()
    return show, day, act, co


def _slot_row(db, act, co, position, qty=1, label=None):
    """An unfilled row exactly as production has them: a placeholder crew
    record whose `display_label` reads "Sparks <something>".
    """
    from models import CrewMember, CrewRow, Position
    label = label or position
    pos = Position.query.filter_by(title=label).first()
    if pos is None:
        pos = Position(title=label, department="General", type="hand")
        db.session.add(pos)
        db.session.flush()
    cm = CrewMember(first_name="First", last_name="Last", active=True,
                    company_id=co.id, position_id=pos.id)
    db.session.add(cm)
    db.session.flush()
    assert cm.is_unnamed_slot
    row = CrewRow(activity_id=act.id, qty=qty, position=position,
                  crew_member_id=cm.id, crew_type="Union Crew", sort_order=10)
    db.session.add(row)
    db.session.commit()
    return row


def _convert(db):
    from migrations import _convert_show3_to_local_labor
    _convert_show3_to_local_labor(db.session)
    db.session.commit()


def test_a_hand_row_is_linked_and_typed(app, db):
    show, day, act, co = _show3(db)
    row = _slot_row(db, act, co, "Lighting Hand", qty=7)
    _convert(db)
    db.session.expire_all()
    assert row.crew_type == "Local Crew"
    assert row.position_ref.title == "Lighting Hand"
    assert row.position_ref.is_local_labor is True
    assert row.is_local_labor is True


def test_the_quantity_and_hours_are_untouched(app, db):
    """The conversion links and labels. It does not renumber anything."""
    from models import CrewRow
    show, day, act, co = _show3(db)
    row = _slot_row(db, act, co, "Scenic Hand", qty=11)
    row.hours = 10.5
    row.notes = "catwalks"
    db.session.commit()
    _convert(db)
    db.session.expire_all()
    again = CrewRow.query.get(row.id)
    assert again.qty == 11
    assert again.hours == 10.5
    assert again.notes == "catwalks"
    assert again.crew_member_id is not None


def test_a_real_person_is_left_alone(app, db):
    """Only rows with nobody in them convert."""
    from models import CrewMember, CrewRow
    show, day, act, co = _show3(db)
    person = CrewMember(first_name="Dana", last_name="Reyes", active=True)
    db.session.add(person)
    db.session.flush()
    row = CrewRow(activity_id=act.id, qty=1, position="A1",
                  crew_member_id=person.id, crew_type="Lead Crew",
                  sort_order=10)
    db.session.add(row)
    db.session.commit()
    _convert(db)
    db.session.expire_all()
    assert row.crew_type == "Lead Crew"
    assert row.is_local_labor is False


def test_every_steward_collapses_to_one_title(app, db):
    show, day, act, co = _show3(db)
    a = _slot_row(db, act, co, "Steward", label="Steward")
    b = _slot_row(db, act, co, "Steward - 2nd", label="Steward")
    _convert(db)
    db.session.expire_all()
    assert a.position_ref.title == "Labor Steward"
    assert b.position_ref.title == "Labor Steward"


def test_the_mislabelled_stewards_are_catalogued_as_shadow_a1s(app, db):
    """Eight production rows read `position = 'Steward'` while pointing at a
    record labelled `Sparks A1`. They sit above an A2 in the union shadow
    block, on days that separately carry a real steward. They are A1s.

    The display string stays as Jason asked; the CATALOGUE follows the
    evidence, so eight audio shadows never land on the steward rate.
    """
    show, day, act, co = _show3(db)
    fake = _slot_row(db, act, co, "Steward", label="A1")
    real = _slot_row(db, act, co, "Steward", label="Steward")
    _convert(db)
    db.session.expire_all()
    assert fake.position_ref.title == "A1 (SHDW)"
    assert fake.position == "Steward", "display string left alone"
    assert real.position_ref.title == "Labor Steward"


def test_asterisk_variants_stay_separate(app, db):
    """Jason: the mark means something. `EIC*` is not `EIC`."""
    show, day, act, co = _show3(db)
    a = _slot_row(db, act, co, "EIC (SHDW)", label="EIC")
    b = _slot_row(db, act, co, "EIC* (SHDW)", label="EIC")
    _convert(db)
    db.session.expire_all()
    assert a.position_ref.id != b.position_ref.id
    assert {a.position_ref.title, b.position_ref.title} == {
        "EIC (SHDW)", "EIC* (SHDW)"}


def test_the_shows_own_wording_wins_over_the_seeds_guess(app, db):
    """Production says `Rigger High`. The seed guessed `High Rigger`."""
    from models import Position
    show, day, act, co = _show3(db)
    row = _slot_row(db, act, co, "Rigger High", qty=4)
    _convert(db)
    db.session.expire_all()
    assert row.position_ref.title == "Rigger High"
    seeded = Position.query.filter_by(title="High Rigger").first()
    assert seeded is None or seeded.is_local_labor is False


def test_a_row_with_no_position_is_still_counted_as_people(app, db):
    """One production row has no position at all and six people on it. It
    cannot be catalogued, but six people still have to eat.
    """
    from models import CrewRow
    show, day, act, co = _show3(db)
    row = _slot_row(db, act, co, "", qty=6, label="TBD Crew")
    row.position = None
    db.session.commit()
    _convert(db)
    db.session.expire_all()
    assert row.crew_type == "Local Crew"
    assert row.position_id is None
    assert act.crew_headcount == 6


def test_an_unapproved_title_is_skipped_not_invented(app, db):
    """A title nobody approved must not quietly create a catalogue entry."""
    from models import Position
    show, day, act, co = _show3(db)
    row = _slot_row(db, act, co, "Underwater Welder", label="Welder")
    _convert(db)
    db.session.expire_all()
    assert row.crew_type != "Local Crew"
    made = Position.query.filter_by(title="Underwater Welder").first()
    assert made is None or made.is_local_labor is False


def test_the_conversion_is_idempotent(app, db):
    show, day, act, co = _show3(db)
    row = _slot_row(db, act, co, "Lighting Hand", qty=7)
    _convert(db)
    first = row.position_id
    _convert(db)
    db.session.expire_all()
    assert row.position_id == first
    assert act.crew_headcount == 7


def test_the_headcount_survives_the_conversion(app, db):
    """The number F&B reads must not move because of a relabelling."""
    show, day, act, co = _show3(db)
    _slot_row(db, act, co, "Lighting Hand", qty=7)
    _slot_row(db, act, co, "Rigger High", qty=4)
    db.session.expire_all()
    before = act.crew_headcount
    _convert(db)
    db.session.expire_all()
    assert before == 11
    assert act.crew_headcount == 11
