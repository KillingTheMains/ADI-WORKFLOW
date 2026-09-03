"""Note 4 — several local labor lines in one submit.

Larry: "there is currently the option to add one line at a time, and then the
page refreshes and then you start over ... maybe just a plus sign to the right
where you could add a line for lighting hands, a line for audio hands, a line
for video hands, and then click add crew to the crew call button."

One refresh at the end is what he asked for, and is fine — unlike note 1's
delete, where he wanted none at all.

"Still have it sort into the correct place" needs no placement code: local
labor renders through `local_labor_groups` → `group_rows_by_department`, so the
grouping is DERIVED from the catalogue's own department order at render time.
The test below proves that rather than assuming it — three lines submitted in
the wrong department order come back grouped correctly.
"""
import datetime as dt

from extensions import db as _db
from models import CrewRow, Position, ScheduleActivity, ScheduleDay, Show


def _fixture(db):
    show = Show(name="Batch Show", code="BS1")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 1), phase="Load In")
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00", description="CREW CALL")
    db.session.add(act); db.session.flush()
    pos = {}
    for title, dept in (("Lighting Hand", "Lighting"),
                        ("Audio Hand", "Audio"),
                        ("Rigger High", "Rigging")):
        p = Position(title=title, department=dept, is_local_labor=True)
        db.session.add(p); db.session.flush()
        pos[title] = p
    db.session.commit()
    return show, day, act, pos


def _url(show, day, act):
    return (f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}"
            f"/crew/add-local-labor")


def test_three_lines_in_one_submit(client, db):
    show, day, act, pos = _fixture(db)
    client.post(_url(show, day, act), data={
        "position_id[]": [str(pos["Lighting Hand"].id),
                          str(pos["Audio Hand"].id),
                          str(pos["Rigger High"].id)],
        "position[]":    ["Lighting Hand", "Audio Hand", "Rigger High"],
        "qty[]":         ["6", "4", "2"],
    }, follow_redirects=True)
    rows = CrewRow.query.filter_by(activity_id=act.id).all()
    assert len(rows) == 3
    assert sorted(r.qty for r in rows) == [2, 4, 6]


def test_each_line_keeps_its_own_quantity_and_position(client, db):
    """The arrays are zipped by index — an off-by-one here would silently give
    the riggers the lighting count."""
    show, day, act, pos = _fixture(db)
    client.post(_url(show, day, act), data={
        "position_id[]": [str(pos["Lighting Hand"].id), str(pos["Rigger High"].id)],
        "position[]":    ["Lighting Hand", "Rigger High"],
        "qty[]":         ["6", "2"],
        "task[]":        ["Hang / Circuit", ""],
        "hours[]":       ["10", ""],
    }, follow_redirects=True)
    by_pos = {r.position: r for r in CrewRow.query.filter_by(activity_id=act.id)}
    assert by_pos["Lighting Hand"].qty == 6
    assert by_pos["Rigger High"].qty == 2
    assert by_pos["Lighting Hand"].task == "Hang / Circuit"
    assert by_pos["Lighting Hand"].hours == 10
    assert by_pos["Rigger High"].task is None


def test_a_blank_line_is_skipped_not_fatal(client, db):
    """The last row of a stack is often left empty. Failing the whole submit
    over it would lose the good lines above."""
    show, day, act, pos = _fixture(db)
    client.post(_url(show, day, act), data={
        "position_id[]": [str(pos["Lighting Hand"].id), ""],
        "position[]":    ["Lighting Hand", ""],
        "qty[]":         ["6", "1"],
    }, follow_redirects=True)
    assert CrewRow.query.filter_by(activity_id=act.id).count() == 1


def test_submitting_nothing_says_so(client, db):
    show, day, act, pos = _fixture(db)
    body = client.post(_url(show, day, act), data={
        "position_id[]": [""], "position[]": [""], "qty[]": ["1"],
    }, follow_redirects=True).data
    assert b"pick a position" in body
    assert CrewRow.query.filter_by(activity_id=act.id).count() == 0


def test_they_land_grouped_by_department_however_they_were_entered(client, db):
    """"Sort into the correct place." Submitted Audio → Rigging → Lighting; the
    catalogue order is Rigging, Lighting, Audio, and the render follows the
    catalogue, not the typing."""
    show, day, act, pos = _fixture(db)
    client.post(_url(show, day, act), data={
        "position_id[]": [str(pos["Audio Hand"].id),
                          str(pos["Rigger High"].id),
                          str(pos["Lighting Hand"].id)],
        "position[]":    ["Audio Hand", "Rigger High", "Lighting Hand"],
        "qty[]":         ["4", "2", "6"],
    }, follow_redirects=True)
    act = _db.session.get(ScheduleActivity, act.id)
    depts = [dept for dept, _rows in act.local_labor_groups]
    assert depts == ["Rigging", "Lighting", "Audio"]


def test_the_rows_are_local_labor(client, db):
    """crew_type drives is_local_labor, which drives every headcount that feeds
    catering."""
    show, day, act, pos = _fixture(db)
    client.post(_url(show, day, act), data={
        "position_id[]": [str(pos["Lighting Hand"].id)],
        "position[]": ["Lighting Hand"], "qty[]": ["6"],
    }, follow_redirects=True)
    row = CrewRow.query.filter_by(activity_id=act.id).first()
    assert row.crew_type == "Local Crew"
    assert row.is_local_labor


def test_the_form_posts_arrays(client, db):
    """A single-value form silently drops every line but the last."""
    html = open("templates/schedule/day.html").read()
    assert 'name="position_id[]"' in html
    assert 'name="qty[]"' in html
    assert "add_local_labor_rows" in html
