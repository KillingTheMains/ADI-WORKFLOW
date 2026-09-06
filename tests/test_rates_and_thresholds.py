"""Capture log #8 (2026-09-05): rates and overtime thresholds.

Jason's answers, verbatim in spirit: standard is an HOURLY rate for the
first 10 hours; OT after 10; DT after 12. A company can have its own deal,
and a person can have their own deal on top of that — so a threshold
resolves person -> company -> default, each threshold on its own.
"""
import billing


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ── thresholds_for ───────────────────────────────────────────────────────────

def test_defaults_are_larrys():
    assert billing.thresholds_for() == (10.0, 12.0)
    assert billing.thresholds_for(None, None) == (10.0, 12.0)


def test_company_terms_beat_the_defaults():
    co = _Obj(ot_after_hours=8, dt_after_hours=None)
    m = _Obj(ot_after_hours=None, dt_after_hours=None, company=co)
    assert billing.thresholds_for(m) == (8.0, 12.0)


def test_a_person_beats_their_company():
    co = _Obj(ot_after_hours=8, dt_after_hours=10)
    m = _Obj(ot_after_hours=9, dt_after_hours=None, company=co)
    # OT from the person, DT still from the company — each resolves alone
    assert billing.thresholds_for(m) == (9.0, 10.0)


def test_zero_means_inherit_not_overtime_from_the_first_minute():
    m = _Obj(ot_after_hours=0, dt_after_hours=0, company=None)
    assert billing.thresholds_for(m) == (10.0, 12.0)


def test_dt_never_starts_before_ot():
    m = _Obj(ot_after_hours=11, dt_after_hours=9, company=None)
    assert billing.thresholds_for(m) == (11.0, 11.0)


def test_a_company_can_be_given_directly_for_a_nameless_line():
    co = _Obj(ot_after_hours=8, dt_after_hours=12)
    assert billing.thresholds_for(None, co) == (8.0, 12.0)


# ── rates_for ────────────────────────────────────────────────────────────────

def test_blank_ot_and_dt_are_multiples_of_standard():
    m = _Obj(rate_standard=50, rate_ot=None, rate_dt=None)
    assert billing.rates_for(m) == (50.0, 75.0, 100.0)


def test_a_typed_ot_or_dt_rate_wins_over_the_multiplier():
    m = _Obj(rate_standard=50, rate_ot=80, rate_dt=None)
    assert billing.rates_for(m) == (50.0, 80.0, 100.0)


def test_no_standard_rate_means_nothing_can_be_derived():
    m = _Obj(rate_standard=None, rate_ot=None, rate_dt=None)
    assert billing.rates_for(m) == (None, None, None)


# ── the split honours the resolved thresholds ────────────────────────────────

def test_split_day_on_a_companys_own_terms():
    co = _Obj(ot_after_hours=8, dt_after_hours=10)
    ot_after, dt_after = billing.thresholds_for(None, co)
    assert billing.split_day(12, ot_after, dt_after) == (8.0, 2.0, 2.0)


# ── the crew form round-trips the thresholds ────────────────────────────────

def _form(**over):
    base = dict(first_name="Rate", last_name="Card", rate_standard="50")
    base.update(over)
    return base


def test_crew_add_stores_thresholds_and_blank_means_null(app, client, db):
    from models import CrewMember
    r = client.post("/crew/add", data=_form(ot_after_hours="8", dt_after_hours=""))
    assert r.status_code in (302, 303)
    m = CrewMember.query.filter_by(last_name="Card").one()
    assert m.ot_after_hours == 8.0
    assert m.dt_after_hours is None
    assert m.rate_standard == 50.0


def test_crew_add_tolerates_a_dollar_sign(app, client, db):
    from models import CrewMember
    client.post("/crew/add", data=_form(last_name="Dollar", rate_standard="$1,250.50"))
    m = CrewMember.query.filter_by(last_name="Dollar").one()
    assert m.rate_standard == 1250.5


def test_crew_edit_shows_what_a_blank_threshold_would_inherit(app, client, db):
    from models import CrewMember, Company
    co = Company(name="Eight Hour Co", ot_after_hours=8)
    db.session.add(co); db.session.flush()
    m = CrewMember(first_name="In", last_name="Herit", company_id=co.id,
                   rate_standard=40)
    db.session.add(m); db.session.commit()
    html = client.get("/crew/%d/edit" % m.id).get_data(as_text=True)
    assert 'name="ot_after_hours"' in html
    assert "Eight Hour Co" in html and "OT after 8" in html
    # blank OT/DT rate placeholders say what they will be
    assert 'placeholder="60.00"' in html and 'placeholder="80.00"' in html


def test_companies_page_saves_terms_and_zero_clears_them(app, client, db):
    from models import Company
    co = Company(name="Terms Co")
    db.session.add(co); db.session.commit()
    html = client.get("/crew/companies").get_data(as_text=True)
    assert "Terms Co" in html and 'name="ot_after_hours"' in html
    r = client.post("/crew/companies/%d/terms" % co.id,
                    data={"ot_after_hours": "8", "dt_after_hours": "10"},
                    headers={"X-Autosave": "1"})
    assert r.status_code == 204
    db.session.refresh(co)
    assert (co.ot_after_hours, co.dt_after_hours) == (8.0, 10.0)
    client.post("/crew/companies/%d/terms" % co.id,
                data={"ot_after_hours": "0", "dt_after_hours": ""})
    db.session.refresh(co)
    assert (co.ot_after_hours, co.dt_after_hours) == (None, None)


def test_the_new_columns_are_in_the_migration_list():
    from migrations import MIGRATIONS
    cols = {(t, c) for t, c, _ in MIGRATIONS}
    for t in ("crew_members", "companies"):
        assert (t, "ot_after_hours") in cols
        assert (t, "dt_after_hours") in cols
