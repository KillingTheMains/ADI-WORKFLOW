"""
Putting local labour on a crew call, and the whole site counting the people.

The requirement in Jason's words: "the whole site would recognize that there
were multiple people involved for the purposes of hours calculations and
headcounts for meals". So these tests follow one line of 18 hands out through
the headcount, the meal service and the client master.
"""
import datetime as dt


def _show_day(db):
    from models import ScheduleDay, Show
    show = Show(name="Local Show", code="LOC26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 21),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.commit()
    return show, day


def _position(db, title="Lighting Hand", dept="Lighting", local=True):
    from models import Position
    p = Position(title=title, department=dept, type="hand",
                 is_local_labor=local)
    db.session.add(p)
    db.session.commit()
    return p


def _call(db, day, time="08:00"):
    from models import ScheduleActivity
    a = ScheduleActivity(day_id=day.id, time=time, description="CREW START",
                         sort_order=10)
    db.session.add(a)
    db.session.commit()
    return a


def _master(show):
    """The client master timeline, as the export builds it."""
    from models import MealService, SubScheduleEntry
    from oss_export import build_master_items
    entries = SubScheduleEntry.query.filter_by(show_id=show.id).all()
    services = MealService.query.filter_by(show_id=show.id).all()
    items, _ = build_master_items(show, entries, services)
    return items


def _add(client, show, day, act, **data):
    return client.post(
        f"/shows/{show.id}/schedule/{day.id}/activities/{act.id}/crew/add",
        data=data)


def test_a_line_of_eighteen_is_eighteen_people(app, client, db):
    """The core requirement, stated as one assertion."""
    show, day = _show_day(db)
    pos = _position(db)
    act = _call(db, day)
    _add(client, show, day, act, qty=18, position_id=pos.id,
         position="Lighting Hand", crew_type="Local Crew",
         task="Hang / Circuit Lights")
    db.session.expire_all()
    assert act.crew_headcount == 18


def test_it_reaches_the_meal_headcount(app, client, db):
    """Eighteen hands eat. This is the number the caterer is given."""
    from models import CrewBreak
    show, day = _show_day(db)
    pos = _position(db)
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "08:00", "add_breaks": "1"})
    from models import ScheduleActivity
    act = ScheduleActivity.query.filter_by(day_id=day.id,
                                           description="CREW START").one()
    _add(client, show, day, act, qty=18, position_id=pos.id,
         position="Lighting Hand", crew_type="Local Crew")
    db.session.expire_all()
    meal = CrewBreak.query.filter_by(offset_minutes=300).one()
    assert meal.derived_headcount == 18


def test_named_leads_and_local_hands_add_up_together(app, client, db):
    from models import CrewMember, ShowCrewAssignment
    show, day = _show_day(db)
    pos = _position(db)
    act = _call(db, day)
    cm = CrewMember(first_name="Lead", last_name="Person", active=True)
    db.session.add(cm)
    db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.commit()

    _add(client, show, day, act, qty=1, crew_member_id=cm.id,
         position="Production Electrician", crew_type="Lead Crew")
    _add(client, show, day, act, qty=18, position_id=pos.id,
         position="Lighting Hand", crew_type="Local Crew")
    db.session.expire_all()
    assert act.crew_headcount == 19


def test_the_task_is_stored_on_the_row(app, client, db):
    from models import CrewRow
    show, day = _show_day(db)
    pos = _position(db)
    act = _call(db, day)
    _add(client, show, day, act, qty=5, position_id=pos.id,
         position="Rigger", crew_type="Local Crew", task="Pin/Bolt Truss")
    row = CrewRow.query.filter_by(activity_id=act.id).one()
    assert row.task == "Pin/Bolt Truss"
    assert row.qty == 5


def test_two_lines_of_the_same_position_stay_separate(app, client, db):
    """Twelve hanging lights and six striking catwalks are two crews doing two
    jobs. Merging them by title would lose both the tasks and the counts.
    """
    from models import CrewRow
    show, day = _show_day(db)
    pos = _position(db)
    act = _call(db, day)
    _add(client, show, day, act, qty=12, position_id=pos.id,
         position="Lighting Hand", crew_type="Local Crew",
         task="Hang / Circuit Lights")
    _add(client, show, day, act, qty=6, position_id=pos.id,
         position="Lighting Hand", crew_type="Local Crew",
         task="Catwalk Strike")
    db.session.expire_all()
    rows = CrewRow.query.filter_by(activity_id=act.id).all()
    assert len(rows) == 2
    assert sorted(r.qty for r in rows) == [6, 12]
    assert act.crew_headcount == 18


