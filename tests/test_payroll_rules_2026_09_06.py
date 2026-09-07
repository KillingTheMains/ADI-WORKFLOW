"""Short turnaround, 6th/7th day, rate units, the company rate card and the
Hours Report's cost toggle — Jason's answers of 2026-09-06.

    Short turn: under 8 hours off between a shift's out time and the next
    day's call -> the whole next shift at OT. Threshold person -> company
    -> default 8. Across days only. Named crew only.
    6th/7th day: from the sixth consecutive calendar day with a call, within
    one show, all day at OT; any day off resets, and so does Monday
    (Jason, 09-07: the week is Mon–Sun). Named crew only.
    DT still after the DT threshold on a flagged day. No stacking.
    Out time = call time + hours (actual where recorded, else estimate).
    A standard rate may be typed as a 10-hour day rate; billing converts.
    Local labor money comes from the company's rate card, per position.
    Money shows only behind ?cost=1.
"""
import datetime as dt

import pytest

import billing


D0 = dt.date(2026, 9, 8)


def _d(i):
    return D0 + dt.timedelta(days=i)


# ── billing.day_flags ────────────────────────────────────────────────────────

def test_short_turn_when_under_eight_hours_off():
    # 08:00 + 18h = 02:00 next day; next call 07:00 -> 5h off
    f = billing.day_flags([(_d(0), "08:00", 18), (_d(1), "07:00", 10)])
    assert f[_d(0)]["short_turn"] is False
    assert f[_d(1)]["short_turn"] is True
    assert round(f[_d(1)]["gap_hours"], 1) == 5.0


def test_exactly_eight_hours_off_is_not_short_turn():
    f = billing.day_flags([(_d(0), "08:00", 15), (_d(1), "07:00", 10)])  # out 23:00, in 07:00
    assert f[_d(1)]["short_turn"] is False


def test_the_threshold_is_a_parameter():
    f = billing.day_flags([(_d(0), "08:00", 15), (_d(1), "07:00", 10)], short_turn_after=9)
    assert f[_d(1)]["short_turn"] is True


def test_two_calls_on_one_day_are_one_working_day():
    """Across days only (Jason): the gap between a 06:00 load-in and a
    18:00 show call on the same date is not a short turn — but the day's
    out is the LATER call's out, so the next morning can be."""
    f = billing.day_flags([(_d(0), "06:00", 8), (_d(0), "18:00", 6),
                           (_d(1), "07:00", 10)])
    assert f[_d(0)]["short_turn"] is False
    assert f[_d(1)]["short_turn"] is True          # out 00:00, in 07:00 -> 7h


def test_a_day_off_breaks_both_rules():
    shifts = [(_d(i), "08:00", 18) for i in range(3)] + [(_d(4), "08:00", 8)]
    f = billing.day_flags(shifts)
    assert f[_d(1)]["short_turn"] and f[_d(2)]["short_turn"]
    assert f[_d(4)]["short_turn"] is False        # a day off in between
    assert f[_d(4)]["streak"] == 1


def test_sixth_day_is_flagged_and_a_day_off_resets():
    """D0 is a Tuesday: Tue..Sun is six straight days, Sunday the 6th.
    The Monday after (index 6) is a new week — see the Monday tests below.
    Skip Tuesday (index 7); Wednesday and Thursday restart at 1, 2."""
    shifts = [(_d(i), "08:00", 8) for i in range(7)] + [(_d(8), "08:00", 8), (_d(9), "08:00", 8)]
    f = billing.day_flags(shifts)
    assert [f[_d(i)]["sixth_day"] for i in range(6)] == [False] * 5 + [True]
    assert f[_d(8)]["streak"] == 1 and f[_d(8)]["sixth_day"] is False
    assert f[_d(9)]["streak"] == 2


# ── the week resets on Monday (Jason, 2026-09-07) ───────────────────────────
#
# "It is consecutive days for sure" — and the week runs Monday to Sunday, so
# Monday starts the count over even with no day off. The 7th day is OT, the
# same as the 6th.

MON = dt.date(2026, 9, 7)
assert MON.weekday() == 0


def _week(*offsets):
    return [(MON + dt.timedelta(days=i), "08:00", 8) for i in offsets]


