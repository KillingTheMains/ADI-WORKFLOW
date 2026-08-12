"""
Deleting section headers with no crew under them.

A header owns everything between it and the next header at or above its own
level. Production carries 136 headers, all level 1, and 29 of them have
nothing underneath.

The subtle one: the day page's main crew table hides local-labour rows now, so
a header whose crew are all local labour LOOKS empty there. It is not, and
deleting it would throw away a real section (ENCORE RIGGING, ENCORE CARPS).
There is a test for exactly that below.
"""
import datetime as dt


def _act(db, code="HDR26"):
    from models import Company, ScheduleActivity, ScheduleDay, Show
    show = Show(name="Header Show", code=code)
    co = Company(name="Sparks")
    db.session.add_all([show, co])
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 29),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.flush()
    a = ScheduleActivity(day_id=day.id, time="08:00",
                         description="CREW START", sort_order=10)
    db.session.add(a)
    db.session.commit()
    return a, co


def _header(db, act, label, level=1, order=0):
    from models import CrewRow
    r = CrewRow(activity_id=act.id, is_group_header=True, group_label=label,
                header_level=level, sort_order=order, qty=0)
    db.session.add(r)
    db.session.commit()
    return r


def _crew(db, act, order=0, local=False, co=None, qty=1):
    from models import CrewMember, CrewRow
    cm = None
    if local:
        cm = CrewMember(first_name="First", last_name="Last", active=True,
                        company_id=co.id if co else None)
        db.session.add(cm)
        db.session.flush()
    else:
        cm = CrewMember(first_name="Dana", last_name="Reyes", active=True)
        db.session.add(cm)
        db.session.flush()
    r = CrewRow(activity_id=act.id, sort_order=order, qty=qty,
                position="Lighting Hand" if local else "A1",
                crew_member_id=cm.id,
                crew_type="Local Crew" if local else "Lead Crew")
    db.session.add(r)
    db.session.commit()
    return r


def _empties(act):
    from migrations import _empty_section_headers
    return [h.group_label for h in _empty_section_headers(act)]


def test_a_header_with_nobody_under_it_is_empty(app, db):
    act, co = _act(db)
    _header(db, act, "ENCORE AUDIO", order=10)
    assert _empties(act) == ["ENCORE AUDIO"]


def test_a_header_with_crew_under_it_is_kept(app, db):
    act, co = _act(db)
    _header(db, act, "LUMENARCHY", order=10)
    _crew(db, act, order=20)
    assert _empties(act) == []


def test_the_last_header_on_a_call_counts_as_empty(app, db):
    """Production has these — a trailing ENCORE CARPS with nothing after it."""
    act, co = _act(db)
    _header(db, act, "LUMENARCHY", order=10)
    _crew(db, act, order=20)
    _header(db, act, "ENCORE CARPS", order=30)
    assert _empties(act) == ["ENCORE CARPS"]


def test_only_the_empty_one_goes(app, db):
    act, co = _act(db)
    _header(db, act, "FULL", order=10)
    _crew(db, act, order=20)
    _header(db, act, "EMPTY", order=30)
    _header(db, act, "ALSO FULL", order=40)
    _crew(db, act, order=50)
    assert _empties(act) == ["EMPTY"]


def test_local_labour_counts_as_crew(app, db):
    """⚠ THE ONE THAT MATTERS. The day page's main table hides local-labour
    rows, so ENCORE RIGGING looks empty there while holding four riggers.
    Judging emptiness from that view would delete real sections.
    """
    act, co = _act(db)
    _header(db, act, "ENCORE RIGGING", order=10)
    row = _crew(db, act, order=20, local=True, co=co, qty=4)
    assert row.is_local_labor is True
    assert _empties(act) == []


def test_a_parent_holding_a_populated_sub_header_is_kept(app, db):
    act, co = _act(db)
    _header(db, act, "ENCORE", level=1, order=10)
    _header(db, act, "ENCORE RIGGING", level=2, order=20)
    _crew(db, act, order=30)
    assert _empties(act) == []


def test_a_parent_whose_sub_headers_are_all_empty_goes_too(app, db):
    """Both in one pass — emptiness is computed before anything is removed."""
    act, co = _act(db)
    _header(db, act, "ENCORE", level=1, order=10)
    _header(db, act, "ENCORE RIGGING", level=2, order=20)
    assert sorted(_empties(act)) == ["ENCORE", "ENCORE RIGGING"]


def test_a_sub_header_with_crew_keeps_itself_and_its_parent(app, db):
    act, co = _act(db)
    _header(db, act, "ENCORE", level=1, order=10)
    _header(db, act, "ENCORE RIGGING", level=2, order=20)
    _crew(db, act, order=30)
    _header(db, act, "ENCORE AUDIO", level=2, order=40)
    assert _empties(act) == ["ENCORE AUDIO"]


def test_a_call_with_no_headers_at_all_is_fine(app, db):
    act, co = _act(db)
    _crew(db, act, order=10)
    assert _empties(act) == []


def test_the_migration_removes_them_and_leaves_the_crew(app, db):
    from migrations import _delete_empty_section_headers
    from models import CrewRow
    act, co = _act(db)
    _header(db, act, "FULL", order=10)
    _crew(db, act, order=20)
    _header(db, act, "EMPTY", order=30)

    _delete_empty_section_headers(db.session)
    db.session.commit()

    labels = [r.group_label for r in CrewRow.query.filter_by(
        is_group_header=True).all()]
    assert labels == ["FULL"]
    assert CrewRow.query.filter_by(is_group_header=False).count() == 1


def test_running_it_twice_removes_nothing_extra(app, db):
    """It should be a no-op afterwards. A sweep that keeps finding work is a
    sweep hiding a live bug.
    """
    from migrations import _delete_empty_section_headers
    from models import CrewRow
    act, co = _act(db)
    _header(db, act, "FULL", order=10)
    _crew(db, act, order=20)
    _header(db, act, "EMPTY", order=30)

    _delete_empty_section_headers(db.session)
    db.session.commit()
    after = CrewRow.query.count()
    _delete_empty_section_headers(db.session)
    db.session.commit()
    assert CrewRow.query.count() == after


def test_headers_on_another_call_are_judged_separately(app, db):
    """A header is empty relative to ITS activity, not the day."""
    from migrations import _delete_empty_section_headers
    from models import CrewRow, ScheduleActivity
    act, co = _act(db)
    other = ScheduleActivity(day_id=act.day_id, time="14:00",
                             description="CREW START", sort_order=20)
    db.session.add(other)
    db.session.commit()
    _header(db, act, "KEEP ME", order=10)
    _crew(db, act, order=20)
    _header(db, other, "KEEP ME", order=10)

    _delete_empty_section_headers(db.session)
    db.session.commit()
    assert CrewRow.query.filter_by(is_group_header=True).count() == 1
    assert CrewRow.query.filter_by(
        is_group_header=True).one().activity_id == act.id
