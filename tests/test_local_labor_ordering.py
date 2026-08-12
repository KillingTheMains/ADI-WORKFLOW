"""
The local labour section of a crew call follows the Local Labor Database.

Jason, 2026-08-12. One ordering function serves both, so the catalogue and the
crew call cannot disagree about where Rigging sits or whether the head reads
above the hands — the same reason `crew_ordering` exists for named crew.

House order: department per `DEPARTMENT_ORDER`, then lead → specialty → hand,
then alphabetical.
"""
import datetime as dt

from local_labor import (DEPARTMENT_ORDER, group_by_department,
                         group_rows_by_department, type_key)


class _P:
    def __init__(self, title, department=None, type=None):
        self.title, self.department, self.type = title, department, type


class _R:
    _n = 0

    def __init__(self, position=None, position_ref=None, qty=1):
        _R._n += 1
        self.id = _R._n
        self.position, self.position_ref, self.qty = position, position_ref, qty
        self.is_group_header = False


def test_a_lead_reads_above_a_shadow_above_a_hand():
    assert type_key("lead") < type_key("specialty") < type_key("hand")


def test_an_unknown_type_sorts_last_rather_than_first():
    """A position nobody typed a type for must not jump the crew chief."""
    assert type_key(None) > type_key("hand")
    assert type_key("") > type_key("hand")


def test_rows_group_into_house_department_order():
    rows = [_R(position_ref=_P("Rigger", "Rigging", "hand")),
            _R(position_ref=_P("Stagehand", "General", "hand")),
            _R(position_ref=_P("LED Hand", "LED", "hand"))]
    assert [d for d, _ in group_rows_by_department(rows)] == \
        ["General", "Rigging", "LED"]


def test_rows_and_the_catalogue_agree_on_department_order():
    """The point of the change, as one assertion."""
    positions = [_P("Rigger", "Rigging", "hand"),
                 _P("Stagehand", "General", "hand"),
                 _P("Audio Hand", "Audio", "hand")]
    rows = [_R(position_ref=p) for p in positions]
    assert [d for d, _ in group_by_department(positions)] == \
           [d for d, _ in group_rows_by_department(rows)]


def test_within_a_department_the_head_reads_first():
    head = _P("Scenic Head", "Scenic", "lead")
    shadow = _P("Scenic Shadow", "Scenic", "specialty")
    hand = _P("Scenic Hand", "Scenic", "hand")
    rows = [_R(position_ref=hand), _R(position_ref=shadow), _R(position_ref=head)]
    _, ordered = group_rows_by_department(rows)[0]
    assert [r.position_ref.title for r in ordered] == \
        ["Scenic Head", "Scenic Shadow", "Scenic Hand"]


def test_two_hands_in_one_department_go_alphabetical():
    a = _P("Zebra Hand", "Lighting", "hand")
    b = _P("Alpha Hand", "Lighting", "hand")
    rows = [_R(position_ref=a), _R(position_ref=b)]
    _, ordered = group_rows_by_department(rows)[0]
    assert [r.position_ref.title for r in ordered] == ["Alpha Hand", "Zebra Hand"]


def test_a_row_with_no_catalogue_position_still_shows(app=None):
    """The production row with six people and no position at all. Hiding it
    would hide six people who have to be fed.
    """
    rows = [_R(position="", position_ref=None, qty=6),
            _R(position_ref=_P("Rigger", "Rigging", "hand"))]
    groups = group_rows_by_department(rows)
    assert [d for d, _ in groups] == ["Rigging", "Unassigned"]
    assert groups[-1][1][0].qty == 6


def test_an_unknown_department_sorts_last_but_is_not_dropped():
    rows = [_R(position_ref=_P("Zebra Wrangler", "Menagerie", "hand")),
            _R(position_ref=_P("Rigger", "Rigging", "hand"))]
    assert [d for d, _ in group_rows_by_department(rows)] == \
        ["Rigging", "Menagerie"]


def test_every_seeded_department_is_in_the_house_order():
    """A department the order does not know sorts last, which is survivable
    but reads as a bug. The seed list should never trip it.
    """
    from local_labor import SEED_POSITIONS
    for _, dept, _ in SEED_POSITIONS:
        assert dept in DEPARTMENT_ORDER, dept


