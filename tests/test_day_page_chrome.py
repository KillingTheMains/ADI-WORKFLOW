"""The day page stops spending space on things nobody uses.

Jason, 2026-08-13, three cuts:

  * "removing the 'add crew row' option from all the events in the schedule
     because all the crew are in the crew call section"
  * "not sure that we need the giant white box underneath all the events with
     the words 'OSS - LINKED TO THIS ACTIVITY'. I think the schedule builder
     would look nicer without all the empty space."
  * "reassess the 'Quick Tools' section as to whether it is useful or not"

What each turned into:

  * "+ Add crew row" renders on CREW CALLS only. Crew rows on a plain activity
    are invisible to the break builder and to every count that reads from crew
    calls, so the control was an invitation to a bug. Existing rows still
    render and can still be deleted — this stops new ones being made there.
  * The OSS panel — a dashed rule, an uppercase heading and a "+ OSS" button
    under EVERY activity whether or not anything was linked — is gone. The
    control moved into the activity header beside Edit and Copy, carrying its
    count; the linked entries draw only when they exist.
  * Quick Tools was four controls in a permanently expanded 250px sidebar
    card. Three were one button each and the fourth, Apply Template, is a
    once-per-day action. They are a "Day tools" menu on the day header now.
    Clone Day was also duplicated — the schedule overview has always had it.
"""
import datetime as dt
import re

import pytest


@pytest.fixture
def day_page(db):
    """A crew call, a plain activity with a linked OSS entry, and a plain
    activity with none."""
    from models import (Company, CrewMember, CrewRow, ScheduleActivity,
                        ScheduleDay, Show, ShowCrewAssignment, SubScheduleEntry)
    show = Show(name="Chrome", code="CHR26")
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    co = Company(name="Sparks")
    db.session.add(co)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 7, 8),
                      sod="7:00 AM", eod="11:00 PM")
    db.session.add(day)
    db.session.flush()

    call = ScheduleActivity(day_id=day.id, time="8:00 AM",
                            description="CREW START", sort_order=10)
    plain = ScheduleActivity(day_id=day.id, time="1:00 PM",
                             description="LOAD IN BEGINS", sort_order=20)
    linked = ScheduleActivity(day_id=day.id, time="6:00 PM",
                              description="DOORS OPEN", sort_order=30)
    db.session.add_all([call, plain, linked])
    db.session.flush()

    cm = CrewMember(first_name="Ann", last_name="One", active=True,
                    company_id=co.id)
    db.session.add(cm)
    db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.add(CrewRow(activity_id=call.id, crew_member_id=cm.id,
                           qty=1, hours=10, position="A1"))
    db.session.add(SubScheduleEntry(show_id=show.id, type="Doors",
                                    schedule_day_id=day.id,
                                    activity_id=linked.id,
                                    time="6:00 PM", activity="Unlock house left"))
    db.session.commit()
    return show, day, call, plain, linked


def _page(client, show, day, strip_comments=False):
    r = client.get("/shows/%d/schedule/%d" % (show.id, day.id))
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    if strip_comments:
        # HTML and CSS comments ARE served. The ones this page carries explain
        # what was removed and why, so they contain the very strings a
        # "did it go?" assertion looks for. Strip them and test the markup.
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return body


def _card(body, act):
    """The one activity card, from its anchor to the next card."""
    start = body.index('id="act-%d"' % act.id)
    nxt = body.find('class="card mb-2 act-card"', start + 1)
    return body[start:nxt if nxt != -1 else len(body)]


# ── Add crew row ─────────────────────────────────────────────────────────

def test_a_crew_call_still_offers_add_crew_row(app, client, db, day_page):
    show, day, call, plain, linked = day_page
    assert "+ Add crew row" in _card(_page(client, show, day), call)


