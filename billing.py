"""The billable day: straight time, overtime, double time.

Larry's model, stated identically across his rate cards and RFQ workbooks
(recorded in the project doc ADI_Larry_Standards_Findings.md §2):

    A day is 10 hours. OT is 1.5x for hours 11-12. DT is 2.0x from hour 13.
    Travel In through Travel Out is billable. Prep hours are separate.

Two deliberate limits on what this module does.

It splits HOURS ONLY and computes no money. Whether ``CrewMember.rate_standard``
is an hourly rate or a 10-hour day rate is genuinely ambiguous — Larry's intake
form collects "10-Hour Day Rate" AND "ST Hourly" as separate fields, and his
live data has both, some of it corrupted by free-text entry. Splitting hours is
correct under either reading; costing them is not. That question goes to Larry.

The split is PER DAY. Overtime is a property of a single day's work, so summing
a person's hours across a show and splitting the total would be wrong in both
directions: it invents overtime for someone who worked eight short days, and
hides it for someone who worked one very long one.
"""

# Larry's documented defaults. Parameters rather than constants because his
# own workbooks say OT/DT are "editable", and a contractor's terms can differ.
STANDARD_DAY_HOURS = 10.0
OT_AFTER_HOURS = 10.0
DT_AFTER_HOURS = 12.0
OT_MULTIPLIER = 1.5
DT_MULTIPLIER = 2.0


def split_day(hours, ot_after=OT_AFTER_HOURS, dt_after=DT_AFTER_HOURS):
    """One day's hours -> ``(straight, overtime, double)``.

    >>> split_day(10)
    (10.0, 0.0, 0.0)
    >>> split_day(12)
    (10.0, 2.0, 0.0)
    >>> split_day(14)
    (10.0, 2.0, 2.0)
    """
    h = float(hours or 0)
    if h <= 0:
        return (0.0, 0.0, 0.0)
    straight = min(h, ot_after)
    overtime = min(max(h - ot_after, 0.0), max(dt_after - ot_after, 0.0))
    double = max(h - dt_after, 0.0)
    return (straight, overtime, double)


def split_days(hours_by_day, ot_after=OT_AFTER_HOURS, dt_after=DT_AFTER_HOURS):
    """Many days -> summed ``(straight, overtime, double)``.

    ``hours_by_day`` is any iterable of per-day hour figures. Each day is split
    on its own before summing, which is the entire point.
    """
    st = ot = dt = 0.0
    for h in hours_by_day:
        a, b, c = split_day(h, ot_after=ot_after, dt_after=dt_after)
        st += a
        ot += b
        dt += c
    return (st, ot, dt)


def weighted_hours(straight, overtime, double,
                   ot_multiplier=OT_MULTIPLIER, dt_multiplier=DT_MULTIPLIER):
    """Hours expressed as straight-time equivalents.

    Not money — a multiplier-weighted hour count. It is the honest halfway
    house while the day-rate-vs-hourly question is open: multiply by whatever
    the straight-time rate turns out to be and the answer is right either way.
    """
    return (float(straight)
            + float(overtime) * ot_multiplier
            + float(double) * dt_multiplier)


def billable_days(hours_by_day, standard_day=STANDARD_DAY_HOURS):
    """How many standard days this many hours represents.

    Larry's workbooks compute straight-time hours as
    ``billable days x 10 + prep hours``. This is the inverse, for reconciling
    a schedule against a quote.
    """
    total = sum(float(h or 0) for h in hours_by_day)
    if standard_day <= 0:
        return 0.0
    return total / standard_day
