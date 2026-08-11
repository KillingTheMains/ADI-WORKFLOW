"""The billable day (2026-08-11).

Larry's model: 10-hour day, OT 1.5x for hours 11-12, DT 2.0x from hour 13.
"""
import pytest

from billing import (billable_days, split_day, split_days, weighted_hours)


@pytest.mark.parametrize("hours,expected", [
    (0, (0.0, 0.0, 0.0)),
    (7.5, (7.5, 0.0, 0.0)),
    (10, (10.0, 0.0, 0.0)),      # a full standard day, no OT
    (10.5, (10.0, 0.5, 0.0)),    # first minute past 10 is OT
    (12, (10.0, 2.0, 0.0)),      # OT band is exactly hours 11-12
    (12.5, (10.0, 2.0, 0.5)),    # hour 13 starts DT
    (14, (10.0, 2.0, 2.0)),
    (24, (10.0, 2.0, 12.0)),
])
def test_split_day(hours, expected):
    assert split_day(hours) == expected


def test_negative_and_none_are_zero():
    assert split_day(None) == (0.0, 0.0, 0.0)
    assert split_day(-5) == (0.0, 0.0, 0.0)


def test_eight_hour_day_produces_no_overtime():
    """A day is 10 hours, not 8 — an 8-hour assumption would invent 0 OT here
    but would also mis-split a 9-hour day. This pins the boundary."""
    assert split_day(9) == (9.0, 0.0, 0.0)


def test_days_are_split_individually_not_in_aggregate():
    """The whole reason this is per-day.

    Eight 8-hour days is 64 hours with NO overtime. Summing first and
    splitting the total would report 10 straight and 54 double.
    """
    assert split_days([8] * 8) == (64.0, 0.0, 0.0)


def test_one_long_day_is_not_hidden_by_short_ones():
    """The other direction: a 14-hour day keeps its OT and DT even when the
    person's other days are short."""
    st, ot, dt = split_days([4, 4, 14])
    assert (st, ot, dt) == (18.0, 2.0, 2.0)


def test_weighted_hours_applies_the_multipliers():
    assert weighted_hours(10, 2, 2) == 10 + 2 * 1.5 + 2 * 2.0


def test_weighted_hours_of_a_plain_day_is_unchanged():
    assert weighted_hours(*split_day(10)) == 10.0


def test_thresholds_are_overridable():
    """Larry's own workbooks say OT/DT are editable, and a contractor's terms
    can differ from the house default."""
    assert split_day(10, ot_after=8, dt_after=12) == (8.0, 2.0, 0.0)
    assert split_day(13, ot_after=8, dt_after=12) == (8.0, 4.0, 1.0)


def test_billable_days_inverts_the_workbook_formula():
    """Larry: straight-time hours = billable days x 10 + prep hours."""
    assert billable_days([10, 10, 10]) == 3.0
    assert billable_days([10, 5]) == 1.5


def test_billable_days_is_safe_with_a_zero_standard_day():
    assert billable_days([10], standard_day=0) == 0.0
