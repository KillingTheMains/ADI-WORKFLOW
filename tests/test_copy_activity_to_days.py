"""Note 16 — copying an activity to other days, and what has to come with it.

`copy_activity_to_days` predates most of the crew-call work and quietly fell
behind it. It copied ten CrewRow fields; by 2026-09-04 the model had more than
that which matter, so a copy silently dropped:

  * `task` — the field local labor lives on. A copied call arrived with every
    "Catwalk Strike" and "Hang / Circuit Lights" stripped off it.
  * `header_level` and `company_id` — so every copied section header landed
    unbound, `company_header_for` could not match it, and the next person
    added to that day got a SECOND header for a company that already had one.

It also copied `sort_order` verbatim into days that already had rows, and
appended the copy to the end of the target day rather than placing it in time
order.

Jason's calls, 2026-09-04: a target day that already has a call keeps it and
the copy lands alongside it chronologically; times are editable per day; the
crew always comes along.
"""
from datetime import date as _date

from crew_sections import company_header_for
from models import (Company, CrewBreak, CrewMember, CrewRow, Position,
                    ScheduleActivity, ScheduleDay, Show)


def _show_with_days(db, n=3):
    # Unique name/code so a test can build two shows without tripping a
    # uniqueness rule on either.
    seq = Show.query.count() + 1
    show = Show(name=f"Copy Show {seq}", code=f"CS{seq}")
    db.session.add(show); db.session.flush()
    days = []
    for i in range(n):
        d = ScheduleDay(show_id=show.id, date=_date(2026, 10, 1 + i),
                        phase="Load In")
        db.session.add(d); db.session.flush()
        days.append(d)
    db.session.commit()
    return show, days


def _crew_call(db, day, time="08:00", description="CREW START", sort_order=10):
    act = ScheduleActivity(day_id=day.id, time=time, description=description,
                           sort_order=sort_order)
    db.session.add(act); db.session.commit()
    return act


def _rows_of(act_id):
    """DISPLAY order, QUERIED. `act.crew_rows` is a cached relationship with no
    order_by and does not see rows flushed since it loaded — the §3 trap."""
    return (CrewRow.query.filter_by(activity_id=act_id)
            .order_by(CrewRow.sort_order, CrewRow.id).all())


def _post(client, show, day, act, data):
    return client.post(
        f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/copy-to-days",
        data=data, follow_redirects=True)


def test_task_survives_the_copy(client, db):
    """The regression this file exists for. `task` is why the 2025 workbook's
    117 welded slot titles collapse to about ten positions — a copy that drops
    it hands Larry a call full of hands with nothing to do."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0])
    from models import find_normalised
    pos = find_normalised(Position.query.all(), "Rigger", attr="title")
    if pos is None:
        pos = Position(title="Rigger")
        db.session.add(pos)
    pos.department, pos.type = "Rigging", "hand"
    db.session.flush()
    db.session.add(CrewRow(activity_id=src.id, sort_order=10,
                           crew_type="Local Crew", qty=6,
                           position_id=pos.id, position="Rigger",
                           task="Catwalk Strike"))
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    copied = ScheduleActivity.query.filter_by(day_id=days[1].id).one()
    rows = _rows_of(copied.id)
    assert [r.task for r in rows] == ["Catwalk Strike"]
    assert rows[0].qty == 6
    assert rows[0].position_id == pos.id


def test_crew_comes_without_being_asked(client, db):
    """There is no `copy_crew` flag any more — a post that never mentions it
    still brings the people."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0])
    db.session.add(CrewRow(activity_id=src.id, sort_order=10,
                           crew_type="Local Crew", qty=4,
                           position="Lighting Hand"))
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    copied = ScheduleActivity.query.filter_by(day_id=days[1].id).one()
    assert len(_rows_of(copied.id)) == 1


def test_a_copied_header_stays_bound_to_its_company(client, db):
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0])
    co = Company(name="Encore")
    db.session.add(co); db.session.flush()
    db.session.add(CrewRow(activity_id=src.id, sort_order=10,
                           is_group_header=True, group_label="Encore",
                           header_level=1, company_id=co.id))
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    copied = ScheduleActivity.query.filter_by(day_id=days[1].id).one()
    header = _rows_of(copied.id)[0]
    assert header.is_group_header
    assert header.company_id == co.id
    assert header.header_level == 1


