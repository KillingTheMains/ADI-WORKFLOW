"""
SOD/EOD anchor rows, and the removal of the hand-typed EOD WRAP activity.

The day's end used to be typed twice — once in Day Settings, once as an
activity — and the two drifted: on production 2026-08-12, of 31 EOD WRAP rows
only 14 matched their day's EOD, 9 disagreed, and 8 sat on days with no EOD at
all. The anchors are derived on every read now, so there is one value.
"""
import datetime as dt


def _day(db, sod="07:00", eod="19:00"):
    from models import Show, ScheduleDay
    show = Show(name="Anchor Show", code="ANC26")
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 1),
                      sod=sod, eod=eod)
    db.session.add(day)
    db.session.commit()
    return show, day


def _act(db, day, time, desc):
    from models import ScheduleActivity
    a = ScheduleActivity(day_id=day.id, time=time, description=desc,
                         sort_order=10)
    db.session.add(a)
    db.session.commit()
    return a


def test_both_anchors_are_returned_and_sorted_by_the_clock(app, db):
    from day_anchors import overlay_for_day
    _, day = _day(db, sod="07:00", eod="19:00")
    rows = overlay_for_day(day)
    assert [r["anchor"] for r in rows] == ["sod", "eod"]
    assert [r["sort_min"] for r in rows] == [7 * 60, 19 * 60]
    assert not any(r["unset"] for r in rows)


def test_an_unset_eod_sorts_past_every_clock_time(app, db):
    """So place_in_day finds no activity at or after it and drops it last.

    Jason, 2026-08-12: an unset EOD belongs at the BOTTOM of the day with an
    instruction, not at the top pretending to be midnight.
    """
    from day_anchors import overlay_for_day
    _, day = _day(db, sod="07:00", eod=None)
    eod = [r for r in overlay_for_day(day) if r["anchor"] == "eod"][0]
    assert eod["unset"] is True
    assert eod["sort_min"] > 23 * 60 + 59


def test_an_unset_sod_sorts_to_the_top(app, db):
    from day_anchors import overlay_for_day
    _, day = _day(db, sod=None, eod="19:00")
    sod = [r for r in overlay_for_day(day) if r["anchor"] == "sod"][0]
    assert sod["unset"] is True
    assert sod["sort_min"] == 0


def test_the_day_page_draws_both_anchors(app, client, db):
    show, day = _day(db, sod="07:00", eod="19:00")
    _act(db, day, "12:00", "GENERAL SESSION")
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    assert "START OF DAY" in html
    assert "END OF DAY" in html
    # And it points at the one place they can be changed.
    assert "edit SOD / EOD in Day Settings" in html


def test_an_unset_eod_asks_for_one_instead_of_rendering_blank(app, client, db):
    show, day = _day(db, sod="07:00", eod=None)
    _act(db, day, "12:00", "GENERAL SESSION")
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    assert "Set the EOD time in Day Settings" in html


def test_an_unset_anchor_carries_no_row_time(app, client, db):
    """The general invariant test walks every `data-row-time` top to bottom and
    requires them non-decreasing. An anchor with no time must therefore not
    claim one — it would sort as 00:00 and fail an invariant it has no
    business being part of.
    """
    show, day = _day(db, sod=None, eod=None)
    _act(db, day, "12:00", "GENERAL SESSION")
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    sod_row = html[html.index('data-anchor="sod"') - 200:html.index('data-anchor="sod"')]
    assert "data-row-time" not in sod_row


def test_an_empty_day_still_says_so(app, client, db):
    """Regression: the empty state used to be gated on `extras_after`, which is
    never empty now because the two anchors always land in it.
    """
    show, day = _day(db)
    html = client.get(f"/shows/{show.id}/schedule/{day.id}").get_data(as_text=True)
    assert "No activities yet" in html


# ── The EOD WRAP removal migration ───────────────────────────────────────────

def test_migration_removes_plain_eod_wrap_rows(app, db):
    from migrations import _remove_eod_wrap_activities
    from models import ScheduleActivity
    _, day = _day(db)
    _act(db, day, "19:00", "EOD WRAP")
    _act(db, day, "12:00", "GENERAL SESSION")

    _remove_eod_wrap_activities(db.session)
    db.session.commit()

    left = [a.description for a in
            ScheduleActivity.query.filter_by(day_id=day.id).all()]
    assert left == ["GENERAL SESSION"]


def test_migration_leaves_a_wrap_row_that_carries_crew(app, db):
    """Deleting a crew call because of its description is the worst outcome
    available here, so anything carrying crew is skipped and named.
    """
    from migrations import _remove_eod_wrap_activities
    from models import CrewRow, ScheduleActivity
    _, day = _day(db)
    act = _act(db, day, "19:00", "EOD WRAP")
    db.session.add(CrewRow(activity_id=act.id, position="A1", qty=1,
                           crew_type="Lead Crew", sort_order=10))
    db.session.commit()

    _remove_eod_wrap_activities(db.session)
    db.session.commit()

    assert ScheduleActivity.query.get(act.id) is not None


def test_migration_leaves_a_label_that_only_contains_the_phrase(app, db):
    from migrations import _remove_eod_wrap_activities
    from models import ScheduleActivity
    _, day = _day(db)
    act = _act(db, day, "18:00", "STRIKE COMPLETE / EOD WRAP")

    _remove_eod_wrap_activities(db.session)
    db.session.commit()

    assert ScheduleActivity.query.get(act.id) is not None


def test_no_seed_template_writes_a_wrap_row(app, db):
    """Applying a template must not put the second copy back."""
    import app as app_module
    src = open(app_module.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    body = src.split("def _seed_day_templates")[1].split("\ndef ")[0]
    # The explanatory comment mentions it; no template ENTRY may.
    entries = [ln for ln in body.splitlines() if ln.strip().startswith('("')]
    assert not [ln for ln in entries if "EOD WRAP" in ln]
