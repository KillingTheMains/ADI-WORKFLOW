"""The day page is ONE timeline, sorted by the clock.

Jason, 2026-08-11, on seeing beverage refreshes bunched together:
"Those refreshes need to fall chronologically into the schedule. Right now
they are all grouped together. And for reference, all schedule events need to
be chronologically displayed."

The cause: recurring events, beverage touchpoints and break periods were
placed and rendered as three separate lists, one after another. Each list was
in time order, but everything landing in the same gap between activities came
out grouped by TYPE — a 12:00 lunch drawing after a 15:00 beverage refresh,
because breaks came after beverages in the markup.
"""
import datetime as dt
import re


def _day_with_everything(db, code):
    """A day with a wide gap, so several things land between two activities."""
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow, CrewBreak,
                        MealService, MealServiceLocation)
    show = Show(name="Order", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10),
                      sod="07:00", eod="20:00")
    db.session.add(day); db.session.flush()

    call = ScheduleActivity(day_id=day.id, time="07:00",
                            description="CREW START", sort_order=0)
    db.session.add(call); db.session.flush()
    db.session.add(CrewRow(activity_id=call.id, qty=11, hours=12.0))
    # Nothing between 08:00 and 18:00 — the gap everything has to sort into.
    db.session.add(ScheduleActivity(day_id=day.id, time="18:00",
                                    description="WRAP", sort_order=10))
    # A lunch break at 12:00.
    act = ScheduleActivity(day_id=day.id, time="12:00", description="LUNCH")
    db.session.add(act); db.session.flush()
    db.session.add(CrewBreak(show_id=show.id, activity_id=act.id,
                             crew_call_id=call.id, label="LUNCH",
                             duration_minutes=60))
    # Beverages set 07:00, refreshing every 2h30.
    svc = MealService(show_id=show.id, schedule_day_id=day.id,
                      name="All Day Beverages", kind="beverages",
                      is_recurring=True, beverage_offset_minutes=0,
                      beverage_interval_minutes=150)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id, sort_order=0))
    db.session.commit()
    return show, day


def _rendered_order(client, show, day):
    """The timeline as the page draws it: (kind, time) top to bottom."""
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    rows = []
    for m in re.finditer(
            r'data-act-time="([^"]*)"'                       # activity card
            r'|Beverage Service (?:Set|Refresh)'             # beverage row
            r'|<span style="font-weight:600;letter-spacing:\.02em;">([^<]+)</span>',
            html):
        if m.group(1) is not None:
            rows.append(("act", m.group(1)))
        elif m.group(2) is not None:
            rows.append(("break", m.group(2).strip()))
        else:
            rows.append(("bev", ""))
    return rows, html


def test_a_break_and_a_beverage_refresh_sort_by_the_clock(app, client, db):
    """Beverages set 07:00 then 09:30 / 12:00 / 14:30 / 17:00; lunch at 12:00.
    The lunch must not be pushed below the 14:30 and 17:00 refreshes."""
    show, day = _day_with_everything(db, "TL01")
    rows, html = _rendered_order(client, show, day)
    kinds = [k for k, _ in rows]
    assert "break" in kinds, rows
    lunch = kinds.index("break")
    bevs = [i for i, k in enumerate(kinds) if k == "bev"]
    # At least one refresh is drawn BEFORE the lunch and at least one after —
    # which is only true if the two lists were merged rather than concatenated.
    assert any(i < lunch for i in bevs), rows
    assert any(i > lunch for i in bevs), rows


def test_the_whole_timeline_never_steps_backwards(app, client, db):
    """The general rule, guarded generally: every timed row on the page, top to
    bottom, in non-decreasing clock order. Activities carry data-act-time;
    break and beverage rows carry data-row-time."""
    show, day = _day_with_everything(db, "TL02")
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    times = [m.group(1) or m.group(2) for m in re.finditer(
        r'data-act-time="(\d{2}:\d{2})"|data-row-time="(\d{2}:\d{2})"', html)]
    assert len(times) >= 6, times
    mins = [int(t[:2]) * 60 + int(t[3:]) for t in times]
    assert mins == sorted(mins), f"out of order: {times}"


def test_the_day_still_renders_with_no_extras_at_all(app, client, db):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Bare", code="TL03", uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10))
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="09:00",
                                    description="LOAD IN"))
    db.session.commit()
    r = client.get("/shows/%d/schedule/%d" % (show.id, day.id))
    assert r.status_code == 200
    assert "LOAD IN" in r.get_data(as_text=True)


def test_activities_render_by_the_clock_not_by_sort_order(app, client, db):
    """`ScheduleDay.activities` is ordered by sort_order — insertion or drag
    order — which is not the clock. Jason: "all schedule events need to be
    chronologically displayed"."""
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Order", code="TL04", uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 10, 10))
    db.session.add(day); db.session.flush()
    # Deliberately inverted: the late activity was entered first.
    db.session.add(ScheduleActivity(day_id=day.id, time="18:00",
                                    description="WRAP", sort_order=0))
    db.session.add(ScheduleActivity(day_id=day.id, time="07:00",
                                    description="CREW START", sort_order=10))
    db.session.commit()
    html = client.get("/shows/%d/schedule/%d" % (show.id, day.id)) \
                 .get_data(as_text=True)
    times = re.findall(r'data-act-time="(\d{2}:\d{2})"', html)
    assert times == ["07:00", "18:00"], times
