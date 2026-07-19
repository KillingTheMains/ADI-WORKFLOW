"""#32 — auto-generate days from phase ranges, with overlapping-phase memberships."""
import datetime as dt


def _setup(db):
    from models import Show, ProductionPhase
    show = Show(name="Gen Show", code="G26")
    db.session.add(show); db.session.flush()
    # Lighting Prep Jul 1–3, Video Prep Jul 2–4 (overlap on Jul 2–3)
    lp = ProductionPhase(show_id=show.id, name="Lighting Prep", phase_type="Prep",
                         start_date=dt.date(2026, 7, 1), end_date=dt.date(2026, 7, 3))
    vp = ProductionPhase(show_id=show.id, name="Video Prep", phase_type="Prep",
                         start_date=dt.date(2026, 7, 2), end_date=dt.date(2026, 7, 4))
    db.session.add_all([lp, vp]); db.session.commit()
    return show, lp, vp


def test_generate_days_and_overlapping_memberships(app, client, db):
    from models import ScheduleDay
    show, lp, vp = _setup(db)
    client.post("/shows/%d/schedule/generate-days" % show.id, data={})
    days = ScheduleDay.query.filter_by(show_id=show.id).order_by(ScheduleDay.date).all()
    assert [d.date for d in days] == [dt.date(2026, 7, d) for d in (1, 2, 3, 4)]

    # Jul 2 belongs to BOTH phases — Lighting Prep Day 2 AND Video Prep Day 1
    jul2 = next(d for d in days if d.date == dt.date(2026, 7, 2))
    assert "Lighting Prep D2" in jul2.phase_labels
    assert "Video Prep D1" in jul2.phase_labels

    # Jul 1 is only Lighting Prep Day 1
    jul1 = next(d for d in days if d.date == dt.date(2026, 7, 1))
    assert jul1.phase_labels == ["Lighting Prep D1"]


def test_generate_is_non_destructive(app, client, db):
    from models import ScheduleDay, DayPhase
    show, lp, vp = _setup(db)
    client.post("/shows/%d/schedule/generate-days" % show.id, data={})
    days_before = ScheduleDay.query.filter_by(show_id=show.id).count()
    memberships_before = DayPhase.query.count()
    # re-run — must add nothing (idempotent)
    client.post("/shows/%d/schedule/generate-days" % show.id, data={})
    assert ScheduleDay.query.filter_by(show_id=show.id).count() == days_before
    assert DayPhase.query.count() == memberships_before