def test_a_copied_header_does_not_spawn_a_duplicate(client, db):
    """The note-3 regression, stated as the behaviour Larry sees. An unbound
    copied header cannot be matched, so adding the first person from that
    company made a second header on the copied call."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0])
    co = Company(name="Encore")
    db.session.add(co); db.session.flush()
    db.session.add(CrewRow(activity_id=src.id, sort_order=10,
                           is_group_header=True, group_label="Encore",
                           header_level=1, company_id=co.id))
    cm = CrewMember(first_name="Ann", last_name="Hand", company_id=co.id)
    db.session.add(cm)
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})
    copied = ScheduleActivity.query.filter_by(day_id=days[1].id).one()
    assert company_header_for(_rows_of(copied.id), cm) is not None

    client.post(
        f"/shows/{show.id}/schedule/{days[1].id}/activities/{copied.id}/crew/add",
        data={"crew_member_id": str(cm.id)}, follow_redirects=True)

    headers = [r for r in _rows_of(copied.id) if r.is_group_header]
    assert len(headers) == 1


def test_copied_rows_get_fresh_sort_order(client, db):
    """Source numbering copied verbatim collides with whatever is already on
    the target and drops ordering through to `id`."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0])
    for i, title in enumerate(("Rigger", "Lighting Hand", "Audio Hand")):
        db.session.add(CrewRow(activity_id=src.id, sort_order=(i + 1) * 10,
                               crew_type="Local Crew", qty=2, position=title))
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    copied = ScheduleActivity.query.filter_by(day_id=days[1].id).one()
    orders = [r.sort_order for r in _rows_of(copied.id)]
    assert orders == [10, 20, 30]


def test_a_per_day_time_is_used_and_a_blank_one_falls_back(client, db):
    """A 06:00 load-in call copied onto a show day usually wants a different
    time. A day left blank keeps the source time rather than losing it."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0], time="06:00")

    _post(client, show, days[0], src, {
        "target_day_ids[]": [str(days[1].id), str(days[2].id)],
        f"target_time_{days[1].id}": "14:00",
        f"target_time_{days[2].id}": "",
    })

    assert ScheduleActivity.query.filter_by(day_id=days[1].id).one().time == "14:00"
    assert ScheduleActivity.query.filter_by(day_id=days[2].id).one().time == "06:00"


def test_the_copy_lands_in_time_order_not_at_the_end(client, db):
    """Jason, 2026-09-04: the copy goes in at the right point chronologically."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0], time="08:00", description="RIGGING CREW START")
    db.session.add_all([
        ScheduleActivity(day_id=days[1].id, time="06:00",
                         description="EARLY CALL", sort_order=10),
        ScheduleActivity(day_id=days[1].id, time="12:00",
                         description="LUNCH", sort_order=20),
    ])
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    ordered = (ScheduleActivity.query.filter_by(day_id=days[1].id)
               .order_by(ScheduleActivity.sort_order).all())
    assert [a.description for a in ordered] == [
        "EARLY CALL", "RIGGING CREW START", "LUNCH"]


def test_an_existing_call_on_the_target_day_is_left_alone(client, db):
    """Two 08:00 calls with different people on them is a real thing. The copy
    lands alongside; it does not merge into or disturb what is there."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0], time="08:00", description="RIGGING CREW START")
    existing = _crew_call(db, days[1], time="08:00",
                          description="LIGHTING CREW START")
    db.session.add(CrewRow(activity_id=existing.id, sort_order=10,
                           crew_type="Local Crew", qty=4,
                           position="Lighting Hand"))
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    acts = ScheduleActivity.query.filter_by(day_id=days[1].id).all()
    assert len(acts) == 2
    assert len(_rows_of(existing.id)) == 1


def test_actual_hours_do_not_come_along(client, db):
    """An actual belongs to the shift that was worked, not to a plan for
    another day."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0])
    db.session.add(CrewRow(activity_id=src.id, sort_order=10,
                           crew_type="Local Crew", qty=2,
                           position="Rigger", hours=10.0, actual_hours=12.5))
    db.session.commit()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    copied = ScheduleActivity.query.filter_by(day_id=days[1].id).one()
    row = _rows_of(copied.id)[0]
    assert row.hours == 10.0
    assert row.actual_hours is None


def test_breaks_do_not_come_along(client, db):
    """`crew_breaks.activity_id` is UNIQUE and breaks are created on the crew
    call now. A copy is a new call, and it starts without one."""
    show, days = _show_with_days(db)
    src = _crew_call(db, days[0])
    brk_act = ScheduleActivity(day_id=days[0].id, time="12:00",
                               description="LUNCH BREAK", sort_order=20)
    db.session.add(brk_act); db.session.flush()
    db.session.add(CrewBreak(show_id=show.id, activity_id=brk_act.id,
                             crew_call_id=src.id, duration_minutes=30,
                             label="Lunch"))
    db.session.commit()
    before = CrewBreak.query.count()

    _post(client, show, days[0], src, {"target_day_ids[]": [str(days[1].id)]})

    assert CrewBreak.query.count() == before
    copied = (ScheduleActivity.query
              .filter_by(day_id=days[1].id, description="CREW START").one())
    assert CrewBreak.query.filter_by(activity_id=copied.id).count() == 0


def test_a_day_belonging_to_another_show_is_ignored(client, db):
    """A stale or forged day id must not write into somebody else's show."""
    show, days = _show_with_days(db)
    _other, other_days = _show_with_days(db)
    src = _crew_call(db, days[0])

    _post(client, show, days[0], src,
          {"target_day_ids[]": [str(other_days[1].id)]})

    assert ScheduleActivity.query.filter_by(day_id=other_days[1].id).count() == 0