def test_monday_to_sunday_flags_saturday_and_sunday_then_monday_is_normal():
    f = billing.day_flags(_week(*range(8)))            # Mon..Sun, next Mon
    flagged = [f[MON + dt.timedelta(days=i)]["sixth_day"] for i in range(8)]
    assert flagged == [False] * 5 + [True, True, False]
    assert f[MON + dt.timedelta(days=7)]["streak"] == 1


def test_tuesday_to_sunday_flags_sunday_only():
    f = billing.day_flags(_week(*range(1, 8)))         # Tue..Sun, next Mon
    assert f[MON + dt.timedelta(days=6)]["sixth_day"] is True     # Sunday
    assert f[MON + dt.timedelta(days=5)]["sixth_day"] is False    # Saturday
    assert f[MON + dt.timedelta(days=7)]["sixth_day"] is False    # Monday


def test_monday_then_wednesday_to_sunday_flags_nothing():
    """Rule B: the Tuesday off resets, so Wed..Sun is a run of five and
    Sunday is a normal day even though six days were worked that week."""
    f = billing.day_flags(_week(0, 2, 3, 4, 5, 6))
    assert not any(v["sixth_day"] for v in f.values())
    assert f[MON + dt.timedelta(days=6)]["streak"] == 5


def test_a_streak_never_passes_seven():
    f = billing.day_flags(_week(*range(21)))           # three straight weeks
    assert max(v["streak"] for v in f.values()) == 7
    assert sum(v["sixth_day"] for v in f.values()) == 6   # Sat+Sun x 3


def test_short_turn_still_looks_across_a_monday():
    sun, mon = MON + dt.timedelta(days=6), MON + dt.timedelta(days=7)
    f = billing.day_flags([(sun, "08:00", 18), (mon, "07:00", 10)])
    assert f[mon]["short_turn"] is True
    assert f[mon]["streak"] == 1


def test_a_row_with_no_call_time_still_counts_toward_the_streak():
    shifts = [(_d(i), None, 8) for i in range(6)]
    f = billing.day_flags(shifts)
    assert f[_d(5)]["sixth_day"] is True
    assert f[_d(5)]["short_turn"] is False        # no clock, no gap


# ── billing.split_day_flagged / short_turn_for / cost_of / rates ────────────

def test_a_flagged_day_is_all_ot_until_dt():
    assert billing.split_day_flagged(8, all_ot=True) == (0.0, 8.0, 0.0)
    assert billing.split_day_flagged(14, all_ot=True) == (0.0, 12.0, 2.0)
    assert billing.split_day_flagged(14, dt_after=13, all_ot=True) == (0.0, 13.0, 1.0)
    assert billing.split_day_flagged(14) == billing.split_day(14)


def test_short_turn_threshold_resolves_person_company_default():
    class Co:  short_turn_hours = 9
    class Me:  short_turn_hours = None; company = Co()
    class Own: short_turn_hours = 10; company = Co()
    assert billing.short_turn_for() == 8.0
    assert billing.short_turn_for(Me()) == 9.0
    assert billing.short_turn_for(Own()) == 10.0
    assert billing.short_turn_for(None, Co()) == 9.0


def test_a_day_rate_is_converted_to_hourly():
    class M: rate_standard = 900; rate_unit = "day"; rate_ot = None; rate_dt = None
    assert billing.rates_for(M()) == (90.0, 135.0, 180.0)
    M.rate_unit = "hourly"
    assert billing.rates_for(M())[0] == 900.0


def test_cost_of_prices_the_split():
    assert billing.cost_of((10, 2, 1), (100, None, None)) == 10 * 100 + 2 * 150 + 1 * 200
    assert billing.cost_of((10, 2, 1), (100, 160, 210)) == 1000 + 320 + 210
    assert billing.cost_of((10, 0, 0), (None, None, None)) is None


# ── the report ───────────────────────────────────────────────────────────────

def _show(db, code):
    from models import Show
    show = Show(name="Payroll " + code, code=code)
    db.session.add(show); db.session.flush()
    return show


def _call(db, show, i, time, hours, member, actual=None):
    from models import ScheduleDay, ScheduleActivity, CrewRow
    day = ScheduleDay.query.filter_by(show_id=show.id, date=_d(i)).first()
    if day is None:
        day = ScheduleDay(show_id=show.id, date=_d(i))
        db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time=time, description="CREW START", sort_order=1)
    db.session.add(act); db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=member.id, qty=1,
                           hours=hours, actual_hours=actual, sort_order=2))
    db.session.flush()
    return day


