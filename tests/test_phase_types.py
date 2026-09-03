"""Note 14 — the phase Type dropdown becomes a list Larry manages.

Jason: "we want Larry to have the ability to add options to that dropdown list
and for everything he adds to carry over between shows in the future and be
reference for all shows in the whole workflow."

`PHASE_TYPES` was a five-item Python constant, so a sixth needed a developer.

The interesting tests here are NOT the CRUD ones. They are:

  · the load-bearing names cannot be renamed or deleted. "Show" is read as a
    literal by `_sync_legacy_dates` to set show.show_start/show_end, and
    "Load In"/"Strike" by `Show._phase_date`. Renaming one silently stops a
    show knowing its own dates — no error, just wrong dates on a schedule.

  · a NEW type survives Auto-Generate Days. This is the note-18 collision:
    PHASE_LABEL_MAP was a closed dict of five, so anything else fell through
    to the else branch and became a day labelled "Setup" with type "Load In" —
    and with templates ticked, the LOAD IN template applied to it. The moment
    Larry can add a type, that stops being theoretical.

  · renaming a non-builtin type carries its existing phases with it, because
    ProductionPhase stores the type as a STRING, not a foreign key.
"""
from datetime import date

from extensions import db as _db
from models import PhaseType, ProductionPhase, ScheduleDay, Show, phase_day_label


def _seed(db):
    """The five, as the migration seeds them."""
    from migrations import _seed_phase_types
    _seed_phase_types(db.session)
    db.session.commit()


def _show(db, **kw):
    s = Show(name=kw.pop("name", "Test Show"), code=kw.pop("code", "TS1"), **kw)
    db.session.add(s); db.session.commit()
    return s


# ── The seed ─────────────────────────────────────────────────────────────────

def test_the_five_are_seeded_and_the_load_bearing_ones_are_marked(db):
    _seed(db)
    names = [t.name for t in PhaseType.query.order_by(PhaseType.sort_order)]
    assert names == ["Prep", "Load In", "Show", "Strike", "Custom"]
    builtin = {t.name for t in PhaseType.query.filter_by(is_builtin=True)}
    assert builtin == {"Load In", "Show", "Strike"}


def test_seeding_twice_creates_nothing(db):
    _seed(db)
    _seed(db)
    assert PhaseType.query.count() == 5


def test_the_accessor_falls_back_when_the_table_is_empty(db):
    """A fresh checkout, or the migration not yet run, must behave exactly as
    the app did before this change.

    Note the table is NOT empty by default here — app startup runs migrations,
    so the seed has already happened by the time a test sees the app. That is
    the correct production behaviour; emptying it is how the fallback path
    gets exercised at all."""
    PhaseType.query.delete()
    _db.session.commit()
    from models import phase_type_names
    assert PhaseType.query.count() == 0
    assert phase_type_names() == ["Prep", "Load In", "Show", "Strike", "Custom"]


def test_the_show_form_options_are_not_hardcoded(client, db):
    """The four phase selects in shows/new.html hardcoded the five options and
    ignored the `phase_types` variable the route had always passed them. So
    "add a phase type" needed a developer in TWO places, and this was the
    second. Found by the test above it failing for the wrong reason."""
    html = open("templates/shows/new.html").read()
    assert '<option value="Strike"' not in html, (
        "a hardcoded phase-type option list is back"
    )
    assert html.count("for t in phase_types") >= 4


# ── Larry's half ─────────────────────────────────────────────────────────────

def test_a_new_type_appears_on_every_show(client, db):
    _seed(db)
    _show(db)
    client.post("/phase-types/new",
                data={"name": "Pre-Rig", "day_label": "Pre-Rig Day"},
                follow_redirects=True)
    assert b"Pre-Rig" in client.get("/shows/new").data


def test_a_duplicate_differing_only_by_case_is_refused(client, db):
    _seed(db)
    client.post("/phase-types/new", data={"name": "PREP"},
                follow_redirects=True)
    assert PhaseType.query.count() == 5


def test_hiding_a_type_removes_it_from_the_show_dropdown(client, db):
    _seed(db)
    pt = PhaseType.query.filter_by(name="Custom").first()
    client.post(f"/phase-types/{pt.id}/toggle", follow_redirects=True)
    from models import phase_type_names
    assert "Custom" not in phase_type_names()


