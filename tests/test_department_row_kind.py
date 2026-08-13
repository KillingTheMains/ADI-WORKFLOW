"""A dock call is a line on the day, at its time, wearing its own code.

Jason, 2026-08-13:

    "DOCK events are REAL events. Those are trucks coming and going and
     delivering and picking up gear from the venue. So they need to be on the
     daily schedules as their own events at the times they are listed with
     probably DOCK in the little indicator box to the left instead of 'AC'."

Two claims, tested separately:

  1. PLACEMENT. An OSS entry with a time and no activity is a row in the day's
     one clock-ordered stream, sorted against the crew calls and the breaks
     and the anchors. It used to be tabulated in a card BELOW the whole
     timeline, so a 06:00 truck printed underneath the 23:00 wrap — which is
     the concrete reason the OSS read as a second schedule rather than a
     summary of this one.

  2. THE CODE. The chip says which department, not the anonymous AC. Two
     letters, because the box is a fixed 26px on screen and a fixed column in
     the PDF and the sheet; the full name rides alongside as a badge.

The row keeps the ACTIVITY's rail and fill on purpose. A truck arriving at
06:00 is an event at 06:00 — structurally the same kind of thing as a load-in,
so it gets the same silhouette. Only the code changes.
"""
import datetime as dt
import re

import pytest


@pytest.fixture
def dock_day(db):
    """A day with two activities and three unlinked department entries, one of
    them earlier than everything else on the day."""
    from models import ScheduleActivity, ScheduleDay, Show, SubScheduleEntry
    show = Show(name="Trucks", code="TRK26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 14),
                      sod="7:00 AM", eod="11:00 PM")
    db.session.add(day)
    db.session.flush()
    call = ScheduleActivity(day_id=day.id, time="8:00 AM",
                            description="CREW START", sort_order=10)
    load = ScheduleActivity(day_id=day.id, time="1:00 PM",
                            description="LOAD IN BEGINS", sort_order=20)
    db.session.add_all([call, load])
    db.session.flush()
    db.session.add_all([
        SubScheduleEntry(show_id=show.id, schedule_day_id=day.id, type="Dock",
                         time="6:00 AM", activity="Truck 1 arrives",
                         count=2, notes="45ft, dock 3"),
        SubScheduleEntry(show_id=show.id, schedule_day_id=day.id, type="Doors",
                         time="5:00 PM", activity="Unlock house left"),
        SubScheduleEntry(show_id=show.id, schedule_day_id=day.id, type="HVAC",
                         time="9:00 AM", activity="Air on in the hall"),
    ])
    db.session.commit()
    return show, day, call, load


def _page(client, show, day):
    r = client.get("/shows/%d/schedule/%d" % (show.id, day.id))
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _strip(body):
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"\{#.*?#\}", "", body, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", body, flags=re.S)


# ── One table of codes, not three ────────────────────────────────────────

def test_the_template_and_the_exporters_agree_on_every_code():
    """brand.DEPT_CODE is what the PDF and the XLSX print; DEPT_CODES in
    _row_kinds.html is what the screen draws. Three bugs this session were one
    question with two spellings, so this asserts the two SURFACES agree rather
    than asserting either is correct on its own."""
    import ast
    import os
    from brand import DEPT_CODE
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo, "templates", "_row_kinds.html")) as fh:
        src = fh.read()
    body = re.search(r"set DEPT_CODES = (\{.*?\})", src, re.S).group(1)
    assert ast.literal_eval(body) == DEPT_CODE


def test_every_department_has_a_code():
    from brand import DEPT_CODE
    from models import SUB_SCHEDULE_TYPES
    assert set(DEPT_CODE) == set(SUB_SCHEDULE_TYPES)


def test_no_department_code_collides_with_a_row_kind():
    """HVAC's obvious code is AC, which is already the ACTIVITY code. Two rows
    meaning different things must never print the same two letters — that is
    the entire premise of the table."""
    from brand import DEPT_CODE, KIND_CODE
    clash = set(DEPT_CODE.values()) & set(KIND_CODE.values())
    assert not clash, "codes mean two things: %s" % sorted(clash)
    assert DEPT_CODE["HVAC"] == "HV"


