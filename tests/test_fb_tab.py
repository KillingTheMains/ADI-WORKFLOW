"""The F&B tab, reframed (2026-08-11).

Jason: "I want to simplify the F&B tab on the OSS, it's too clunky. I don't
think we need so many editable lines."

It was the same disease the day page had — a permanently mounted data-entry
grid — plus a second one: it kept asking for data the app already knows. A
service's window derives from the break it feeds; its headcount derives from
the crew call. So the tab now READS by default and only asks for what is
genuinely F&B's own.
"""
import datetime as dt


def _show(db, code, locations=1, linked=True, typed_count=None):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, CrewBreak,
                        MealService, MealServiceLocation)
    show = Show(name="FB", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="20:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.flush()
    db.session.add(CrewRow(activity_id=call.id, qty=11, hours=10.0))
    act = ScheduleActivity(day_id=day.id, time="12:00", description="LUNCH")
    db.session.add(act); db.session.flush()
    svc = MealService(show_id=show.id, schedule_day_id=day.id, name="Crew Lunch",
                      kind="lunch", setup_minutes=30, holdover_minutes=30)
    db.session.add(svc); db.session.flush()
    for i in range(locations):
        db.session.add(MealServiceLocation(
            meal_service_id=svc.id, location_name=["Backstage", "FOH"][i],
            start_time="12:00", headcount=typed_count, sort_order=i * 10))
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label="LUNCH", duration_minutes=60,
                   catered="yes" if linked else "unconfirmed",
                   meal_service_id=svc.id if linked else None)
    db.session.add(cb)
    if linked:
        svc.activity_id = act.id
    db.session.commit()
    return show, day, svc, cb


def _tab(client, show):
    return client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)


# ── it reads before it asks ─────────────────────────────────────────────────

def test_the_editor_is_folded_away(app, client, db):
    show, day, svc, cb = _show(db, "FB01")
    html = _tab(client, show)
    assert 'id="svc-%d"' % svc.id in html
    assert 'class="collapse" id="svc-%d"' % svc.id in html


def test_the_line_says_what_it_is_without_opening_anything(app, client, db):
    show, day, svc, cb = _show(db, "FB02")
    html = _tab(client, show)
    assert "Crew Lunch" in html
    assert "Backstage" in html
    assert "11 to feed" in html


def test_one_save_for_the_service_and_its_locations(app, client, db):
    show, day, svc, cb = _show(db, "FB03", locations=2)
    html = _tab(client, show)
    assert "Save Crew Lunch" in html
    assert html.count("/service/%d/save" % svc.id) == 1


def test_a_single_location_service_gets_no_table(app, client, db):
    """A table for one row is noise, and it is the common case."""
    show, day, svc, cb = _show(db, "FB04", locations=1)
    html = _tab(client, show)
    assert ">Where<" in html
    show2, day2, svc2, cb2 = _show(db, "FB05", locations=2)
    html2 = _tab(client, show2)
    assert ">Location<" in html2


# ── it shows what it can derive ─────────────────────────────────────────────

def test_the_service_window_is_derived_not_asked_for(app, client, db):
    """Break 12:00–13:00, 30 before and 30 after — F&B works 11:30 to 13:30.
    This is step 2's missing UI half, arriving as part of the reframe."""
    show, day, svc, cb = _show(db, "FB06")
    html = _tab(client, show)
    assert "11:30 AM – 1:30 PM" in html
    assert "worked out from the break, not typed" in html


def test_a_food_out_breach_warns_and_does_not_block(app, client, db):
    show, day, svc, cb = _show(db, "FB07")
    svc.setup_minutes = 60          # 60 + 60 + 30 = 150, over the 120 max
    db.session.commit()
    html = _tab(client, show)
    assert "food out 150m" in html
    # Still perfectly saveable.
    r = client.post("/shows/%d/oss/fb/service/%d/save" % (show.id, svc.id),
                    data={"name": "Crew Lunch", "kind": "lunch",
                          "setup_minutes": "60", "holdover_minutes": "30"})
    assert r.status_code in (302, 200)
    assert svc.setup_minutes == 60


def test_an_unlinked_service_has_no_derived_window(app, client, db):
    show, day, svc, cb = _show(db, "FB08", linked=False)
    html = _tab(client, show)
    assert "worked out from the break" not in html


# ── saving ──────────────────────────────────────────────────────────────────

def test_the_save_writes_service_and_every_location_at_once(app, client, db):
    show, day, svc, cb = _show(db, "FB09", locations=2)
    a, b = svc.locations_ordered
    client.post("/shows/%d/oss/fb/service/%d/save" % (show.id, svc.id),
                data={"name": "Crew Dinner", "kind": "dinner",
                      "notes": "no nuts",
                      "setup_minutes": "45", "holdover_minutes": "15",
                      "loc_%d_location_name" % a.id: "Green Room",
                      "loc_%d_headcount" % a.id: "7",
                      "loc_%d_location_name" % b.id: "Dock",
                      "loc_%d_headcount" % b.id: "4"})
    assert svc.name == "Crew Dinner"
    assert svc.kind == "dinner"
    assert svc.notes == "no nuts"
    assert svc.setup_minutes == 45
    assert a.location_name == "Green Room" and a.headcount == 7
    assert b.location_name == "Dock" and b.headcount == 4


def test_clearing_a_count_hands_it_back_to_the_crew(app, client, db):
    """Blank still means 'follow the crew', same as before the reframe."""
    show, day, svc, cb = _show(db, "FB10", typed_count=14)
    loc = svc.locations[0]
    assert loc.is_overridden is True
    client.post("/shows/%d/oss/fb/service/%d/save" % (show.id, svc.id),
                data={"name": svc.name, "kind": svc.kind,
                      "loc_%d_headcount" % loc.id: ""})
    assert loc.is_overridden is False
    assert loc.effective_headcount == 11        # the crew call


def test_a_typed_count_that_disagrees_with_the_crew_is_flagged(app, client, db):
    show, day, svc, cb = _show(db, "FB11", typed_count=14)
    html = _tab(client, show)
    assert "crew says 11" in html


def test_the_add_forms_are_behind_one_button(app, client, db):
    """Eleven days of permanently mounted create forms was a dozen controls a
    day for something used once."""
    show, day, svc, cb = _show(db, "FB12")
    html = _tab(client, show)
    assert "+ Add a service to this day" in html
    assert 'id="add-svc-%d"' % day.id in html


def test_the_feeds_line_survived_the_reframe(app, client, db):
    show, day, svc, cb = _show(db, "FB13")
    html = _tab(client, show)
    assert "Feeds" in html
    assert "off the 7:00 AM crew call" in html
