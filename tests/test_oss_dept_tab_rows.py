"""A department tab is one day-grouped table, not a warning box on top of one.

Recurring events used to be listed for every department in a box styled
#FEF3C7 / #FCD34D / #92400E — the app's WARNING colour, the same treatment as
"no F&B" — above that department's own entries table, with no day grouping at
all. Doors is the only tab on show 3 that has any, and it has twenty-one of
them against six entries of its own, so the one tab where recurring events
ARE the schedule read as a warning about itself.

These tests fix the shape that replaces it: build_dept_rows() merges the two
into one stream ordered by day then clock, and the tab renders it with the
day page's row-kind language — RC for recurring, AC for entered, chip and
rail, day header bands.
"""
import datetime as dt

import pytest

from oss_export import build_dept_rows


# ── The merge, in isolation ──────────────────────────────────────────────

class _Day:
    def __init__(self, id, date, label=None, phase=None):
        self.id, self.date, self.label, self.phase = id, date, label, phase


class _Entry:
    """Just enough SubScheduleEntry for build_dept_rows()."""
    def __init__(self, day, time, sort_order=0):
        self.schedule_day = day
        self.schedule_day_id = day.id if day else None
        self.effective_time = time
        self.sort_order = sort_order


def _event(day, name, sort_min, time=None, end_time=None):
    return {"day": day, "name": name, "sort_min": sort_min,
            "time": time or "—", "end_time": end_time, "hardcoded": True}


def test_rows_are_grouped_by_day_in_date_order():
    d1 = _Day(1, dt.date(2026, 7, 8))
    d2 = _Day(2, dt.date(2026, 7, 9))
    grouped = build_dept_rows(
        [_Entry(d2, "9:00 AM")],
        [_event(d1, "DOORS OPEN", 18 * 60)],
    )
    assert [day.id for day, _ in grouped] == [1, 2]
    assert [len(rows) for _, rows in grouped] == [1, 1]


def test_a_day_is_one_contiguous_block_not_two():
    """The failure the old two-list layout guaranteed: every recurring event
    in one place and every entry in another, so a single day was read twice."""
    d = _Day(1, dt.date(2026, 7, 8))
    grouped = build_dept_rows(
        [_Entry(d, "8:00 AM"), _Entry(d, "11:00 PM")],
        [_event(d, "DOORS OPEN", 18 * 60), _event(d, "DOORS CLOSE", 23 * 60)],
    )
    assert len(grouped) == 1
    assert len(grouped[0][1]) == 4


def test_within_a_day_the_order_is_the_clock():
    d = _Day(1, dt.date(2026, 7, 8))
    grouped = build_dept_rows(
        [_Entry(d, "8:00 AM"), _Entry(d, "7:00 PM")],
        [_event(d, "DOORS OPEN", 18 * 60), _event(d, "LOBBY SWEEP", 7 * 60)],
    )
    (_, rows), = grouped
    names = [r["event"]["name"] if r["kind"] == "recur" else r["time"]
             for r in rows]
    assert names == ["LOBBY SWEEP", "8:00 AM", "DOORS OPEN", "7:00 PM"]


def test_recurring_leads_an_entry_on_the_same_minute():
    """A recurring event is a fixed fact of the venue's day; the department's
    entry is the response to it, so it reads second."""
    d = _Day(1, dt.date(2026, 7, 8))
    grouped = build_dept_rows(
        [_Entry(d, "6:00 PM")],
        [_event(d, "DOORS OPEN", 18 * 60)],
    )
    (_, rows), = grouped
    assert [r["kind"] for r in rows] == ["recur", "act"]


def test_a_dateless_day_sorts_last_rather_than_first():
    dated = _Day(1, dt.date(2026, 7, 8))
    undated = _Day(2, None)
    grouped = build_dept_rows([_Entry(undated, "8:00 AM"),
                               _Entry(dated, "8:00 AM")], [])
    assert [day.id for day, _ in grouped] == [1, 2]


def test_each_row_carries_exactly_one_of_entry_or_event():
    d = _Day(1, dt.date(2026, 7, 8))
    grouped = build_dept_rows([_Entry(d, "8:00 AM")],
                              [_event(d, "DOORS OPEN", 18 * 60)])
    (_, rows), = grouped
    for r in rows:
        assert (r["entry"] is None) != (r["event"] is None)


def test_no_entries_and_no_events_is_no_days():
    assert build_dept_rows([], []) == []


# ── The Doors tab, rendered ──────────────────────────────────────────────

