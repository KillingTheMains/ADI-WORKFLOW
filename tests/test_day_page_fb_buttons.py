"""Food is added on the day it happens.

Jason, 2026-08-13: "The OSS and all the tabs are purely intended to be a
summary of things that exist on the daily schedules in the schedule builder.
They are not their own schedules themselves." ... "Maybe we move to a system
that adds a meal service via a button on the daily schedule builder next to
the 'Add crew call' button ... Also add a 'add all day beverage service'
button and an 'Add Other Event' button all up there by the 'create crew call'
button. That last one replaces the current 'add activity' button."

The load-bearing claim in this file is NOT that the day page has two new
buttons — it is that those buttons reach the SAME routes the F&B tab reaches.
A second create path would be a second set of defaults, and the F&B tab would
start disagreeing with the day page about what a meal service is. That is the
shape of every bug this session has had. So the tests assert the endpoints,
and that both callers of those endpoints still land where they came from.
"""
import datetime as dt
import re

import pytest


@pytest.fixture
def fb_day(db):
    from models import ScheduleActivity, ScheduleDay, Show
    show = Show(name="Feeding", code="FED26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 3),
                      sod="7:00 AM", eod="11:00 PM")
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="8:00 AM",
                           description="CREW START", sort_order=10)
    db.session.add(act)
    db.session.commit()
    return show, day, act


def _url(show, day):
    return "/shows/%d/schedule/%d" % (show.id, day.id)


def _page(client, show, day, strip_comments=False):
    r = client.get(_url(show, day))
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    if strip_comments:
        # Comments are served, and the ones on this page quote the very words
        # a "did it go?" assertion searches for. Three tests this session
        # passed for that reason and were wrong.
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        body = re.sub(r"\{#.*?#\}", "", body, flags=re.S)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return body


# ── The buttons exist, and say what Jason asked them to say ──────────────

def test_the_day_offers_all_four_doors(app, client, db, fb_day):
    show, day, act = fb_day
    body = _page(client, show, day, strip_comments=True)
    for label in ("👥 Create Crew Call", "🍽 Add Meal Service",
                  "🥤 All-Day Beverages", "+ Add Other Event"):
        assert label in body, label


def test_add_activity_was_renamed_not_duplicated(app, client, db, fb_day):
    """'That last one replaces the current add activity button.' Replaces."""
    show, day, act = fb_day
    body = _page(client, show, day, strip_comments=True)
    assert "+ Add Activity" not in body
    assert body.count("+ Add Other Event") == 1
    # ...and it still opens the same panel, so nothing was lost in the rename.
    assert 'data-bs-target="#add-activity-panel"' in body
    assert 'id="add-activity-panel"' in body


# ── They post to the OSS routes, not to new ones ─────────────────────────

def test_the_meal_button_posts_to_the_f_and_b_tabs_own_route(app, client, db, fb_day):
    from flask import url_for
    show, day, act = fb_day
    body = _page(client, show, day)
    with app.test_request_context():
        assert url_for("oss.fb_service_add", show_id=show.id) in body


def test_the_beverage_button_posts_to_the_f_and_b_tabs_own_route(app, client, db, fb_day):
    from flask import url_for
    show, day, act = fb_day
    body = _page(client, show, day)
    with app.test_request_context():
        assert url_for("oss.fb_standing_add", show_id=show.id) in body


def test_the_day_is_prefilled_so_the_user_never_picks_it(app, client, db, fb_day):
    show, day, act = fb_day
    body = _page(client, show, day)
    assert body.count('name="schedule_day_id" value="%d"' % day.id) >= 2


def test_the_meal_modal_offers_the_real_kind_list(app, client, db, fb_day):
    """Not a retyped copy. A kind added to models must appear here."""
    from models import MEAL_KINDS
    show, day, act = fb_day
    body = _page(client, show, day)
    start = body.index('id="addMealServiceModal"')
    modal = body[start:body.index("</div>", body.index("modal-footer", start))]
    for k in MEAL_KINDS:
        assert '<option value="%s">' % k in modal, k


def test_a_meal_can_be_tied_to_an_event_on_this_day(app, client, db, fb_day):
    show, day, act = fb_day
    body = _page(client, show, day)
    start = body.index('id="addMealServiceModal"')
    modal = body[start:start + 6000]
    assert 'name="activity_id"' in modal
    assert '<option value="%d">' % act.id in modal


# ── Where a post from the day page returns to ────────────────────────────