def test_order_is_explicit_because_phases_are_chronological(client, db):
    _seed(db)
    pt = PhaseType.query.filter_by(name="Show").first()
    client.post(f"/phase-types/{pt.id}/move", data={"dir": "up"},
                follow_redirects=True)
    names = [t.name for t in PhaseType.query.order_by(PhaseType.sort_order)]
    assert names.index("Show") < names.index("Load In")


# ── The guard rails ──────────────────────────────────────────────────────────

def test_a_load_bearing_type_cannot_be_renamed(client, db):
    """`_sync_legacy_dates` finds the phase named "Show" to set the show's own
    start and end dates."""
    _seed(db)
    pt = PhaseType.query.filter_by(name="Show").first()
    client.post(f"/phase-types/{pt.id}/edit", data={"name": "Showtime"},
                follow_redirects=True)
    assert _db.session.get(PhaseType, pt.id).name == "Show"


def test_a_load_bearing_type_cannot_be_deleted(client, db):
    _seed(db)
    pt = PhaseType.query.filter_by(name="Strike").first()
    client.post(f"/phase-types/{pt.id}/delete", follow_redirects=True)
    assert _db.session.get(PhaseType, pt.id) is not None


def test_a_type_in_use_cannot_be_deleted(client, db):
    _seed(db)
    s = _show(db)
    client.post("/phase-types/new", data={"name": "Pre-Rig"},
                follow_redirects=True)
    pt = PhaseType.query.filter_by(name="Pre-Rig").first()
    _db.session.add(ProductionPhase(show_id=s.id, name="Rig week",
                                    phase_type="Pre-Rig"))
    _db.session.commit()
    client.post(f"/phase-types/{pt.id}/delete", follow_redirects=True)
    assert _db.session.get(PhaseType, pt.id) is not None


def test_renaming_carries_existing_phases_with_it(client, db):
    """ProductionPhase stores the type as a STRING. Rename without moving them
    and those phases point at a name no longer in the list."""
    _seed(db)
    s = _show(db)
    client.post("/phase-types/new", data={"name": "Pre-Rig"},
                follow_redirects=True)
    pt = PhaseType.query.filter_by(name="Pre-Rig").first()
    _db.session.add(ProductionPhase(show_id=s.id, name="Rig week",
                                    phase_type="Pre-Rig"))
    _db.session.commit()

    client.post(f"/phase-types/{pt.id}/edit", data={"name": "Pre Rig"},
                follow_redirects=True)
    moved = ProductionPhase.query.filter_by(phase_type="Pre Rig").count()
    orphaned = ProductionPhase.query.filter_by(phase_type="Pre-Rig").count()
    assert (moved, orphaned) == (1, 0)


# ── The note-18 collision ────────────────────────────────────────────────────

def test_a_new_type_keeps_its_own_day_label_on_auto_generate(client, db):
    """THE ONE THAT MATTERS. PHASE_LABEL_MAP was a closed dict of five, so a
    type outside it produced a day labelled "Setup" and typed "Load In" — and
    with templates ticked, the LOAD IN template applied to it."""
    _seed(db)
    s = _show(db)
    client.post("/phase-types/new",
                data={"name": "Pre-Rig", "day_label": "Pre-Rig Day"},
                follow_redirects=True)
    _db.session.add(ProductionPhase(show_id=s.id, name="Rig week",
                                    phase_type="Pre-Rig",
                                    start_date=date(2026, 10, 1),
                                    end_date=date(2026, 10, 2)))
    _db.session.commit()

    client.post(f"/shows/{s.id}/schedule/generate-days", follow_redirects=True)
    days = ScheduleDay.query.filter_by(show_id=s.id).all()
    assert days, "no days generated"
    assert {d.phase for d in days} == {"Pre-Rig Day"}, (
        "a custom phase type was relabelled — the note-18 collision is back"
    )


def test_the_day_label_helper_falls_back_for_the_original_five(db):
    """Behaviour for existing shows must be identical to before."""
    assert phase_day_label("Prep") == "Setup"
    assert phase_day_label("Show") == "Show Day"
    assert phase_day_label("Custom") == "Setup"
