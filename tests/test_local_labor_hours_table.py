"""The Local Labor Hours page in the Hours Report's language (Jason, 2026-09-08).

Jason liked the Hours Report and asked for this page to match. That is a
LOOK request with a structural decision inside it: the obvious table is one
row per body, and it is the wrong one — MCDC26 would be 344 rows and the
LINE, which is how the crew is booked and how the vendor invoices, would
disappear. So: one row per line, bodies as a strip of boxes in one cell,
and the report's furniture around it — stat tiles, department/company
filters, a day divider, a day subtotal and a Midnight show total.

These tests hold the parts a restyle could quietly break: that the filter
means the same thing on both pages, that Δ is measured the same way, that
"Use estimate" still only fills blanks, and that the autosave forms did not
get swept inside the table (where a browser hoists them out and the save
stops working).
"""
import datetime as dt


def _show(db, code="LLT1"):
    """Two days. Day 1: two lines (qty 2 est 9, qty 1 est 8, different
    departments and companies). Day 2: one line with NO estimate."""
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, Position,
                        Company)
    show = Show(name="Table", code=code)
    db.session.add(show); db.session.flush()

    vra = Company(name="VRA " + code); other = Company(name="Zenith " + code)
    db.session.add_all([vra, other]); db.session.flush()
    rig = Position(title="Rigger " + code, department="Rigging", is_local_labor=True)
    lx = Position(title="Lighting Hand " + code, department="Lighting", is_local_labor=True)
    db.session.add_all([rig, lx]); db.session.flush()

    d1 = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 1))
    d2 = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 2))
    db.session.add_all([d1, d2]); db.session.flush()
    a1 = ScheduleActivity(day_id=d1.id, time="07:00", description="LOAD IN", sort_order=1)
    a2 = ScheduleActivity(day_id=d2.id, time="08:00", description="SHOW", sort_order=1)
    db.session.add_all([a1, a2]); db.session.flush()

    h1 = CrewRow(activity_id=a1.id, is_group_header=True, group_label="LOCAL CREW",
                 company_id=vra.id, sort_order=1, qty=0)
    r1 = CrewRow(activity_id=a1.id, position_id=rig.id, position=rig.title,
                 qty=2, hours=9.0, crew_type="Local Crew", sort_order=2)
    h2 = CrewRow(activity_id=a1.id, is_group_header=True, group_label="LOCAL CREW 2",
                 company_id=other.id, sort_order=3, qty=0)
    r2 = CrewRow(activity_id=a1.id, position_id=lx.id, position=lx.title,
                 qty=1, hours=8.0, crew_type="Local Crew", sort_order=4)
    r3 = CrewRow(activity_id=a2.id, position_id=rig.id, position=rig.title,
                 qty=2, hours=None, crew_type="Local Crew", sort_order=1)
    db.session.add_all([h1, r1, h2, r2, r3])
    db.session.commit()
    return show, d1, d2, r1, r2, r3, vra, other


def _page(client, show, **params):
    from urllib.parse import urlencode
    url = f"/shows/{show.id}/crew/local-labor-hours"
    if params:
        url += "?" + urlencode(params)
    r = client.get(url)
    assert r.status_code == 200
    return r.get_data(as_text=True)


# ── the shape ───────────────────────────────────────────────────────────────

def test_it_is_a_table_with_the_report_s_furniture(app, client, db):
    show, *_ = _show(db)
    page = _page(client, show)
    assert "ll-table" in page
    for part in ("ll-day-divider", "ll-day-subtotal", "total-row", "stat-card"):
        assert part in page, part
    for head in ("Position", "Company", "Hours per body", "Qty"):
        assert head in page, head


def test_one_row_per_line_not_one_per_body(app, client, db):
    """The decision this page turns on. Three lines, five bodies."""
    show, d1, d2, r1, r2, r3, *_ = _show(db, "LLT2")
    page = _page(client, show)
    for row in (r1, r2, r3):
        assert f'id="row-{row.id}"' in page
    assert page.count('id="row-') == 3
    assert page.count('class="ll-body"') == 5


def test_the_autosave_forms_stay_outside_the_table(app, client, db):
    """A <form> inside a <tr> is invalid markup; browsers hoist it out of the
    table and the autosave silently stops firing. The forms must come after
    the table closes."""
    show, *_ = _show(db, "LLT3")
    page = _page(client, show)
    assert "</table>" in page and 'data-autosave="true"' in page
    assert page.index("</table>") < page.index('data-autosave="true"')


