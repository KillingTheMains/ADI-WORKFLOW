"""Derived meal headcounts (2026-08-11, breaks step 4).

The bug being closed: a headcount typed into MealServiceLocation by hand does
not move when the crew does, so F&B is told a number that was true when
somebody typed it and is wrong by the time the food is cooked.
"""
import datetime as dt


def _show_with_call(db, code, crew=(("Ollie", None), ("Sam", None))):
    """A day, a crew call, and `crew` rows on it. Each entry is
    (name_override, qty) — qty only matters for unnamed slots."""
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow)
    show = Show(name="Derive", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="22:00")
    db.session.add(day); db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START")
    db.session.add(call); db.session.flush()
    for i, (name, qty) in enumerate(crew):
        db.session.add(CrewRow(activity_id=call.id, sort_order=i,
                               name_override=name, qty=qty or 1))
    db.session.commit()
    return show, day, call


def _break_with_service(db, show, day, call, label="LUNCH"):
    from models import (CrewBreak, MealService, MealServiceLocation,
                        ScheduleActivity)
    act = ScheduleActivity(day_id=day.id, time="12:00",
                           description=f"{label} BREAK")
    db.session.add(act); db.session.flush()
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name=label.title(), kind="lunch")
    db.session.add(svc); db.session.flush()
    loc = MealServiceLocation(meal_service_id=svc.id, location_name="Backstage",
                              start_time="12:00", sort_order=0)
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   offset_minutes=300, duration_minutes=60, label=label,
                   catered="yes", meal_service_id=svc.id)
    db.session.add_all([loc, cb]); db.session.commit()
    return cb, svc, loc


# ── the count itself ────────────────────────────────────────────────────────

def test_a_call_counts_named_people_once_and_slots_by_qty(app, db):
    show, day, call = _show_with_call(
        db, "DH01", crew=[("Ollie", 1), (None, 4), ("Sam", 1)])
    # 2 named + a 4-strong unnamed slot
    assert call.crew_headcount == 6


def test_one_person_on_two_rows_is_still_one_mouth(app, db):
    """A rigger who also runs a follow spot eats once."""
    from models import CrewMember, CrewRow
    show, day, call = _show_with_call(db, "DH02", crew=[(None, 3)])
    person = CrewMember(first_name="Ollie", last_name="M")
    db.session.add(person); db.session.flush()
    db.session.add_all([
        CrewRow(activity_id=call.id, crew_member_id=person.id, sort_order=8),
        CrewRow(activity_id=call.id, crew_member_id=person.id, sort_order=9),
    ])
    db.session.commit()
    assert call.crew_headcount == 4          # 3 slots + one person, once


def test_section_headers_are_not_people(app, db):
    from models import CrewRow
    show, day, call = _show_with_call(db, "DH03", crew=[(None, 5)])
    db.session.add(CrewRow(activity_id=call.id, is_group_header=True,
                           group_label="ENCORE", sort_order=7, qty=1))
    db.session.commit()
    assert call.crew_headcount == 5