def test_the_codes_are_unique_among_themselves():
    from brand import DEPT_CODE
    assert len(set(DEPT_CODE.values())) == len(DEPT_CODE)


def test_every_code_is_two_capitals():
    """The box is a fixed 26px on screen and a fixed column on paper."""
    from brand import DEPT_CODE
    for dept, code in DEPT_CODE.items():
        assert re.fullmatch(r"[A-Z]{2}", code), "%s -> %r" % (dept, code)


# ── The row is on the timeline ───────────────────────────────────────────

def test_a_dock_entry_draws_on_the_day(app, client, db, dock_day):
    show, day, call, load = dock_day
    body = _page(client, show, day)
    assert "Truck 1 arrives" in body


def test_it_draws_before_the_activity_it_precedes(app, client, db, dock_day):
    """THE fix. A 06:00 truck belongs above the 08:00 crew call, not in a card
    underneath the whole day."""
    show, day, call, load = dock_day
    body = _page(client, show, day)
    assert body.index("Truck 1 arrives") < body.index('id="act-%d"' % call.id)


def test_the_entries_sort_against_each_other_by_the_clock(app, client, db,
                                                          dock_day):
    show, day, call, load = dock_day
    body = _page(client, show, day)
    assert (body.index("Truck 1 arrives")        # 06:00
            < body.index("Air on in the hall")   # 09:00
            < body.index("Unlock house left"))   # 17:00


def test_a_late_entry_draws_after_the_last_activity(app, client, db, dock_day):
    show, day, call, load = dock_day
    body = _page(client, show, day)
    assert body.index("Unlock house left") > body.index('id="act-%d"' % load.id)


def test_the_old_card_below_the_timeline_is_gone(app, client, db, dock_day):
    """It listed the same rows a second time, under a heading that framed them
    as leftovers rather than as events."""
    show, day, call, load = dock_day
    body = _strip(_page(client, show, day))
    assert "Operational items (not linked to an activity)" not in body
    assert body.count("Truck 1 arrives") == 1, "the row must not render twice"


def test_the_row_carries_its_detail(app, client, db, dock_day):
    show, day, call, load = dock_day
    body = _page(client, show, day)
    row = body[body.index("Truck 1 arrives"):][:800]
    assert "45ft, dock 3" in row
    assert "2 ea" in row


def test_the_row_can_still_be_deleted_from_the_day(app, client, db, dock_day):
    """Losing the card must not lose the delete. A wrong row you cannot remove
    from where you are looking at it is how the parked list got to ten."""
    from flask import url_for
    from models import SubScheduleEntry
    show, day, call, load = dock_day
    entry = SubScheduleEntry.query.filter_by(activity="Truck 1 arrives").one()
    body = _page(client, show, day)
    with app.test_request_context():
        assert url_for("oss.delete_entry", show_id=show.id,
                       entry_id=entry.id) in body


def test_adding_one_is_still_offered(app, client, db, dock_day):
    """The door has to survive too — otherwise a dock call can only be made
    from the OSS hub, which is the direction this whole pass reverses."""
    from flask import url_for
    show, day, call, load = dock_day
    body = _strip(_page(client, show, day))
    assert "+ Add a department event" in body
    with app.test_request_context():
        assert url_for("oss.add_entry", show_id=show.id) in body


# ── The chip ─────────────────────────────────────────────────────────────

def test_the_chip_says_the_department_not_ac(app, client, db, dock_day):
    """The quoted ask: "probably DOCK in the little indicator box to the left
    instead of 'AC'"."""
    show, day, call, load = dock_day
    body = _page(client, show, day)
    row = body[body.index('title="Dock"'):][:400]
    assert ">DK<" in row


def test_each_department_gets_its_own_chip(app, client, db, dock_day):
    show, day, call, load = dock_day
    body = _page(client, show, day)
    for dept, code in (("Dock", "DK"), ("Doors", "DR"), ("HVAC", "HV")):
        assert 'title="%s"' % dept in body, dept
        chunk = body[body.index('title="%s"' % dept):][:400]
        assert ">%s<" % code in chunk, dept


def test_the_full_department_name_rides_alongside(app, client, db, dock_day):
    """Two letters is an alphabet, not a label. Nothing is lost because the
    name is on the row."""
    show, day, call, load = dock_day
    body = _page(client, show, day)
    row = body[body.index("Truck 1 arrives"):][:900]
    assert "🚚 Dock" in row


