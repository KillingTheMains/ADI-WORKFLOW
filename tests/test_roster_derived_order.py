"""Crew calls derive their order from the show roster (note 2, 2026-08-11).

The Crew Database seeds the roster; the roster then governs every crew call in
that show, live. "Live" means DERIVED at render — no sync step, nothing stored
per call that can drift.
"""
import datetime as dt

from crew_ordering import order_crew_rows, roster_index


def _show_with_day(db, code="ORD26"):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Order Show", code=code)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 1))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:00",
                           description="CREW START")
    db.session.add(act); db.session.flush()
    return show, day, act


def _person(db, first, last, company_id=None, sort_order=None):
    from models import CrewMember
    cm = CrewMember(first_name=first, last_name=last,
                    company_id=company_id, sort_order=sort_order)
    db.session.add(cm); db.session.flush()
    return cm


def _assign(db, show, cm, sort_order=None):
    from models import ShowCrewAssignment
    a = ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id,
                           sort_order=sort_order)
    db.session.add(a); db.session.flush()
    return a


def _row(db, act, cm, sort_order):
    from models import CrewRow
    r = CrewRow(activity_id=act.id, crew_member_id=cm.id if cm else None,
                sort_order=sort_order)
    db.session.add(r); db.session.flush()
    return r


def test_crew_call_follows_roster_not_insertion_order(app, db):
    show, day, act = _show_with_day(db)
    a = _person(db, "Anna", "Alpha")
    b = _person(db, "Ben", "Bravo")
    c = _person(db, "Cal", "Charlie")
    # Roster order: C, A, B
    _assign(db, show, c, sort_order=10)
    _assign(db, show, a, sort_order=20)
    _assign(db, show, b, sort_order=30)
    # Rows added in a different order entirely.
    _row(db, act, a, 10); _row(db, act, b, 20); _row(db, act, c, 30)
    db.session.commit()

    names = [r.display_name for r in act.ordered_crew_rows]
    assert names == ["Cal Charlie", "Anna Alpha", "Ben Bravo"]


def test_reordering_the_roster_updates_the_crew_call_live(app, db):
    """No sync step: the crew rows are untouched, the order still changes."""
    show, day, act = _show_with_day(db, code="ORD27")
    a = _person(db, "Anna", "Alpha")
    b = _person(db, "Ben", "Bravo")
    asg_a = _assign(db, show, a, sort_order=10)
    asg_b = _assign(db, show, b, sort_order=20)
    _row(db, act, a, 10); _row(db, act, b, 20)
    db.session.commit()
    assert [r.display_name for r in act.ordered_crew_rows] == \
        ["Anna Alpha", "Ben Bravo"]

    stored = [(r.id, r.sort_order) for r in act.crew_rows]

    asg_a.sort_order, asg_b.sort_order = 20, 10
    db.session.commit()
    db.session.expire_all()

    assert [r.display_name for r in act.ordered_crew_rows] == \
        ["Ben Bravo", "Anna Alpha"]
    # The crew rows themselves were never rewritten.
    from models import ScheduleActivity
    again = ScheduleActivity.query.get(act.id)
    assert [(r.id, r.sort_order) for r in again.crew_rows] == stored


def test_section_headers_stay_put_and_sorting_is_within_sections(app, db):
    from models import CrewRow
    show, day, act = _show_with_day(db, code="ORD28")
    a = _person(db, "Anna", "Alpha")
    b = _person(db, "Ben", "Bravo")
    c = _person(db, "Cal", "Charlie")
    d = _person(db, "Dee", "Delta")
    # Roster order puts everyone in reverse.
    for i, p in enumerate([d, c, b, a]):
        _assign(db, show, p, sort_order=(i + 1) * 10)

    db.session.add(CrewRow(activity_id=act.id, is_group_header=True,
                           group_label="ENCORE", sort_order=10))
    _row(db, act, a, 20); _row(db, act, b, 30)
    db.session.add(CrewRow(activity_id=act.id, is_group_header=True,
                           group_label="VRA", sort_order=40))
    _row(db, act, c, 50); _row(db, act, d, 60)
    db.session.commit()

    rendered = [(r.group_label if r.is_group_header else r.display_name)
                for r in act.ordered_crew_rows]
    # Headers hold position; members reorder only inside their own section.
    assert rendered == ["ENCORE", "Ben Bravo", "Anna Alpha",
                        "VRA", "Dee Delta", "Cal Charlie"]


def test_unlinked_rows_hold_their_place_at_the_end_of_a_section(app, db):
    show, day, act = _show_with_day(db, code="ORD29")
    a = _person(db, "Anna", "Alpha")
    _assign(db, show, a, sort_order=10)
    _row(db, act, None, 10)   # free-text row, no roster position
    _row(db, act, a, 20)
    db.session.commit()

    rows = act.ordered_crew_rows
    assert rows[0].crew_member_id == a.id
    assert rows[1].crew_member_id is None


def test_roster_falls_back_to_crew_database_order(app, db):
    """Nobody has dragged the roster yet, so the Crew Database order wins."""
    from models import Company
    show, day, act = _show_with_day(db, code="ORD30")
    co_a = Company(name="Aardvark AV"); co_b = Company(name="Zulu Rigging")
    db.session.add_all([co_a, co_b]); db.session.flush()
    # Company first, then sort_order within it.
    late = _person(db, "Zed", "Zulu", company_id=co_b.id, sort_order=10)
    early = _person(db, "Mia", "Mid", company_id=co_a.id, sort_order=20)
    _assign(db, show, late, sort_order=None)
    _assign(db, show, early, sort_order=None)
    db.session.commit()

    index = roster_index(show.id)
    assert index[early.id] < index[late.id]


def test_order_crew_rows_is_pure_and_needs_no_app_context():
    """The sorting helper is plain data in, plain data out."""
    class R:
        def __init__(self, id, cm, hdr=False, label=None, so=0):
            self.id, self.crew_member_id = id, cm
            self.is_group_header, self.group_label = hdr, label
            self.sort_order = so

    rows = [R(1, None, hdr=True, label="A"), R(2, 99), R(3, 7)]
    out = order_crew_rows(rows, {7: 0, 99: 1})
    assert [r.id for r in out] == [1, 3, 2]
