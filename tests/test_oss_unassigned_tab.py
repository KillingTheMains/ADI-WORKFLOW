"""The Unassigned tab lists entries that cannot be placed on their day.

It did not always mean that. Jason, 2026-08-13 (first pass): "Unlinked entries
should be their own tab in the OSS view and not randomly assigned to 'dock'."
So the tab was born listing every entry with no activity link, and offering a
dropdown to attach one.

He corrected the design the same day, once he saw it:

    "DOCK events are REAL events. Those are trucks coming and going and
     delivering and picking up gear from the venue. So they need to be on the
     daily schedules as their own events at the times they are listed ... I'm
     not sure that the dropdown is the right direction because these will most
     likely be independent events that need their own line in the daily
     schedules. What we're looking to do with the unassigned tab is just
     assign a department, not add it to another event on the day."

That reframing invalidated the old rule, and the old rule could not simply be
kept alongside the new UI:

  · An unlinked entry now draws its OWN row on the day timeline, at its own
    time. So "has no activity" stopped being a defect — it is the normal shape
    of a dock call.
  · `SubScheduleEntry.type` is NOT NULL, so every entry already has a
    department. A tab whose only control is a department picker, whose
    membership is defined by the activity link, can never be emptied by using
    it. The user picks a department, saves, and the row stays put.

So the membership rule is now "cannot be placed on the day at all" — no
activity to take a time from, and no readable time of its own — and the form
offers the time, which is the thing actually missing. The department picker
stays because the rows here are department-WRONG (see the placeholder bug at
the bottom of this file), not department-less.
"""
import datetime as dt
import re

import pytest


