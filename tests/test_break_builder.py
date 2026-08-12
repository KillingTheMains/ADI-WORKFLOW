"""
The crew-start-anchored break BUILDER is gone (2026-08-12). This file guards
its absence.

It used to test `schedule.build_day_schedule` and `schedule.smart_breaks`,
which generated breaks as ordinary ScheduleActivity rows labelled
`COFFEE BREAK — 8:00 AM CREW`, `LUNCH BREAK — 30 min`, `EOD WRAP`. Those
assertions encoded the OLD spec: they are the exact shape the 08-12 repair
migrations spent the day undoing, and the same shape as MCDC26's 21 breaks
still stuck at 60 minutes, because a label is not a duration.

Breaks are created on the crew call now, through `breaks.break_options_for` —
one door, one definition of the add list, and a real `CrewBreak` with a kind
and a duration behind it. Jason's call, 2026-08-12: close both legacy doors
rather than keep one for old shows.

So this is a tombstone, not a deletion. The risk worth testing is that
somebody re-adds a one-click generator because "there used to be one" — these
tests fail loudly if either route comes back.
"""
import pytest


@pytest.mark.parametrize("endpoint", [
    "schedule.build_day_schedule",
    "schedule.smart_breaks",
])
def test_legacy_break_generators_are_gone(app, endpoint):
    """Neither generator may be reachable by URL.

    If this fails, a break is being written as a labelled activity somewhere
    again. Read `breaks.py`'s kind section and the removal note in
    routes/schedule.py before putting it back.
    """
    from flask import url_for
    with app.test_request_context():
        with pytest.raises(Exception):
            url_for(endpoint, show_id=1, day_id=1)


def test_no_route_still_builds_breaks_as_activities(app):
    """No registered rule may point at the old build/smart-break paths."""
    rules = {str(r) for r in app.url_map.iter_rules()}
    offenders = [r for r in rules
                 if r.endswith("/build-schedule") or r.endswith("/smart-breaks")]
    assert not offenders, (
        "legacy break-generation route(s) reintroduced: " + ", ".join(offenders))
