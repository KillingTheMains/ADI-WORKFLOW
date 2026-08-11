"""Standing beverage service (2026-08-11, respecified by Jason).

A beverage service is its own thing, not a meal and not a break:

* it is SET at the day's **SOD plus an offset chosen when it is created**
  (negative for before SOD) — not off the first crew call, which was the
  earlier guess;
* it refreshes on **its own interval**, chosen at creation;
* **no refresh within one interval of EOD** — setting out a fresh service with
  less than a full interval of day left is waste;
* **crew breaks are never linked to it.** A beverage table feeds nobody AT a
  break.

The touchpoints are computed on every read and placed onto the day's timeline
the way recurring events are, so they appear on the schedule as events without
going stale when SOD or EOD moves.
"""
import datetime as dt

from beverage_service import (NO_EOD, NO_SOD, SETUP_AFTER_EOD,
                              crew_windows_for_day, overlay_for_day,
                              plan_for_day)


def _day(db, code, sod="07:00", eod="20:00", calls=(("07:00", 10, 8.0),)):
    from models import Show, ScheduleDay, ScheduleActivity, CrewRow
    show = Show(name="Bev", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod=sod, eod=eod)
    db.session.add(day); db.session.flush()
    for i, (time, qty, hours) in enumerate(calls):
        act = ScheduleActivity(day_id=day.id, time=time,
                               description="CREW START", sort_order=i)
        db.session.add(act); db.session.flush()
        db.session.add(CrewRow(activity_id=act.id, qty=qty, hours=hours,
                               sort_order=0))
    db.session.commit()
    return show, day


def _times(day, **kw):
    return [p["time"] for p in plan_for_day(day, **kw)["points"]]


# ── anchored to SOD, by an amount chosen at creation ────────────────────────

def test_the_service_is_set_relative_to_sod(app, db):
    show, day = _day(db, "BV01", sod="07:00")
    assert _times(day, offset=-30)[0] == "06:30"
    assert _times(day, offset=0)[0] == "07:00"
    assert _times(day, offset=30)[0] == "07:30"


def test_the_anchor_is_sod_not_the_first_crew_call(app, db):
    """The earlier guess was the first crew call. Jason respecified it."""
    show, day = _day(db, "BV02", sod="06:00", calls=[("09:00", 10, 8.0)])
    assert _times(day, offset=0)[0] == "06:00"


def test_the_interval_is_whatever_was_chosen(app, db):
    show, day = _day(db, "BV03", sod="07:00", eod="20:00")
    assert _times(day, offset=0, interval=150)[:3] == ["07:00", "09:30", "12:00"]
    assert _times(day, offset=0, interval=120)[:3] == ["07:00", "09:00", "11:00"]


# ── the EOD rule ────────────────────────────────────────────────────────────

def test_no_refresh_within_one_interval_of_eod(app, db):
    """Jason's rule: a fresh service set out with less than a full interval of
    day left would be cleared away almost immediately."""
    show, day = _day(db, "BV04", sod="07:00", eod="20:00")
    times = _times(day, offset=0, interval=150)
    assert times == ["07:00", "09:30", "12:00", "14:30", "17:00"]
    assert "19:30" not in times          # inside the last 2h30


def test_a_refresh_exactly_one_interval_before_eod_is_kept(app, db):
    show, day = _day(db, "BV05", sod="07:00", eod="19:30")
    assert _times(day, offset=0, interval=150)[-1] == "17:00"


def test_a_short_day_still_gets_its_set(app, db):
    """The set is the service starting, not a top-up nobody will drink."""
    show, day = _day(db, "BV06", sod="07:00", eod="08:00")
    times = _times(day, offset=0, interval=150)
    assert times == ["07:00"]


# ── refusing to guess ───────────────────────────────────────────────────────

def test_no_sod_means_no_anchor_and_a_stated_reason(app, db):
    show, day = _day(db, "BV07", sod=None)
    plan = plan_for_day(day)
    assert plan["points"] == []
    assert plan["reason"] == NO_SOD


def test_no_eod_means_no_refreshes_and_a_stated_reason(app, db):
    """An empty list with no reason reads as 'no beverages needed'."""
    show, day = _day(db, "BV08", eod=None)
    plan = plan_for_day(day)
    assert plan["points"] == []
    assert plan["reason"] == NO_EOD


def test_a_day_that_ends_before_the_set_says_so(app, db):
    show, day = _day(db, "BV09", sod="07:00", eod="06:00")
    assert plan_for_day(day, offset=0)["reason"] == SETUP_AFTER_EOD


# ── headcounts ──────────────────────────────────────────────────────────────

def test_the_set_counts_the_crew_arriving_before_the_first_refresh(app, db):
    show, day = _day(db, "BV10", sod="07:00", eod="20:00",
                     calls=[("07:00", 10, 12.0), ("10:00", 4, 8.0)])
    # Set at 07:00, first refresh 09:30 — the 10:00 crew is not in yet.
    assert plan_for_day(day, offset=0)["points"][0]["headcount"] == 10


def test_each_refresh_counts_who_is_on_site_then(app, db):
    show, day = _day(db, "BV11", sod="07:00", eod="20:00",
                     calls=[("07:00", 10, 13.0), ("09:30", 4, 5.0)])
    by_time = {p["time"]: p["headcount"]
               for p in plan_for_day(day, offset=0)["points"]}
    assert by_time["12:00"] == 14        # both crews on site
    assert by_time["14:30"] == 10        # the 09:30 crew went home at 14:30


