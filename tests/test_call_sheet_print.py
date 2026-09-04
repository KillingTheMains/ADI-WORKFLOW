"""The call sheet prints what is on the screen, not both views at once.

`@media print` used to force every `.view-section` open, so a printed sheet
carried the By Call Time table AND the By Department table — the same crew
listed twice. On one day that reads as a long sheet. On a ten-day packet
(note 17) it is twenty pages where Larry asked for ten, which is what made it
worth fixing rather than living with.

Comments are stripped before every assertion here. The house rule is that a
CSS comment is SERVED, and this file is exactly the shape that trips over it:
the comment left in the print block explains the rule that was removed, so an
assertion looking for the rule's absence would match the prose describing it.
"""
import datetime as dt
import re

from models import ScheduleActivity, ScheduleDay, Show


def _print_block(css):
    """The body of `@media print { ... }`, comments stripped.

    Brace-matched rather than read to the first `}`, because a media query's
    first closing brace belongs to the first rule inside it.
    """
    i = css.index("@media print")
    start = css.index("{", i)
    depth, j = 0, start
    while j < len(css):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return re.sub(r"/\*.*?\*/", "", css[start:j], flags=re.S)


def _sheet_css(client, db):
    seq = Show.query.count() + 1
    show = Show(name=f"Print Show {seq}", code=f"PR{seq}")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 12, 1))
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="08:00",
                                    description="CREW START", sort_order=10))
    db.session.commit()
    r = client.get(f"/shows/{show.id}/schedule/{day.id}/call-sheet")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_print_does_not_force_both_views_open(client, db):
    """The whole point. Printing follows the selected tab."""
    block = _print_block(_sheet_css(client, db))
    assert ".view-section" not in block, (
        "an override here makes every sheet print twice, once per view"
    )


def test_the_base_rules_still_decide_which_view_shows(client, db):
    """Removing the print override only works because these still stand — and
    `.active` is set server-side, so a browser with JS off still prints the
    call-time view rather than nothing at all."""
    css = _sheet_css(client, db)
    assert ".view-section { display: none; }" in css
    assert ".view-section.active { display: block; }" in css
    assert 'class="view-section active" data-view="by-call"' in css


def test_the_tabs_themselves_are_not_printed(client, db):
    block = _print_block(_sheet_css(client, db))
    assert ".view-tabs" in block


def test_a_packet_still_breaks_the_page_between_days(client, db):
    """The print block earns its keep for note 17 — this guards the removal
    above from taking the page break with it."""
    block = _print_block(_sheet_css(client, db))
    assert "page-break-before: always" in block
