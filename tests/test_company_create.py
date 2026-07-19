"""'+ New company' inline creation from company dropdowns (parallels #41 positions)."""


def test_companies_create(app, client, db):
    from models import Company
    r = client.post("/crew/companies/create", data={"name": "New Vendor Co", "code": "NVC"})
    j = r.get_json()
    assert j["ok"] is True and j["name"] == "New Vendor Co"
    made = Company.query.filter_by(name="New Vendor Co").first()
    assert made is not None and made.code == "NVC"


def test_companies_create_dedupes_case_insensitively(app, client, db):
    from models import Company
    db.session.add(Company(name="Acme")); db.session.commit()
    r = client.post("/crew/companies/create", data={"name": "acme"})
    j = r.get_json()
    assert j["ok"] is True and j.get("duplicate") is True
    assert Company.query.filter(db.func.lower(Company.name) == "acme").count() == 1


def test_companies_create_requires_name(app, client, db):
    r = client.post("/crew/companies/create", data={"name": "   "})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