def test_the_row_keeps_the_activity_silhouette(app, client, db, dock_day):
    """Structurally it IS an ordinary event, so it wears the activity rail
    rather than inventing an eighth pattern for a thing that is not an eighth
    kind."""
    show, day, call, load = dock_day
    body = _page(client, show, day)
    row = body[body.index('class="mb-2 d-flex align-items-center gap-2 oss-timeline-row'):][:400]
    assert "border-left:2px solid var(--adi-kind-act)" in row


def test_an_unknown_department_still_draws_a_chip(app, client, db, dock_day):
    """A blank box on a show morning reads as "no data", which is a stronger
    and wronger claim than "ordinary row"."""
    from models import SubScheduleEntry
    show, day, call, load = dock_day
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    type="Pyro", time="7:30 AM",
                                    activity="Flame check"))
    db.session.commit()
    body = _page(client, show, day)
    assert "Flame check" in body
    row = body[body.index("Flame check") - 700:body.index("Flame check")]
    assert ">AC<" in row


# ── All three surfaces say the same thing ────────────────────────────────
#
# Jason, 2026-08-13: "the OSS and its tabs are just a reflection of the day
# schedule, so anything you change should encompass all 3 areas of the site.
# If we are changing the way something looks on the day schedule, then it
# should change the way it looks on the OSS ... and in the OSS tabs."
#
# The first cut of this work changed only the day page, so a linked dock call
# showed nothing, an unlinked one showed DK, and both showed AC on the hub —
# three spellings of one fact. These assert the surfaces AGREE rather than
# asserting any one of them is right, which is the only guard that has held
# up this session.

def test_one_rule_decides_the_code_everywhere():
    """brand.row_code is what the exporters call and what row_chip mirrors."""
    from brand import row_code
    assert row_code("act", "Dock") == "DK"
    assert row_code("act", None) == "AC"
    assert row_code("act", "Pyro") == "AC"
    # A crew call stays CC even when it carries a department: what the reader
    # needs from that row is that it is a crew call.
    assert row_code("crew", "F&B") == "CC"
    assert row_code("break", "F&B") == "BR"


def test_the_exporters_call_the_shared_rule():
    """Not brand.KIND_CODE directly — that is how the sheet came to print AC
    for a row the screen called DK."""
    import os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("oss_xlsx.py", "oss_pdf.py"):
        with open(os.path.join(repo, name)) as fh:
            src = fh.read()
        assert "brand.row_code(kind" in src, name
        assert 'brand.KIND_CODE.get(kind' not in src, \
            "%s still codes a row without consulting its department" % name


def test_a_linked_entry_carries_the_chip_on_the_day_page(app, client, db,
                                                         dock_day):
    """34 of production's 44 entries are LINKED, so they draw inside their
    activity card rather than as timeline rows. That pill carried only an
    emoji, which is why the codes looked absent on a real day."""
    from models import SubScheduleEntry
    show, day, call, load = dock_day
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    activity_id=load.id, type="Dock",
                                    activity="Truck 3 unloads"))
    db.session.commit()
    body = _page(client, show, day)
    card = body[body.index('id="act-%d"' % load.id):]
    card = card[:card.find('class="card mb-2 act-card"', 1)]
    assert "Truck 3 unloads" in card
    chunk = card[card.index("Truck 3 unloads") - 900:]
    assert ">DK<" in chunk, "a linked dock call must carry its code too"


def test_the_oss_master_prints_the_same_code_as_the_day(app, client, db,
                                                        dock_day):
    show, day, call, load = dock_day
    body = client.get("/shows/%d/oss?tab=master" % show.id).get_data(as_text=True)
    pane = body[body.index('id="tab-master"'):]
    assert 'title="Dock"' in pane and ">DK<" in pane
    assert 'title="HVAC"' in pane and ">HV<" in pane


def test_the_department_tab_prints_it_too(app, client, db, dock_day):
    show, day, call, load = dock_day
    body = client.get("/shows/%d/oss?tab=Dock" % show.id).get_data(as_text=True)
    assert 'title="Dock"' in body and ">DK<" in body
