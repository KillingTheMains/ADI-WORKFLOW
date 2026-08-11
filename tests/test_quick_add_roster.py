"""Add-to-roster from the day editor (note 4, 2026-08-11).

The crew-call dropdown is roster-only, so there has to be an in-place way to
add a missing person. Navigating to the roster page and back would lose the
user's position on an autosaving form.
"""


def _show(db, code="QA26"):
    from models import Show
    s = Show(name="Quick Add Show", code=code)
    db.session.add(s); db.session.commit()
    return s


def test_adds_an_existing_crew_database_member_to_the_roster(app, client, db):
    from models import CrewMember, ShowCrewAssignment
    show = _show(db)
    cm = CrewMember(first_name="Ada", last_name="Byron")
    db.session.add(cm); db.session.commit()

    r = client.post("/shows/%d/crew/quick-add" % show.id,
                    data={"crew_member_id": cm.id})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["id"] == cm.id
    assert ShowCrewAssignment.query.filter_by(
        show_id=show.id, crew_member_id=cm.id).count() == 1


def test_creates_a_new_person_and_assigns_them(app, client, db):
    from models import CrewMember, ShowCrewAssignment
    show = _show(db, "QA27")
    r = client.post("/shows/%d/crew/quick-add" % show.id,
                    data={"first_name": "Grace", "last_name": "Hopper"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    cm = CrewMember.query.get(body["id"])
    assert cm.full_name == "Grace Hopper"
    assert ShowCrewAssignment.query.filter_by(show_id=show.id).count() == 1


def test_nameless_slot_allowed_when_company_or_position_given(app, client, db):
    """An unfilled slot is legitimate — it renders as COMPANY + POSITION."""
    from models import Company, CrewMember
    show = _show(db, "QA28")
    co = Company(name="Sparks Inc", code="SPARKS")
    db.session.add(co); db.session.commit()

    r = client.post("/shows/%d/crew/quick-add" % show.id,
                    data={"first_name": "", "last_name": "",
                          "company_id": co.id})
    assert r.status_code == 200
    cm = CrewMember.query.get(r.get_json()["id"])
    assert cm.is_unnamed_slot is True
    assert cm.display_label == "SPARKS — TBD"


def test_blank_everything_is_rejected(app, client, db):
    """A record with no name AND no company/position tells a reader nothing."""
    show = _show(db, "QA29")
    r = client.post("/shows/%d/crew/quick-add" % show.id,
                    data={"first_name": "", "last_name": ""})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_adding_someone_twice_does_not_duplicate_the_assignment(app, client, db):
    from models import CrewMember, ShowCrewAssignment
    show = _show(db, "QA30")
    cm = CrewMember(first_name="Alan", last_name="Turing")
    db.session.add(cm); db.session.commit()

    for _ in range(2):
        r = client.post("/shows/%d/crew/quick-add" % show.id,
                        data={"crew_member_id": cm.id})
        assert r.status_code == 200
    assert ShowCrewAssignment.query.filter_by(
        show_id=show.id, crew_member_id=cm.id).count() == 1
    assert r.get_json()["already_on_roster"] is True


def test_new_assignment_has_no_manual_sort_order(app, client, db):
    """sort_order stays NULL so they slot into their Crew Database position
    rather than landing at the bottom of the roster."""
    from models import ShowCrewAssignment
    show = _show(db, "QA31")
    r = client.post("/shows/%d/crew/quick-add" % show.id,
                    data={"first_name": "Nell", "last_name": "Nine"})
    a = ShowCrewAssignment.query.filter_by(
        show_id=show.id, crew_member_id=r.get_json()["id"]).one()
    assert a.sort_order is None
