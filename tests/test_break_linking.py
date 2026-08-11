"""Linking a break to its F&B service, from either side (2026-08-11).

The hole this fills: a break got a service exactly one way — mark it Provided
and a NEW one is created. So if the catering order is built first, every
Provided made a duplicate beside the real service and orphaned the real one.
"""
import datetime as dt

import break_linking


def _fixture(db, code, svc_name="Crew Lunch", svc_time="12:00",
             recurring=False):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, CrewBreak,
                        MealService, MealServiceLocation)
    show = Show(name="Link", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.flush()
    db.session.add(CrewRow(activity_id=call.id, qty=11, hours=10.0))
    act = ScheduleActivity(day_id=day.id, time="12:00", description="LUNCH")
    db.session.add(act); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   label="LUNCH", duration_minutes=60)
    svc = MealService(show_id=show.id, schedule_day_id=day.id, name=svc_name,
                      kind="lunch", is_recurring=recurring)
    db.session.add_all([cb, svc]); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       start_time=svc_time, sort_order=0))
    db.session.commit()
    return show, day, call, cb, svc


# ── the transaction ─────────────────────────────────────────────────────────

def test_linking_sets_both_pointers(app, db):
    """CrewBreak.meal_service_id is who feeds this break; MealService
    .activity_id is what the service is ABOUT, and the export's one-event-one-
    row merge reads THAT one. The old dropdown set only the first, so a
    hand-linked pair printed twice."""
    show, day, call, cb, svc = _fixture(db, "LK01")
    ok, msg = break_linking.link(cb, svc)
    db.session.commit()
    assert ok, msg
    assert cb.meal_service_id == svc.id
    assert svc.activity_id == cb.activity_id


def test_linking_is_the_statement_that_it_is_provided(app, db):
    show, day, call, cb, svc = _fixture(db, "LK02")
    assert cb.catered == "unconfirmed"
    break_linking.link(cb, svc)
    db.session.commit()
    assert cb.catered == "yes"


def test_the_headcount_follows_the_crew_once_linked(app, db):
    show, day, call, cb, svc = _fixture(db, "LK03")
    assert svc.derived_headcount is None
    break_linking.link(cb, svc)
    db.session.commit()
    assert svc.derived_headcount == 11
    assert svc.total_headcount == 11


def test_a_service_feeds_only_one_break(app, db):
    """Two crew groups on one service is food out for three hours."""
    from models import ScheduleActivity, CrewBreak
    show, day, call, cb, svc = _fixture(db, "LK04")
    break_linking.link(cb, svc)
    db.session.commit()
    act = ScheduleActivity(day_id=day.id, time="13:00", description="LUNCH 2")
    db.session.add(act); db.session.flush()
    other = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                      label="LUNCH", duration_minutes=60)
    db.session.add(other); db.session.commit()
    ok, msg = break_linking.link(other, svc)
    assert ok is False
    assert "already feeds" in msg


def test_a_standing_service_cannot_feed_a_break(app, db):
    """It runs all day with its own refresh touchpoints — it feeds nobody
    AT a break."""
    show, day, call, cb, svc = _fixture(db, "LK05", svc_name="All Day Beverages",
                                        recurring=True)
    ok, msg = break_linking.link(cb, svc)
    assert ok is False
    assert "standing service" in msg


def test_a_service_cannot_feed_a_break_on_another_day(app, db):
    from models import ScheduleDay
    show, day, call, cb, svc = _fixture(db, "LK06")
    other_day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 11))
    db.session.add(other_day); db.session.flush()
    svc.schedule_day_id = other_day.id
    db.session.commit()
    ok, msg = break_linking.link(cb, svc)
    assert ok is False
    assert "own day" in msg


def test_an_already_fed_break_must_be_unlinked_first(app, db):
    from models import MealService
    show, day, call, cb, svc = _fixture(db, "LK07")
    break_linking.link(cb, svc)
    db.session.commit()
    second = MealService(show_id=show.id, schedule_day_id=day.id,
                         name="Other Lunch", kind="lunch")
    db.session.add(second); db.session.commit()
    ok, msg = break_linking.link(cb, second)
    assert ok is False
    assert "Unlink it first" in msg


# ── unlinking asks what the break becomes ───────────────────────────────────

def test_unlink_refuses_without_a_status(app, db):
    """'Provided — by what?' stops being answerable. Picking one quietly is
    how a crew stops being fed with nobody deciding to stop feeding it."""
    show, day, call, cb, svc = _fixture(db, "LK08")
    break_linking.link(cb, svc)
    db.session.commit()
    ok, msg = break_linking.unlink(cb, "")
    assert ok is False
    assert cb.meal_service_id == svc.id


