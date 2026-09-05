"""The managed-lookup pattern's last loose end — 2026-09-05.

`positions.title` had no unique index and every creation site compared with
`lower()`. The importer creates positions, so "Load-In" arriving in a crew
file could sit down beside the load-bearing "Load In" and split every count
that reads through it.

Two rules now, doing different jobs — the same split PhaseType.name already
uses. `find_normalised` catches the HUMAN duplicates at the screen (hyphens,
double spaces, case); the unique index catches exact repeats at the database,
where nothing can route around it.

NOTE ON FIXTURES: the `db` fixture arrives already seeded — 23 positions and
18 phase types, including "Rigger" and "Load In". So every test here invents
its own name and asserts on a DELTA, never an absolute count. The first draft
of this file did neither, and the unique index rejected its setup rows: the
guard catching its own author is a reasonable advertisement for the guard.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db as _db
from models import Position, PhaseType, find_normalised, normalise_type_name


# ── the rule itself ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Load-In", "Load In"),
    ("Load In", "load  in"),
    ("Rigger", "rigger "),
    ("Pre-Rig", "Pre Rig"),
    ("A1", "a1"),
])
def test_these_are_one_name(a, b):
    assert normalise_type_name(a) == normalise_type_name(b)


def test_lower_is_not_this_rule():
    """The line that shipped the bug, fed to the guard. If `lower()` were
    sufficient this would fail and the module would be pointless."""
    assert "Load-In".lower() != "Load In".lower()
    assert normalise_type_name("Load-In") == normalise_type_name("Load In")


def test_find_normalised_can_exclude_itself(db):
    """Renaming a row must not clash with the row being renamed."""
    p = Position(title="Probe Grip")
    _db.session.add(p); _db.session.commit()
    assert find_normalised(Position.query.all(), "probe  grip",
                           attr="title") is p
    assert find_normalised(Position.query.all(), "probe-grip", attr="title",
                           exclude_id=p.id) is None


def test_blank_never_matches(db):
    for empty in ("", "   ", None, "-", "  -  "):
        assert find_normalised(Position.query.all(), empty,
                               attr="title") is None


# ── the database backstop ────────────────────────────────────────────────────

def test_the_unique_index_refuses_an_exact_second_rigger(db):
    """The half no route can route around."""
    _db.session.add(Position(title="Probe Rigger")); _db.session.commit()
    _db.session.add(Position(title="Probe Rigger"))
    with pytest.raises(IntegrityError):
        _db.session.commit()
    _db.session.rollback()


def test_the_index_exists_by_name(db):
    """db.create_all() builds it from the model on a fresh database; the
    migration builds it on production. Both must end up with the constraint,
    so assert the constraint rather than the index name."""
    from sqlalchemy import inspect as sa_inspect
    cols = {c["name"]: c for c in sa_inspect(_db.engine).get_columns("positions")}
    assert "title" in cols
    uniques = sa_inspect(_db.engine).get_indexes("positions")
    assert any(ix["unique"] and ix["column_names"] == ["title"]
               for ix in uniques), uniques


# ── the sites that create positions ──────────────────────────────────────────

def test_the_importer_finds_the_hyphen_variant(db):
    """routes/crew_import.py — the site the capture log names. A crew file
    writing "Lighting-Hand" must resolve ONTO the existing "Lighting Hand"
    rather than creating a second one beside it."""
    p = Position(title="Probe Lighting Hand")
    _db.session.add(p); _db.session.commit()
    before = Position.query.count()
    found = find_normalised(Position.query.all(), "probe-lighting  hand",
                            attr="title")
    assert found is not None and found.id == p.id
    assert Position.query.count() == before


def test_quick_add_reports_the_hyphenated_form_as_a_duplicate(client, db):
    """routes/crew.py — the modal that slots a new option into a dropdown."""
    _db.session.add(Position(title="Probe Board Op")); _db.session.commit()
    before = Position.query.count()
    r = client.post("/crew/positions/create",
                    data={"title": "probe-board  op"})
    assert r.status_code == 200
    assert r.get_json()["duplicate"] is True
    assert Position.query.count() == before


def test_local_labor_add_adopts_the_existing_position(client, db):
    """routes/local_labor_routes.py — marks the existing one rather than
    making a second."""
    p = Position(title="Probe Deck Hand", is_local_labor=False)
    _db.session.add(p); _db.session.commit()
    before = Position.query.count()
    client.post("/local-labor/add", data={"title": "probe-deck  hand"},
                follow_redirects=True)
    assert Position.query.count() == before
    assert _db.session.get(Position, p.id).is_local_labor is True


# ── phase types: the route that still compared with lower() ─────────────────

def test_phase_type_create_rejects_the_hyphen_variant(client, db):
    """"Pre Rig" typed next to "Pre-Rig" is the capture log's own example.
    The route's comment described this trap while the code compared with
    lower() — the comment was right and the code was not."""
    _db.session.add(PhaseType(name="Probe-Rig", day_label="Probe-Rig"))
    _db.session.commit()
    before = PhaseType.query.count()
    client.post("/phase-types/new", data={"name": "Probe Rig"},
                follow_redirects=True)
    assert PhaseType.query.count() == before


def test_phase_type_rename_rejects_the_hyphen_variant(client, db):
    _db.session.add(PhaseType(name="Probe-Rig", day_label="Probe-Rig"))
    other = PhaseType(name="Probe Rehearsals", day_label="Probe Rehearsals")
    _db.session.add(other); _db.session.commit()
    client.post(f"/phase-types/{other.id}/edit", data={"name": "probe  rig"},
                follow_redirects=True)
    assert _db.session.get(PhaseType, other.id).name == "Probe Rehearsals"


def test_a_phase_type_can_still_be_renamed_to_a_genuinely_new_name(client, db):
    """The guard must not block ordinary renames — the failure mode of a
    clash check that accidentally matches the row against itself."""
    pt = PhaseType(name="Probe Alpha", day_label="Probe Alpha")
    _db.session.add(pt); _db.session.commit()
    client.post(f"/phase-types/{pt.id}/edit", data={"name": "Probe Beta"},
                follow_redirects=True)
    assert _db.session.get(PhaseType, pt.id).name == "Probe Beta"