def test_a_break_reads_its_headcount_off_its_crew_call(app, db):
    show, day, call = _show_with_call(db, "DH04", crew=[(None, 11)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    assert cb.derived_headcount == 11
    assert svc.derived_headcount == 11
    assert loc.effective_headcount == 11
    assert svc.total_headcount == 11


def test_the_count_follows_the_crew(app, db):
    """The whole point. Add crew, and F&B is told about them."""
    from models import CrewRow
    show, day, call = _show_with_call(db, "DH05", crew=[(None, 11)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    assert svc.total_headcount == 11
    db.session.add(CrewRow(activity_id=call.id, sort_order=99, qty=4))
    db.session.commit()
    assert svc.total_headcount == 15


def test_no_crew_call_derives_nothing_rather_than_zero(app, db):
    """Zero would tell a caterer not to come. Unknown must read as unknown."""
    from models import CrewBreak, ScheduleActivity
    show, day, call = _show_with_call(db, "DH06", crew=[(None, 6)])
    act = ScheduleActivity(day_id=day.id, time="12:00", description="LUNCH")
    db.session.add(act); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=None,
                   label="LUNCH", duration_minutes=60)
    db.session.add(cb); db.session.commit()
    assert cb.derived_headcount is None


def test_a_service_with_no_break_derives_nothing(app, db):
    from models import MealService, MealServiceLocation
    show, day, call = _show_with_call(db, "DH07", crew=[(None, 6)])
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="Client Lunch", kind="lunch")
    db.session.add(svc); db.session.flush()
    loc = MealServiceLocation(meal_service_id=svc.id, sort_order=0)
    db.session.add(loc); db.session.commit()
    assert svc.derived_headcount is None
    assert loc.effective_headcount is None
    assert svc.total_headcount == 0


# ── overrides ───────────────────────────────────────────────────────────────

def test_a_typed_figure_wins_and_is_marked_as_typed(app, db):
    show, day, call = _show_with_call(db, "DH08", crew=[(None, 11)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    loc.headcount = 14
    db.session.commit()
    assert loc.effective_headcount == 14
    assert loc.is_overridden is True
    assert svc.headcount_is_derived is False
    # The derived figure is still visible, so the disagreement can be seen.
    assert loc.derived_headcount == 11


def test_clearing_the_box_hands_the_number_back_to_the_crew(app, client, db):
    """The revert. Blank must mean 'follow the crew', not 'nobody is eating'."""
    show, day, call = _show_with_call(db, "DH09", crew=[(None, 11)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    client.post("/shows/%d/oss/fb/location/%d/edit" % (show.id, loc.id),
                data={"headcount": "14", "location_name": "Backstage"})
    assert loc.effective_headcount == 14
    client.post("/shows/%d/oss/fb/location/%d/edit" % (show.id, loc.id),
                data={"headcount": "", "location_name": "Backstage"})
    assert loc.is_overridden is False
    assert loc.effective_headcount == 11


def test_typed_locations_take_their_share_off_the_top(app, db):
    from models import MealServiceLocation
    show, day, call = _show_with_call(db, "DH10", crew=[(None, 20)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    loc.headcount = 12
    second = MealServiceLocation(meal_service_id=svc.id, location_name="FOH",
                                 sort_order=10)
    db.session.add(second); db.session.commit()
    assert second.effective_headcount == 8       # the balance
    assert svc.total_headcount == 20


def test_a_third_location_does_not_double_count_the_balance(app, db):
    from models import MealServiceLocation
    show, day, call = _show_with_call(db, "DH11", crew=[(None, 20)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    db.session.add_all([
        MealServiceLocation(meal_service_id=svc.id, location_name="FOH",
                            sort_order=10),
        MealServiceLocation(meal_service_id=svc.id, location_name="Dock",
                            sort_order=20),
    ])
    db.session.commit()
    assert svc.total_headcount == 20


# ── marking a break provided ────────────────────────────────────────────────

def _edit(client, show, day, cb, **data):
    return client.post("/shows/%d/schedule/%d/breaks/%d/edit"
                       % (show.id, day.id, cb.id), data=data)


def _bare_break(db, show, day, call, label="LUNCH"):
    from models import CrewBreak, ScheduleActivity
    act = ScheduleActivity(day_id=day.id, time="12:00",
                           description=f"{label} BREAK")
    db.session.add(act); db.session.flush()
    cb = CrewBreak(show_id=show.id, activity_id=act.id, crew_call_id=call.id,
                   offset_minutes=300, duration_minutes=60, label=label)
    db.session.add(cb); db.session.commit()
    return cb


def test_marking_a_break_provided_creates_the_service(app, client, db):
    """Otherwise 'provided' changes a dropdown and F&B never hears about it."""
    show, day, call = _show_with_call(db, "DH12", crew=[(None, 11)])
    cb = _bare_break(db, show, day, call)
    _edit(client, show, day, cb, catered="yes")
    assert cb.meal_service_id is not None
    svc = cb.meal_service
    assert svc.name == "Lunch"
    assert svc.kind == "lunch"
    assert svc.schedule_day_id == day.id
    # No number typed anywhere: it follows the crew from the start.
    assert svc.headcount_is_derived is True
    assert svc.total_headcount == 11


def test_the_new_service_carries_the_break_window(app, client, db):
    show, day, call = _show_with_call(db, "DH13", crew=[(None, 11)])
    cb = _bare_break(db, show, day, call)
    _edit(client, show, day, cb, catered="yes")
    loc = cb.meal_service.locations[0]
    assert loc.start_time == "12:00"
    assert loc.end_time == "13:00"       # 60-minute break


def test_marking_it_provided_twice_does_not_make_two_services(app, client, db):
    from models import MealService
    show, day, call = _show_with_call(db, "DH14", crew=[(None, 11)])
    cb = _bare_break(db, show, day, call)
    _edit(client, show, day, cb, catered="yes")
    _edit(client, show, day, cb, catered="yes", label="LUNCH")
    assert MealService.query.filter_by(show_id=show.id).count() == 1


def test_unlinking_a_service_is_not_undone_by_a_replacement(app, client, db):
    """Clearing the dropdown is a deliberate act; handing back a fresh service
    would make it impossible to do."""
    from models import MealService
    show, day, call = _show_with_call(db, "DH15", crew=[(None, 11)])
    cb = _bare_break(db, show, day, call)
    _edit(client, show, day, cb, catered="yes")
    _edit(client, show, day, cb, catered="yes", meal_service_id="")
    assert cb.meal_service_id is None
    assert MealService.query.filter_by(show_id=show.id).count() == 1


def test_not_provided_unlinks_but_keeps_the_service(app, client, db):
    """A dropdown change must not destroy work F&B has done on a service."""
    from models import MealService
    show, day, call = _show_with_call(db, "DH16", crew=[(None, 11)])
    cb = _bare_break(db, show, day, call)
    _edit(client, show, day, cb, catered="yes")
    svc_id = cb.meal_service_id
    _edit(client, show, day, cb, catered="no", meal_service_id=str(svc_id))
    assert cb.catered == "no"
    assert cb.meal_service_id is None
    assert MealService.query.get(svc_id) is not None


def test_an_unconfirmed_break_with_a_link_reads_as_provided(app, client, db):
    show, day, call = _show_with_call(db, "DH17", crew=[(None, 11)])
    cb = _bare_break(db, show, day, call)
    _edit(client, show, day, cb, catered="yes")
    svc_id = cb.meal_service_id
    _edit(client, show, day, cb, catered="unconfirmed",
          meal_service_id=str(svc_id))
    assert cb.catered == "yes"


# ── the number reaches the surfaces that matter ─────────────────────────────

def test_the_master_export_carries_the_derived_count(app, db):
    """A stale number in an export is a number somebody cooks to."""
    from oss_export import build_master_items
    from models import CrewRow
    show, day, call = _show_with_call(db, "DH18", crew=[(None, 11)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    db.session.add(CrewRow(activity_id=call.id, sort_order=99, qty=4))
    db.session.commit()
    items, _hardcoded = build_master_items(show, [], [svc])
    fb = [i for i in items if i.get("dept") == "F&B"]
    assert fb, "the meal service should reach the master timeline"
    assert any(i.get("count") == 15 for i in fb)


def test_the_day_page_shows_what_fb_will_be_told(app, client, db):
    show, day, call = _show_with_call(db, "DH19", crew=[(None, 11)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert "11 crew" in html


def test_the_fb_tab_offers_the_derived_figure_as_a_placeholder(app, client, db):
    """Blank box, greyed crew figure behind it — that is what makes clearing
    the box an obvious way back."""
    show, day, call = _show_with_call(db, "DH20", crew=[(None, 11)])
    cb, svc, loc = _break_with_service(db, show, day, call)
    html = client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)
    assert 'placeholder="11"' in html
    assert "from crew" in html


# ── one service per crew group ──────────────────────────────────────────────

def test_a_service_cannot_be_fed_to_two_breaks(app, client, db):
    """Sharing one service across two crew groups puts food out for three
    hours, and gives the service two crew calls to derive from."""
    from models import ScheduleActivity
    show, day, call = _show_with_call(db, "DH21", crew=[(None, 8)])
    second_call = ScheduleActivity(day_id=day.id, time="09:00",
                                   description="CREW START")
    db.session.add(second_call); db.session.commit()
    first = _bare_break(db, show, day, call, label="LUNCH")
    _edit(client, show, day, first, catered="yes")
    svc_id = first.meal_service_id

    second = _bare_break(db, show, day, second_call, label="LUNCH 2")
    _edit(client, show, day, second, meal_service_id=str(svc_id))
    assert second.meal_service_id is None
    assert first.meal_service_id == svc_id


def test_the_day_page_no_longer_offers_a_service_picker(app, client, db):
    """The picker was retired on 2026-08-11 — one question, one control, and
    the service follows from the answer. The 1:1 rule is now enforced only in
    edit_break, which is what test_a_service_cannot_be_fed_to_two_breaks
    covers. This test exists so that guard is never mistaken for dead code."""
    from models import ScheduleActivity
    show, day, call = _show_with_call(db, "DH22", crew=[(None, 8)])
    second_call = ScheduleActivity(day_id=day.id, time="09:00",
                                   description="CREW START")
    db.session.add(second_call); db.session.commit()
    first = _bare_break(db, show, day, call, label="LUNCH")
    _edit(client, show, day, first, catered="yes")
    _bare_break(db, show, day, second_call, label="LUNCH 2")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    assert 'name="meal_service_id"' not in html