def _member(db, first, last, company=None, **kw):
    from models import CrewMember
    m = CrewMember(first_name=first, last_name=last,
                   company_id=company.id if company else None, **kw)
    db.session.add(m); db.session.flush()
    return m


def _get(client, show, **params):
    return client.get(f"/shows/{show.id}/crew/hours", query_string=params).get_data(as_text=True)


def test_report_marks_a_short_turn_day_and_charges_it_at_ot(app, client, db):
    show = _show(db, "PR1")
    m = _member(db, "Short", "Turn PR1")
    _call(db, show, 0, "08:00", 18, m)         # out 02:00
    _call(db, show, 1, "07:00", 10, m)         # 5h off -> whole day OT
    db.session.commit()
    html = _get(client, show)
    assert ">ST</sup>" in html
    assert "1 short-turn day" in html
    # day 1: 10 ST + 2 OT + 6 DT ; day 2 flagged: 0 ST + 10 OT
    assert "ST <strong>10.0</strong>" in html
    assert "OT <strong>12.0</strong>" in html
    assert "DT <strong>6.0</strong>" in html


def test_a_recorded_actual_moves_the_out_time(app, client, db):
    """The estimate said 18 hours (out 02:00); the actual says 12 (out 20:00)
    — 11 hours off, not a short turn."""
    show = _show(db, "PR2")
    m = _member(db, "Actual", "Wins PR2")
    _call(db, show, 0, "08:00", 18, m, actual=12)
    _call(db, show, 1, "07:00", 10, m)
    db.session.commit()
    html = _get(client, show)
    assert ">ST</sup>" not in html


def test_the_persons_own_short_turn_threshold_is_used(app, client, db):
    show = _show(db, "PR3")
    m = _member(db, "Own", "Threshold PR3", short_turn_hours=12)
    _call(db, show, 0, "08:00", 12, m)         # out 20:00
    _call(db, show, 1, "07:00", 10, m)         # 11h off: fine at 8, short at 12
    db.session.commit()
    html = _get(client, show)
    assert ">ST</sup>" in html
    assert "under 12 hours off" in html


def test_local_labor_gets_neither_rule(app, client, db):
    """A body is per call. Six straight 18-hour days of local labor are six
    separate crews; no short turn, no sixth day."""
    from models import Position, CrewRow, ScheduleDay, ScheduleActivity
    show = _show(db, "PR4")
    pos = Position(title="Hand PR4", department="Lighting", is_local_labor=True)
    db.session.add(pos); db.session.flush()
    for i in range(7):
        day = ScheduleDay(show_id=show.id, date=_d(i)); db.session.add(day); db.session.flush()
        act = ScheduleActivity(day_id=day.id, time="08:00", description="CREW START", sort_order=1)
        db.session.add(act); db.session.flush()
        db.session.add(CrewRow(activity_id=act.id, position_id=pos.id, position=pos.title,
                               qty=4, hours=18, crew_type="Local Crew", sort_order=2))
    db.session.commit()
    html = _get(client, show)
    assert ">ST</sup>" not in html and ">6+</sup>" not in html
    assert "short-turn day" not in html
    # 7 days x 4 bodies x (10 ST + 2 OT + 6 DT)
    assert "ST <strong>280.0</strong>" in html


def test_no_money_without_the_toggle_and_money_with_it(app, client, db):
    from models import Company
    co = Company(name="Cost Co PR5"); db.session.add(co); db.session.flush()
    show = _show(db, "PR5")
    m = _member(db, "Paid", "Person PR5", co, rate_standard=100)
    n = _member(db, "Unpaid", "Person PR5", co)
    _call(db, show, 0, "08:00", 12, m)         # 10 ST + 2 OT = 1000 + 300
    _call(db, show, 0, "08:00", 8, n)
    db.session.commit()
    plain = _get(client, show)
    assert "$1,300.00" not in plain
    assert "Show cost" in plain
    costed = _get(client, show, cost=1)
    assert "$1,300.00" in costed
    assert "no rate" in costed                  # Unpaid has none
    assert "Hide cost" in costed
    assert "Labor Cost" in costed


def test_a_day_rate_on_the_record_is_priced_hourly(app, client, db):
    show = _show(db, "PR6")
    m = _member(db, "Day", "Rate PR6", rate_standard=1000, rate_unit="day")
    _call(db, show, 0, "08:00", 10, m)
    db.session.commit()
    assert "$1,000.00" in _get(client, show, cost=1)


