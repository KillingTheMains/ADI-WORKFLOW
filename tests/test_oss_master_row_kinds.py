"""The OSS master schedule says what kind of row each row is.

build_master_items() has decided a `kind` for every row since sitting 5 — it
is the one place that actually knows whether a row is a crew call, a break, a
beverage service, a recurring event or an ordinary activity — and both
exporters print it through brand.KIND_CODE. The screen was the only surface
that threw it away: every row rendered as the same grey line, so the master
tab was the one view of a show day that could not tell you what you were
looking at.

Interface Spec §07: chip, rail, silhouette.
"""
import datetime as dt

import pytest


@pytest.fixture
def master_show(db):
    """Two days. Each carries three recurring events and one OSS entry, so the
    master timeline has both kinds in it and more than one day to group."""
    from models import Show, ScheduleDay, HardCodedEvent, SubScheduleEntry
    show = Show(name="Master Kinds", code="MK26")
    db.session.add(show)
    db.session.flush()
    days = []
    for n in (8, 9):
        d = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, n),
                        sod="8:00 AM", eod="11:00 PM")
        db.session.add(d)
        days.append(d)
    for name, anchor, offset in (("HOUSE OPEN", "SOD", 0),
                                 ("DOORS OPEN", "SOD", 120),
                                 ("DOORS CLOSE", "EOD", -30)):
        db.session.add(HardCodedEvent(name=name, department="Doors",
                                      start_anchor=anchor,
                                      start_offset=offset, active=True))
    db.session.flush()
    for d in days:
        db.session.add(SubScheduleEntry(show_id=show.id, type="Dock",
                                        schedule_day_id=d.id, time="9:00 AM",
                                        activity="Truck 1 in"))
    db.session.commit()
    return show


def _master_pane(body):
    start = body.index('id="tab-master"')
    end = body.index('<div class="tab-pane oss-tab-pane', start)
    return body[start:end]


def _pane(client, show):
    return _master_pane(client.get("/shows/%d/oss?tab=master"
                                   % show.id).get_data(as_text=True))


def test_every_master_row_carries_a_kind_chip(client, master_show):
    """The load-bearing one. A row with no chip is a row the reader has to
    guess at, and on paper the chip is the only channel left."""
    pane = _pane(client, master_show)
    day_headers = pane.count('class="oss-master-day-header"')
    header_row = 1                      # the <thead> row
    data_rows = pane.count("<tr") - day_headers - header_row
    assert data_rows > 0
    assert pane.count('<span title="') == data_rows


def test_recurring_and_entered_rows_are_told_apart(client, master_show):
    pane = _pane(client, master_show)
    assert pane.count('title="recur"') == 6      # 3 events x 2 days
    # One Dock entry per day. They print DK, not AC: the OSS is a summary of
    # the day schedules, so a row that says DK on the day cannot say AC here.
    assert pane.count('title="Dock"') == 2
    assert pane.count('title="act"') == 0


def test_the_rails_are_the_day_pages_rails(client, master_show):
    """Same declarations, from templates/_row_kinds.html — not a second
    vocabulary that drifts."""
    pane = _pane(client, master_show)
    assert "border-left:4px dotted var(--adi-gold-lt);" in pane
    assert "border-left:2px solid var(--adi-kind-act);" in pane
    assert "background:var(--adi-tint-recur);" in pane


def test_the_fill_is_on_the_cells_not_the_row(client, master_show):
    """Bootstrap paints every <td> over its <tr>'s background, so a fill set
    on the row silently never appears. This is the assertion that catches a
    well-meaning tidy-up that moves it back."""
    pane = _pane(client, master_show)
    assert "<tr style=" not in pane
    assert '<td style="background:var(--adi-tint-recur);' in pane


def test_a_day_still_groups_under_one_band(client, master_show):
    pane = _pane(client, master_show)
    assert pane.count('class="oss-master-day-header"') == 2
    for n in (8, 9):
        assert dt.date(2026, 7, n).strftime("%A, %B %-d, %Y") in pane


def test_the_day_band_spans_the_new_column_count(client, master_show):
    """The chip column made it seven. A stale colspan leaves a white notch in
    the band, which reads as a rendering fault on a printed page."""
    pane = _pane(client, master_show)
    assert 'colspan="7"' in pane
    assert 'colspan="6"' not in pane


def test_an_unknown_kind_costs_a_rail_not_the_page(client, master_show):
    """kind_chip_safe / RAIL.get: the OSS page is opened on a show morning.
    A row kind nobody anticipated should degrade, not 500."""
    from flask import render_template_string
    out = render_template_string(
        "{% import '_row_kinds.html' as rk %}"
        "[{{ rk.row_shell('nonesuch') }}][{{ rk.row_fill('nonesuch') }}]"
        "{{ rk.kind_chip_safe('nonesuch') }}")
    assert "[][]" in out
    assert 'title="act"' in out
