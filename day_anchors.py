"""
SOD and EOD as timeline rows — computed on every read.

A day's start and end used to be typed twice: once into Day Settings, and
again as an ordinary `EOD WRAP` activity somebody added by hand or inherited
from a template. The two drifted. On 2026-08-12 production carried 31 EOD WRAP
rows and only 14 of them agreed with the day's own EOD; eight days had a wrap
row and no EOD at all.

So the anchors are DERIVED here and never stored, the same way beverage
touchpoints are: change SOD or EOD in Day Settings and the row moves. There is
one place to edit them and one value behind them.

An anchor with no time still renders. A day whose EOD is blank is a day whose
end nobody has set, and saying so on the timeline is the whole point — an
absent row would read as "no end needed" rather than "nobody has said".
"""
from time_utils import parse_minutes

SOD_LABEL = "START OF DAY"
EOD_LABEL = "END OF DAY"

# Past any real clock time, so place_in_day finds no activity at or after it
# and drops the row to the bottom of the day. Jason, 2026-08-12: an unset EOD
# belongs at the end of the schedule with an instruction, not at the top.
_UNSET_EOD_SORT = 24 * 60 + 60


def overlay_for_day(day):
    """The day's two anchor rows. Each is a dict:

        {anchor, label, time, sort_min, unset}

    ``anchor`` is 'sod' or 'eod'; ``time`` is the stored canonical HH:MM or
    None; ``unset`` says the day has no value yet, which the template turns
    into an instruction instead of a clock.

    Returns both rows always. Ordering is left to place_in_day, which reads
    ``sort_min`` — an unset SOD sorts to the top of the day and an unset EOD
    to the bottom.
    """
    if day is None:
        return []
    rows = []
    for anchor, raw, label, unset_sort in (
            ("sod", getattr(day, "sod", None), SOD_LABEL, 0),
            ("eod", getattr(day, "eod", None), EOD_LABEL, _UNSET_EOD_SORT)):
        # parse_minutes, not sort_minutes: the latter returns a 1,000,000
        # sentinel rather than None, so an unset anchor would test as later
        # than every activity and the `is None` branch would never run.
        mins = parse_minutes(raw)
        rows.append({
            "anchor":   anchor,
            "label":    label,
            "time":     raw or None,
            "sort_min": unset_sort if mins is None else mins,
            "unset":    mins is None,
        })
    return rows
