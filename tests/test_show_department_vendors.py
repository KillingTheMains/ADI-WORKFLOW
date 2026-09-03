"""Notes 2 and 10 — which company supplies each department, and its job number.

Larry: "rigging comes from one company, audio comes from one company, lighting
comes from one company." There was nowhere in the app to say that.

Design decisions these tests hold in place, from
ADI_Vendor_Attribution_Proposal.md:

  · ONE ROW PER DEPARTMENT PER SHOW. Not per day, not per crew line — that
    was the entire point, because per-line is the data entry burden Larry is
    asking to be rid of.
  · The job number lives on the VENDOR row, not the show (note 10). A show
    with three vendors has three job numbers, so one field on the show would
    have been wrong the first time two suppliers were used.
  · The department vocabulary is local_labor's DEPARTMENT_ORDER — crew
    disciplines — and NOT the operations sub-schedule list (Dock, F&B, Haze).
    Those are two separate layers.

Steps 4 and 5 of the proposal — reading this on the crew call headers and in
the schedule export — are deliberately NOT built yet.
"""
from extensions import db as _db
from local_labor import DEPARTMENT_ORDER
from models import Company, ShowDepartmentVendor, Show, vendor_map_for_show


def _show(db, name="Vendor Show", code="VS1"):
    s = Show(name=name, code=code)
    db.session.add(s); db.session.commit()
    return s


def _co(db, name):
    c = Company(name=name)
    db.session.add(c); db.session.commit()
    return c


def test_the_block_renders_on_the_show_page(client, db):
    s = _show(db)
    body = client.get(f"/shows/{s.id}").data
    assert b"Local Labor Vendors" in body
    assert b"Rigging" in body and b"Lighting" in body


def test_departments_are_the_crew_discipline_list(client, db):
    """NOT the operations sub-schedules. A rigger is not a Dock event."""
    s = _show(db)
    body = client.get(f"/shows/{s.id}").data.decode()
    for d in DEPARTMENT_ORDER:
        assert d in body
    assert "Haze" not in body


def test_a_department_can_be_assigned_a_vendor(client, db):
    s, co = _show(db), _co(db, "Acme Staging")
    client.post(f"/shows/{s.id}/vendors",
                data={"company_Rigging": str(co.id)}, follow_redirects=True)
    v = vendor_map_for_show(s.id)
    assert v["Rigging"].company_id == co.id


def test_different_departments_can_have_different_vendors(client, db):
    """The whole point of the note."""
    s = _show(db)
    rig, lx = _co(db, "High Steel"), _co(db, "Bright Sparks")
    client.post(f"/shows/{s.id}/vendors",
                data={"company_Rigging": str(rig.id),
                      "company_Lighting": str(lx.id)}, follow_redirects=True)
    v = vendor_map_for_show(s.id)
    assert (v["Rigging"].company_id, v["Lighting"].company_id) == (rig.id, lx.id)


def test_the_job_number_is_per_vendor_not_per_show(client, db):
    """Note 10. Three vendors, three job numbers — a single field on the show
    would be wrong the first time two suppliers were used."""
    s = _show(db)
    rig, aud = _co(db, "High Steel"), _co(db, "Loud Co")
    client.post(f"/shows/{s.id}/vendors",
                data={"company_Rigging": str(rig.id), "job_Rigging": "HS-2026-11",
                      "company_Audio": str(aud.id),   "job_Audio": "LC-884"},
                follow_redirects=True)
    v = vendor_map_for_show(s.id)
    assert v["Rigging"].job_number == "HS-2026-11"
    assert v["Audio"].job_number == "LC-884"


def test_saving_twice_updates_rather_than_duplicating(client, db):
    """One row per department per show — the unique constraint in shape."""
    s = _show(db)
    a, b = _co(db, "First Co"), _co(db, "Second Co")
    for co in (a, b):
        client.post(f"/shows/{s.id}/vendors",
                    data={"company_Rigging": str(co.id)}, follow_redirects=True)
    rows = ShowDepartmentVendor.query.filter_by(show_id=s.id,
                                                department="Rigging").all()
    assert len(rows) == 1
    assert rows[0].company_id == b.id


def test_clearing_a_department_removes_the_row(client, db):
    """"No vendor set" gets exactly one representation, not two."""
    s, co = _show(db), _co(db, "Acme Staging")
    client.post(f"/shows/{s.id}/vendors",
                data={"company_Rigging": str(co.id)}, follow_redirects=True)
    client.post(f"/shows/{s.id}/vendors",
                data={"company_Rigging": ""}, follow_redirects=True)
    assert vendor_map_for_show(s.id) == {}


def test_a_job_number_alone_is_kept(client, db):
    """The vendor may be known before it is in the company list."""
    s = _show(db)
    client.post(f"/shows/{s.id}/vendors",
                data={"job_Scenic": "TBC-19"}, follow_redirects=True)
    v = vendor_map_for_show(s.id)
    assert v["Scenic"].job_number == "TBC-19"
    assert v["Scenic"].company_id is None


def test_vendors_are_per_show(client, db):
    """A vendor on one show must not leak onto another."""
    a, b = _show(db, "Show A", "SA"), _show(db, "Show B", "SB")
    co = _co(db, "Acme Staging")
    client.post(f"/shows/{a.id}/vendors",
                data={"company_Rigging": str(co.id)}, follow_redirects=True)
    assert vendor_map_for_show(b.id) == {}
