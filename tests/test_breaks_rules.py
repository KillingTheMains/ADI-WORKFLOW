"""Break/meal arithmetic (2026-08-11 overhaul, step 1).

Jason's confirmed rules: 30 before, 1 hour service, 30 after, 2 hours max food
out. Beverages set 30 before the first crew call, refreshed every 2h30, never
past EOD.
"""
from breaks import (BEVERAGE_REFRESH_INTERVAL, FOOD_OUT_MAX_MINUTES,
                    beverage_touchpoints, breaches_food_out_rule, called_before,
                    food_out_minutes, on_site_at, service_window)


def _m(h, m=0):
    return h * 60 + m


# ── Service window ───────────────────────────────────────────────────────────

def test_house_default_window():
    """13:00 break -> food out 12:30 to 14:30."""
    assert service_window(_m(13)) == (_m(12, 30), _m(14, 30))


def test_window_respects_custom_setup_and_holdover():
    assert service_window(_m(13), duration=30, setup=15, holdover=0) == \
        (_m(12, 45), _m(13, 30))


# ── The 2-hour rule ──────────────────────────────────────────────────────────

def test_house_default_is_exactly_on_the_limit():
    """30 + 60 + 30 = 120. The rule is what sets the defaults."""
    assert food_out_minutes() == FOOD_OUT_MAX_MINUTES
    assert breaches_food_out_rule() is False


def test_a_longer_service_breaches():
    assert breaches_food_out_rule(duration=90) is True


def test_a_shorter_service_does_not():
    assert breaches_food_out_rule(duration=30) is False


def test_longer_setup_can_breach_on_its_own():
    assert breaches_food_out_rule(setup=60) is True


# ── Beverage touchpoints ─────────────────────────────────────────────────────

def test_setup_is_thirty_minutes_before_the_first_call():
    points = beverage_touchpoints(_m(7), _m(22))
    assert points[0] == _m(6, 30)


def test_refreshes_every_two_and_a_half_hours():
    points = beverage_touchpoints(_m(7), _m(22))
    gaps = [b - a for a, b in zip(points, points[1:])]
    assert set(gaps) == {BEVERAGE_REFRESH_INTERVAL}


def test_refreshes_never_pass_eod():
    """Jason: refreshes must not surpass the EOD listed on the day."""
    eod = _m(18)
    points = beverage_touchpoints(_m(7), eod)
    assert points[-1] <= eod
    assert all(p <= eod for p in points)


def test_a_refresh_landing_exactly_on_eod_is_kept():
    # setup 06:30, refreshes 09:00, 11:30, 14:00 — EOD at 14:00 keeps it.
    assert beverage_touchpoints(_m(7), _m(14))[-1] == _m(14)


def test_missing_eod_generates_nothing():
    """A day with no EOD cannot have refreshes. Guessing an end to the day
    would put F&B on site for a shift nobody scheduled."""
    assert beverage_touchpoints(_m(7), None) == []


def test_missing_first_call_generates_nothing():
    assert beverage_touchpoints(None, _m(22)) == []


def test_setup_after_eod_generates_nothing():
    assert beverage_touchpoints(_m(23), _m(22)) == []


# ── Headcounts ───────────────────────────────────────────────────────────────

def test_on_site_counts_only_crew_currently_working():
    windows = [(_m(7), _m(17), 4), (_m(9), _m(19), 2), (_m(20), _m(23), 5)]
    assert on_site_at(windows, _m(8)) == 4        # only the 07:00 crew
    assert on_site_at(windows, _m(10)) == 6       # both day crews
    assert on_site_at(windows, _m(18)) == 2       # first crew has wrapped
    assert on_site_at(windows, _m(21)) == 5       # night crew only


def test_crew_with_no_end_time_counts_as_still_on_site():
    """hours not filled in. Under-catering silently is worse than
    over-catering — callers mark these as estimates."""
    assert on_site_at([(_m(7), None, 3)], _m(23)) == 3


def test_a_crew_is_not_on_site_before_their_call():
    assert on_site_at([(_m(9), _m(17), 4)], _m(8)) == 0


def test_called_before_drives_the_setup_headcount():
    """Jason: setup headcount is the crew calls beginning before the first
    refresh."""
    windows = [(_m(7), _m(17), 4), (_m(9), _m(19), 2), (_m(12), _m(20), 6)]
    assert called_before(windows, _m(9, 30)) == 6      # 07:00 and 09:00 crews
    assert called_before(windows, _m(7)) == 0          # boundary is exclusive
