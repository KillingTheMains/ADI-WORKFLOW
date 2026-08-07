"""The F&B tab must surface ALL F&B events — in particular legacy (old-format)
SubScheduleEntry type='F&B' rows that the tab (which reads only meal services)
would otherwise never show. Covers shows whose v2 data-migration never reached
this database."""
import datetime as dt


def test_fb_tab_surfaces_and_converts_legacy_entries(app, client, db):
    from models import Show, ScheduleDay, SubScheduleEntry, MealService
    show = Show(name="FB Fix", code="FBX")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 8, 3))
    db.session.add(day); db.session.flush()
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    type="F&B", activity="Crew Lunch", time="12:00",
                                    count=30, sort_order=1))
    db.session.commit()

    # before: the tab flags the legacy item (it wasn't showing as a meal service)
    body = client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)
    assert "in the old format" in body

    # one-click convert
    client.post("/shows/%d/oss/fb/convert-legacy" % show.id)
    assert SubScheduleEntry.query.filter_by(show_id=show.id, type="F&B").count() == 0
    svc = MealService.query.filter_by(show_id=show.id, name="Crew Lunch").first()
    assert svc is not None
    assert svc.schedule_day_id == day.id
    assert svc.kind == "lunch"                      # kind guessed from the name
    assert len(svc.locations) == 1
    assert svc.locations[0].headcount == 30         # count carried over

    # after: banner gone, event now shows as a meal service
    body2 = client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)
    assert "in the old format" not in body2
    assert "Crew Lunch" in body2


def test_fb_convert_noop_when_nothing_legacy(app, client, db):
    from models import Show
    show = Show(name="Clean FB", code="CFB")
    db.session.add(show); db.session.commit()
    r = client.post("/shows/%d/oss/fb/convert-legacy" % show.id, follow_redirects=True)
    assert r.status_code == 200
    body = client.get("/shows/%d/oss?tab=F%%26B" % show.id).get_data(as_text=True)
    assert "in the old format" not in body


def test_add_entry_rejects_fb_type(app, client, db):
    """The generic OSS entry-add must never create a legacy F&B entry."""
    from models import Show, ScheduleDay, SubScheduleEntry
    import datetime as dt
    show = Show(name="Guard1", code="G1")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 8, 5))
    db.session.add(day); db.session.commit()
    client.post("/shows/%d/oss/add" % show.id,
                data={"type": "F&B", "activity": "Sneaky Lunch",
                      "schedule_day_id": day.id},
                follow_redirects=True)
    assert SubScheduleEntry.query.filter_by(show_id=show.id, type="F&B").count() == 0


def test_clone_day_skips_legacy_fb(app, client, db):
    """Cloning a day must not propagate legacy F&B entries (real meals clone via
    the meal-service path)."""
    from models import Show, ScheduleDay, SubScheduleEntry
    import datetime as dt
    show = Show(name="Guard2", code="G2")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 8, 6))
    db.session.add(day); db.session.flush()
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    type="F&B", activity="Old Lunch"))
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    type="Dock", activity="Truck 1"))
    db.session.commit()
    client.post("/shows/%d/schedule/%d/clone" % (show.id, day.id))
    new_day = (ScheduleDay.query.filter_by(show_id=show.id)
               .order_by(ScheduleDay.id.desc()).first())
    entries = SubScheduleEntry.query.filter_by(schedule_day_id=new_day.id).all()
    assert {e.type for e in entries} == {"Dock"}   # Dock cloned, F&B skipped
