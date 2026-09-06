"""Capture log #7 (2026-09-05): the hours report knows about bodies, terms
and companies.

Additive: everything test_hours_report_billing.py asserts still holds.
"""
import datetime as dt


def _show(db, code):
    from models import Show
    show = Show(name="Report " + code, code=code)
    db.session.add(show); db.session.flush()
    return show


def _day(db, show, i=0):
    from models import ScheduleDay, ScheduleActivity
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 11, 1) + dt.timedelta(days=i))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:00", description="LOAD IN", sort_order=1)
    db.session.add(act); db.session.flush()
    return day, act


def _local_position(db, title, dept="Lighting"):
    from models import Position
    p = Position.query.filter_by(title=title).first()
    if p is None:
        p = Position(title=title, department=dept, is_local_labor=True)
        db.session.add(p); db.session.flush()
    return p


def _local_line(db, act, pos, qty, est, company=None, sort=2):
    from models import CrewRow
    hdr = CrewRow(activity_id=act.id, is_group_header=True, qty=0, sort_order=sort - 1,
                  group_label=(company.name if company else "LOCAL CREW"),
                  company_id=(company.id if company else None))
    row = CrewRow(activity_id=act.id, position_id=pos.id, position=pos.title,
                  qty=qty, hours=est, crew_type="Local Crew", sort_order=sort)
    db.session.add_all([hdr, row]); db.session.flush()
    return row


def _named(db, act, first, last, hours, company=None, actual=None, dept=None, sort=10):
    from models import CrewMember, CrewRow, Position
    cm = CrewMember(first_name=first, last_name=last,
                    company_id=company.id if company else None)
    if dept:
        p = Position(title=f"{dept} Lead {last}", department=dept)
        db.session.add(p); db.session.flush()
        cm.position_id = p.id
    db.session.add(cm); db.session.flush()
    row = CrewRow(activity_id=act.id, crew_member_id=cm.id, qty=1, hours=hours,
                  actual_hours=actual, sort_order=sort)
    db.session.add(row); db.session.flush()
    return cm, row


