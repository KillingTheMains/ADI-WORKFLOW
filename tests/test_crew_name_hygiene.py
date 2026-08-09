"""
Crew name normalisation and placeholder detection.

Two real records named "First"/"Last" — one with a stray double space — were
sitting in the live Crew Database, appearing in 21 crew calls and inflating
headcounts by one or two on those days. The stray space also made them look
like two different people.
"""
import pytest


def _member(db, first, last):
    from models import CrewMember
    m = CrewMember(first_name=first, last_name=last)
    db.session.add(m); db.session.commit()
    return m


@pytest.mark.parametrize("first,last,expected", [
    ("First ", "Last", "First Last"),
    (" Ada", "Lovelace ", "Ada Lovelace"),
    ("Ada", "Lovelace", "Ada Lovelace"),
    ("Mary  Jane", "Watson", "Mary Jane Watson"),
])
def test_names_are_normalised_on_write(app, db, first, last, expected):
    """Covers every write path at once — add, edit, bulk and the importer."""
    assert _member(db, first, last).full_name == expected


@pytest.mark.parametrize("first,last", [
    ("First", "Last"), ("first", "last"), ("TBD", "TBD"),
    ("Test", "Person"), ("Ada", "TBA"),
])
def test_placeholder_names_are_detected(app, db, first, last):
    assert _member(db, first, last).looks_like_placeholder


@pytest.mark.parametrize("first,last", [
    ("Ada", "Lovelace"), ("Larry", "Kargol"), ("Firstborn", "Lastly"),
])
def test_real_names_are_not_flagged(app, db, first, last):
    """Must not catch people whose names merely contain those words."""
    assert not _member(db, first, last).looks_like_placeholder


def test_two_placeholders_that_differed_only_by_whitespace_now_match(app, db):
    """The exact live situation: 'First Last' and 'First  Last' read as two
    different people. After normalisation they are plainly the same record."""
    a = _member(db, "First", "Last")
    b = _member(db, "First ", " Last")
    assert a.full_name == b.full_name == "First Last"
    assert a.looks_like_placeholder and b.looks_like_placeholder


def test_migration_tidies_and_reports(app, db, capsys):
    from migrations import _tidy_crew_name_whitespace
    from models import CrewMember
    # Bypass the validator to simulate rows written before it existed.
    db.session.execute(CrewMember.__table__.insert().values(
        first_name="First ", last_name="Last"))
    db.session.execute(CrewMember.__table__.insert().values(
        first_name="Ada", last_name="Lovelace"))
    db.session.commit()

    _tidy_crew_name_whitespace(db.session)
    names = sorted(m.full_name for m in CrewMember.query.all())
    assert names == ["Ada Lovelace", "First Last"]

    out = capsys.readouterr().out
    assert "tidied whitespace in 1 crew name field(s)" in out
    assert "placeholder-looking crew" in out and "First Last" in out
    assert "Ada Lovelace" not in out.split("placeholder-looking crew")[-1]


def test_saving_a_placeholder_warns_the_user(app, client, db):
    r = client.post("/crew/add", data={"first_name": "First",
                                       "last_name": "Last"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"looks like a placeholder" in r.data
