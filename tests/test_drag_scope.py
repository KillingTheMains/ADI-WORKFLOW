"""A section move must not rewrite the show roster (bug found live 2026-08-11).

Sections are per-activity. The roster is show-wide. Letting a header drag
write back reordered the roster from the resulting flat sequence and scrambled
the order on every other crew call in the show.
"""
import datetime as dt


def _fixture(db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        CrewMember, ShowCrewAssignment)
    show = Show(name="Scope Show", code="SCP26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 6))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:00", description="CREW START")
    db.session.add(act); db.session.flush()

    people = []
    for i, (f, l) in enumerate([("Ann", "One"), ("Bob", "Two")]):
        cm = CrewMember(first_name=f, last_name=l)
        db.session.add(cm); db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id,
                                          sort_order=(i + 1) * 10))
        people.append(cm)

    hdr_a = CrewRow(activity_id=act.id, is_group_header=True,
                    group_label="A", sort_order=10)
    row_a = CrewRow(activity_id=act.id, crew_member_id=people[0].id, sort_order=20)
    hdr_b = CrewRow(activity_id=act.id, is_group_header=True,
                    group_label="B", sort_order=30)
    row_b = CrewRow(activity_id=act.id, crew_member_id=people[1].id, sort_order=40)
    db.session.add_all([hdr_a, row_a, hdr_b, row_b]); db.session.flush()
    db.session.commit()
    return show, day, act, people, [hdr_a, row_a, hdr_b, row_b]


def _roster(db, show):
    from models import ShowCrewAssignment
    return [(a.crew_member.full_name, a.sort_order) for a in
            ShowCrewAssignment.query.filter_by(show_id=show.id)
            .order_by(ShowCrewAssignment.sort_order).all()]


def test_moving_a_section_leaves_the_roster_alone(app, client, db):
    show, day, act, people, rows = _fixture(db)
    hdr_a, row_a, hdr_b, row_b = rows
    before = _roster(db, show)

    # Drag section B above section A — the flat person order flips, but this
    # is a SECTION move and must not touch the roster.
    r = client.post("/shows/%d/schedule/%d/activities/%d/crew/reorder"
                    % (show.id, day.id, act.id),
                    json={"ids": [hdr_b.id, row_b.id, hdr_a.id, row_a.id],
                          "moved_header": True})
    assert r.status_code == 200
    assert r.get_json()["roster_written"] is False
    assert _roster(db, show) == before


def test_moving_a_name_still_writes_the_roster(app, client, db):
    show, day, act, people, rows = _fixture(db)
    hdr_a, row_a, hdr_b, row_b = rows

    r = client.post("/shows/%d/schedule/%d/activities/%d/crew/reorder"
                    % (show.id, day.id, act.id),
                    json={"ids": [hdr_a.id, row_b.id, hdr_b.id, row_a.id],
                          "moved_header": False})
    assert r.status_code == 200
    assert r.get_json()["roster_written"] is True
    assert [n for n, _ in _roster(db, show)] == ["Bob Two", "Ann One"]


def test_section_move_still_persists_the_row_order(app, client, db):
    """The rows do move — only the roster write is suppressed."""
    from models import CrewRow
    show, day, act, people, rows = _fixture(db)
    hdr_a, row_a, hdr_b, row_b = rows
    client.post("/shows/%d/schedule/%d/activities/%d/crew/reorder"
                % (show.id, day.id, act.id),
                json={"ids": [hdr_b.id, row_b.id, hdr_a.id, row_a.id],
                      "moved_header": True})
    got = sorted(CrewRow.query.filter_by(activity_id=act.id).all(),
                 key=lambda r: r.sort_order)
    assert [r.id for r in got] == [hdr_b.id, row_b.id, hdr_a.id, row_a.id]


def test_reset_clears_manual_roster_positions(app, client, db):
    show, day, act, people, rows = _fixture(db)
    client.post("/shows/%d/crew/reset-order" % show.id)
    assert all(so is None for _, so in _roster(db, show))