def test_a_plain_activity_does_not(app, client, db, day_page):
    """The cut. Crew belongs on the call that brings them in."""
    show, day, call, plain, linked = day_page
    body = _page(client, show, day)
    assert "+ Add crew row" not in _card(body, plain)
    assert "+ Add crew row" not in _card(body, linked)


def test_the_page_offers_it_exactly_once_per_crew_call(app, client, db, day_page):
    show, day, call, plain, linked = day_page
    assert _page(client, show, day).count("+ Add crew row") == 1


# ── The OSS box ──────────────────────────────────────────────────────────

PILL = "border-radius:14px"      # the linked-OSS chip, and only that


def test_the_old_oss_heading_is_gone_everywhere(app, client, db, day_page):
    """The words Jason quoted. They appeared under every activity."""
    body = _page(client, day_page[0], day_page[1], strip_comments=True)
    assert "OSS · linked to this activity" not in body
    # The dashed rule that framed the panel.
    assert "border-top:1px dashed #e9e0c0" not in body


def test_an_activity_with_no_oss_draws_no_oss_panel(app, client, db, day_page):
    show, day, call, plain, linked = day_page
    card = _card(_page(client, show, day), plain)
    # The collapse is present because that is where the add form lives, but a
    # shut collapse has no height. Nothing else may be drawn for it.
    assert PILL not in card, "the linked-entry strip should not render"


def test_the_oss_control_moved_into_the_header(app, client, db, day_page):
    show, day, call, plain, linked = day_page
    card = _card(_page(client, show, day), plain)
    header_end = card.index("</div>", card.index("act-action-btn"))
    assert 'data-bs-target="#add-oss-%d"' % plain.id in card[:header_end]


def test_a_linked_activity_shows_its_count_and_its_entries(app, client, db, day_page):
    show, day, call, plain, linked = day_page
    card = _card(_page(client, show, day), linked)
    assert "Unlock house left" in card
    assert PILL in card, "the linked entry pill should render"
    # The header button carries the count, so the page says so before you open
    # anything.
    assert "OSS&nbsp;1" in card


def test_the_add_form_is_still_reachable_for_every_activity(app, client, db, day_page):
    """Folding the panel away must not remove the ability to add one."""
    show, day, call, plain, linked = day_page
    body = _page(client, show, day)
    for act in (call, plain, linked):
        assert 'id="add-oss-%d"' % act.id in body


# ── Quick Tools ──────────────────────────────────────────────────────────

def test_the_quick_tools_panel_is_gone(app, client, db, day_page):
    body = _page(client, day_page[0], day_page[1], strip_comments=True)
    assert "⚡ Quick Tools" not in body
    assert 'class="card mb-3 tools-card"' not in body


def test_every_day_action_survived_the_move(app, client, db, day_page):
    """A tidy-up that loses a feature is not a tidy-up. Assert the ROUTES,
    which is what actually has to still be reachable."""
    from flask import url_for
    show, day = day_page[0], day_page[1]
    body = _page(client, show, day)
    assert "Day tools" in body
    with app.test_request_context():
        for endpoint in ("schedule.apply_template", "schedule.bulk_shift",
                         "schedule.clone_day", "schedule.delete_day"):
            assert url_for(endpoint, show_id=show.id, day_id=day.id) in body, endpoint
    assert 'id="applyTemplateModal"' in body
    assert 'id="bulkShiftModal"' in body


def test_apply_template_still_posts_to_its_own_route(app, client, db, day_page):
    from flask import url_for
    show, day = day_page[0], day_page[1]
    body = _page(client, show, day)
    with app.test_request_context():
        action = url_for("schedule.apply_template", show_id=show.id, day_id=day.id)
    assert action in body


def test_delete_day_is_behind_the_menu_and_still_confirms(app, client, db, day_page):
    """It is destructive and it used to sit in the open on every page view."""
    show, day = day_page[0], day_page[1]
    body = _page(client, show, day)
    assert "Delete this entire day" in body
    assert "dropdown-item text-danger" in body
