"""Standing beverage service (2026-08-11, breaks step 5).

Jason's spec: set up 30 minutes before the first crew call, refresh every
2h30, and NEVER past the day's EOD. A day with no EOD gets no refreshes and a
stated reason — guessing an end to the day would put F&B on site for a shift
nobody scheduled.
"""
import datetime as dt

from beverage_service import (NO_CREW_START, NO_EOD, crew_windows_for_day,
                              plan_for_day)


def _day(db, code, eod="22:00", calls=(("07:00", 10, 8.0),)):
    """A show day with crew starts. Each call is (time, qty, hours)."""
    from models import Show, ScheduleDay, ScheduleActivity, CrewRow
    show = Show(name="Bev", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod=eod)
    db.session.add(day); db.session.flush()
    for i, (time, qty, hours) in enumerate(calls):
        act = ScheduleActivity(day_id=day.id, time=time,
                               description="CREW START", sort_order=i)
        db.session.add(act); db.session.flush()
        db.session.add(CrewRow(activity_id=act.id, qty=qty, hours=hours,
                               sort_order=0))
    db.session.commit()
    return show, day


# ── the shape of the day ────────────────────────────────────────────────────

def test_setup_is_thirty_minutes_before_the_first_crew_call(app, db):
    show, day = _day(db, "BV01", calls=[("07:00", 10, 8.0)])
    plan = plan_for_day(day)
    assert plan["reason"] is None
    assert plan["points"][0]["time"] == "06:30"
    assert plan["points"][0]["kind"] == "setup"


def test_refreshes_run_every_two_and_a_half_hours(app, db):
    show, day = _day(db, "BV02", eod="18:00", calls=[("07:00", 10, 12.0)])
    times = [p["time"] for p in plan_for_day(day)["points"]]
    assert times == ["06:30", "09:00", "11:30", "14:00", "16:30"]


def test_a_refresh_never_lands_past_eod(app, db):
    """The one hard rule. 17:30 would be the next one; the day ends at 17:00."""
    show, day = _day(db, "BV03", eod="17:00", calls=[("07:00", 10, 12.0)])
    times = [p["time"] for p in plan_for_day(day)["points"]]
    assert times[-1] == "16:30"
    assert "17:30" not in times


def test_a_refresh_landing_exactly_on_eod_is_kept(app, db):
    show, day = _day(db, "BV04", eod="16:30", calls=[("07:00", 10, 12.0)])
    times = [p["time"] for p in plan_for_day(day)["points"]]
    assert times[-1] == "16:30"


def test_the_earliest_crew_call_is_the_anchor(app, db):
    """Not the first one entered — the earliest one on the clock."""
    show, day = _day(db, "BV05", calls=[("09:00", 4, 8.0), ("07:00", 10, 8.0)])
    assert plan_for_day(day)["points"][0]["time"] == "06:30"


# ── refusing to guess ───────────────────────────────────────────────────────

def test_no_eod_means_no_refreshes_and_a_stated_reason(app, db):
    """An empty list with no reason reads as 'no beverages needed'."""
    show, day = _day(db, "BV06", eod=None)
    plan = plan_for_day(day)
    assert plan["points"] == []
    assert plan["reason"] == NO_EOD


def test_no_crew_start_means_nothing_to_set_up_ahead_of(app, db):
    show, day = _day(db, "BV07", calls=[])
    plan = plan_for_day(day)
    assert plan["points"] == []
    assert plan["reason"] == NO_CREW_START


def test_an_untimed_crew_start_is_not_an_anchor(app, db):
    from models import ScheduleActivity
    show, day = _day(db, "BV08", calls=[])
    db.session.add(ScheduleActivity(day_id=day.id, time=None,
                                    description="CREW START"))
    db.session.commit()
    assert plan_for_day(day)["reason"] == NO_CREW_START


# ── headcounts ──────────────────────────────────────────────────────────────

def test_setup_counts_the_crew_arriving_before_the_first_refresh(app, db):
    """06:30 setup, first refresh 09:00 — the 07:00 crew counts, 09:00 does not."""
    show, day = _day(db, "BV09", eod="20:00",
                     calls=[("07:00", 10, 12.0), ("09:00", 4, 8.0)])
    plan = plan_for_day(day)
    assert plan["points"][0]["headcount"] == 10


def test_each_refresh_counts_who_is_on_site_then(app, db):
    show, day = _day(db, "BV10", eod="20:00",
                     calls=[("07:00", 10, 13.0), ("09:30", 4, 8.0)])
    by_time = {p["time"]: p["headcount"] for p in plan_for_day(day)["points"]}
    assert by_time["09:00"] == 10          # the 09:30 crew is not in yet
    assert by_time["11:30"] == 14          # both on site
    assert by_time["19:00"] == 10          # the 09:30 crew went home at 17:30


def test_missing_hours_over_counts_and_says_so(app, db):
    """Under-catering because a planner left Hrs blank is the worse failure."""
    show, day = _day(db, "BV11", eod="20:00", calls=[("07:00", 10, None)])
    plan = plan_for_day(day)
    assert plan["estimated"] is True
    assert plan["points"][-1]["headcount"] == 10     # nobody counted off site


