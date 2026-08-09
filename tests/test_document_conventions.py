"""
Document conventions Larry settled on 2026-08-09.

These govern GENERATED DOCUMENTS only. The on-screen app deliberately still
shows 12-hour times — screens and client documents have different readers.
"""
import datetime as dt

import pytest


@pytest.mark.parametrize("stored,expected", [
    ("13:00", "13:00"), ("1:00 PM", "13:00"), ("8:00 AM", "08:00"),
    ("00:30", "00:30"), ("12:00 PM", "12:00"), ("", ""), (None, ""),
])
def test_generated_documents_use_24_hour(stored, expected):
    import brand
    assert brand.fmt_time(stored) == expected


def test_date_formats():
    import brand
    d = dt.date(2026, 1, 19)          # a Monday
    assert brand.fmt_date(d) == "Mon 19 Jan"
    assert brand.fmt_date(d, "short") == "1/19"
    assert brand.fmt_date(d, "full") == "Mon 19 Jan 2026"
    assert brand.fmt_date(None) == ""


def test_screens_still_show_12_hour(app):
    """The |to_12hr filter is untouched — this is a deliberate split, so if
    someone 'tidies' it later this test explains why not."""
    with app.app_context():
        assert app.jinja_env.filters["to_12hr"]("13:00") == "1:00 PM"


def test_xlsx_master_renders_24_hour_times(app, db):
    """The export that goes to a client must not carry AM/PM."""
    import re
    from models import (Show, ScheduleDay, ScheduleActivity, SubScheduleEntry,
                        AgencySetting)
    from oss_xlsx import build_workbook

    show = Show(name="Clock Show", code="CK26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 1, 19))
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="08:00",
                                    description="LOAD IN", sort_order=10))
    db.session.add(SubScheduleEntry(show_id=show.id, schedule_day_id=day.id,
                                    type="Dock", time="1:00 PM",
                                    activity="DOCK PUSH", sort_order=0))
    db.session.commit()

    ws = build_workbook(show, SubScheduleEntry.query.all(), [],
                        agency=AgencySetting.get())["Master Schedule"]
    times = [ws.cell(row=r, column=1).value for r in range(3, ws.max_row + 1)
             if ws.cell(row=r, column=2).value]
    assert "13:00" in times, times
    assert not any(re.search(r"[AP]M", str(t or ""), re.I) for t in times), times


def test_xlsx_day_banner_uses_the_house_date_format(app, db):
    from models import Show, ScheduleDay, ScheduleActivity, AgencySetting
    from oss_xlsx import build_workbook

    show = Show(name="Date Show", code="DT26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 1, 19))
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="08:00",
                                    description="LOAD IN", sort_order=10))
    db.session.commit()

    ws = build_workbook(show, [], [], agency=AgencySetting.get())["Master Schedule"]
    banners = [ws.cell(row=r, column=1).value for r in range(3, ws.max_row + 1)
               if ws.cell(row=r, column=2).value is None]
    assert "Mon 19 Jan 2026" in banners, banners
