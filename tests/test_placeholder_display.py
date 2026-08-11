"""Unfilled-slot display (note 8, 2026-08-11).

A placeholder crew record is an unfilled slot, not junk: it still gets called,
fed and scheduled, so it stays in headcounts. It just renders as
COMPANY + POSITION instead of "First Last".
"""


def _mk(db, first, last, company=None, position=None):
    from models import CrewMember, Company, Position
    co = po = None
    if company:
        co = Company(name=company[0], code=company[1])
        db.session.add(co)
    if position:
        po = Position(title=position)
        db.session.add(po)
    db.session.flush()
    cm = CrewMember(first_name=first, last_name=last,
                    company_id=co.id if co else None,
                    position_id=po.id if po else None)
    db.session.add(cm)
    db.session.flush()
    return cm


def test_real_name_is_untouched(app, db):
    cm = _mk(db, "Ollie", "Marsden")
    assert cm.is_unnamed_slot is False
    assert cm.display_label == "Ollie Marsden"


def test_surname_matching_a_placeholder_word_is_not_a_slot(app, db):
    """Regression: 'name' is in PLACEHOLDER_NAMES, but this is a real person.

    The save-time warning may still fire; substituting the displayed name must
    not, because that would hide a real person from a call sheet.
    """
    cm = _mk(db, "Old", "Name")
    assert cm.looks_like_placeholder is True    # warning still fires
    assert cm.is_unnamed_slot is False          # display does not substitute
    assert cm.display_label == "Old Name"


def test_placeholder_renders_company_and_position(app, db):
    cm = _mk(db, "First", "Last", company=("Sparks Inc", "SPARKS"),
             position="Lead Rigger")
    assert cm.is_unnamed_slot is True
    assert cm.display_label == "SPARKS Lead Rigger"


def test_company_name_used_when_no_code(app, db):
    cm = _mk(db, "First", "Last", company=("Lumenarchy Inc", None),
             position="Steward")
    assert cm.display_label == "Lumenarchy Inc Steward"


def test_falls_back_to_company_only(app, db):
    cm = _mk(db, "First", "Last", company=("Sparks Inc", "SPARKS"))
    assert cm.display_label == "SPARKS — TBD"


def test_falls_back_to_position_only(app, db):
    cm = _mk(db, "TBD", "TBD", position="Lead Rigger")
    assert cm.display_label == "Lead Rigger — TBD"


def test_falls_back_to_bare_tbd(app, db):
    cm = _mk(db, "First", "Last")
    assert cm.display_label == "TBD"


def test_crew_row_marks_unfilled_and_keeps_headcount(app, db):
    from models import Show, ScheduleDay, ScheduleActivity, CrewRow
    import datetime as dt
    show = Show(name="S", code="S26"); db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 1))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00", description="CREW START")
    db.session.add(act); db.session.flush()
    slot = _mk(db, "First", "Last", company=("Sparks Inc", "SPARKS"),
               position="Steward")
    row = CrewRow(activity_id=act.id, crew_member_id=slot.id, qty=1)
    db.session.add(row); db.session.commit()

    assert row.is_unfilled is True
    assert row.display_name == "SPARKS Steward"
    # qty is untouched — an unfilled slot still counts toward the call.
    assert row.qty == 1


def test_group_header_is_never_unfilled(app, db):
    from models import Show, ScheduleDay, ScheduleActivity, CrewRow
    import datetime as dt
    show = Show(name="S2", code="S27"); db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 2))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00", description="CREW START")
    db.session.add(act); db.session.flush()
    hdr = CrewRow(activity_id=act.id, is_group_header=True, group_label="ENCORE")
    db.session.add(hdr); db.session.commit()
    assert hdr.is_unfilled is False
