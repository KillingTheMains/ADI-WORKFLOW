"""Stage 2: an activity can say which department it belongs to.

Jason, 2026-08-13: "The OSS and all the tabs are purely intended to be a
summary of things that exist on the daily schedules ... they are not their own
schedules themselves."

They currently are, and ONE absence is why. `ScheduleActivity` had six columns
and none of them could say "I am a Dock event", so the department taxonomy
could only live on `SubScheduleEntry` — which then needed its own day, time,
count and notes to hang it on, and became a second schedule.
`schedule_day_id` NOT NULL against a nullable `activity_id` is that decision
written into the schema.

This stage is deliberately INERT. The columns exist, nothing writes them and
nothing reads them, so it deploys on its own with no behaviour change at all.
Stage 3 turns them on from the day page; stage 4 migrates the entries; stage 5
makes the OSS a view and deletes `oss_export`'s `claimed` de-duplication pass,
which only exists because there is a second source to de-duplicate against.

Measured on production 2026-08-13: 288 activities, 78 already claimed by an
OSS entry or a meal, 210 that would carry no department at all.
"""
import datetime as dt

import pytest


@pytest.fixture
def activity(db):
    from models import ScheduleActivity, ScheduleDay, Show
    show = Show(name="Dept", code="DEP26")
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 8))
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="8:00 AM",
                           description="LOAD IN BEGINS")
    db.session.add(act)
    db.session.commit()
    return act


# ── The columns ──────────────────────────────────────────────────────────

def test_an_ordinary_activity_has_no_department(app, db, activity):
    """NULL is the common case — 210 of 288 on production."""
    assert activity.department is None
    assert activity.count is None
    assert activity.duration_hrs is None


def test_a_department_round_trips(app, db, activity):
    from models import ScheduleActivity
    activity.department = "Dock"
    activity.count = 3
    activity.duration_hrs = 1.5
    db.session.commit()
    db.session.expire_all()

    fresh = ScheduleActivity.query.get(activity.id)
    assert fresh.department == "Dock"
    assert fresh.count == 3
    assert fresh.duration_hrs == 1.5


def test_the_column_holds_the_type_key_not_the_label(app, db, activity):
    """The same vocabulary HardCodedEvent.department already stores, and the
    same one SubScheduleEntry.type stores. Three of the ten differ from what
    users see, and mixing key and label is how one department shows up twice
    on the master and produces two sheets in the export."""
    from models import SUB_SCHEDULE_TYPES
    activity.department = "House LX"
    db.session.commit()
    assert activity.department in SUB_SCHEDULE_TYPES
    assert activity.dept_meta["label"] == "House Lights"


# ── dept_meta ────────────────────────────────────────────────────────────

def test_no_department_means_no_meta(app, db, activity):
    assert activity.dept_meta is None


@pytest.mark.parametrize("key,label", [
    ("Hazer", "Haze"),
    ("House LX", "House Lights"),
    ("HVAC", "HVAC / AC"),
    ("Dock", "Dock"),
])
def test_dept_meta_resolves_the_label(app, db, activity, key, label):
    activity.department = key
    assert activity.dept_meta["label"] == label


def test_dept_meta_matches_the_oss_entry_lookup(app, db, activity):
    """One vocabulary while both models exist. If these ever disagree, the
    unification would be merging two different taxonomies."""
    from models import SUB_SCHEDULE_TYPES, SubScheduleEntry
    for key in SUB_SCHEDULE_TYPES:
        activity.department = key
        entry = SubScheduleEntry(type=key)
        assert activity.dept_meta == entry.meta, key


def test_an_unknown_department_degrades_rather_than_raising(app, db, activity):
    """A department that is not in the list should cost a label, not the day
    page. Same fallback SubScheduleEntry.meta uses."""
    activity.department = "Pyro"
    assert activity.dept_meta["label"] == "Pyro"
    assert activity.dept_meta["sort"] == 99


# ── Stage 2 is inert ─────────────────────────────────────────────────────

def test_the_day_page_renders_the_same_with_a_department_set(app, client, db,
                                                             activity):
    """Nothing reads these yet. This is what makes stage 2 deployable on its
    own: the columns land, and the app does not change."""
    url = "/shows/%d/schedule/%d" % (activity.day.show_id, activity.day_id)
    before = client.get(url).get_data(as_text=True)

    activity.department = "Dock"
    activity.count = 3
    activity.duration_hrs = 1.5
    db.session.commit()

    assert client.get(url).get_data(as_text=True) == before


def test_the_master_export_is_unchanged_by_a_department(app, db, activity):
    from oss_export import build_master_items
    show = activity.day.show
    before, _hc = build_master_items(show, [], [])

    activity.department = "Dock"
    db.session.commit()
    after, _hc2 = build_master_items(show, [], [])

    assert [i["activity"] for i in after] == [i["activity"] for i in before]
    assert [i["dept"] for i in after] == [i["dept"] for i in before]


# ── The migration ────────────────────────────────────────────────────────

def test_the_columns_are_registered_for_existing_databases(app):
    """A fresh database gets them from create_all; production gets them from
    the column-add list, which is idempotent and skipped when present."""
    from migrations import MIGRATIONS
    added = {(t, c) for t, c, _ddl in MIGRATIONS}
    assert ("schedule_activities", "department") in added
    assert ("schedule_activities", "count") in added
    assert ("schedule_activities", "duration_hrs") in added


def test_all_three_are_nullable(app, db, activity):
    """210 of 288 production activities will never have any of them. A NOT
    NULL here would need a back-fill with nothing to back-fill from."""
    from models import ScheduleActivity
    cols = ScheduleActivity.__table__.columns
    for name in ("department", "count", "duration_hrs"):
        assert cols[name].nullable, name
