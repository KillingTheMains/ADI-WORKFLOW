"""Tests for Crew Database bulk edit (#42) — non-destructive Position/Company.

Rule: a field left on '— leave unchanged —' (blank) must NOT overwrite; each
selected member keeps its current value. Applies only to the selected ids.
"""


def _mk(db):
    from models import CrewMember, Company, Position
    c1 = Company(name="Co One"); c2 = Company(name="Co Two")
    p1 = Position(title="Pos One"); p2 = Position(title="Pos Two")
    db.session.add_all([c1, c2, p1, p2]); db.session.flush()
    a = CrewMember(first_name="A", last_name="A", position_id=p1.id, company_id=c1.id)
    b = CrewMember(first_name="B", last_name="B", position_id=p1.id, company_id=c1.id)
    c = CrewMember(first_name="C", last_name="C", position_id=p1.id, company_id=c1.id)
    db.session.add_all([a, b, c]); db.session.commit()
    return dict(c1=c1.id, c2=c2.id, p1=p1.id, p2=p2.id, a=a.id, b=b.id, c=c.id)


def test_bulk_edit_applies_to_selected_only(client, db):
    from models import CrewMember
    ids = _mk(db)
    client.post("/crew/bulk-edit", data={
        "ids": f"{ids['a']},{ids['b']}",
        "position_id": str(ids["p2"]), "company_id": str(ids["c2"]),
    })
    a = CrewMember.query.get(ids["a"])
    b = CrewMember.query.get(ids["b"])
    c = CrewMember.query.get(ids["c"])
    assert (a.position_id, a.company_id) == (ids["p2"], ids["c2"])
    assert (b.position_id, b.company_id) == (ids["p2"], ids["c2"])
    # third member was NOT selected -> untouched
    assert (c.position_id, c.company_id) == (ids["p1"], ids["c1"])


def test_bulk_edit_blank_field_is_preserved(client, db):
    from models import CrewMember
    ids = _mk(db)
    # change position only; company left blank must NOT be wiped
    client.post("/crew/bulk-edit", data={
        "ids": str(ids["a"]), "position_id": str(ids["p2"]), "company_id": "",
    })
    a = CrewMember.query.get(ids["a"])
    assert a.position_id == ids["p2"]     # changed
    assert a.company_id == ids["c1"]      # preserved, not blanked


def test_bulk_edit_both_blank_changes_nothing(client, db):
    from models import CrewMember
    ids = _mk(db)
    client.post("/crew/bulk-edit", data={
        "ids": str(ids["a"]), "position_id": "", "company_id": "",
    })
    a = CrewMember.query.get(ids["a"])
    assert (a.position_id, a.company_id) == (ids["p1"], ids["c1"])   # unchanged