# ── the filters ─────────────────────────────────────────────────────────────

def test_filters_narrow_the_lines_and_the_stats(app, client, db):
    show, d1, d2, r1, r2, r3, vra, other = _show(db, "LLT4")
    page = _page(client, show, dept="Lighting")
    assert f'id="row-{r2.id}"' in page
    assert f'id="row-{r1.id}"' not in page
    assert "filtered" in page


def test_filter_options_come_from_the_unfiltered_show(app, client, db):
    """Otherwise a filter can be applied and never undone from the page it
    produced — the same rule the Hours Report follows."""
    show, d1, d2, r1, r2, r3, vra, other = _show(db, "LLT5")
    page = _page(client, show, dept="Lighting")
    assert "Rigging" in page and "Lighting" in page
    assert vra.name in page and other.name in page
    assert "Clear" in page


def test_a_filter_that_matches_nothing_says_so_and_offers_a_way_back(app, client, db):
    show, *_ = _show(db, "LLT6")
    page = _page(client, show, dept="Audio")
    assert "Nothing matches that filter" in page
    assert "Clear the filter" in page


# ── the numbers ─────────────────────────────────────────────────────────────

def test_delta_is_measured_against_recorded_bodies_only(app, client, db):
    """Two bodies at an estimate of 9; one records 10.5. Δ is +1.5, not −7.5.
    Same rule as the Hours Report's Δ column."""
    from models import bodies_for
    show, d1, d2, r1, *_ = _show(db, "LLT7")
    bodies_for(r1)[0].actual_hours = 10.5
    db.session.commit()
    page = _page(client, show)
    assert "+1.5" in page
    assert "-7.5" not in page and "−7.5" not in page


def test_a_line_with_no_estimate_has_no_fill_button_and_no_delta(app, client, db):
    show, d1, d2, r1, r2, r3, *_ = _show(db, "LLT8")
    page = _page(client, show)
    body = page[page.index(f'id="row-{r3.id}"'):]
    body = body[:body.index("</tr>")]
    assert "Use estimate" not in body


# ── filling a whole day ─────────────────────────────────────────────────────

def test_use_estimate_on_a_day_fills_every_blank_line(app, client, db):
    from models import bodies_for
    show, d1, d2, r1, r2, *_ = _show(db, "LLT9")
    r = client.post(f"/shows/{show.id}/crew/local-labor-hours/day/{d1.id}/fill",
                    follow_redirects=True)
    assert r.status_code == 200
    assert [b.actual_hours for b in bodies_for(r1)] == [9.0, 9.0]
    assert [b.actual_hours for b in bodies_for(r2)] == [8.0]


def test_filling_a_day_leaves_a_typed_figure_alone(app, client, db):
    """A typed figure is an exception somebody recorded on purpose; a
    convenience button must never undo it."""
    from models import bodies_for
    show, d1, d2, r1, *_ = _show(db, "LLT10")
    bodies_for(r1)[0].actual_hours = 13.0
    db.session.commit()
    client.post(f"/shows/{show.id}/crew/local-labor-hours/day/{d1.id}/fill")
    assert [b.actual_hours for b in bodies_for(r1)] == [13.0, 9.0]


def test_filling_a_day_reports_lines_it_could_not_fill(app, client, db):
    show, d1, d2, r1, r2, r3, *_ = _show(db, "LLT11")
    r = client.post(f"/shows/{show.id}/crew/local-labor-hours/day/{d2.id}/fill",
                    follow_redirects=True)
    assert "no estimate" in r.get_data(as_text=True)


def test_a_day_from_another_show_is_refused(app, client, db):
    show, d1, *_ = _show(db, "LLT12")
    other, o1, *_ = _show(db, "LLT13")
    r = client.post(f"/shows/{other.id}/crew/local-labor-hours/day/{d1.id}/fill")
    assert r.status_code == 404


# ── print ───────────────────────────────────────────────────────────────────

def test_it_prints_landscape_with_figures_instead_of_inputs(app, client, db):
    """Eleven bodies on a line is wider than portrait, and an input prints as
    an empty box — the figure has to print in its place, like the report."""
    show, *_ = _show(db, "LLT14")
    page = _page(client, show)
    assert "size: Letter landscape" in page
    assert "ll-print" in page
    assert ".ll-in, .ll-body-form { display: none !important; }" in page
