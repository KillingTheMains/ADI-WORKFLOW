"""The billable day: straight time, overtime, double time.

Larry's model, stated identically across his rate cards and RFQ workbooks
(recorded in the project doc ADI_Larry_Standards_Findings.md §2):

    A day is 10 hours. OT is 1.5x for hours 11-12. DT is 2.0x from hour 13.
    Travel In through Travel Out is billable. Prep hours are separate.

Two deliberate limits on what this module does.

It splits HOURS ONLY and computes no money — yet. The rate question is now
ANSWERED (Jason, 2026-09-05): ``CrewMember.rate_standard`` is an HOURLY rate
for the first 10 hours; OT after 10, DT after 12 by default. The reason this
module still stops short of money is data, not rules: Larry's intake form
collected "10-Hour Day Rate" AND "ST Hourly" as separate fields and the live
data has both, some of it free-text. Costing needs the rate column cleaned
first (capture log #8), then the split here is priced as
``st*rate + ot*rate*1.5 + dt*rate*2.0`` — ``rates_for`` already resolves the
three rates, and ``thresholds_for`` resolves WHERE a person's day splits
(person -> company -> default), so the report can split on the right terms
before a dollar is ever shown.

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

# How a crew record's standard rate was entered (Jason, 2026-09-06). Larry's
# intake form collected "10-Hour Day Rate" and "ST Hourly" as two fields;
# the record keeps the number as typed and says which it is. `rates_for`
# converts a day rate to hourly by the standard day.
RATE_UNIT_HOURLY = "hourly"
RATE_UNIT_DAY = "day"
RATE_UNITS = (RATE_UNIT_HOURLY, RATE_UNIT_DAY)


def thresholds_for(member=None, company=None):
    """``(ot_after, dt_after)`` for a person: person -> company -> default.

    Each threshold resolves on its own, so a person with only a custom DT
    still takes OT from their company or the default. Blank means inherit;
    zero is not a threshold anyone means, so it inherits too. A company given
    directly is used when the member has none (a local labor line's header
    company, say).
    """
    co = company if company is not None else getattr(member, "company", None)

    def pick(attr, default):
        for src in (member, co):
            v = getattr(src, attr, None) if src is not None else None
            if v:
                return float(v)
        return default

    ot = pick("ot_after_hours", OT_AFTER_HOURS)
    dt = pick("dt_after_hours", DT_AFTER_HOURS)
    if dt < ot:
        dt = ot      # DT can never start before OT does
    return (ot, dt)


def rates_for(member):
    """``(standard, ot, dt)`` hourly rates, or ``None`` where unknown.

    rate_standard is hourly for the first 10 hours (Jason, 2026-09-05). OT
    and DT typed on the person win; left blank they are 1.5x and 2x of
    standard. With no standard rate at all, nothing can be derived.
    """
    std = getattr(member, "rate_standard", None)
    std = float(std) if std else None
    # 2026-09-06: a rate can be entered as a 10-hour DAY rate. The record
    # says which (`rate_unit`); billing always works in hourly terms.
    if std and getattr(member, "rate_unit", None) == RATE_UNIT_DAY:
        std = round(std / STANDARD_DAY_HOURS, 4)
    ot = getattr(member, "rate_ot", None)
    dt = getattr(member, "rate_dt", None)
    ot = float(ot) if ot else (round(std * OT_MULTIPLIER, 2) if std else None)
    dt = float(dt) if dt else (round(std * DT_MULTIPLIER, 2) if std else None)
    return (std, ot, dt)


def rates_for_local(company, position):
    """``(standard, ot, dt)`` hourly rates for a local labor line, from the
    company's rate card (one standard rate per position), or ``None``s.
    OT and DT are 1.5x and 2x — a rate card carries the straight rate."""
    if company is None or position is None:
        return (None, None, None)
    card = getattr(company, "rate_card", None)
    std = None
    if card is not None:
        for entry in card:
            if entry.position_id == getattr(position, "id", None) and entry.rate_standard:
                std = float(entry.rate_standard)
                break
    if not std:
        return (None, None, None)
    return (std, round(std * OT_MULTIPLIER, 2), round(std * DT_MULTIPLIER, 2))


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


# ── Short turnaround and 6th/7th day (Jason, 2026-09-06) ─────────────────────
#
# Two more rules, both NAMED CREW ONLY. Local labor bodies are per call, not
# a person across days (Jason, 09-05 and again 09-06), so neither rule can
# apply to them — nothing says Monday's Lighting Hand #2 is Tuesday's.
#
#   Short turnaround: fewer than 8 hours off the clock between one shift's
#   out time and the next shift's call. The WHOLE next shift is at OT.
#   Across days only — two calls in one day are one working day.
#   The threshold resolves person -> company -> default 8, like OT/DT.
#
#   6th/7th day: the sixth and seventh of consecutive calendar days with a
#   call, within one show. All day at OT (the 7th is OT, same as the 6th).
#   Any day off resets — and so does Monday, regardless (Jason, 09-07): the
#   week runs Monday to Sunday, so Mon–Sun straight makes Saturday and
#   Sunday the 6th/7th day and the next Monday is day one again; Tuesday
#   to Sunday makes Sunday the 6th. A streak can never pass seven.
#
#   On either kind of day DT still starts after the person's DT threshold.
#   No stacking: an hour is ST, OT or DT, and the flags only raise the floor.
#
# Out time is call time + hours (the recorded actual where there is one,
# else the estimate). It ignores unpaid meal breaks, so it flags a little
# early rather than a little late — the conservative side for a rule that
# raises someone's pay.
SHORT_TURN_HOURS = 8.0
SIXTH_DAY = 6


def short_turn_for(member=None, company=None):
    """Hours off the clock a person needs before their next shift, or the
    next shift is short turnaround. person -> company -> default 8."""
    co = company if company is not None else getattr(member, "company", None)
    for src in (member, co):
        v = getattr(src, "short_turn_hours", None) if src is not None else None
        if v:
            return float(v)
    return SHORT_TURN_HOURS


def day_flags(shifts, short_turn_after=SHORT_TURN_HOURS):
    """Which of a person's days are short turnaround or 6th/7th day.

    ``shifts`` is an iterable of ``(date, call_time, hours)`` — one per crew
    row, any order. ``date`` is a ``datetime.date``; ``call_time`` is
    ``"HH:MM"`` (24-hour) or None; ``hours`` is the billable figure for
    that call. Several rows on one date are one working day: the day's in
    is the earliest call, its out is the latest ``call + hours``.

    Returns ``{date: {"short_turn": bool, "streak": int, "sixth_day": bool,
    "gap_hours": float|None}}``.

    >>> import datetime as dt
    >>> d = dt.date(2026, 9, 8)
    >>> f = day_flags([(d, "08:00", 18), (d + dt.timedelta(days=1), "07:00", 10)])
    >>> f[d + dt.timedelta(days=1)]["short_turn"]
    True
    >>> f[d]["short_turn"]
    False
    """
    import datetime as _dt

    by_date = {}
    for date, call_time, hours in shifts:
        if date is None:
            continue
        h = float(hours or 0)
        start = _parse_clock(call_time)
        d = by_date.setdefault(date, {"in": None, "out": None, "hours": 0.0})
        d["hours"] += h
        if start is not None:
            begin = _dt.datetime.combine(date, start)
            end = begin + _dt.timedelta(hours=h)
            if d["in"] is None or begin < d["in"]:
                d["in"] = begin
            if d["out"] is None or end > d["out"]:
                d["out"] = end

    flags = {}
    prev_date = prev_out = None
    streak = 0
    for date in sorted(by_date):
        d = by_date[date]
        # Consecutive days extend the streak; a gap or a Monday starts it
        # over. Short turnaround below still looks across the Monday.
        if (prev_date is not None and (date - prev_date).days == 1
                and date.weekday() != 0):
            streak += 1
        else:
            streak = 1
        gap = None
        short = False
        if (prev_out is not None and d["in"] is not None
                and prev_date is not None and (date - prev_date).days == 1):
            gap = (d["in"] - prev_out).total_seconds() / 3600.0
            short = gap < short_turn_after
        flags[date] = {"short_turn": short, "streak": streak,
                       "sixth_day": streak >= SIXTH_DAY, "gap_hours": gap}
        prev_date = date
        prev_out = d["out"] if d["out"] is not None else None
    return flags


def _parse_clock(value):
    """'HH:MM' -> datetime.time, else None. Tolerates 'H:MM' and '7:00 AM'."""
    import datetime as _dt
    if not value:
        return None
    s = str(value).strip().upper()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%H%M"):
        try:
            return _dt.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def split_day_flagged(hours, ot_after=OT_AFTER_HOURS, dt_after=DT_AFTER_HOURS,
                      all_ot=False):
    """``split_day`` with the floor raised to OT when ``all_ot`` — a short
    turnaround day or a 6th/7th day. DT still starts at ``dt_after``.

    >>> split_day_flagged(10, all_ot=True)
    (0.0, 10.0, 0.0)
    >>> split_day_flagged(14, all_ot=True)
    (0.0, 12.0, 2.0)
    """
    if not all_ot:
        return split_day(hours, ot_after, dt_after)
    h = float(hours or 0)
    if h <= 0:
        return (0.0, 0.0, 0.0)
    return (0.0, min(h, dt_after), max(h - dt_after, 0.0))


def cost_of(split, rates):
    """Dollars for a ``(st, ot, dt)`` split at ``(std, ot_rate, dt_rate)``,
    or None when the standard rate is unknown."""
    std, ot_rate, dt_rate = rates
    if std is None:
        return None
    st, ot, dt = split
    return round(st * std + ot * (ot_rate or std * OT_MULTIPLIER)
                 + dt * (dt_rate or std * DT_MULTIPLIER), 2)