def test_unlink_applies_the_status_it_was_given(app, db):
    show, day, call, cb, svc = _fixture(db, "LK09")
    break_linking.link(cb, svc)
    db.session.commit()
    ok, msg = break_linking.unlink(cb, "no")
    db.session.commit()
    assert ok
    assert cb.meal_service_id is None
    assert cb.catered == "no"


def test_unlink_clears_the_about_pointer_too(app, db):
    """Otherwise the export keeps merging a service into a break it no longer
    feeds, and the break vanishes from the printed schedule."""
    show, day, call, cb, svc = _fixture(db, "LK10")
    break_linking.link(cb, svc)
    db.session.commit()
    break_linking.unlink(cb, "unconfirmed")
    db.session.commit()
    assert svc.activity_id is None


def test_unlink_keeps_the_service(app, db):
    from models import MealService
    show, day, call, cb, svc = _fixture(db, "LK11")
    break_linking.link(cb, svc)
    db.session.commit()
    break_linking.unlink(cb, "unconfirmed")
    db.session.commit()
    assert MealService.query.filter_by(show_id=show.id).count() == 1


# ── candidates and suggestions ──────────────────────────────────────────────

def test_a_linked_service_is_not_offered_again(app, db):
    show, day, call, cb, svc = _fixture(db, "LK12")
    assert svc in break_linking.candidates_for_break(cb)
    break_linking.link(cb, svc)
    db.session.commit()
    assert break_linking.candidates_for_break(cb) == []


def test_standing_services_are_never_candidates(app, db):
    show, day, call, cb, svc = _fixture(db, "LK13", recurring=True)
    assert break_linking.candidates_for_break(cb) == []
    assert break_linking.candidates_for_service(svc) == []


def test_a_close_service_is_marked_suggested_not_chosen(app, db):
    show, day, call, cb, svc = _fixture(db, "LK14", svc_time="12:30")
    assert break_linking.is_suggested(cb, svc) is True
    # Marked only — nothing was linked.
    assert cb.meal_service_id is None


def test_a_distant_service_is_offered_but_not_suggested(app, db):
    show, day, call, cb, svc = _fixture(db, "LK15", svc_time="19:00")
    assert break_linking.is_suggested(cb, svc) is False
    assert svc in break_linking.candidates_for_break(cb)


# ── the two doors ───────────────────────────────────────────────────────────

def test_the_fb_tab_links_a_service_to_a_break(app, client, db):
    show, day, call, cb, svc = _fixture(db, "LK16")
    client.post("/shows/%d/oss/fb/service/%d/feeds" % (show.id, svc.id),
                data={"break_id": str(cb.id)})
    assert cb.meal_service_id == svc.id
    assert cb.catered == "yes"


def test_the_fb_tab_unlinks_with_the_chosen_status(app, client, db):
    show, day, call, cb, svc = _fixture(db, "LK17")
    break_linking.link(cb, svc); db.session.commit()
    client.post("/shows/%d/oss/fb/service/%d/unlink" % (show.id, svc.id),
                data={"then_status": "no"})
    assert cb.meal_service_id is None
    assert cb.catered == "no"


def test_the_day_page_links_a_break_to_a_service(app, client, db):
    show, day, call, cb, svc = _fixture(db, "LK18")
    client.post("/shows/%d/schedule/%d/breaks/%d/link"
                % (show.id, day.id, cb.id), data={"service_id": str(svc.id)})
    assert cb.meal_service_id == svc.id


def test_a_hand_linked_pair_prints_as_one_row(app, db):
    """The latent bug the old dropdown carried: only meal_service_id was set,
    so the export never merged them and one lunch printed twice."""
    from oss_export import build_master_items
    show, day, call, cb, svc = _fixture(db, "LK19")
    break_linking.link(cb, svc)
    db.session.commit()
    items, _hc = build_master_items(show, [], [svc])
    lunches = [i for i in items
               if "LUNCH" in (i["activity"] or "").upper()
               or "CREW LUNCH" in (i["activity"] or "").upper()]
    assert len(lunches) == 1


# ── the day page says so, under the event ───────────────────────────────────

def test_the_day_page_says_the_event_is_linked(app, client, db):
    show, day, call, cb, svc = _fixture(db, "LK20")
    break_linking.link(cb, svc)
    db.session.commit()
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "This event is linked to the F&amp;B service" in html
    assert "Crew Lunch" in html


def test_an_unlinked_break_says_nothing(app, client, db):
    show, day, call, cb, svc = _fixture(db, "LK21")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "This event is linked to the F&amp;B service" not in html


def test_the_picker_only_appears_when_there_is_a_choice(app, client, db):
    show, day, call, cb, svc = _fixture(db, "LK22")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "or link a service that already exists" in html
    break_linking.link(cb, svc)
    db.session.commit()
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "or link a service that already exists" not in html