def test_adding_a_meal_from_the_day_returns_to_the_day(app, client, db, fb_day):
    """The complaint this whole change answers is being taken somewhere you
    did not ask to go. Landing on the OSS hub would be the same bug."""
    show, day, act = fb_day
    r = client.post("/shows/%d/oss/fb/service/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "Crew Lunch",
        "kind": "lunch", "next": _url(show, day)})
    assert r.status_code == 302
    assert r.headers["Location"].endswith(_url(show, day))


def test_adding_beverages_from_the_day_returns_to_the_day(app, client, db, fb_day):
    show, day, act = fb_day
    r = client.post("/shows/%d/oss/fb/standing/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "All Day Beverages",
        "next": _url(show, day)})
    assert r.status_code == 302
    assert r.headers["Location"].endswith(_url(show, day))


def test_the_f_and_b_tab_still_returns_to_the_f_and_b_tab(app, client, db, fb_day):
    """No ?next=, so nothing changed for the caller that was there first."""
    show, day, act = fb_day
    r = client.post("/shows/%d/oss/fb/service/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "Crew Lunch", "kind": "lunch"})
    assert r.status_code == 302
    assert "/oss" in r.headers["Location"]
    assert _url(show, day) not in r.headers["Location"]


def test_next_cannot_send_the_user_off_site(app, client, db, fb_day):
    """Same cheap guard _redirect_after_change uses: a next= that is not a
    site-relative path is ignored rather than followed."""
    show, day, act = fb_day
    r = client.post("/shows/%d/oss/fb/service/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "Crew Lunch",
        "kind": "lunch", "next": "http://example.com/evil"})
    assert r.status_code == 302
    assert "example.com" not in r.headers["Location"]


def test_a_meal_added_from_the_day_lands_on_that_day(app, client, db, fb_day):
    """The redirect is not the point; the row is."""
    from models import MealService
    show, day, act = fb_day
    client.post("/shows/%d/oss/fb/service/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "Crew Lunch",
        "kind": "lunch", "location_name": "Backstage", "start_time": "12:00",
        "next": _url(show, day)})
    svcs = MealService.query.filter_by(schedule_day_id=day.id).all()
    assert [s.name for s in svcs] == ["Crew Lunch"]
    assert [l.location_name for l in svcs[0].locations] == ["Backstage"]


# ── One beverage table per day, said before you click ────────────────────

def test_the_beverage_button_goes_away_once_the_day_has_one(app, client, db, fb_day):
    """The route already refuses a second. A button that is refused is a
    button that should not have been offered."""
    show, day, act = fb_day
    client.post("/shows/%d/oss/fb/standing/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "All Day Beverages"})
    body = _page(client, show, day, strip_comments=True)
    assert 'data-bs-target="#addBeverageServiceModal"' not in body
    assert "All Day Beverages — on" in body


def test_the_meal_button_never_goes_away(app, client, db, fb_day):
    """Days have several meals. Only the beverage table is one-per-day."""
    show, day, act = fb_day
    client.post("/shows/%d/oss/fb/service/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "Crew Lunch", "kind": "lunch"})
    body = _page(client, show, day, strip_comments=True)
    assert 'data-bs-target="#addMealServiceModal"' in body


def test_the_hidden_button_matches_the_routes_own_predicate(app, client, db, fb_day):
    """The button hides on `is_standing`; the route refuses on
    `is_beverage_service`. If those two ever disagree the UI offers something
    the server rejects — which is exactly the bug is_standing was changed to
    fix on 2026-08-13. One question, one answer."""
    from breaks import is_beverage_service
    from models import MealService
    show, day, act = fb_day
    client.post("/shows/%d/oss/fb/standing/add" % show.id, data={
        "schedule_day_id": str(day.id), "name": "All Day Beverages"})
    svc = MealService.query.filter_by(schedule_day_id=day.id).one()
    assert svc.is_standing is is_beverage_service(svc) is True


def test_a_legacy_beverage_row_also_hides_the_button(app, client, db, fb_day):
    """MCDC26's beverage services all carry is_recurring=False. The old
    predicate read that column and so never fired; this one reads the row."""
    from models import MealService
    show, day, act = fb_day
    db.session.add(MealService(show_id=show.id, schedule_day_id=day.id,
                               name="All Day Beverages", kind="other",
                               is_recurring=False))
    db.session.commit()
    body = _page(client, show, day, strip_comments=True)
    assert 'data-bs-target="#addBeverageServiceModal"' not in body
