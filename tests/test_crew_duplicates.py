"""Possible-duplicate crew records — the report, and only a report.

Found 2026-09-09: seven names existed more than once on production (Jose Mora
three times). It costs real money — the 6th/7th-consecutive-day rule and the
short-turnaround rule both resolve per `crew_member_id`, so a person split
across two records is two short weeks to the payroll rules and never one long
one, and two records can hold two different rates.

Jason's call on the day: report it, do not merge it. So the tests that matter
most here are the ones asserting nothing changes.
"""
import datetime as dt

import pytest

from crew_duplicates import find_duplicates, normalise_name, usage_by_member


def _member(db, first, last, **kw):
    from models import CrewMember
    m = CrewMember(first_name=first, last_name=last, **kw)
    db.session.add(m)
    db.session.flush()
    return m


def _booking(db, member, show_name, date, qty=1, hours=10):
    """One crew row for `member`, on its own show/day/activity."""
    from models import Show, ScheduleDay, ScheduleActivity, CrewRow
    show = Show(name=show_name)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=date)
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="8:00 AM",
                           description="CREW START", sort_order=10)
    db.session.add(act); db.session.flush()
    row = CrewRow(activity_id=act.id, crew_member_id=member.id,
                  position="A1", qty=qty, hours=hours, sort_order=1)
    db.session.add(row); db.session.flush()
    return show


# ── the matching rule ───────────────────────────────────────────────────────

def test_normalise_name_folds_case_and_whitespace():
    assert normalise_name("Jose", "Mora") == normalise_name("  jose ", "MORA")
    assert normalise_name("Jose", "Mora") == normalise_name("Jose ", " Mora")
    assert normalise_name("", "") == ""


def test_two_records_one_name_is_a_group(app, db):
    a = _member(db, "Jose", "Mora")
    b = _member(db, "jose", "mora")
    other = _member(db, "Larry", "Kargol")
    db.session.commit()

    groups = find_duplicates([a, b, other])
    assert len(groups) == 1
    assert groups[0]["name"] in ("Jose Mora", "jose mora")
    assert groups[0]["count"] == 2
    assert {r["member"].id for r in groups[0]["records"]} == {a.id, b.id}


def test_a_unique_name_is_not_reported(app, db):
    a = _member(db, "Larry", "Kargol")
    b = _member(db, "Kevin", "Leckey")
    db.session.commit()
    assert find_duplicates([a, b]) == []


def test_stand_ins_are_not_duplicates_of_each_other(app, db):
    """After the punctuation rule there are dozens of TBDs. They are not a person."""
    tbds = [_member(db, "TBD", "") for _ in range(4)]
    dots = [_member(db, ".", ".") for _ in range(3)]
    db.session.commit()
    assert find_duplicates(tbds + dots) == []


def test_a_blank_name_is_skipped(app, db):
    blanks = [_member(db, "", ""), _member(db, "", "")]
    db.session.commit()
    assert find_duplicates(blanks) == []


# ── the evidence beside each record ─────────────────────────────────────────

def test_usage_counts_shows_rows_and_hours(app, db):
    a = _member(db, "Dakota", "Wagenbrenner")
    _booking(db, a, "Show One", dt.date(2026, 10, 19), qty=1, hours=11)
    _booking(db, a, "Show Two", dt.date(2026, 10, 20), qty=2, hours=10)
    db.session.commit()

    usage = usage_by_member([a.id])
    assert usage[a.id]["shows"] == 2
    assert usage[a.id]["rows"] == 2
    assert usage[a.id]["hours"] == 31.0        # 11 + (10 × 2)


def test_an_unused_record_reports_zeroes(app, db):
    a = _member(db, "Chris", "Dallos")
    b = _member(db, "Chris", "Dallos")
    _booking(db, a, "Busy Show", dt.date(2026, 10, 19))
    db.session.commit()

    groups = find_duplicates([a, b])
    records = groups[0]["records"]
    # Most-used first, so the keeper is at the top and the empty one below.
    assert records[0]["member"].id == a.id
    assert records[0]["shows"] == 1
    assert records[1]["member"].id == b.id
    assert records[1]["shows"] == 0
    assert records[1]["rows"] == 0
    assert records[1]["hours"] == 0.0


def test_groups_are_ordered_biggest_first(app, db):
    trio = [_member(db, "Jose", "Mora") for _ in range(3)]
    pair = [_member(db, "Kevin", "Leckey") for _ in range(2)]
    db.session.commit()

    groups = find_duplicates(trio + pair)
    assert [g["count"] for g in groups] == [3, 2]


# ── it is a report ──────────────────────────────────────────────────────────

def test_find_duplicates_changes_nothing(app, db):
    """The whole point: no merge, no delete, no rename."""
    a = _member(db, "Jose", "Mora", rate_standard=45.0)
    b = _member(db, "Jose", "Mora", rate_standard=50.0)
    _booking(db, a, "Some Show", dt.date(2026, 10, 19))
    db.session.commit()

    from models import CrewMember, CrewRow
    before_members = CrewMember.query.count()
    before_rows = CrewRow.query.count()

    find_duplicates(CrewMember.query.all())

    assert CrewMember.query.count() == before_members
    assert CrewRow.query.count() == before_rows
    assert a.rate_standard == 45.0
    assert b.rate_standard == 50.0
    assert (a.first_name, a.last_name) == ("Jose", "Mora")


# ── on the page ─────────────────────────────────────────────────────────────

def test_the_panel_appears_only_when_there_are_duplicates(app, client, db):
    from models import CrewMember

    _member(db, "Larry", "Kargol")
    db.session.commit()
    body = client.get("/crew/").get_data(as_text=True)
    assert "on more than one record" not in body

    _member(db, "Larry", "Kargol")
    db.session.commit()
    body = client.get("/crew/").get_data(as_text=True)
    assert "on more than one record" in body
    assert "Larry Kargol" in body


def test_the_panel_does_not_break_an_empty_database(app, client, db):
    r = client.get("/crew/")
    assert r.status_code == 200
