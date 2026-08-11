"""Crew names render one per row (note 5, 2026-08-11).

Larry wants the show book's tall call-sheet list everywhere. The headcount
stays as the row above — it is load-bearing in the workflow.
"""
from oss_export import master_label


def test_crew_row_reads_as_a_headcount():
    item = {"source": "crew", "count": 11, "activity": "A, B, C"}
    assert master_label(item) == "11 crew called"


def test_singular_crew_row():
    assert master_label({"source": "crew", "count": 1, "activity": "A"}) == \
        "1 crew called"


def test_non_crew_rows_keep_their_own_label():
    item = {"source": "activity", "count": None, "activity": "LOAD IN"}
    assert master_label(item) == "LOAD IN"


def test_the_exports_agree_on_the_label():
    """Regression: the XLSX printed a headcount while the PDF printed the
    full comma-joined name list for the same event."""
    import oss_pdf, oss_xlsx
    assert oss_pdf.master_label is master_label
    assert oss_xlsx.master_label is master_label


def test_xlsx_master_writes_one_row_per_name(app, db, tmp_path):
    """The names appear beneath the headcount, not joined into one cell."""
    import datetime as dt
    from models import (Show, ScheduleDay, ScheduleActivity, CrewRow,
                        CrewMember, ShowCrewAssignment)
    import openpyxl, oss_xlsx

    show = Show(name="Names Show", code="NAM26")
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 5), sod="07:00")
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="07:00",
                           description="CREW START")
    db.session.add(act); db.session.flush()
    for f, l in [("Ann", "One"), ("Bob", "Two")]:
        cm = CrewMember(first_name=f, last_name=l)
        db.session.add(cm); db.session.flush()
        db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
        db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id))
    db.session.commit()

    path = tmp_path / "m.xlsx"
    wb = oss_xlsx.build_workbook(show, entries=[], meal_services=[])
    wb.save(path)

    ws = openpyxl.load_workbook(path)["Master Schedule"]
    col_c = [c.value for c in ws["C"] if c.value]
    assert "2 crew called" in col_c
    assert "Ann One" in col_c and "Bob Two" in col_c
    # Not squashed into a single cell.
    assert not any(v and "," in str(v) and "Ann One" in str(v) for v in col_c)
