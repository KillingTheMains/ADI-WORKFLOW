"""
Client-facing Master OSS PDF.

The reason this is generated natively rather than through a browser's print
dialog is pagination, so that is what most of these tests are about: a day
that runs past the foot of a page must be labelled "continued", column headers
must repeat, and a short day must never be broken at all.
"""
import datetime as dt
import io

import pytest


def _pages(show, entries, meals=(), agency=None):
    """Render and return a list of per-page text."""
    pypdf = pytest.importorskip("pypdf")
    from oss_pdf import build_pdf
    buf = io.BytesIO()
    build_pdf(buf, show, list(entries), list(meals), agency=agency)
    buf.seek(0)
    return [p.extract_text() or "" for p in pypdf.PdfReader(buf).pages]


def _long_day_show(db, n_items=70):
    from models import Show, ScheduleDay, ScheduleActivity, SubScheduleEntry
    show = Show(name="Paginate Show", code="PG26", room_name="Main Hall")
    db.session.add(show); db.session.flush()
    busy = ScheduleDay(show_id=show.id, date=dt.date(2026, 1, 19))
    quiet = ScheduleDay(show_id=show.id, date=dt.date(2026, 1, 20))
    db.session.add_all([busy, quiet]); db.session.flush()
    depts = ["Dock", "Hazer", "Doors", "Security", "House LX"]
    for i in range(n_items):
        hh, mm = divmod(360 + i * 12, 60)
        db.session.add(SubScheduleEntry(
            show_id=show.id, schedule_day_id=busy.id, type=depts[i % len(depts)],
            time="%02d:%02d" % (hh % 24, mm), sort_order=i,
            activity=f"Item {i:02d} — long enough to wrap onto a second line"))
    db.session.add(ScheduleActivity(day_id=quiet.id, time="09:00",
                                    description="QUIET DAY ONLY ITEM",
                                    sort_order=1))
    db.session.commit()
    return show


def test_route_returns_a_pdf(app, client, db):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Route Show", code="RT26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 1, 19))
    db.session.add(day); db.session.flush()
    db.session.add(ScheduleActivity(day_id=day.id, time="08:00",
                                    description="LOAD IN", sort_order=1))
    db.session.commit()

    r = client.get("/shows/%d/oss/master.pdf" % show.id)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"
    assert "RT26_Master_Schedule_" in r.headers["Content-Disposition"]


def test_a_day_that_spans_pages_is_labelled_continued(app, db):
    """The thing browser print-to-PDF cannot do."""
    from models import SubScheduleEntry
    show = _long_day_show(db)
    pages = _pages(show, SubScheduleEntry.query.all())
    assert len(pages) > 3, "70 items should not fit on one page"

    day_pages = [i for i, t in enumerate(pages, 1) if "Mon 19 Jan 2026" in t]
    continued = {i for i, t in enumerate(pages, 1) if "continued" in t}
    assert len(day_pages) > 1, "the busy day should span pages"
    # Every page the day runs onto after the first must be labelled. The
    # department sections later in the document legitimately carry their own
    # continuation labels too, hence a subset rather than an equality check.
    assert set(day_pages[1:]).issubset(continued), (day_pages, sorted(continued))


def test_the_first_page_of_a_day_is_not_labelled_continued(app, db):
    from models import SubScheduleEntry
    show = _long_day_show(db)
    pages = _pages(show, SubScheduleEntry.query.all())
    first = next(i for i, t in enumerate(pages) if "Mon 19 Jan 2026" in t)
    assert "continued" not in pages[first]


def test_column_headers_repeat_on_every_continuation_page(app, db):
    from models import SubScheduleEntry
    show = _long_day_show(db)
    pages = _pages(show, SubScheduleEntry.query.all())
    for i, text in enumerate(pages, 1):
        if "Mon 19 Jan 2026" in text:
            assert "Dept" in text and "Item" in text, \
                f"page {i} carries schedule rows but no column header"


def test_a_short_day_is_never_split(app, db):
    """Two items must not be torn across a page boundary."""
    from models import SubScheduleEntry
    show = _long_day_show(db)
    pages = _pages(show, SubScheduleEntry.query.all())
    # Skip the cover — it carries the date span "Mon 19 Jan – Tue 20 Jan 2026"
    # and would otherwise match.
    start = next(i for i, t in enumerate(pages) if "Schedule by day" in t)
    body = pages[start:]
    hits = [i for i, t in enumerate(body) if "QUIET DAY ONLY ITEM" in t]
    quiet_header = [i for i, t in enumerate(body) if "Tue 20 Jan 2026" in t]
    # The quiet day's header and its only row belong on the same page.
    assert hits and quiet_header
    assert quiet_header[0] in hits, (quiet_header, hits)
    # And it is never itself labelled as a continuation. Checked as the exact
    # rendered string — a page can legitimately hold the tail of the busy day
    # (which IS labelled) and the whole of the quiet one.
    assert not any("Tue 20 Jan 2026 · continued" in t for t in body)


def test_times_are_24_hour_throughout(app, db):
    import re
    from models import SubScheduleEntry
    show = _long_day_show(db, n_items=6)
    body = "\n".join(_pages(show, SubScheduleEntry.query.all()))
    assert "06:00" in body
    assert not re.search(r"\d\s?[AP]M\b", body), "found a 12-hour time"


def test_document_has_cover_glance_days_and_departments(app, db):
    from models import SubScheduleEntry
    show = _long_day_show(db, n_items=8)
    pages = _pages(show, SubScheduleEntry.query.all())
    body = "\n".join(pages)
    assert "Master Schedule" in pages[0] and "Main Hall" in pages[0]
    assert "DEPARTMENT KEY" in pages[0]
    assert "At a glance" in body
    assert "Schedule by day" in body
    assert "Schedule by department" in body


def test_empty_show_still_renders(app, db):
    from models import Show
    show = Show(name="Empty Show", code="EM26")
    db.session.add(show); db.session.commit()
    pages = _pages(show, [])
    assert pages and "No schedule items yet." in "\n".join(pages)
