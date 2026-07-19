"""Canonical crew ordering (#29 Phase 1): downstream sorts follow the Crew
Database sort_order within a company, not alphabetical last name."""


def test_canonical_order_by_sort_order_within_company(app, db):
    from models import CrewMember, Company
    from crew_ordering import crew_order_by, crew_sort_key
    co = Company(name="Z Co"); db.session.add(co); db.session.flush()
    # alphabetical order would be Aaa, Bbb, Ccc; sort_order says Bbb, Ccc, Aaa
    a = CrewMember(first_name="Aaa", last_name="Aaa", company_id=co.id, sort_order=30)
    b = CrewMember(first_name="Bbb", last_name="Bbb", company_id=co.id, sort_order=10)
    c = CrewMember(first_name="Ccc", last_name="Ccc", company_id=co.id, sort_order=20)
    db.session.add_all([a, b, c]); db.session.commit()

    ordered = (CrewMember.query.filter_by(company_id=co.id)
               .order_by(*crew_order_by()).all())
    assert [m.first_name for m in ordered] == ["Bbb", "Ccc", "Aaa"]

    # in-memory key agrees with the ORM ordering
    assert sorted([a, b, c], key=crew_sort_key) == [b, c, a]


def test_unset_sort_order_falls_to_end_then_name(app, db):
    from models import CrewMember, Company
    from crew_ordering import crew_sort_key
    co = Company(name="Y Co"); db.session.add(co); db.session.flush()
    ranked = CrewMember(first_name="Ranked", last_name="R", company_id=co.id, sort_order=5)
    zeb = CrewMember(first_name="Zeb", last_name="Zeb", company_id=co.id)   # no sort_order
    amy = CrewMember(first_name="Amy", last_name="Amy", company_id=co.id)   # no sort_order
    db.session.add_all([ranked, zeb, amy]); db.session.commit()
    order = sorted([zeb, amy, ranked], key=crew_sort_key)
    # ranked first (has sort_order), then unset ones alphabetically by last name
    assert order == [ranked, amy, zeb]
