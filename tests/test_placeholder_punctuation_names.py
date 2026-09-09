"""A name made of punctuation is a stand-in, not a person.

Found 2026-09-09 on the production snapshot. `PLACEHOLDER_NAMES` knew TBD,
TBA, Unknown, N/A, XXX, First, Last, Test and Name — and did not know ".".

There were **43 crew records named ". ."** (32 ENCORE, 11 GES), and they were
the stand-ins Grace Hopper Celebration 2026's union labor lines hang off.
Because the rule did not recognise them, `CrewRow.is_local_labor` took the
"a named person wins" branch and every one of those lines was classified as a
real individual instead of a count of bodies.

Measured on that show before the fix, changing nothing else:

    local labor bodies      140  ->  206
    rows counted as named   283  ->  265

66 bodies — 47% of the show's local labor — were booked as 18 people, and
those 18 then had per-person OT, DT, short-turnaround and 6th/7th-consecutive
day rules applied to multi-body hours.

The fix is the SHAPE of the thing rather than one more literal: a name part
with no letter and no digit anywhere is not a name. Enumerating "." would
have left "-", "--" and "?" to be found the same way in a month.
"""
import datetime as dt

import pytest

import models
from models import CrewMember


# ── the rule ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("first,last", [
    (".", "."),          # the 43 records on production
    (".", ""),
    ("-", "-"),
    ("--", "--"),
    ("?", ""),
    ("...", ".."),
    ("·", "·"),
    (".", "-"),
])
def test_punctuation_only_names_are_stand_ins(first, last):
    assert models.name_is_unnamed_slot(first, last) is True


@pytest.mark.parametrize("first,last", [
    ("Jose", "Mora"),
    ("José", "Muñoz"),        # isalnum is Unicode-aware
    ("Ryan", "Name"),         # half a match is still a person — deliberate
    ("Last", "Kargol"),
    ("O'Brien", "."),         # one real half is enough to be a person
    (".", "Mora"),
    ("X Æ", "A-12"),
])
def test_real_names_are_still_people(first, last):
    assert models.name_is_unnamed_slot(first, last) is False


def test_a_blank_name_is_not_a_placeholder():
    """Unchanged: blank means 'no information', not 'a stand-in'."""
    assert models.name_is_unnamed_slot("", "") is False
    assert models.name_is_unnamed_slot(None, None) is False


def test_the_known_words_still_work():
    assert models.name_is_unnamed_slot("TBD", "") is True
    assert models.name_is_unnamed_slot("First", "Last") is True
    assert models.name_is_unnamed_slot("Unknown", "Unknown") is True


# ── what it changes downstream ──────────────────────────────────────────────

def test_a_dot_named_row_is_local_labor_again(app, db):
    """The actual consequence: 4 bodies, not 1 person."""
    from models import Show, ScheduleDay, ScheduleActivity, CrewRow, Position, Company

    show = Show(name="Dot Show", code="DOT26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 19))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="8:00 AM", description="CREW START",
                           sort_order=10)
    db.session.add(act); db.session.flush()

    pos = Position.query.filter_by(title="Rigger High").first()
    if pos is None:
        pos = Position(title="Rigger High", department="Rigging", is_local_labor=True)
        db.session.add(pos)
    else:
        pos.is_local_labor = True
    company = Company(name="ENCORE", code="ENCORE")
    db.session.add(company); db.session.flush()

    dot = CrewMember(first_name=".", last_name=".", company_id=company.id,
                     position_id=pos.id)
    db.session.add(dot); db.session.flush()

    row = CrewRow(activity_id=act.id, crew_member_id=dot.id, position_id=pos.id,
                  position="Rigger High", qty=4, hours=10, sort_order=1)
    db.session.add(row); db.session.commit()

    assert dot.is_unnamed_slot is True
    assert row.is_local_labor is True, "a '. .' row read as a named person"
    assert models.count_people([row]) == 4

    # and it renders as what it actually is, rather than as ". ."
    assert row.display_name == "ENCORE Rigger High"


def test_looks_like_placeholder_agrees(app, db):
    """The save-time warning uses the same rule, so the two cannot disagree."""
    dot = CrewMember(first_name=".", last_name=".")
    real = CrewMember(first_name="Jose", last_name="Mora")
    db.session.add_all([dot, real]); db.session.flush()
    assert dot.looks_like_placeholder is True
    assert real.looks_like_placeholder is False


# ── the migration ───────────────────────────────────────────────────────────

def test_migration_renames_punctuation_names_and_spares_people(app, db):
    from migrations import _punctuation_only_crew_names_to_tbd

    dot = CrewMember(first_name=".", last_name=".")
    dash = CrewMember(first_name="-", last_name="")
    real = CrewMember(first_name="Jose", last_name="Mora")
    half = CrewMember(first_name=".", last_name="Mora")   # a person: one real half
    tbd = CrewMember(first_name="TBD", last_name="")
    db.session.add_all([dot, dash, real, half, tbd])
    db.session.commit()

    _punctuation_only_crew_names_to_tbd(db.session)

    assert (dot.first_name, dot.last_name) == ("TBD", "")
    assert (dash.first_name, dash.last_name) == ("TBD", "")
    assert (real.first_name, real.last_name) == ("Jose", "Mora")
    assert (half.first_name, half.last_name) == (".", "Mora")
    assert (tbd.first_name, tbd.last_name) == ("TBD", "")


def test_migration_is_registered():
    from migrations import DATA_MIGRATIONS
    keys = [k for k, _fn in DATA_MIGRATIONS]
    assert "2026-09-09-punctuation-only-crew-names-to-tbd" in keys
