"""Editing breaks on the crew call (2026-08-11, step 3)."""
import datetime as dt

from models import CATERED_NO, CATERED_UNCONFIRMED, CATERED_YES


def _setup(db, code="BE26", new_breaks=True):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewBreak,
                        MealService)
    show = Show(name="Edit", code=code, uses_new_breaks=new_breaks)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10), sod="07:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    brk_act = ScheduleActivity(day_id=day.id, time="12:00",
                               description="LUNCH BREAK")
    db.session.add_all([call, brk_act]); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=brk_act.id,
                   crew_call_id=call.id, offset_minutes=300,
                   duration_minutes=60, label="LUNCH")
    ms = MealService(show_id=show.id, schedule_day_id=day.id, name="Crew Lunch",
                     kind="lunch")
    db.session.add_all([cb, ms]); db.session.commit()
    return show, day, call, brk_act, cb, ms


def _edit(client, show, day, cb, **data):
    return client.post("/shows/%d/schedule/%d/breaks/%d/edit"
                       % (show.id, day.id, cb.id), data=data)


def test_duration_is_limited_to_the_offered_choices(app, client, db):
    show, day, call, act, cb, ms = _setup(db)
    _edit(client, show, day, cb, duration_minutes="30")
    assert cb.duration_minutes == 30
    _edit(client, show, day, cb, duration_minutes="45")   # not offered
    assert cb.duration_minutes == 30


def test_changing_the_time_keeps_the_offset_honest(app, client, db):
    """Otherwise the stored offset quietly disagrees with the clock."""
    show, day, call, act, cb, ms = _setup(db, "BE27")
    _edit(client, show, day, cb, time="14:30")
    assert act.time == "14:30"
    assert cb.offset_minutes == 450        # 07:00 -> 14:30


def test_provided_can_be_set_either_way(app, client, db):
    show, day, call, act, cb, ms = _setup(db, "BE28")
    _edit(client, show, day, cb, catered="yes")
    assert cb.catered == CATERED_YES
    _edit(client, show, day, cb, catered="no")
    assert cb.catered == CATERED_NO


def test_a_bogus_state_is_ignored(app, client, db):
    show, day, call, act, cb, ms = _setup(db, "BE29")
    _edit(client, show, day, cb, catered="maybe")
    assert cb.catered == CATERED_UNCONFIRMED


def test_linking_a_service_marks_it_provided(app, client, db):
    """Leaving it unconfirmed next to a real meal service is contradictory."""
    show, day, call, act, cb, ms = _setup(db, "BE30")
    assert cb.catered == CATERED_UNCONFIRMED
    _edit(client, show, day, cb, meal_service_id=str(ms.id))
    assert cb.meal_service_id == ms.id
    assert cb.catered == CATERED_YES


def test_unlinking_a_service_leaves_the_state_alone(app, client, db):
    show, day, call, act, cb, ms = _setup(db, "BE31")
    _edit(client, show, day, cb, meal_service_id=str(ms.id))
    _edit(client, show, day, cb, meal_service_id="")
    assert cb.meal_service_id is None
    assert cb.catered == CATERED_YES     # the user says so; not overridden


def test_add_break_creates_an_activity_and_a_record(app, client, db):
    from models import CrewBreak, ScheduleActivity
    show, day, call, act, cb, ms = _setup(db, "BE32")
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/add"
                % (show.id, day.id, call.id),
                data={"label": "COFFEE", "offset_minutes": "150",
                      "duration_minutes": "15"})
    made = CrewBreak.query.filter_by(show_id=show.id).all()
    assert len(made) == 2
    new = [b for b in made if b.label == "COFFEE"][0]
    assert new.duration_minutes == 15
    assert new.crew_call_id == call.id
    # 07:00 + 2:30
    assert ScheduleActivity.query.get(new.activity_id).time == "09:30"


def test_added_meal_break_starts_unconfirmed(app, client, db):
    """A new MEAL break presumes nothing — somebody still has to say whether
    F&B provides it.

    Rewritten 2026-08-12, NOT weakened. It used to add at +2:30 and assert
    unconfirmed; +2:30 is now a coffee slot, and a coffee break deliberately
    has no catering question at all (see test_break_kinds). The intent of this
    test — "adding a break does not quietly answer the question for you" —
    belongs to the meal slot, so it asks there. That a coffee break does the
    opposite is asserted separately rather than lost here.
    """
    from models import CrewBreak
    show, day, call, act, cb, ms = _setup(db, "BE33")
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/add"
                % (show.id, day.id, call.id),
                data={"label": "TEA", "offset_minutes": "300",
                      "duration_minutes": "60"})
    new = CrewBreak.query.filter_by(label="TEA").one()
    assert new.catered == CATERED_UNCONFIRMED


def test_a_crew_call_with_no_time_cannot_take_a_break(app, client, db):
    from models import CrewBreak, ScheduleActivity
    show, day, call, act, cb, ms = _setup(db, "BE34")
    untimed = ScheduleActivity(day_id=day.id, time=None,
                               description="CREW START")
    db.session.add(untimed); db.session.commit()
    before = CrewBreak.query.count()
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/add"
                % (show.id, day.id, untimed.id),
                data={"label": "X", "offset_minutes": "150"})
    assert CrewBreak.query.count() == before


def test_deleting_a_break_removes_its_activity_too(app, client, db):
    from models import CrewBreak, ScheduleActivity
    show, day, call, act, cb, ms = _setup(db, "BE35")
    act_id = act.id
    client.post("/shows/%d/schedule/%d/breaks/%d/delete"
                % (show.id, day.id, cb.id))
    assert CrewBreak.query.filter_by(show_id=show.id).count() == 0
    assert ScheduleActivity.query.get(act_id) is None


def test_break_row_renders_only_for_switched_over_shows(app, client, db):
    show, day, call, act, cb, ms = _setup(db, "BE36", new_breaks=False)
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "+ Break" not in html
    assert 'id="breaks-%d"' % call.id not in html


def test_break_row_renders_when_switched_on(app, client, db):
    """The editor lives on the crew call and the break reads as a period row
    (2026-08-11). Neither is the old always-mounted strip."""
    show, day, call, act, cb, ms = _setup(db, "BE37", new_breaks=True)
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert 'id="breaks-%d"' % call.id in html       # the folded editor
    assert "+ Break" in html
    assert "Not Provided" in html                   # one catering control
    assert "LUNCH" in html                          # the period row