def test_missing_hours_over_counts_and_says_so(app, db):
    show, day = _day(db, "BV12", calls=[("07:00", 10, None)])
    plan = plan_for_day(day, offset=0)
    assert plan["estimated"] is True
    assert plan["points"][-1]["headcount"] == 10


def test_crew_rows_off_a_non_crew_start_are_not_counted_again(app, db):
    from models import CrewRow, ScheduleActivity
    show, day = _day(db, "BV13", calls=[("07:00", 10, 12.0)])
    load_in = ScheduleActivity(day_id=day.id, time="08:00",
                               description="LOAD IN / SETUP RIGGING")
    db.session.add(load_in); db.session.flush()
    db.session.add(CrewRow(activity_id=load_in.id, qty=10, hours=10.0))
    db.session.commit()
    windows, _est = crew_windows_for_day(day)
    assert sum(qty for _s, _e, qty in windows) == 10


# ── it is a service on the schedule, and its own kind of thing ──────────────

def _standing(db, show, day, name="All Day Beverages", offset=-30, interval=150):
    from models import MealService, MealServiceLocation
    svc = MealService(show_id=show.id, schedule_day_id=day.id, name=name,
                      kind="beverages", is_recurring=True,
                      beverage_offset_minutes=offset,
                      beverage_interval_minutes=interval)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       location_name="Backstage", sort_order=0))
    db.session.commit()
    return svc


def test_a_service_uses_its_own_offset_and_interval(app, db):
    show, day = _day(db, "BV14", sod="07:00", eod="20:00")
    svc = _standing(db, show, day, offset=0, interval=120)
    assert [p["time"] for p in svc.beverage_plan["points"]][:3] == \
        ["07:00", "09:00", "11:00"]


def test_the_touchpoints_are_placeable_schedule_rows(app, db):
    show, day = _day(db, "BV15", sod="07:00", eod="20:00")
    svc = _standing(db, show, day, offset=0)
    rows = overlay_for_day(day, [svc])
    assert rows
    assert all("sort_min" in r for r in rows)
    assert rows[0]["label"] == "Beverage Service Set"
    assert rows[1]["label"] == "Beverage Service Refresh"


def test_an_ordinary_meal_service_produces_no_touchpoints(app, db):
    from models import MealService
    show, day = _day(db, "BV16")
    svc = MealService(show_id=show.id, schedule_day_id=day.id, name="Lunch",
                      kind="lunch")
    db.session.add(svc); db.session.commit()
    assert overlay_for_day(day, [svc]) == []
    assert svc.beverage_plan is None


def test_the_refreshes_appear_on_the_daily_schedule(app, client, db):
    """Jason wanted them as events on the schedule, not only on the F&B tab."""
    show, day = _day(db, "BV17", sod="07:00", eod="20:00")
    _standing(db, show, day, offset=0)
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "Beverage Service Refresh" in html
    assert "Beverage Service Set" in html


def test_they_move_when_the_day_does(app, client, db):
    """Computed on every read — the reason they are not stored rows."""
    show, day = _day(db, "BV18", sod="07:00", eod="20:00")
    svc = _standing(db, show, day, offset=0)
    assert svc.beverage_plan["points"][0]["time"] == "07:00"
    day.sod = "09:00"
    db.session.commit()
    assert svc.beverage_plan["points"][0]["time"] == "09:00"


def test_creating_one_stores_the_chosen_offset_and_interval(app, client, db):
    from models import MealService
    show, day = _day(db, "BV19", sod="07:00", eod="20:00")
    client.post("/shows/%d/oss/fb/standing/add" % show.id,
                data={"schedule_day_id": str(day.id),
                      "beverage_offset_minutes": "0",
                      "beverage_interval_minutes": "120"})
    svc = MealService.query.filter_by(show_id=show.id).one()
    assert svc.beverage_offset_minutes == 0
    assert svc.beverage_interval_minutes == 120
    assert svc.is_standing is True


# ── crew breaks are never fed by a beverage service ─────────────────────────

def test_the_backfill_does_not_link_a_break_to_a_beverage_service(app, db):
    """It classifies such a break Not Provided — correctly — but used to write
    the service in anyway, pointing thirty MCDC26 breaks at one service and
    breaking the 1:1 the model relies on."""
    import break_backfill
    from models import ScheduleActivity, CrewBreak
    show, day = _day(db, "BV20", sod="07:00", eod="20:00")
    svc = _standing(db, show, day, name="Beverage Break")
    act = ScheduleActivity(day_id=day.id, time="09:30",
                           description="COFFEE BREAK — 07:00 CREW")
    db.session.add(act); db.session.flush()
    svc.activity_id = act.id
    db.session.commit()

    break_backfill.apply(show)
    cb = CrewBreak.query.filter_by(show_id=show.id).one()
    assert cb.catered == "no"            # a beverage service is not a meal
    assert cb.meal_service_id is None    # and it does not feed the break


def test_a_beverage_service_can_never_be_linked_to_a_break(app, db):
    import break_linking
    from models import ScheduleActivity, CrewBreak
    show, day = _day(db, "BV21")
    svc = _standing(db, show, day)
    act = ScheduleActivity(day_id=day.id, time="12:00", description="LUNCH")
    db.session.add(act); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, label="LUNCH",
                   duration_minutes=60)
    db.session.add(cb); db.session.commit()
    ok, msg = break_linking.link(cb, svc)
    assert ok is False
    assert "standing service" in msg
