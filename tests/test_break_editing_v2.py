"""Jason's four changes after using the reworked day page (2026-08-11).

1. Breaks show start AND end, plus the duration in words.
2. One Save for a whole crew call's breaks, not one per row.
3. The offset picks the length: +2:30 and +8:30 coffee, +5:00 lunch.
4. Provided / Not Provided / TBD — and Provided is what makes the F&B service.
"""
import datetime as dt

from breaks import default_duration_for, duration_text, window_end


def _setup(db, code, breaks=(("LUNCH", "12:00", 60),)):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, CrewBreak)
    show = Show(name="V2", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.flush()
    db.session.add(CrewRow(activity_id=call.id, qty=11, hours=10.0))
    made = []
    for label, time, dur in breaks:
        act = ScheduleActivity(day_id=day.id, time=time,
                               description=f"{label} BREAK")
        db.session.add(act); db.session.flush()
        cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                       label=label, duration_minutes=dur, offset_minutes=300)
        db.session.add(cb); made.append(cb)
    db.session.commit()
    return show, day, call, made


# ── 1. start, end and duration ──────────────────────────────────────────────

def test_a_break_knows_when_the_crew_is_back(app, db):
    show, day, call, (cb,) = _setup(db, "V201")
    assert cb.end_time == "13:00"


def test_an_untimed_break_has_no_end(app, db):
    """Not 00:00 — that would read as a real time on a call sheet."""
    from models import ScheduleActivity, CrewBreak
    show, day, call, (cb,) = _setup(db, "V202")
    cb.activity.time = None
    db.session.commit()
    assert cb.end_time == ""


def test_the_duration_reads_in_words(app):
    assert duration_text(15) == "15 Minutes"
    assert duration_text(60) == "60 Minutes"
    assert duration_text(None) == ""


def test_window_end_refuses_to_guess_a_start(app):
    assert window_end(None, 60) is None


def test_the_period_row_shows_the_window(app, client, db):
    show, day, call, (cb,) = _setup(db, "V203")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "12:00 PM – 1:00 PM" in html
    assert "60 Minutes" in html


def test_the_window_moves_with_the_duration(app, client, db):
    show, day, call, (cb,) = _setup(db, "V204")
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/save"
                % (show.id, day.id, call.id),
                data={"duration_minutes_%d" % cb.id: "15"})
    assert cb.end_time == "12:15"


# ── 2. one Save for the whole crew call ─────────────────────────────────────

def _save(client, show, day, call, **data):
    return client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/save"
                       % (show.id, day.id, call.id), data=data)


def test_every_break_on_the_call_saves_in_one_submit(app, client, db):
    """The panel folds shut when you are done. A per-row Save loses the rows
    you did not press."""
    show, day, call, (coffee, lunch) = _setup(
        db, "V205", breaks=[("COFFEE", "09:30", 15), ("LUNCH", "12:00", 60)])
    _save(client, show, day, call, **{
        "label_%d" % coffee.id: "TEA",
        "duration_minutes_%d" % coffee.id: "30",
        "catered_%d" % coffee.id: "no",
        "label_%d" % lunch.id: "DINNER",
        "duration_minutes_%d" % lunch.id: "60",
        "catered_%d" % lunch.id: "yes",
    })
    assert coffee.label == "TEA"
    assert coffee.duration_minutes == 30
    assert coffee.catered == "no"
    assert lunch.label == "DINNER"
    assert lunch.catered == "yes"


def test_saving_one_call_leaves_another_alone(app, client, db):
    from models import ScheduleActivity, CrewRow, CrewBreak
    show, day, call, (lunch,) = _setup(db, "V206")
    other = ScheduleActivity(day_id=day.id, time="08:00",
                             description="CREW START")
    db.session.add(other); db.session.flush()
    db.session.add(CrewRow(activity_id=other.id, qty=6, hours=10.0))
    act = ScheduleActivity(day_id=day.id, time="13:00", description="LUNCH B")
    db.session.add(act); db.session.flush()
    theirs = CrewBreak(show_id=show.id, activity_id=act.id,
                       crew_call_id=other.id, label="LUNCH",
                       duration_minutes=60)
    db.session.add(theirs); db.session.commit()
    _save(client, show, day, call, **{"label_%d" % lunch.id: "EARLY LUNCH"})
    assert lunch.label == "EARLY LUNCH"
    assert theirs.label == "LUNCH"


