"""OSS entries that hang off no activity get their own tab, not a department.

Jason, 2026-08-13: "Unlinked entries should be their own tab in the OSS view
and not randomly assigned to 'dock'. It should carry a warning like the little
warning sign next to the F&B header. Then it should list them by day and allow
the user to select the proper category."

On production all ten unlinked entries were tagged Dock, which reads as a Dock
backlog and is not one. The mechanism is two steps:

  1. The "+ OSS" button on an activity had NO placeholder on its department
     select, so the first option — Dock, sort 1 — is what a browser submits
     when nobody touches it. (The day-level and empty-state forms on the same
     page already had a placeholder. This one did not.)
  2. `delete_activity` deliberately keeps OSS entries alive when their
     activity goes, copying its time across and nulling the link.

So: added in a hurry under a department nobody chose, then orphaned by a
delete. Both halves are fixed here — the placeholder, and the tab that
surfaces the result.

The tab's criterion is UNLINKED, not "Dock". An entry with no activity behind
it appears on no day page, which is the OSS acting as a second schedule rather
than summarising the first — the thing the unification exists to end.
"""
import datetime as dt

import pytest


@pytest.fixture
def show_with_strays(db):
    """Two days, two activities each, five unlinked entries all wearing a
    department nobody chose, and one properly linked entry."""
    from models import ScheduleActivity, ScheduleDay, Show, SubScheduleEntry
    show = Show(name="Strays", code="STR26")
    db.session.add(show)
    db.session.flush()
    days = []
    for n in range(2):
        d = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8 + n),
                        sod="7:00 AM", eod="11:00 PM")
        db.session.add(d)
        db.session.flush()
        for t, desc in (("8:00 AM", "CREW START"), ("1:00 PM", "LOAD IN BEGINS")):
            db.session.add(ScheduleActivity(day_id=d.id, time=t, description=desc))
        days.append(d)
    db.session.flush()

    for day, time, label in (
            (days[0], "7:00 AM", "Truck 1 arrives"),
            (days[0], "10:30 AM", "Truck 2 arrives"),
            (days[0], "4:00 PM", "House lights to 50%"),
            (days[1], "6:30 AM", "Unlock stage door"),
            (days[1], "9:00 PM", "Overnight security on")):
        db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                        type="Dock", time=time, activity=label))
    act = ScheduleActivity.query.filter_by(day_id=days[0].id).first()
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=days[0].id,
                                    activity_id=act.id, type="Security",
                                    activity="Bag check opens"))
    db.session.commit()
    return show, days, act


def _oss(client, show, tab="unassigned"):
    r = client.get("/shows/%d/oss?tab=%s" % (show.id, tab))
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _pane(body):
    start = body.index('id="tab-unassigned"')
    end = body.find('<div class="tab-pane oss-tab-pane', start)
    return body[start:end if end != -1 else len(body)]


# ── The tab ──────────────────────────────────────────────────────────────

def test_unlinked_entries_get_their_own_tab(app, client, db, show_with_strays):
    show, _days, _act = show_with_strays
    body = _oss(client, show)
    assert 'id="tab-unassigned"' in body
    assert "Unassigned" in body


def test_it_carries_a_warning_badge_with_the_count(app, client, db,
                                                   show_with_strays):
    """Like the one beside the F&B header — same amber, same ⚠."""
    show, _days, _act = show_with_strays
    body = _oss(client, show)
    nav = body[body.index('<ul class="nav nav-tabs'):body.index("</ul>")]
    assert "⚠ 5" in nav
    assert "#FEF3C7" in nav


def test_the_linked_entry_is_not_on_it(app, client, db, show_with_strays):
    """The criterion is unlinked, not a department."""
    show, _days, _act = show_with_strays
    assert "Bag check opens" not in _pane(_oss(client, show))


def test_they_are_listed_by_day(app, client, db, show_with_strays):
    show, _days, _act = show_with_strays
    pane = _pane(_oss(client, show))
    assert pane.count('class="oss-day-header"') == 2
    assert dt.date(2026, 9, 8).strftime("%A, %B %-d, %Y") in pane
    assert dt.date(2026, 9, 9).strftime("%A, %B %-d, %Y") in pane


def test_every_row_offers_the_full_department_list(app, client, db,
                                                   show_with_strays):
    """"select the proper category" — so every category has to be offered.

    Compared against the ESCAPED key: "F&B" renders as value="F&amp;B", and a
    raw comparison passes for nine departments and fails for the tenth."""
    from markupsafe import escape
    from models import SUB_SCHEDULE_TYPES
    show, _days, _act = show_with_strays
    pane = _pane(_oss(client, show))
    assert pane.count('name="type"') == 5
    for t in SUB_SCHEDULE_TYPES:
        assert 'value="%s"' % escape(t) in pane, t