def test_the_client_master_shows_the_line_and_counts_the_people(app, client, db):
    """It used to skip any row with no crew member, so eighteen hands appeared
    nowhere on the master and the count beside the call was the leads only.
    """
    show, day = _show_day(db)
    pos = _position(db)
    act = _call(db, day)
    _add(client, show, day, act, qty=18, position_id=pos.id,
         position="Lighting Hand", crew_type="Local Crew",
         task="Catwalk Strike")
    db.session.expire_all()

    crew = [i for i in _master(show) if i.get("source") == "crew"]
    assert len(crew) == 1
    assert "18 × Lighting Hand — Catwalk Strike" in crew[0]["activity"]
    assert crew[0]["count"] == 18


def test_the_master_count_adds_leads_to_hands(app, client, db):
    from models import CrewMember, ShowCrewAssignment
    show, day = _show_day(db)
    pos = _position(db)
    act = _call(db, day)
    cm = CrewMember(first_name="Lead", last_name="Person", active=True)
    db.session.add(cm)
    db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.commit()
    _add(client, show, day, act, qty=1, crew_member_id=cm.id,
         position="Production Electrician", crew_type="Lead Crew")
    _add(client, show, day, act, qty=14, position_id=pos.id,
         position="Rigger", crew_type="Local Crew")
    db.session.expire_all()

    crew = [i for i in _master(show) if i.get("source") == "crew"][0]
    assert crew["count"] == 15
    assert "14 × Rigger" in crew["activity"]


# ── The catalogue page ───────────────────────────────────────────────────────

def test_the_catalogue_lists_only_local_labour(app, client, db):
    _position(db, "Lighting Hand", "Lighting", local=True)
    _position(db, "A1", "Audio", local=False)
    html = client.get("/local-labor").get_data(as_text=True)
    assert "Lighting Hand" in html
    assert ">A1<" not in html


def test_adding_a_title_that_already_exists_flags_it_instead_of_duplicating(app, client, db):
    """A second "Rigger" would split every count that matters."""
    from models import Position
    _position(db, "Pyro Hand", "Specialty", local=False)
    client.post("/local-labor/add", data={"title": "pyro hand",
                                          "department": "Specialty"})
    rows = Position.query.filter(Position.title.ilike("pyro hand")).all()
    assert len(rows) == 1
    assert rows[0].is_local_labor is True


def test_removing_from_the_catalogue_deletes_nothing(app, client, db):
    """A show from last year is entitled to keep saying it called 14 riggers."""
    from models import CrewRow, Position
    show, day = _show_day(db)
    pos = _position(db, "Rigger", "Rigging")
    act = _call(db, day)
    _add(client, show, day, act, qty=14, position_id=pos.id,
         position="Rigger", crew_type="Local Crew")

    client.post(f"/local-labor/{pos.id}/remove")
    db.session.expire_all()
    assert Position.query.get(pos.id) is not None
    assert Position.query.get(pos.id).is_local_labor is False
    assert CrewRow.query.filter_by(position_id=pos.id).count() == 1


def test_the_seed_migration_does_not_duplicate_an_existing_title(app, db):
    from migrations import _seed_local_labor_positions
    from models import Position
    # The seed already ran at app startup, so simulate the real production
    # case: a position with this title exists and is NOT flagged.
    existing = Position.query.filter(Position.title.ilike("stagehand")).one()
    existing.is_local_labor = False
    db.session.commit()

    _seed_local_labor_positions(db.session)
    db.session.commit()

    matches = Position.query.filter(Position.title.ilike("stagehand")).all()
    assert len(matches) == 1, "flagged, not duplicated"
    assert matches[0].is_local_labor is True


def test_the_seed_migration_is_idempotent(app, db):
    from migrations import _seed_local_labor_positions
    from models import Position
    _seed_local_labor_positions(db.session)
    db.session.commit()
    first = Position.query.filter_by(is_local_labor=True).count()

    _seed_local_labor_positions(db.session)
    db.session.commit()
    assert Position.query.filter_by(is_local_labor=True).count() == first
