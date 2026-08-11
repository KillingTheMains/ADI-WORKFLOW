"""Dragging a name in a crew call reorders the SHOW ROSTER (note 1, decision A).

One order for the show, not one per call. The subtlety is that a crew call
holds only a subset of the roster, so a drag must not flatten everyone else.
"""
import datetime as dt


def _fixture(db):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        CrewMember, ShowCrewAssignment)
    show = Show(name="Drag Show", code="DRG26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 3))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:00", description="CREW START")
    db.session.add(act); db.session.flush()

    people, rows = [], []
    for i, (f, l) in enumerate([("Ann", "One"), ("Bob", "Two"),
                                ("Cid", "Three"), ("Dot", "Four")]):
        cm = CrewMember(first_name=f, last_name=l)
        db.session.add(cm); db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id,
                                          sort_order=(i + 1) * 10))
        people.append(cm)
    # Only three of the four are on this call.
    for i, cm in enumerate(people[:3]):
        r = CrewRow(activity_id=act.id, crew_member_id=cm.id,
                    sort_order=(i + 1) * 10)
        db.session.add(r); db.session.flush()
        rows.append(r)
    db.session.commit()
    return show, day, act, people, rows


def _roster_names(db, show):
    from models import ShowCrewAssignment
    a = (ShowCrewAssignment.query.filter_by(show_id=show.id)
         .order_by(ShowCrewAssignment.sort_order).all())
    return [x.crew_member.full_name for x in a]


def test_drag_rewrites_the_roster_order(app, client, db):
    show, day, act, people, rows = _fixture(db)
    assert _roster_names(db, show)[:3] == ["Ann One", "Bob Two", "Cid Three"]

    # Drag Cid to the top of the call.
    new_ids = [rows[2].id, rows[0].id, rows[1].id]
    r = client.post(
        "/shows/%d/schedule/%d/activities/%d/crew/reorder"
        % (show.id, day.id, act.id), json={"ids": new_ids})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    assert _roster_names(db, show)[:3] == ["Cid Three", "Ann One", "Bob Two"]


def test_people_not_on_the_call_keep_their_place(app, client, db):
    """Dot is last in the roster and absent from the call — she stays last."""
    show, day, act, people, rows = _fixture(db)
    new_ids = [rows[2].id, rows[0].id, rows[1].id]
    client.post("/shows/%d/schedule/%d/activities/%d/crew/reorder"
                % (show.id, day.id, act.id), json={"ids": new_ids})
    assert _roster_names(db, show)[-1] == "Dot Four"


def test_other_crew_calls_follow_immediately(app, client, db):
    """The whole point: reorder once, every call in the show agrees."""
    from models import ScheduleActivity, CrewRow
    show, day, act, people, rows = _fixture(db)
    other = ScheduleActivity(day_id=day.id, time="12:00", description="CREW START")
    db.session.add(other); db.session.flush()
    for i, cm in enumerate(people[:3]):
        db.session.add(CrewRow(activity_id=other.id, crew_member_id=cm.id,
                               sort_order=(i + 1) * 10))
    db.session.commit()

    client.post("/shows/%d/schedule/%d/activities/%d/crew/reorder"
                % (show.id, day.id, act.id),
                json={"ids": [rows[2].id, rows[0].id, rows[1].id]})
    db.session.expire_all()

    again = ScheduleActivity.query.get(other.id)
    assert [r.display_name for r in again.ordered_crew_rows] == \
        ["Cid Three", "Ann One", "Bob Two"]


def test_mismatched_row_list_is_rejected(app, client, db):
    show, day, act, people, rows = _fixture(db)
    r = client.post("/shows/%d/schedule/%d/activities/%d/crew/reorder"
                    % (show.id, day.id, act.id),
                    json={"ids": [rows[0].id]})
    assert r.status_code == 400