# ── On a real crew call ──────────────────────────────────────────────────────

def _call(db):
    from models import Company, ScheduleActivity, ScheduleDay, Show
    show = Show(name="Order Show", code="ORD26")
    co = Company(name="Sparks")
    db.session.add_all([show, co])
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 30),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="CREW START", sort_order=10)
    db.session.add(act)
    db.session.commit()
    return show, day, act, co


def _ll_row(db, act, title, dept, typ, qty=1, order=10):
    from models import CrewRow, Position
    p = Position.query.filter_by(title=title).first()
    if p is None:
        p = Position(title=title, department=dept, type=typ,
                     is_local_labor=True)
        db.session.add(p)
        db.session.flush()
    p.is_local_labor = True
    r = CrewRow(activity_id=act.id, qty=qty, position=title, position_id=p.id,
                crew_type="Local Crew", sort_order=order)
    db.session.add(r)
    db.session.commit()
    return r


def test_the_call_groups_local_labour_by_department(app, db):
    show, day, act, co = _call(db)
    _ll_row(db, act, "LED Hand", "LED", "hand", qty=3, order=10)
    _ll_row(db, act, "Rigger High", "Rigging", "hand", qty=4, order=20)
    _ll_row(db, act, "Crew Chief", "General", "lead", qty=1, order=30)
    db.session.expire_all()
    assert [d for d, _ in act.local_labor_groups] == \
        ["General", "Rigging", "LED"]


def test_the_call_puts_the_head_above_the_hands(app, db):
    show, day, act, co = _call(db)
    _ll_row(db, act, "Scenic Hand", "Scenic", "hand", qty=11, order=10)
    _ll_row(db, act, "Scenic Head", "Scenic", "lead", qty=1, order=20)
    db.session.expire_all()
    _, rows = act.local_labor_groups[0]
    assert [r.position for r in rows] == ["Scenic Head", "Scenic Hand"]


def test_the_department_totals_are_people_not_lines(app, db):
    show, day, act, co = _call(db)
    _ll_row(db, act, "Lighting Hand", "Lighting", "hand", qty=7, order=10)
    _ll_row(db, act, "Dimmer Hand", "Lighting", "hand", qty=3, order=20)
    db.session.expire_all()
    dept, rows = act.local_labor_groups[0]
    assert dept == "Lighting"
    assert sum(r.people for r in rows) == 10


def test_the_grouping_holds_every_row_exactly_once(app, db):
    """A grouping that drops or duplicates a row would silently change the
    headcount printed above it.
    """
    show, day, act, co = _call(db)
    _ll_row(db, act, "Lighting Hand", "Lighting", "hand", qty=7, order=10)
    _ll_row(db, act, "Rigger High", "Rigging", "hand", qty=4, order=20)
    _ll_row(db, act, "Crew Chief", "General", "lead", qty=1, order=30)
    db.session.expire_all()
    flat = [r.id for _, rows in act.local_labor_groups for r in rows]
    assert sorted(flat) == sorted(r.id for r in act.local_labor_rows)
    assert len(flat) == len(set(flat))
    assert sum(r.people for _, rows in act.local_labor_groups
               for r in rows) == act.crew_headcount


def test_named_crew_stay_out_of_the_local_section(app, db):
    from models import CrewMember, CrewRow
    show, day, act, co = _call(db)
    person = CrewMember(first_name="Dana", last_name="Reyes", active=True)
    db.session.add(person)
    db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, qty=1, position="A1",
                           crew_member_id=person.id, crew_type="Lead Crew",
                           sort_order=5))
    _ll_row(db, act, "Lighting Hand", "Lighting", "hand", qty=7, order=10)
    db.session.commit()
    db.session.expire_all()
    assert [r.position for r in act.local_labor_rows] == ["Lighting Hand"]


def test_the_day_page_draws_the_department_headings(app, client, db):
    show, day, act, co = _call(db)
    _ll_row(db, act, "Rigger High", "Rigging", "hand", qty=4, order=10)
    _ll_row(db, act, "Crew Chief", "General", "lead", qty=1, order=20)
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    body = html[html.index("Local Labour"):]
    assert body.index("General") < body.index("Rigging")
    assert "4 people" in body
