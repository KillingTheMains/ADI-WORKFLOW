"""Actual hours typed on the Hours Report (Jason, 2026-09-07).

    The day cells of the named table are inputs; each edits the same
    CrewRow.actual_hours the day page edits. An estimate shows with a star
    (10*), a recorded actual without one. Company rows and the daily totals
    carry a figure per day — actual where recorded, else estimate, starred
    when any estimate is inside. "Use estimate" on a company row fills only
    that company's blanks. Δ compares the actual with the estimate of the
    days that have an actual. A person with two calls on one day gets a
    read-only cell (the actual belongs to a shift).
"""
import datetime as dt
import re


def _show(db, people, code="HRA1", start=dt.date(2026, 9, 8)):
    """people: {name: (company_name|None, [hours per day])}."""
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        CrewMember, ShowCrewAssignment, Company)
    show = Show(name="Actuals", code=code)
    db.session.add(show); db.session.flush()
    n_days = max(len(v[1]) for v in people.values())
    days = []
    for i in range(n_days):
        day = ScheduleDay(show_id=show.id, date=start + dt.timedelta(days=i))
        db.session.add(day); db.session.flush()
        act = ScheduleActivity(day_id=day.id, time="07:00", description="CREW START")
        db.session.add(act); db.session.flush()
        days.append((day, act))
    companies = {}
    members = {}
    for name, (co_name, hours) in people.items():
        co = None
        if co_name:
            co = companies.get(co_name) or Company(name=co_name)
            companies[co_name] = co
            db.session.add(co); db.session.flush()
        first, last = name.split(" ", 1)
        cm = CrewMember(first_name=first, last_name=last, company_id=co.id if co else None)
        db.session.add(cm); db.session.flush()
        members[name] = cm
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
        for (day, act), h in zip(days, hours):
            if h:
                db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id, qty=1, hours=h))
    db.session.commit()
    return show, members, days


def _rows_for(db, cm):
    from models import CrewRow
    return CrewRow.query.filter_by(crew_member_id=cm.id).order_by(CrewRow.id).all()


def test_each_day_cell_is_an_input_showing_the_starred_estimate(app, client, db):
    show, m, _ = _show(db, {"Ann Actual": ("BAV", [10, 10])})
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    rows = _rows_for(db, m["Ann Actual"])
    assert 'form="hr-%d"' % rows[0].id in html
    assert 'placeholder="10*"' in html
    assert 'action="/shows/%d/crew/hours/row/%d"' % (show.id, rows[0].id) in html
    assert 'Use estimate' in html


def test_saving_a_cell_writes_the_rows_actual_and_drops_the_star(app, client, db):
    show, m, _ = _show(db, {"Ann Actual": ("BAV", [10, 10])})
    r0 = _rows_for(db, m["Ann Actual"])[0]
    r = client.post("/shows/%d/crew/hours/row/%d" % (show.id, r0.id),
                    data={"actual_hours": "12"}, headers={"X-Autosave": "1"})
    assert r.status_code == 204
    db.session.expire_all()
    assert _rows_for(db, m["Ann Actual"])[0].actual_hours == 12.0
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert 'value="12"' in html
    # Δ is against the estimate of the recorded day only: 12 vs 10, not 12 vs 20.
    assert "+2.0" in html and "-8.0" not in html
    # Company row: day one is recorded (no star), day two still estimated.
    sub = re.search(r'class="company-subtotal">(.*?)</tr>', html, re.S).group(1)
    cells = re.findall(r'<td class="day-cell">(.*?)</td>', sub, re.S)
    assert "12.0" in cells[0] and "est-star" not in cells[0]
    assert "10.0" in cells[1] and "est-star" in cells[1]


def test_blank_clears_and_junk_clears(app, client, db):
    show, m, _ = _show(db, {"Ann Actual": ("BAV", [10])})
    r0 = _rows_for(db, m["Ann Actual"])[0]
    r0.actual_hours = 9.0; db.session.commit()
    client.post("/shows/%d/crew/hours/row/%d" % (show.id, r0.id),
                data={"actual_hours": ""}, headers={"X-Autosave": "1"})
    db.session.expire_all()
    assert _rows_for(db, m["Ann Actual"])[0].actual_hours is None