DOORS_EVENTS = [
    ("HOUSE OPEN", "SOD", 0),
    ("DOORS OPEN", "SOD", 120),
    ("DOORS CLOSE", "EOD", -30),
]


@pytest.fixture
def doors_show(db):
    """Three days, three recurring Doors events each (nine occurrences), plus
    two entries of the department's own — Doors' shape in miniature."""
    from models import Show, ScheduleDay, HardCodedEvent, SubScheduleEntry
    show = Show(name="Doors Shape", code="DOOR26")
    db.session.add(show)
    db.session.flush()
    days = []
    for n in (8, 9, 10):
        d = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, n),
                        sod="8:00 AM", eod="11:00 PM")
        db.session.add(d)
        days.append(d)
    for name, anchor, offset in DOORS_EVENTS:
        db.session.add(HardCodedEvent(
            name=name, department="Doors", start_anchor=anchor,
            start_offset=offset, active=True))
    db.session.flush()
    db.session.add(SubScheduleEntry(show_id=show.id, type="Doors",
                                    schedule_day_id=days[0].id,
                                    time="9:00 AM", activity="Unlock loading"))
    db.session.add(SubScheduleEntry(show_id=show.id, type="Doors",
                                    schedule_day_id=days[1].id,
                                    time="10:00 PM", activity="Key handback"))
    db.session.commit()
    return show


PANE = '<div class="tab-pane oss-tab-pane'


def _doors_pane(body):
    """The Doors pane alone. Every tab is rendered into the page, and the F&B
    tab legitimately still carries amber warning badges, so a whole-page
    assertion about colour would be measuring the wrong thing."""
    # The tab's help line is unique to Doors; walk out to its pane's bounds.
    anchor = body.index("Door lock/unlock times and who has keys.")
    start = body.rindex(PANE, 0, anchor)
    end = body.find(PANE, anchor)
    return body[start:end if end != -1 else len(body)]


def test_recurring_events_are_no_longer_an_amber_warning_box(client, doors_show):
    r = client.get("/shows/%d/oss?tab=Doors" % doors_show.id)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # The exact box that was removed. Its three hexes are also three of the
    # ~500 off-brand occurrences still open as a design decision.
    assert "background:#FEF3C7;border:1px solid #FCD34D" not in body
    assert "#92400E" not in _doors_pane(body)


def test_recurring_events_still_surface_and_say_so(client, doors_show):
    body = client.get("/shows/%d/oss?tab=Doors"
                      % doors_show.id).get_data(as_text=True)
    for name, _, _ in DOORS_EVENTS:
        assert name in body
    # Renamed to "Recurring Events" on 2026-08-11 (note 7); the wording is
    # asserted by test_hardcoded_oss_surfacing too.
    assert "Recurring Events" in body


def test_the_tab_groups_by_day(client, doors_show):
    body = client.get("/shows/%d/oss?tab=Doors"
                      % doors_show.id).get_data(as_text=True)
    pane = _doors_pane(body)
    assert pane.count('class="oss-day-header"') == 3
    for n in (8, 9, 10):
        assert dt.date(2026, 7, n).strftime("%A, %B %-d, %Y") in pane


def test_both_kinds_share_one_table_and_are_told_apart_by_the_chip(
        client, doors_show):
    body = client.get("/shows/%d/oss?tab=Doors"
                      % doors_show.id).get_data(as_text=True)
    pane = _doors_pane(body)
    # Nine recurring occurrences (3 events x 3 days) and two entries.
    assert pane.count('title="recur"') == 9
    assert pane.count('title="act"') == 2
    # One table, not two.
    assert pane.count("<table") == 1


def test_a_recurring_row_offers_no_edit_or_delete(client, doors_show):
    """It is computed from SOD/EOD and lives on the Recurring Events page.
    Two entries means exactly two Edit buttons, whatever else is in the table.
    """
    body = client.get("/shows/%d/oss?tab=Doors"
                      % doors_show.id).get_data(as_text=True)
    pane = _doors_pane(body)
    assert pane.count(">Edit</button>") == 2
    assert pane.count(">Del</button>") == 2


def test_the_rows_carry_the_day_pages_rails(client, doors_show):
    """The same language, from the same macro — templates/_row_kinds.html."""
    pane = _doors_pane(client.get("/shows/%d/oss?tab=Doors"
                                  % doors_show.id).get_data(as_text=True))
    assert "border-left:4px dotted var(--adi-gold-lt);" in pane   # recur
    assert "border-left:2px solid var(--adi-kind-act);" in pane   # act
    assert "background:var(--adi-tint-recur);" in pane
