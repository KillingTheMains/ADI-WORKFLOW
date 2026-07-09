"""Tests for the Travel page: company section banners (#28), grand-total
hotel nights on exports (#28), and the bulk travel-date editor (P1)."""
import datetime as dt
import io
import openpyxl


def _seed(db):
    from models import Company, Position, CrewMember, Show, ShowCrewAssignment
    bav = Company(name="BAV Productions")
    ct  = Company(name="CT Rentals")
    a1  = Position(title="A1", department="Audio")
    db.session.add_all([bav, ct, a1])
    db.session.flush()
    # Two BAV crew, one CT crew
    c1 = CrewMember(first_name="Ann",  last_name="Adams", company_id=bav.id, position_id=a1.id)
    c2 = CrewMember(first_name="Bob",  last_name="Boyd",  company_id=bav.id, position_id=a1.id)
    c3 = CrewMember(first_name="Cara", last_name="Cole",  company_id=ct.id,  position_id=a1.id)
    show = Show(name="Test Show", code="TS26")
    db.session.add_all([c1, c2, c3, show])
    db.session.flush()
    d = dt.date(2026, 7, 1)
    a_ann = ShowCrewAssignment(show_id=show.id, crew_member_id=c1.id,
                               travel_in_date=d, travel_out_date=d + dt.timedelta(days=3))  # 3 nights
    a_bob = ShowCrewAssignment(show_id=show.id, crew_member_id=c2.id,
                               travel_in_date=d, travel_out_date=d + dt.timedelta(days=2))  # 2 nights
    a_cara = ShowCrewAssignment(show_id=show.id, crew_member_id=c3.id,
                                travel_in_date=d, travel_out_date=d + dt.timedelta(days=1))  # 1 night
    db.session.add_all([a_ann, a_bob, a_cara])
    db.session.commit()
    return show.id, [a_ann.id, a_bob.id, a_cara.id]


def test_travel_page_shows_grand_total_nights(client, db):
    show_id, _ = _seed(db)
    r = client.get(f"/shows/{show_id}/crew/travel")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Grand-total hotel nights:" in body
    # 3 + 2 + 1 = 6
    assert "<strong>6</strong>" in body


def test_travel_page_company_banner_when_sorted_by_company(client, db):
    show_id, _ = _seed(db)
    r = client.get(f"/shows/{show_id}/crew/travel?sort=company")
    body = r.get_data(as_text=True)
    assert 'class="company-banner"' in body
    assert "BAV Productions" in body and "2 travelers" in body
    assert "CT Rentals" in body and "1 traveler" in body
    # No banners when not sorted by company
    r2 = client.get(f"/shows/{show_id}/crew/travel?sort=name")
    assert 'class="company-banner"' not in r2.get_data(as_text=True)


def test_travel_xlsx_has_nights_total_and_banners(client, db):
    show_id, _ = _seed(db)
    r = client.get(f"/shows/{show_id}/crew/travel.xlsx?sort=company")
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.get_data()))
    ws = wb.active
    cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    joined = " ".join(cells)
    assert "Grand-total hotel nights:" in joined
    assert "6" in cells  # nights total value
    assert any("BAV Productions" in c and "traveler" in c for c in cells)


def test_bulk_dates_updates_selected(client, db):
    show_id, aids = _seed(db)
    from models import ShowCrewAssignment
    # Apply a new travel-in + show window to the first two only
    r = client.post(f"/shows/{show_id}/crew/travel/bulk-dates", data={
        "assignment_ids": [str(aids[0]), str(aids[1])],
        "travel_in_date": "2026-08-01",
        "start_date": "2026-08-02",
        "end_date": "2026-08-05",
        "travel_out_date": "2026-08-06",
    })
    assert r.status_code in (200, 302)
    a0 = ShowCrewAssignment.query.get(aids[0])
    a1 = ShowCrewAssignment.query.get(aids[1])
    a2 = ShowCrewAssignment.query.get(aids[2])
    assert a0.travel_in_date == dt.date(2026, 8, 1)
    assert a0.start_date == dt.date(2026, 8, 2)
    assert a0.end_date == dt.date(2026, 8, 5)
    assert a0.travel_out_date == dt.date(2026, 8, 6)
    assert a1.travel_in_date == dt.date(2026, 8, 1)
    # Unselected row untouched
    assert a2.travel_in_date == dt.date(2026, 7, 1)


def test_bulk_dates_only_sets_provided_fields(client, db):
    show_id, aids = _seed(db)
    from models import ShowCrewAssignment
    before_out = ShowCrewAssignment.query.get(aids[0]).travel_out_date
    # Only send travel_in_date — other fields blank should be left alone
    r = client.post(f"/shows/{show_id}/crew/travel/bulk-dates", data={
        "assignment_ids": [str(aids[0])],
        "travel_in_date": "2026-09-09",
        "start_date": "",
        "end_date": "",
        "travel_out_date": "",
    })
    assert r.status_code in (200, 302)
    a0 = ShowCrewAssignment.query.get(aids[0])
    assert a0.travel_in_date == dt.date(2026, 9, 9)
    assert a0.travel_out_date == before_out  # unchanged