def _get(client, show, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get("/shows/%d/crew/hours%s" % (show.id, "?" + q if q else "")).get_data(as_text=True)


def test_local_labor_appears_as_a_line_per_company_and_position(app, client, db):
    show = _show(db, "HRL1")
    day, act = _day(db, show)
    pos = _local_position(db, "Lighting Hand HRL1")
    _local_line(db, act, pos, qty=6, est=10)
    db.session.commit()
    html = _get(client, show)
    assert "Local Labor" in html and "6 bodies" in html
    assert "Lighting Hand HRL1" in html
    assert "6×</span>10" in html     # bodies × estimate, nothing recorded yet
    assert "60.0" in html            # line total
    assert "Unnamed / TBD" not in html   # local labor is not TBD any more


def test_per_body_actuals_split_per_body(app, client, db):
    """Six booked at 10. Four left at 10, two stayed to 13: OT is 2×2=4,
    DT 2×1=2 — not the 0 a line-level average of 11 would give, and not the
    (0 OT, 0 DT) of 'most people worked ten'."""
    from models import bodies_for
    show = _show(db, "HRL2")
    day, act = _day(db, show)
    pos = _local_position(db, "Lighting Hand HRL2")
    row = _local_line(db, act, pos, qty=6, est=10)
    for i, b in enumerate(bodies_for(row)):
        b.actual_hours = 13 if i >= 4 else 10
    db.session.commit()
    html = _get(client, show)
    assert "Billable split" in html
    assert "66.0" in html             # recorded sum on the day
    # OT 4 (two bodies × hours 11-12), DT 2 (two bodies × hour 13)
    assert "OT <strong>4.0</strong>" in html
    assert "DT <strong>2.0</strong>" in html


def test_a_partly_recorded_line_is_marked(app, client, db):
    from models import bodies_for
    show = _show(db, "HRL3")
    day, act = _day(db, show)
    pos = _local_position(db, "Rigger HRL3", dept="Rigging")
    row = _local_line(db, act, pos, qty=3, est=8)
    bodies_for(row)[0].actual_hours = 9
    db.session.commit()
    html = _get(client, show)
    assert "1 of 3 recorded" in html
    assert "the estimate stands in" in html


def test_local_labor_takes_its_companys_terms(app, client, db):
    """A house crew on an 8-hour day: 10 hours is 8 ST + 2 OT for them."""
    from models import Company
    co = Company(name="House Crew HRL4", ot_after_hours=8)
    db.session.add(co); db.session.flush()
    show = _show(db, "HRL4")
    day, act = _day(db, show)
    pos = _local_position(db, "Stagehand HRL4", dept="General")
    _local_line(db, act, pos, qty=2, est=10, company=co)
    db.session.commit()
    html = _get(client, show)
    assert "OT 8 · DT 12" in html
    assert "OT <strong>4.0</strong>" in html      # 2 bodies × 2 OT hours
    assert "House Crew HRL4 local labor (OT after 8, DT after 12)" in html


def test_a_named_person_on_their_own_terms(app, client, db):
    from models import Company
    show = _show(db, "HRL5")
    day, act = _day(db, show)
    cm, row = _named(db, act, "Eight", "Hour", hours=10)
    cm.ot_after_hours = 8
    db.session.commit()
    html = _get(client, show)
    assert "Billable split" in html
    assert "OT <strong>2.0</strong>" in html
    assert "Hour, Eight (OT after 8, DT after 12)" in html or "Eight Hour (OT after 8, DT after 12)" in html


def test_a_recorded_actual_is_what_gets_split(app, client, db):
    """Estimated 10, actually 14: the split is on 14."""
    show = _show(db, "HRL6")
    day, act = _day(db, show)
    _named(db, act, "Long", "Night", hours=10, actual=14)
    db.session.commit()
    html = _get(client, show)
    assert "OT <strong>2.0</strong>" in html and "DT <strong>2.0</strong>" in html


def test_company_subtotals_follow_each_group(app, client, db):
    from models import Company
    a = Company(name="Alpha AV HRL7"); b = Company(name="Bravo Sound HRL7")
    db.session.add_all([a, b]); db.session.flush()
    show = _show(db, "HRL7")
    day, act = _day(db, show)
    _named(db, act, "One", "Alpha", 10, company=a, sort=10)
    _named(db, act, "Two", "Alpha", 8, company=a, sort=11)
    _named(db, act, "Three", "Bravo", 6, company=b, sort=12)
    db.session.commit()
    html = _get(client, show)
    assert "Alpha AV HRL7 · 2 people" in html
    assert "Bravo Sound HRL7 · 1 person" in html
    assert "18.0" in html


def test_filters_by_department_and_company(app, client, db):
    from models import Company
    a = Company(name="Alpha AV HRL8"); b = Company(name="Bravo Sound HRL8")
    db.session.add_all([a, b]); db.session.flush()
    show = _show(db, "HRL8")
    day, act = _day(db, show)
    _named(db, act, "Lyle", "Lampwright", 10, company=a, dept="Lighting", sort=10)
    _named(db, act, "Sonia", "Soundperson", 8, company=b, dept="Audio", sort=11)
    pos = _local_position(db, "Rigger HRL8", dept="Rigging")
    _local_line(db, act, pos, qty=2, est=10, company=a, sort=20)
    db.session.commit()

    html = _get(client, show, dept="Audio")
    assert "Soundperson" in html and "Lampwright" not in html and "Rigger HRL8" not in html
    assert "filtered" in html

    html = _get(client, show, company="Alpha+AV+HRL8")
    assert "Lampwright" in html and "Soundperson" not in html and "Rigger HRL8" in html

    # the option list is unfiltered, so the filter can be undone from here
    assert 'value="Bravo Sound HRL8"' in html
    assert ">Clear<" in html


def test_a_show_with_only_local_labor_still_renders_the_report(app, client, db):
    show = _show(db, "HRL9")
    day, act = _day(db, show)
    pos = _local_position(db, "Stagehand HRL9", dept="General")
    _local_line(db, act, pos, qty=4, est=10)
    db.session.commit()
    html = _get(client, show)
    assert "No hours tracked yet" not in html
    assert "Stagehand HRL9" in html


def test_a_local_line_linked_to_a_placeholder_record_is_still_a_count(app, client, db):
    """Show 3 in production links every local labor line to one placeholder
    crew record per position — 42 records all named "First Last" at Sparks,
    which `display_label` renders as "<Company> Lighting Hand". Before 09-06
    the report tested crew_member_id first and claimed those as named
    people: 8 hands x 10 hrs became one person working 80 hours in a day,
    split 10 ST + 2 OT + 68 DT. A local labor row linked to a STAND-IN record
    is a count. (A row linked to a real person is that person — see the
    next test.)"""
    from models import CrewMember, CrewRow, Company
    co = Company(name="Placeholder Labor Co HRL10")
    db.session.add(co); db.session.flush()
    show = _show(db, "HRL10")
    day, act = _day(db, show)
    pos = _local_position(db, "Lighting Hand HRL10")
    ph = CrewMember(first_name="First", last_name="Last", company_id=co.id,
                    position_id=pos.id)
    db.session.add(ph); db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=ph.id,
                           position_id=pos.id, position=pos.title, qty=8,
                           hours=10, crew_type="Local Crew", sort_order=2))
    db.session.commit()
    html = _get(client, show)
    assert "8 bodies" in html
    assert "8×</span>10" in html
    assert "Placeholder Labor Co HRL10" in html     # company from the record
    assert "Billable split" not in html            # 8 x 10 is no overtime
    assert "80.0" in html
    # not a named person, and no "1 named crew" line for it
    assert "0 named crew" in html


def test_a_named_person_on_a_catalogue_position_is_named_crew(app, client, db):
    """Jason, 2026-09-06: a named person wins. Jason Chrimes and Brian
    Fugelsang sat on "Scenic Head" — a title the local labor catalogue also
    carries — for seven days of MCDC26, and the catalogue rule turned them
    into a two-body local line: names gone, hours split on Sparks' terms.
    A row that names a real crew member is that person, whatever the title."""
    from models import CrewMember, CrewRow, Company
    co = Company(name="Accelerator Scenic HRL11")
    db.session.add(co); db.session.flush()
    show = _show(db, "HRL11")
    day, act = _day(db, show)
    pos = _local_position(db, "Scenic Head HRL11", dept="Scenic")
    person = CrewMember(first_name="Jason", last_name="Chrimes HRL11",
                        company_id=co.id, position_id=pos.id)
    db.session.add(person); db.session.flush()
    row = CrewRow(activity_id=act.id, crew_member_id=person.id,
                  position_id=pos.id, position=pos.title, qty=1,
                  hours=10, crew_type="Lead Crew", sort_order=2)
    db.session.add(row); db.session.commit()
    assert row.is_local_labor is False
    html = _get(client, show)
    assert "Chrimes HRL11" in html
    assert "1 named crew" in html
    assert "local labor bod" not in html      # no local table at all