def test_the_day_page_offers_one_save_button_per_call(app, client, db):
    show, day, call, made = _setup(
        db, "V207", breaks=[("COFFEE", "09:30", 15), ("LUNCH", "12:00", 60)])
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "Save 2 breaks" in html
    assert html.count("breaks/save") == 1


# ── 3. the offset picks the length ──────────────────────────────────────────

def test_the_house_length_for_each_offset(app):
    assert default_duration_for(150) == 15     # morning coffee
    assert default_duration_for(300) == 60     # lunch
    assert default_duration_for(510) == 15     # afternoon coffee


def test_an_unknown_offset_falls_back_rather_than_crashing(app):
    assert default_duration_for(None) == 60
    assert default_duration_for("nonsense") == 60


def test_adding_a_coffee_break_is_fifteen_minutes(app, client, db):
    """Nobody takes an hour for a coffee. The server applies the mapping too,
    so a browser with JS off cannot save a different answer."""
    from models import CrewBreak
    show, day, call, made = _setup(db, "V208", breaks=[])
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/add"
                % (show.id, day.id, call.id),
                data={"label": "COFFEE", "offset_minutes": "150"})
    cb = CrewBreak.query.filter_by(label="COFFEE").one()
    assert cb.duration_minutes == 15


def test_adding_a_lunch_break_is_an_hour(app, client, db):
    from models import CrewBreak
    show, day, call, made = _setup(db, "V209", breaks=[])
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/add"
                % (show.id, day.id, call.id),
                data={"label": "LUNCH", "offset_minutes": "300"})
    cb = CrewBreak.query.filter_by(label="LUNCH").one()
    assert cb.duration_minutes == 60


def test_an_explicit_duration_still_wins(app, client, db):
    from models import CrewBreak
    show, day, call, made = _setup(db, "V210", breaks=[])
    client.post("/shows/%d/schedule/%d/crew-call/%d/breaks/add"
                % (show.id, day.id, call.id),
                data={"label": "COFFEE", "offset_minutes": "150",
                      "duration_minutes": "30"})
    cb = CrewBreak.query.filter_by(label="COFFEE").one()
    assert cb.duration_minutes == 30


# ── 4. Provided / Not Provided / TBD ────────────────────────────────────────

def test_the_three_words_are_what_the_page_says(app, client, db):
    show, day, call, (cb,) = _setup(db, "V211")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert ">Provided<" in html
    assert ">Not Provided<" in html
    assert ">TBD<" in html
    assert "Crew sort themselves" not in html
    assert "not decided" not in html


def test_provided_is_what_creates_the_fb_service(app, client, db):
    """Jason: 'If a break is classified as Provided THAT is when it becomes a
    service in the F&B tab.'"""
    from models import MealService
    show, day, call, (cb,) = _setup(db, "V212")
    assert cb.meal_service_id is None
    _save(client, show, day, call, **{"catered_%d" % cb.id: "yes"})
    assert cb.meal_service_id is not None
    svc = MealService.query.filter_by(show_id=show.id).one()
    assert svc.schedule_day_id == day.id
    assert svc.total_headcount == 11        # follows the crew call


def test_not_provided_makes_no_service(app, client, db):
    from models import MealService
    show, day, call, (cb,) = _setup(db, "V213")
    _save(client, show, day, call, **{"catered_%d" % cb.id: "no"})
    assert cb.meal_service_id is None
    assert MealService.query.filter_by(show_id=show.id).count() == 0


def test_tbd_makes_no_service_but_stays_visible_to_fb(app, client, db):
    from models import MealService
    show, day, call, (cb,) = _setup(db, "V214")
    _save(client, show, day, call, **{"catered_%d" % cb.id: "unconfirmed"})
    assert MealService.query.filter_by(show_id=show.id).count() == 0
    assert cb.visible_to_fnb is True         # TBD is not "no"


def test_two_breaks_marked_provided_get_a_service_each(app, client, db):
    from models import MealService
    show, day, call, (coffee, lunch) = _setup(
        db, "V215", breaks=[("COFFEE", "09:30", 15), ("LUNCH", "12:00", 60)])
    _save(client, show, day, call, **{
        "catered_%d" % coffee.id: "yes", "catered_%d" % lunch.id: "yes"})
    assert MealService.query.filter_by(show_id=show.id).count() == 2
    assert coffee.meal_service_id != lunch.meal_service_id