def test_local_labor_is_priced_from_the_company_rate_card(app, client, db):
    from models import Company, CompanyPositionRate, Position, CrewRow, ScheduleDay, ScheduleActivity
    co = Company(name="Card Co PR7"); db.session.add(co); db.session.flush()
    pos = Position(title="Hand PR7", department="Lighting", is_local_labor=True)
    other = Position(title="Rigger PR7", department="Rigging", is_local_labor=True)
    db.session.add_all([pos, other]); db.session.flush()
    db.session.add(CompanyPositionRate(company_id=co.id, position_id=pos.id, rate_standard=50))
    show = _show(db, "PR7")
    day = ScheduleDay(show_id=show.id, date=_d(0)); db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00", description="CREW START", sort_order=1)
    db.session.add(act); db.session.flush()
    hdr = CrewRow(activity_id=act.id, is_group_header=True, qty=0, sort_order=1,
                  group_label=co.name, company_id=co.id)
    db.session.add(hdr)
    db.session.add(CrewRow(activity_id=act.id, position_id=pos.id, position=pos.title,
                           qty=2, hours=12, crew_type="Local Crew", sort_order=2))
    db.session.add(CrewRow(activity_id=act.id, position_id=other.id, position=other.title,
                           qty=1, hours=8, crew_type="Local Crew", sort_order=3))
    db.session.commit()
    html = _get(client, show, cost=1)
    # 2 bodies x (10 x 50 + 2 x 75) = 1,300
    assert "$1,300.00" in html
    assert "no rate" in html                    # the rigger has no card entry


# ── the rate card page and the forms ────────────────────────────────────────

def test_rate_card_page_lists_catalogue_positions_and_saves(app, client, db):
    from models import Company, CompanyPositionRate, Position
    co = Company(name="Card Page PR8"); db.session.add(co); db.session.flush()
    pos = Position(title="Hand PR8", department="Lighting", is_local_labor=True)
    db.session.add(pos); db.session.commit()
    html = client.get(f"/crew/companies/{co.id}/rates").get_data(as_text=True)
    assert "Hand PR8" in html
    r = client.post(f"/crew/companies/{co.id}/rates/{pos.id}",
                    data={"rate_standard": "$52.50"}, headers={"X-Autosave": "1"})
    assert r.status_code == 204
    assert CompanyPositionRate.query.filter_by(company_id=co.id, position_id=pos.id).one().rate_standard == 52.5
    # blank clears
    client.post(f"/crew/companies/{co.id}/rates/{pos.id}", data={"rate_standard": ""},
                headers={"X-Autosave": "1"})
    assert CompanyPositionRate.query.filter_by(company_id=co.id, position_id=pos.id).one().rate_standard is None
    # and the companies page links to it
    companies = client.get("/crew/companies").get_data(as_text=True)
    assert f"/crew/companies/{co.id}/rates" in companies
    assert "Short turn" in companies


def test_company_short_turn_saves(app, client, db):
    from models import Company
    co = Company(name="Terms PR9"); db.session.add(co); db.session.commit()
    client.post(f"/crew/companies/{co.id}/terms", data={"short_turn_hours": "9"},
                headers={"X-Autosave": "1"})
    assert Company.query.get(co.id).short_turn_hours == 9.0


def test_crew_form_saves_rate_unit_and_short_turn(app, client, db):
    from models import CrewMember
    client.post("/crew/add", data={"first_name": "Form", "last_name": "Fields PR10",
                                   "rate_standard": "950", "rate_unit": "day",
                                   "short_turn_hours": "10"})
    m = CrewMember.query.filter_by(last_name="Fields PR10").one()
    assert (m.rate_unit, m.rate_standard, m.short_turn_hours) == ("day", 950.0, 10.0)
    client.post(f"/crew/{m.id}/edit", data={"first_name": "Form", "last_name": "Fields PR10",
                                            "rate_standard": "95", "rate_unit": "bogus",
                                            "short_turn_hours": ""})
    m = CrewMember.query.get(m.id)
    assert (m.rate_unit, m.short_turn_hours) == ("hourly", None)


def test_the_three_columns_are_registered_for_migration():
    from migrations import MIGRATIONS
    cols = {(t, c) for t, c, _ in MIGRATIONS}
    assert ("crew_members", "short_turn_hours") in cols
    assert ("companies", "short_turn_hours") in cols
    assert ("crew_members", "rate_unit") in cols
