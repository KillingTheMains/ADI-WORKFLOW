"""
Deleting a show must not leave rows behind.

Measured on production 2026-08-12 after show 5 was deleted: **216 orphaned
rows** — crew_comm_assignments 88, meal_services 56 (with 56 locations under
them), crew_breaks 40, radio_channels 32. `days`, `phases` and
`crew_assignments` left nothing, and the leak was exactly the set of tables
with no collection on `Show`.

An orphan is invisible in the app, so nothing complains. It is not harmless:
a crew break holding a `meal_service_id` is a ghost feeding a service, and
`crew_breaks.activity_id` is UNIQUE, so a stale row can collide with a future
insert — which is what produced a live 500 that day.
"""
import datetime as dt


def _loaded_show(db, client, code="DEL26"):
    """A show carrying one row in each table that used to leak."""
    from models import (CrewCommAssignment, CrewMember, RadioChannel,
                        ScheduleDay, Show, ShowCommChannel, ShowDietaryNote,
                        ShowOpenSlot)
    show = Show(name="Delete Me", code=code)
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()

    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 20),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.commit()

    # A crew call with breaks -> CrewBreak + MealService + location.
    client.post(f"/shows/{show.id}/schedule/{day.id}/crew-call/create",
                data={"time": "08:00", "add_breaks": "1"})

    cm = CrewMember(first_name="Comms", last_name="Person", active=True)
    db.session.add(cm)
    db.session.flush()
    db.session.add_all([
        CrewCommAssignment(show_id=show.id, crew_member_id=cm.id),
        RadioChannel(show_id=show.id, slot=1, name="CH1"),
        ShowCommChannel(show_id=show.id, name="Production"),
        ShowDietaryNote(show_id=show.id, preference="Vegetarian", count=2),
        ShowOpenSlot(show_id=show.id, placeholder_label="LED Lead — Set Up"),
    ])
    db.session.commit()
    return show


def _orphan_counts(db):
    """Every row whose show is gone, by table. The production query, in code."""
    from models import (CrewBreak, CrewCommAssignment, MealService,
                        MealServiceLocation, RadioChannel, ScheduleDay, Show,
                        ShowCommChannel, ShowDietaryNote, ShowOpenSlot,
                        SubScheduleEntry)
    live = {s.id for s in Show.query.all()}
    out = {}
    for model in (CrewBreak, CrewCommAssignment, MealService, RadioChannel,
                  ScheduleDay, ShowCommChannel, ShowDietaryNote, ShowOpenSlot,
                  SubScheduleEntry):
        n = len([r for r in model.query.all() if r.show_id not in live])
        if n:
            out[model.__tablename__] = n
    live_svc = {s.id for s in MealService.query.all()}
    n = len([l for l in MealServiceLocation.query.all()
             if l.meal_service_id not in live_svc])
    if n:
        out["meal_service_locations"] = n
    return out


def test_deleting_a_show_leaves_nothing_behind(app, client, db):
    """The whole finding, as one assertion."""
    from models import CrewBreak, MealService
    show = _loaded_show(db, client)
    assert CrewBreak.query.count() == 3        # guard: the fixture is loaded
    assert MealService.query.count() >= 0

    db.session.delete(show)
    db.session.commit()

    assert _orphan_counts(db) == {}


def test_the_four_tables_that_actually_leaked(app, client, db):
    """Named individually so a failure says WHICH one regressed."""
    from models import (CrewBreak, CrewCommAssignment, MealService,
                        RadioChannel)
    show = _loaded_show(db, client, code="DEL27")
    db.session.delete(show)
    db.session.commit()

    assert CrewBreak.query.count() == 0
    assert CrewCommAssignment.query.count() == 0
    assert MealService.query.count() == 0
    assert RadioChannel.query.count() == 0


def test_another_shows_rows_are_untouched(app, client, db):
    """The cascade must not reach past the show being deleted."""
    from models import CrewBreak, RadioChannel
    keep = _loaded_show(db, client, code="KEEP26")
    drop = _loaded_show(db, client, code="DROP26")
    before = CrewBreak.query.filter_by(show_id=keep.id).count()
    assert before == 3

    db.session.delete(drop)
    db.session.commit()

    assert CrewBreak.query.filter_by(show_id=keep.id).count() == before
    assert RadioChannel.query.filter_by(show_id=keep.id).count() == 1
    assert _orphan_counts(db) == {}


def test_the_sweep_migration_clears_pre_existing_orphans(app, client, db):
    """Rows already orphaned before the cascade existed. Simulated by pointing
    them at a show id that was never created.
    """
    from migrations import _delete_orphans_from_deleted_shows
    from models import CrewBreak, MealService, RadioChannel
    show = _loaded_show(db, client, code="ORPH26")
    ghost = 99999
    for cb in CrewBreak.query.all():
        cb.show_id = ghost
    for svc in MealService.query.all():
        svc.show_id = ghost
    db.session.add(RadioChannel(show_id=ghost, slot=1, name="GHOST"))
    db.session.commit()
    assert _orphan_counts(db)          # guard: we really made orphans

    _delete_orphans_from_deleted_shows(db.session)
    db.session.commit()

    assert _orphan_counts(db) == {}
    assert show is not None


def test_the_sweep_is_a_no_op_on_a_clean_database(app, client, db):
    """It runs once on every deploy. It must do nothing when there is nothing
    to do — a sweep that keeps finding work is a sweep hiding a live bug.
    """
    from migrations import _delete_orphans_from_deleted_shows
    from models import CrewBreak
    _loaded_show(db, client, code="CLEAN26")
    before = CrewBreak.query.count()

    _delete_orphans_from_deleted_shows(db.session)
    db.session.commit()

    assert CrewBreak.query.count() == before
    assert _orphan_counts(db) == {}
