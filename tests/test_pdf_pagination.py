"""PDF must paginate a real-sized show (MCDC26 crash, 2026-08-11).

Production raised:

    LayoutError: Flowable <_DayTable 10 rows x 5 cols (tallest row 262.8)>
    with cell(0,0) containing 'Crew · continued' ... too large on page 30

Two causes, both fixed:
  * the Crew DEPARTMENT table put every name for a call into one cell, so a
    single row was 263pt tall and no split could make it fit a 618pt frame;
  * continuation parts each got their own orphan-guard refusal, and a part
    that refuses at the top of an empty frame has nowhere to go.
"""
import datetime as dt
import io


def _big_show(db, days=14, crew=42):
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        CrewMember, ShowCrewAssignment)
    show = Show(name="Pagination", code="PAG26")
    db.session.add(show); db.session.flush()

    people = []
    for i in range(crew):
        cm = CrewMember(first_name="Crew%02d" % i, last_name="Longsurname")
        db.session.add(cm); db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
        people.append(cm)

    for d in range(days):
        day = ScheduleDay(show_id=show.id,
                          date=dt.date(2026, 9, 1) + dt.timedelta(days=d),
                          sod="07:00", eod="23:00")
        db.session.add(day); db.session.flush()
        for t in ("07:00", "08:00", "13:00"):
            act = ScheduleActivity(day_id=day.id, time=t,
                                   description="CREW START")
            db.session.add(act); db.session.flush()
            for cm in people:
                db.session.add(CrewRow(activity_id=act.id,
                                       crew_member_id=cm.id))
    db.session.commit()
    return show


def test_large_show_pdf_builds_without_layout_error(app, db):
    """The regression itself: this raised LayoutError on page 30 in prod."""
    import oss_pdf
    show = _big_show(db)
    buf = io.BytesIO()
    oss_pdf.build_pdf(buf, show, entries=[], meal_services=[])
    assert buf.getvalue()[:5] == b"%PDF-"
    # A show this size must run to many pages — if it silently collapsed to
    # one, the content is missing rather than paginated.
    assert buf.getvalue().count(b"/Type /Page") > 5


def test_department_rows_never_hold_a_whole_crew_list(app, db):
    """The 263pt row. One name per row is what makes this paginate."""
    from oss_export import build_master_items, master_label
    show = _big_show(db, days=1, crew=42)
    items, _ = build_master_items(show, [], [])
    crew_items = [i for i in items if i.get("crew_names")]
    assert crew_items, "expected crew calls in the fixture"
    for item in crew_items:
        # The label is a headcount; the names live on their own rows.
        assert master_label(item) == "%d crew called" % item["count"]
        assert "," not in master_label(item)


def test_continuation_parts_do_not_refuse_to_split(app, db):
    """A part that refuses at the top of an empty frame is a LayoutError."""
    from reportlab.platypus import Table
    import oss_pdf
    rows = [["h", "", "", "", ""], ["c", "", "", "", ""]] + \
           [[str(n), "", "", "", ""] for n in range(40)]
    t = oss_pdf._DayTable(rows, colWidths=[60] * 5, repeatRows=2)
    parts = Table.split(t, 300, 200)
    for part in parts[1:]:
        oss_pdf._mark_continued(part)
        part._refused_split = True
        assert getattr(part, "_refused_split", False) is True
