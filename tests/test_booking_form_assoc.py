"""#43 — booking-sheet row forms live outside the table (form= association), so
autosave works without the load-bearing Save button and the HTML is valid
(a <form> is not a legal child of <tr>)."""
import datetime as dt


def _show_with_assignment(db):
    from models import Show, CrewMember, Company, ShowCrewAssignment
    show = Show(name="FA Show", code="FA26"); db.session.add(show); db.session.flush()
    co = Company(name="Acme"); db.session.add(co); db.session.flush()
    cm = CrewMember(first_name="Dana", last_name="Reed", company_id=co.id)
    db.session.add(cm); db.session.flush()
    a = ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id)
    db.session.add(a); db.session.commit()
    return show, a


def test_row_forms_are_outside_the_table(app, client, db):
    show, a = _show_with_assignment(db)
    body = client.get("/shows/%d/crew" % show.id).get_data(as_text=True)
    # empty form element rendered (it lives below the table)
    assert 'id="assign-row-%d"' % a.id in body
    # the row's inputs are associated to it via form=
    assert 'form="assign-row-%d"' % a.id in body


def test_edit_assignment_still_saves(app, client, db):
    from models import ShowCrewAssignment
    show, a = _show_with_assignment(db)
    client.post("/shows/%d/crew/assignment/%d/edit" % (show.id, a.id),
                data={"role_override": "Lead Hand", "_autosave": "1"})
    saved = ShowCrewAssignment.query.get(a.id)
    assert saved.role_override == "Lead Hand"