def test_hours_that_are_set_are_not_treated_as_an_estimate(app, db):
    show, day = _day(db, "BV12", eod="20:00", calls=[("07:00", 10, 8.0)])
    assert plan_for_day(day)["estimated"] is False


def test_one_person_on_two_rows_of_a_call_is_one_body(app, db):
    from models import CrewMember, CrewRow, ScheduleActivity
    show, day = _day(db, "BV13", eod="20:00", calls=[("07:00", 3, 12.0)])
    person = CrewMember(first_name="Ollie", last_name="M")
    db.session.add(person); db.session.flush()
    act = ScheduleActivity.query.filter_by(day_id=day.id).first()
    db.session.add_all([
        CrewRow(activity_id=act.id, crew_member_id=person.id, hours=12.0,
                sort_order=8),
        CrewRow(activity_id=act.id, crew_member_id=person.id, hours=12.0,
                sort_order=9),
    ])
    db.session.commit()
    windows, _est = crew_windows_for_day(day)
    assert sum(qty for _s, _e, qty in windows) == 4


def test_crew_rows_off_a_non_crew_start_are_not_counted_again(app, db):
    """A rigger on LOAD IN is the same rigger who was called at 07:00."""
    from models import CrewRow, ScheduleActivity
    show, day = _day(db, "BV14", eod="20:00", calls=[("07:00", 10, 12.0)])
    load_in = ScheduleActivity(day_id=day.id, time="08:00",
                               description="LOAD IN / SETUP RIGGING")
    db.session.add(load_in); db.session.flush()
    db.session.add(CrewRow(activity_id=load_in.id, qty=10, hours=10.0))
    db.session.commit()
    windows, _est = crew_windows_for_day(day)
    assert sum(qty for _s, _e, qty in windows) == 10


# ── the service, and the tab ────────────────────────────────────────────────

def _standing(db, show, day, name="All Day Beverages"):
    from models import MealService, MealServiceLocation
    svc = MealService(show_id=show.id, schedule_day_id=day.id, name=name,
                      kind="beverages", is_recurring=True)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       location_name="Backstage", sort_order=0))
    db.session.commit()
    return svc


def test_an_ordinary_service_has_no_beverage_plan(app, db):
    from models import MealService
    show, day = _day(db, "BV15")
    svc = MealService(show_id=show.id, schedule_day_id=day.id, name="Lunch",
                      kind="lunch")
    db.session.add(svc); db.session.commit()
    assert svc.is_standing is False
    assert svc.beverage_plan is None


def test_a_standing_service_carries_the_day_s_plan(app, db):
    show, day = _day(db, "BV16", eod="18:00", calls=[("07:00", 10, 12.0)])
    svc = _standing(db, show, day)
    assert svc.is_standing is True
    assert [p["time"] for p in svc.beverage_plan["points"]][:2] == ["06:30", "09:00"]


def test_the_plan_moves_when_the_crew_call_does(app, db):
    """Computed, never stored — that is the whole point."""
    from models import ScheduleActivity
    show, day = _day(db, "BV17", eod="18:00", calls=[("07:00", 10, 12.0)])
    svc = _standing(db, show, day)
    assert svc.beverage_plan["points"][0]["time"] == "06:30"
    act = ScheduleActivity.query.filter_by(day_id=day.id).first()
    act.time = "08:00"
    db.session.commit()
    assert svc.beverage_plan["points"][0]["time"] == "07:30"


def test_the_touchpoints_render_on_the_fb_tab(app, client, db):
    show, day = _day(db, "BV18", eod="18:00", calls=[("07:00", 10, 12.0)])
    _standing(db, show, day)
    html = client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)
    assert "Setup &amp; refreshes" in html
    assert "06:30" in html
    assert "Refresh" in html


def test_the_tab_says_why_a_day_with_no_eod_has_none(app, client, db):
    show, day = _day(db, "BV19", eod=None, calls=[("07:00", 10, 12.0)])
    _standing(db, show, day)
    html = client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)
    assert "no EOD set" in html


def test_adding_a_standing_service(app, client, db):
    from models import MealService
    show, day = _day(db, "BV20", eod="18:00", calls=[("07:00", 10, 12.0)])
    client.post("/shows/%d/oss/fb/standing/add" % show.id,
                data={"schedule_day_id": str(day.id),
                      "name": "All Day Beverages",
                      "location_name": "Backstage"})
    svc = MealService.query.filter_by(show_id=show.id).one()
    assert svc.is_recurring is True
    assert svc.kind == "beverages"
    assert len(svc.locations) == 1
    # No times typed: they are worked out from the day.
    assert svc.locations[0].start_time is None
    assert svc.beverage_plan["points"][0]["time"] == "06:30"


def test_only_one_standing_service_per_day(app, client, db):
    from models import MealService
    show, day = _day(db, "BV21", eod="18:00", calls=[("07:00", 10, 12.0)])
    for _ in range(2):
        client.post("/shows/%d/oss/fb/standing/add" % show.id,
                    data={"schedule_day_id": str(day.id)})
    assert MealService.query.filter_by(show_id=show.id, is_recurring=True).count() == 1