@pytest.fixture
def show_with_strays(db):
    """Two days. Three entries with no time and no activity — the ones this
    tab is for — plus two timed unlinked entries and one linked entry, which
    between them cover every way an entry can be fine."""
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

    # UNPLACEABLE: no activity, no time. These belong on the tab.
    for day, label in ((days[0], "Truck 1 arrives"),
                       (days[0], "House lights to 50%"),
                       (days[1], "Unlock stage door")):
        db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                        type="Dock", activity=label))
    # PLACEABLE: unlinked but timed. These draw on the day page and are fine.
    for day, time, label in ((days[0], "10:30 AM", "Truck 2 arrives"),
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


def _strip(body):
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return re.sub(r"\{#.*?#\}", "", body, flags=re.S)


# ── What the tab holds ───────────────────────────────────────────────────

def test_unplaceable_entries_get_their_own_tab(app, client, db, show_with_strays):
    show, _days, _act = show_with_strays
    body = _oss(client, show)
    assert 'id="tab-unassigned"' in body
    assert "Unassigned" in body


def test_it_carries_a_warning_badge_with_the_count(app, client, db,
                                                   show_with_strays):
    """Like the one beside the F&B header — same amber, same ⚠. Three, not
    five: the two timed entries are not problems."""
    show, _days, _act = show_with_strays
    nav_src = _oss(client, show)
    nav = nav_src[nav_src.index('<ul class="nav nav-tabs'):nav_src.index("</ul>")]
    assert "⚠ 3" in nav
    assert "#FEF3C7" in nav


def test_a_timed_unlinked_entry_is_not_a_problem(app, client, db,
                                                 show_with_strays):
    """THE change. It has a time, so it draws its own line on the day page —
    which is exactly what Jason asked a dock event to do. Listing it as
    unassigned would be calling a working feature a fault."""
    show, _days, _act = show_with_strays
    assert "Truck 2 arrives" not in _pane(_oss(client, show))


def test_a_linked_entry_is_not_on_it_either(app, client, db, show_with_strays):
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
    assert pane.count('name="type"') == 3
    for t in SUB_SCHEDULE_TYPES:
        assert 'value="%s"' % escape(t) in pane, t


def test_the_activity_dropdown_is_gone(app, client, db, show_with_strays):
    """"I'm not sure that the dropdown is the right direction because these
    will most likely be independent events that need their own line." """
    show, _days, _act = show_with_strays
    pane = _strip(_pane(_oss(client, show)))
    assert 'name="activity_id"' not in pane
    assert "leave it off the day" not in pane


def test_every_row_offers_a_time_instead(app, client, db, show_with_strays):
    show, _days, _act = show_with_strays
    pane = _pane(_oss(client, show))
    assert pane.count('type="time" name="time"') == 3


def test_the_tab_disappears_when_there_is_nothing_on_it(app, client, db,
                                                        show_with_strays):
    """A queue that cannot reach empty is a warning nobody reads."""
    from models import SubScheduleEntry
    show, _days, _act = show_with_strays
    for e in SubScheduleEntry.query.filter_by(activity_id=None, time=None).all():
        db.session.delete(e)
    db.session.commit()
    body = _strip(_oss(client, show, tab="master"))
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
    """It still has no time, so it still cannot be placed. The flash says so
    rather than letting it look resolved."""
    show, _days, _act = show_with_strays
    entry = _stray(show)
    r = client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                    data={"type": "Security"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "stays on this tab" in body
    assert "Truck 1 arrives" in _pane(body)


def test_a_time_takes_it_off_the_tab(app, client, db, show_with_strays):
    """The exit. It can be placed on the day now, so it is no longer a loose
    end — and it leaves without ever being attached to another event."""
    show, _days, _act = show_with_strays
    entry = _stray(show)
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Dock", "time": "06:15"}, follow_redirects=True)
    db.session.expire_all()
    fixed = _stray(show)
    assert fixed.time == "06:15"
    assert fixed.activity_id is None, "it must NOT have been linked to anything"
    assert "Truck 1 arrives" not in _pane(_oss(client, show))


def test_a_classified_entry_keeps_its_own_clock(app, client, db,
                                                show_with_strays):
    """The old form nulled `time` when it linked an entry, because a linked
    entry takes its time from the activity. Nothing links here any more, so
    the time it was just given must survive — a truck booked at 06:15 against
    a 06:00 load-in is not a 06:00 truck."""
    show, _days, _act = show_with_strays
    entry = _stray(show)
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Dock", "time": "06:15"}, follow_redirects=True)
    db.session.expire_all()
    assert _stray(show).effective_time == "06:15"


def test_a_blank_time_does_not_wipe_an_existing_one(app, client, db,
                                                    show_with_strays):
    """Re-filing a timed entry's department must not cost it its time. Blank
    means 'leave it alone', which is the same partial-post rule the route
    avoids _apply_form_to_entry for."""
    show, _days, _act = show_with_strays
    entry = _stray(show, "Truck 2 arrives")
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Security"}, follow_redirects=True)
    db.session.expire_all()
    fixed = _stray(show, "Truck 2 arrives")
    assert fixed.type == "Security"
    assert fixed.time == "10:30 AM"


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


def test_an_unreadable_time_is_refused_and_changes_nothing(app, client, db,
                                                           show_with_strays):
    show, _days, _act = show_with_strays
    entry = _stray(show)
    client.post("/shows/%d/oss/%d/classify" % (show.id, entry.id),
                data={"type": "Security", "time": "half six"},
                follow_redirects=True)
    db.session.expire_all()
    fixed = _stray(show)
    assert fixed.time is None
    assert fixed.type == "Dock", "a rejected post must not half-apply"


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
    wearing a department nobody chose, and why the picker on this tab is
    still worth having even though `type` is NOT NULL."""
    import os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo, "templates", "schedule", "day.html")) as fh:
        day = re.sub(r"\{#.*?#\}", "", fh.read(), flags=re.S)

    selects = [m.start() for m in re.finditer(r'<select name="type"', day)]
    assert selects, "expected the OSS department selects to still be there"
    for pos in selects:
        chunk = day[pos:day.index("</select>", pos)]
        assert '<option value="">' in chunk, \
            "an OSS department select with no placeholder defaults to Dock"