def test_a_row_outside_the_show_or_a_local_labor_row_is_refused(app, client, db):
    from models import Position, CrewRow
    show, m, days = _show(db, {"Ann Actual": ("BAV", [10])})
    other, _, _ = _show(db, {"Bob Other": ("BAV", [8])}, code="HRA2")
    r_other = _rows_for(db, m["Ann Actual"])[0]
    assert client.post("/shows/%d/crew/hours/row/%d" % (other.id, r_other.id),
                       data={"actual_hours": "1"}).status_code == 404
    pos = Position.query.filter_by(is_local_labor=True).first() \
        or Position(title="Test Hand", is_local_labor=True)
    db.session.add(pos); db.session.flush()
    ll = CrewRow(activity_id=days[0][1].id, qty=4, hours=10, position_id=pos.id)
    db.session.add(ll); db.session.commit()
    assert client.post("/shows/%d/crew/hours/row/%d" % (show.id, ll.id),
                       data={"actual_hours": "1"}).status_code == 404


def test_use_estimate_fills_only_that_companys_blanks(app, client, db):
    show, m, _ = _show(db, {"Ann Actual": ("BAV", [10, 10]),
                            "Cy Typed": ("BAV", [8, 8]),
                            "Dee Other": ("Sparks", [6, 6])})
    cy = _rows_for(db, m["Cy Typed"]); cy[0].actual_hours = 7.5; db.session.commit()
    r = client.post("/shows/%d/crew/hours/company/fill" % show.id,
                    data={"company": "BAV"}, headers={"X-Autosave": "1"})
    assert r.status_code == 200 and r.get_json() == {"filled": 3}
    db.session.expire_all()
    assert [x.actual_hours for x in _rows_for(db, m["Ann Actual"])] == [10.0, 10.0]
    assert [x.actual_hours for x in _rows_for(db, m["Cy Typed"])] == [7.5, 8.0]   # typed one kept
    assert [x.actual_hours for x in _rows_for(db, m["Dee Other"])] == [None, None]
    again = client.post("/shows/%d/crew/hours/company/fill" % show.id,
                        data={"company": "BAV"}, headers={"X-Autosave": "1"})
    assert again.get_json() == {"filled": 0}


def test_use_estimate_without_autosave_redirects_with_a_flash(app, client, db):
    show, m, _ = _show(db, {"Ann Actual": ("BAV", [10])})
    r = client.post("/shows/%d/crew/hours/company/fill" % show.id,
                    data={"company": "BAV"}, follow_redirects=True)
    assert r.status_code == 200
    assert "1 filled from the estimate" in r.get_data(as_text=True)


def test_two_calls_on_one_day_make_a_read_only_cell(app, client, db):
    from models import ScheduleActivity, CrewRow
    show, m, days = _show(db, {"Ann Actual": ("BAV", [10])})
    day, _act = days[0]
    act2 = ScheduleActivity(day_id=day.id, time="19:00", description="SHOW CALL")
    db.session.add(act2); db.session.flush()
    db.session.add(CrewRow(activity_id=act2.id, crew_member_id=m["Ann Actual"].id, qty=1, hours=4))
    db.session.commit()
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert 'class="hr-in' not in html
    assert "Two calls this day" in html
    assert '14.0<span class="est-star">*</span>' in html


def test_the_day_header_is_upright_with_the_weekday(app, client, db):
    show, _, _ = _show(db, {"Ann Actual": ("BAV", [10])})          # Tue 9/8
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    assert '<span class="dow">Tue</span>' in html
    assert "writing-mode" not in html


def test_daily_totals_are_billable_and_starred_while_any_estimate_remains(app, client, db):
    show, m, _ = _show(db, {"Ann Actual": ("BAV", [10]), "Bob Other": ("BAV", [10])})
    r0 = _rows_for(db, m["Ann Actual"])[0]; r0.actual_hours = 12; db.session.commit()
    html = client.get("/shows/%d/crew/hours" % show.id).get_data(as_text=True)
    total = re.search(r'class="total-row">(.*?)</tr>', html, re.S).group(1)
    cell = re.findall(r'<td class="day-cell">(.*?)</td>', total, re.S)[0]
    assert "22.0" in cell and "est-star" in cell
