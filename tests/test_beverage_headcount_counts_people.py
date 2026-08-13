"""The beverage headcount counted LINES, not people. Second copy of the 2026-08-12 bug.

`count_people` was rewritten on 2026-08-12 because the old rule threw `qty`
away whenever a row carried a `crew_member_id` — and an UNFILLED SLOT carries
one, pointing at a placeholder record like "Sparks Lighting Hand". So a line
reading `14 × Rigger` counted as one body.

`beverage_service.crew_windows_for_day` carried its own copy of that rule and
the copy was never updated. Nothing pointed the two at each other, so the fix
landed in one file and not the other:

    if row.crew_member_id:
        qty = 1              # <- the old rule, still live
    else:
        qty = row.qty or 1

Measured on the shape production has — three named leads plus local labour
lines of 14, 7 and 6 — `count_people` said **30** and the beverage refresh
said **SIX**. Six lines counted as six bodies. That number is what a beverage
order is placed against.

Jason, 2026-08-13: "the automatic head counts aren't correct. It only appears
to be counting each line on the local labor crew call section and not the
actual quantity of people."

There is now ONE definition, `models.iter_people`, and both callers use it.
"""
import datetime as dt

import pytest

import beverage_service
from breaks import called_before, on_site_at
from models import count_people, iter_people


@pytest.fixture
def call_of_thirty(db):
    """Three named leads and three local-labour lines of 14, 7 and 6.

    The local rows are PLACEHOLDER-BACKED — they carry a crew_member_id
    pointing at an unfilled slot — because that is what production has and it
    is the condition the old rule got wrong.
    """
    from models import (Company, CrewMember, CrewRow, Position, ScheduleActivity,
                        ScheduleDay, Show, ShowCrewAssignment)
    show = Show(name="Thirty", code="THR26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    co = Company(name="Sparks")
    db.session.add(co)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 8),
                      sod="7:00 AM", eod="11:00 PM")
    db.session.add(day)
    db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="8:00 AM",
                            description="CREW START", sort_order=10)
    db.session.add(call)
    db.session.flush()

    for first, last in [("Ann", "One"), ("Bob", "Two"), ("Cy", "Three")]:
        cm = CrewMember(first_name=first, last_name=last, active=True,
                        company_id=co.id)
        db.session.add(cm)
        db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
        db.session.add(CrewRow(activity_id=call.id, crew_member_id=cm.id,
                               qty=1, hours=10, position="Lead"))

    for title, qty in [("Rigger", 14), ("Lighting Hand", 7),
                       ("Lighting Hand", 6)]:
        pos = Position.query.filter_by(title=title).first()
        if pos is None:
            pos = Position(title=title, department="Rigging", type="hand",
                           is_local_labor=True)
            db.session.add(pos)
            db.session.flush()
        pos.is_local_labor = True
        slot = CrewMember(first_name="First", last_name="Last", active=True,
                          company_id=co.id, position_id=pos.id)
        db.session.add(slot)
        db.session.flush()
        assert slot.is_unnamed_slot, "fixture must be an unfilled slot"
        db.session.add(CrewRow(activity_id=call.id, crew_member_id=slot.id,
                               position_id=pos.id, position=title, qty=qty,
                               hours=10, crew_type="Local Crew"))
    db.session.commit()
    return show, day, call


# ── The bug, stated directly ─────────────────────────────────────────────

def test_the_beverage_window_carries_people_not_lines(app, db, call_of_thirty):
    show, day, call = call_of_thirty
    windows, _est = beverage_service.crew_windows_for_day(day)
    assert sorted(qty for _s, _e, qty in windows) == [1, 1, 1, 6, 7, 14]


def test_a_refresh_is_ordered_for_thirty_not_six(app, db, call_of_thirty):
    show, day, call = call_of_thirty
    windows, _est = beverage_service.crew_windows_for_day(day)
    assert on_site_at(windows, 9 * 60) == 30


def test_the_setup_count_is_thirty_too(app, db, call_of_thirty):
    show, day, call = call_of_thirty
    windows, _est = beverage_service.crew_windows_for_day(day)
    assert called_before(windows, 9 * 60) == 30


def test_the_beverage_count_agrees_with_the_crew_call(app, db, call_of_thirty):
    """The assertion that would have caught this on 2026-08-12. Two surfaces
    describing the same crew at the same moment must not disagree."""
    show, day, call = call_of_thirty
    windows, _est = beverage_service.crew_windows_for_day(day)
    assert on_site_at(windows, 9 * 60) == call.crew_headcount
    assert on_site_at(windows, 9 * 60) == day.computed_crew_count


# ── The one definition ───────────────────────────────────────────────────

def test_iter_people_sums_to_count_people(app, db, call_of_thirty):
    show, day, call = call_of_thirty
    rows = list(call.crew_rows)
    assert sum(n for _r, n in iter_people(rows)) == count_people(rows)


def test_a_named_person_on_two_rows_is_one_person(app, db):
    """Yielded as 0 the second time rather than skipped, so a caller iterating
    rows still sees every row."""
    from models import (Company, CrewMember, CrewRow, ScheduleActivity,
                        ScheduleDay, Show, ShowCrewAssignment)
    show = Show(name="Dup", code="DUP26")
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 8))
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="CREW START")
    db.session.add(act)
    db.session.flush()
    cm = CrewMember(first_name="Ann", last_name="One", active=True)
    db.session.add(cm)
    db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id, qty=1))
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id, qty=1))
    db.session.commit()

    counts = [n for _r, n in iter_people(act.crew_rows)]
    assert counts == [1, 0]
    assert count_people(act.crew_rows) == 1


def test_a_section_header_is_nobody(app, db):
    from models import CrewRow
    header = CrewRow(is_group_header=True, group_label="LEAD CREW", qty=1)
    assert list(iter_people([header])) == []


def test_beverage_service_holds_no_second_copy_of_the_rule(app):
    """The reason this bug survived a fix: the rule lived in two files and
    nothing pointed them at each other."""
    import inspect
    import re
    src = inspect.getsource(beverage_service.crew_windows_for_day)
    # Comments stripped: the ones in there quote the old rule deliberately, to
    # stop somebody putting it back, and an assertion that reads them is
    # testing the prose rather than the code.
    code = re.sub(r"#.*", "", src)
    assert "iter_people" in code
    assert "row.crew_member_id" not in code, \
        "the headcount rule belongs in models.iter_people, not here"
    assert "row.qty" not in code, \
        "reading qty here means a second copy of the rule has grown back"