def test_the_tab_disappears_when_there_is_nothing_on_it(app, client, db,
                                                        show_with_strays):
    """A queue that cannot reach empty is a warning nobody reads."""
    import re
    from models import SubScheduleEntry
    show, _days, _act = show_with_strays
    for e in SubScheduleEntry.query.filter_by(activity_id=None).all():
        db.session.delete(e)
    db.session.commit()
    body = _oss(client, show, tab="master")
    # Comments are served, and the ones around this block say "Unassigned" on
    # purpose. Strip them and test the markup.
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"\{#.*?#\}", "", body, flags=re.S)
    assert 'id="tab-unassigned"' not in body
    assert "Unassigned" not in body


# ── Classifying ──────────────────────────────────────────────────────────

def _stray(show, label="Truck 1 arrives"):
    from models import SubScheduleEntry
    return SubScheduleEntry.query.filter_by(show_id=show.id,
                                            activity=label).one()


def test_setting_a_department_files_it(app, client, db, show_with_strays):
    show, _days, _act = show_with_strays
    entry = _stray(show)
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Security"}, follow_redirects=True)
    db.session.expire_all()
    assert _stray(show).type == "Security"


def test_a_department_alone_leaves_it_on_the_tab(app, client, db,
                                                 show_with_strays):
    """It still appears on no day page, so it is still unassigned. The flash
    says so rather than letting it look resolved."""
    show, _days, _act = show_with_strays
    entry = _stray(show)
    r = client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                    data={"type": "Security"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "stays on this tab" in body
    assert "Truck 1 arrives" in _pane(body)


def test_linking_it_to_an_activity_takes_it_off(app, client, db,
                                                show_with_strays):
    show, _days, act = show_with_strays
    entry = _stray(show)
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Security", "activity_id": act.id},
                follow_redirects=True)
    db.session.expire_all()
    fixed = _stray(show)
    assert fixed.activity_id == act.id
    assert fixed.type == "Security"
    assert "Truck 1 arrives" not in _pane(_oss(client, show))


def test_linking_clears_the_entrys_own_clock(app, client, db,
                                             show_with_strays):
    """Same rule the full write path uses: a linked entry has no time of its
    own, because the activity is the single source of truth for when it
    happens. Two clocks is how they drift."""
    show, _days, act = show_with_strays
    entry = _stray(show)
    assert entry.time
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Security", "activity_id": act.id},
                follow_redirects=True)
    db.session.expire_all()
    fixed = _stray(show)
    assert fixed.time is None
    assert fixed.effective_time == act.time


def test_it_writes_only_the_two_fields_it_is_given(app, client, db,
                                                   show_with_strays):
    """It does NOT go through _apply_form_to_entry, which reads label, count,
    hours and notes off the form — a partial post through that would blank
    everything this triage screen does not carry."""
    from models import SubScheduleEntry
    show, _days, _act = show_with_strays
    entry = _stray(show)
    entry.count = 3
    entry.duration_hrs = 1.5
    entry.notes = "45ft, dock 3"
    db.session.commit()

    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Security"}, follow_redirects=True)
    db.session.expire_all()
    fixed = SubScheduleEntry.query.get(entry.id)
    assert fixed.count == 3
    assert fixed.duration_hrs == 1.5
    assert fixed.notes == "45ft, dock 3"
    assert fixed.activity == "Truck 1 arrives"


def test_an_unknown_department_is_refused(app, client, db, show_with_strays):
    show, _days, _act = show_with_strays
    entry = _stray(show)
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Pyro"}, follow_redirects=True)
    db.session.expire_all()
    assert _stray(show).type == "Dock"


def test_an_activity_from_another_day_is_refused(app, client, db,
                                                 show_with_strays):
    """The entry's day is the entry's day. Linking across one would put it on
    a page it does not belong to."""
    from models import ScheduleActivity
    show, days, _act = show_with_strays
    entry = _stray(show)
    other = ScheduleActivity.query.filter_by(day_id=days[1].id).first()
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Security", "activity_id": other.id},
                follow_redirects=True)
    db.session.expire_all()
    assert _stray(show).activity_id is None


def test_an_entry_from_another_show_is_refused(app, client, db,
                                               show_with_strays):
    """The app has no authentication; the show check is the only guard."""
    from models import Show
    show, _days, _act = show_with_strays
    other = Show(name="Other", code="OTH26")
    db.session.add(other)
    db.session.commit()
    entry = _stray(show)
    client.post("/shows/%d/oss/%d/classify" % (other.id, entry.id),
                data={"type": "Security"}, follow_redirects=True)
    db.session.expire_all()
    assert _stray(show).type == "Dock"


# ── The cause ────────────────────────────────────────────────────────────

def test_every_oss_department_select_has_a_placeholder():
    """Without one the browser submits the first option — Dock, sort 1 —
    whenever nobody touches the select. That is how ten entries ended up
    wearing a department nobody chose."""
    import os
    import re
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo, "templates", "schedule", "day.html")) as fh:
        day = re.sub(r"\{#.*?#\}", "", fh.read(), flags=re.S)

    selects = [m.start() for m in re.finditer(r'<select name="type"', day)]
    assert selects, "expected the OSS department selects to still be there"
    for pos in selects:
        chunk = day[pos:day.index("</select>", pos)]
        assert '<option value="">' in chunk, \
            "an OSS department select with no placeholder defaults to Dock"
