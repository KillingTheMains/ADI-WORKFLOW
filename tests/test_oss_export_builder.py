"""
The shared master-timeline builder behind the Master tab, the XLSX and the PDF.

The point of this module is that there is exactly ONE assembly. If an export
rebuilt the timeline itself it would drift from the page — which is how the
master and the F&B tab came to disagree in the first place.
"""
import datetime as dt


def _build(db, when=dt.date(2026, 11, 3)):
    from models import (Show, ScheduleDay, ScheduleActivity, SubScheduleEntry,
                        MealService, MealServiceLocation)
    show = Show(name="Export Show", code="EX26")
    db.session.add(show); db.session.flush()
    d1 = ScheduleDay(show_id=show.id, date=when)
    d2 = ScheduleDay(show_id=show.id, date=when + dt.timedelta(days=1))
    db.session.add_all([d1, d2]); db.session.flush()
    db.session.add(ScheduleActivity(day_id=d1.id, time="08:00",
                                    description="LOAD IN", sort_order=10))
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=d1.id,
                                    type="Dock", time="13:00",
                                    activity="DOCK PUSH", sort_order=0))
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=d2.id,
                                    type="Security", time="09:00",
                                    activity="GUARD ON", sort_order=0))
    svc = MealService(show_id=show.id, schedule_day_id=d1.id,
                      name="Lunch", kind="lunch", sort_order=0)
    db.session.add(svc); db.session.flush()
    db.session.add(MealServiceLocation(meal_service_id=svc.id,
                                       location_name="BOH",
                                       start_time="12:00", sort_order=0))
    db.session.commit()
    return show, d1, d2


def _items(db, show):
    from models import SubScheduleEntry, MealService
    from oss_export import build_master_items
    entries = SubScheduleEntry.query.filter_by(show_id=show.id).all()
    meals = MealService.query.filter_by(show_id=show.id).all()
    items, _hardcoded = build_master_items(show, entries, meals)
    return items


def test_builder_covers_every_source(app, db):
    show, _d1, _d2 = _build(db)
    labels = [i["activity"] for i in _items(db, show)]
    assert "LOAD IN" in labels          # day activity
    assert "DOCK PUSH" in labels        # department OSS entry
    assert "GUARD ON" in labels
    assert any("Lunch" in l for l in labels)   # F&B meal service


def test_builder_returns_chronological_order(app, db):
    show, _d1, _d2 = _build(db)
    items = _items(db, show)
    keys = [(i["day"].date, i["sort_time"]) for i in items]
    assert keys == sorted(keys), "master items are not in day/time order"


def test_group_by_day_keeps_each_day_contiguous(app, db):
    """The exports page-break on day boundaries, so a day must be ONE run."""
    from oss_export import group_by_day
    show, d1, d2 = _build(db)
    groups = group_by_day(_items(db, show))
    assert [day.id for day, _ in groups] == [d1.id, d2.id]
    assert len({day.id for day, _ in groups}) == len(groups)  # no day twice
    for day, rows in groups:
        assert all(r["day_id"] == day.id for r in rows)


def test_group_by_department_orders_by_oss_position(app, db):
    """Schedule and Crew lead; departments follow their SUB_SCHEDULE_META sort."""
    from oss_export import group_by_department
    show, _d1, _d2 = _build(db)
    depts = [d for d, _ in group_by_department(_items(db, show))]
    assert depts[0] == "Schedule"
    assert depts.index("Dock") < depts.index("F&B") < depts.index("Security") \
        or depts.index("Dock") < depts.index("Security")  # Dock sorts first


def test_department_style_survives_black_and_white(app):
    """Every department needs a distinct TEXT label, not just a colour —
    these documents get printed in mono constantly."""
    from oss_export import DEPARTMENT_STYLE, department_style
    shorts = [v["short"] for v in DEPARTMENT_STYLE.values()]
    assert len(shorts) == len(set(shorts)), "duplicate department short labels"
    assert all(s for s in shorts), "a department has no text label"
    assert department_style("Not A Real Dept")["hex"]   # safe fallback


def test_master_tab_renders_from_the_shared_builder(app, client, db):
    """Page and builder must agree — that's the whole point of the module."""
    show, _d1, _d2 = _build(db)
    body = client.get("/shows/%d/oss?tab=master" % show.id).get_data(as_text=True)
    pane = body[:body.index('id="tab-1"')]

    # Every row the builder produces must appear on the rendered master, and
    # in the same relative order the builder put them in.
    labels = [i["activity"] for i in _items(db, show) if i["activity"]]
    positions = []
    for label in labels:
        assert label in pane, f"builder produced {label!r} but the page omits it"
        positions.append(pane.index(label))
    assert positions == sorted(positions), \
        "page renders the builder's rows in a different order"
