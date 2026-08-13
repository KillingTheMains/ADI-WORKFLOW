"""The show book gets a Local Labor section.

`show_book.html` rendered `act.ordered_crew_rows` in ONE table with a Name
column, so a local-labour line — "14 × Rigger", a count of a position that has
no name and never will — sat interleaved among the named crew with that column
blank. Blank in the Name column already means something else in this document:
an unfilled slot, a called position with nobody in it yet, which Larry
deliberately scans for. So the show book was quietly reporting fourteen riggers
as an open slot for one person.

The headcount was never affected — the quantities print, so nobody was
under-fed. This is a legibility defect in a CLIENT-FACING document, which is
where it matters most.

The day page has done this correctly since 2026-08-12: local labour is its own
block, no Name column, grouped by department in Local Labor Database order,
headcount stated in the header. This is the same treatment, for paper.
"""
import datetime as dt


def _show(db):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Book Show", code="BK26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 21),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="CREW START", sort_order=10)
    db.session.add(act)
    db.session.commit()
    return show, day, act


def _person(db, show, act, first="Ann", last="One"):
    from models import CrewMember, CrewRow, ShowCrewAssignment
    cm = CrewMember(first_name=first, last_name=last, active=True)
    db.session.add(cm)
    db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id))
    db.session.commit()


def _local(db, act, title="Rigger", dept="Rigging", qty=14, task=None):
    from models import CrewRow, Position
    pos = Position.query.filter_by(title=title).first()
    if pos is None:
        pos = Position(title=title, department=dept, type="hand",
                       is_local_labor=True)
        db.session.add(pos)
        db.session.flush()
    pos.is_local_labor = True
    db.session.add(CrewRow(activity_id=act.id, position_id=pos.id,
                           position=title, qty=qty, task=task))
    db.session.commit()


def _book(client, show):
    r = client.get("/shows/%d/oss/show-book" % show.id)
    assert r.status_code == 200, r.status_code
    return r.get_data(as_text=True)


def test_local_labour_gets_its_own_block(app, client, db):
    show, day, act = _show(db)
    _person(db, show, act)
    _local(db, act, "Rigger", "Rigging", 14, task="Pin / Bolt Truss")
    body = _book(client, show)
    assert "Local Labour" in body
    assert 'class="ll-block"' in body


def test_the_block_states_the_headcount(app, client, db):
    """The number the block exists to get right. A reader should not have to
    add a column to find out how many bodies are coming."""
    show, day, act = _show(db)
    _local(db, act, "Lighting Hand", "Lighting", 7)
    _local(db, act, "Rigger", "Rigging", 14)
    body = _book(client, show)
    assert "21 people" in body


def test_a_local_line_is_not_listed_among_the_named_crew(app, client, db):
    """The actual defect: it used to be a row in the Name-column table."""
    show, day, act = _show(db)
    _person(db, show, act)
    _local(db, act, "Rigger", "Rigging", 14)
    body = _book(client, show)
    named_table = body[:body.index('class="ll-block"')]
    assert "Ann One" in named_table
    assert "Rigger" not in named_table


def test_the_block_has_no_name_column(app, client, db):
    """A count of a position has no name, and a blank Name cell in this
    document already means "unfilled slot" — a different, more alarming
    thing."""
    show, day, act = _show(db)
    _local(db, act, "Rigger", "Rigging", 14)
    body = _book(client, show)
    block = body[body.index('class="ll-block"'):]
    block = block[:block.index("</table>")]
    assert ">Name<" not in block
    assert ">Task<" in block
    assert ">How many<" in block


def test_it_groups_by_department(app, client, db):
    show, day, act = _show(db)
    _local(db, act, "Rigger", "Rigging", 14)
    _local(db, act, "Lighting Hand", "Lighting", 7)
    block = _book(client, show)
    block = block[block.index('class="ll-block"'):]
    assert "Rigging" in block
    assert "Lighting" in block


def test_a_call_of_only_local_labour_renders_no_empty_named_table(app, client, db):
    """Four riggers and no named lead. An empty five-column table with a Name
    header and nothing under it reads as a mistake."""
    show, day, act = _show(db)
    _local(db, act, "Rigger", "Rigging", 4)
    body = _book(client, show)
    assert 'class="ll-block"' in body
    assert ">Name<" not in body


def test_a_call_of_only_named_crew_renders_no_local_block(app, client, db):
    show, day, act = _show(db)
    _person(db, show, act)
    body = _book(client, show)
    assert "Ann One" in body
    assert 'class="ll-block"' not in body


def test_the_hatch_is_present(app, client, db):
    """Not decoration. It says "multiples of a POSITION, not people", and it
    is the channel that survives a mono laser at arm's length."""
    show, day, act = _show(db)
    _local(db, act, "Rigger", "Rigging", 14)
    assert "repeating-linear-gradient(45deg" in _book(client, show)


def test_the_hours_are_labelled_as_each(app, client, db):
    """14 riggers at 10 hours is 140 hours, and the column says 10. The show
    book is read by people who bill from it."""
    show, day, act = _show(db)
    _local(db, act, "Rigger", "Rigging", 14)
    body = _book(client, show)
    assert "Hours are <em>each</em>" in body
