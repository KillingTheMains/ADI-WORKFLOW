"""Fourteen riggers must not look like one person named "14 × Rigger".

oss_export appended a local-labour line to the SAME `names` list as a person:

    if row.crew_member_id:
        names.append(who)          # "Ann One"
        continue
    names.append(line_label(...))  # "14 × Rigger"   <- same list

Everything downstream read that list. So on the master tab, in the client PDF
and in the XLSX, "14 × Rigger" rendered identically to a person's name — one
indented row under "N crew called", no code, no count of its own. Fourteen
humans and one human were the same shape on the page.

The day page fixed this in e076de1 and again in sitting 3, where local labour
is its own block with the LL chip, a 45° hatch and a headcount in the header.
The exports never got it. These tests are that fix.

The headcount was never wrong — `crew_headcount` counts qty, and
test_headcount_counts_people covers it. This is entirely about what a reader
sees.
"""
import datetime as dt

import pytest

from oss_export import build_master_items


def _show(db, code="LLN26"):
    from models import Show, ScheduleDay, ScheduleActivity
    show = Show(name="Split Show", code=code)
    show.uses_new_breaks = True
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 21),
                      sod="07:00", eod="19:00")
    db.session.add(day)
    db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="08:00",
                           description="CREW START", sort_order=10)
    db.session.add(act)
    db.session.commit()
    return show, day, act


def _person(db, show, act, first="Ann", last="One"):
    from models import CrewMember, CrewRow, ShowCrewAssignment
    cm = CrewMember(first_name=first, last_name=last, active=True)
    db.session.add(cm)
    db.session.flush()
    db.session.add(ShowCrewAssignment(show_id=show.id, crew_member_id=cm.id))
    db.session.add(CrewRow(activity_id=act.id, crew_member_id=cm.id))
    db.session.commit()
    return cm


def _local(db, act, title="Rigger", qty=14, task=None):
    from models import CrewRow, Position
    pos = Position.query.filter_by(title=title).first()
    if pos is None:
        pos = Position(title=title, department="Rigging", type="hand",
                       is_local_labor=True)
        db.session.add(pos)
        db.session.flush()
    db.session.add(CrewRow(activity_id=act.id, position_id=pos.id,
                           position=title, qty=qty, task=task))
    db.session.commit()
    return pos


def _crew_item(show):
    from models import MealService, SubScheduleEntry
    entries = SubScheduleEntry.query.filter_by(show_id=show.id).all()
    meals = MealService.query.filter_by(show_id=show.id).all()
    items, _ = build_master_items(show, entries, meals)
    crew = [i for i in items if i.get("source") == "crew"]
    assert len(crew) == 1
    return crew[0]


# ── The assembly ─────────────────────────────────────────────────────────

def test_a_person_is_a_name_and_a_position_count_is_not(app, db):
    show, day, act = _show(db)
    _person(db, show, act)
    _local(db, act, "Rigger", 14)
    item = _crew_item(show)
    assert item["crew_names"] == ["Ann One"]
    assert [l["label"] for l in item["local_lines"]] == ["14 × Rigger"]


def test_the_local_line_carries_its_own_headcount(app, db):
    """The number is what the block exists to get right; it should not have
    to be parsed back out of the label."""
    show, day, act = _show(db)
    _local(db, act, "Lighting Hand", 7, task="Catwalk Strike")
    line, = _crew_item(show)["local_lines"]
    assert line["qty"] == 7
    assert line["position"] == "Lighting Hand"
    assert line["task"] == "Catwalk Strike"


def test_the_qty_agrees_with_the_label(app, db):
    """Two readings of the same field disagreed once already."""
    show, day, act = _show(db)
    _local(db, act, "Rigger", 14)
    line, = _crew_item(show)["local_lines"]
    assert line["label"].startswith("%d × " % line["qty"])


def test_a_call_that_is_entirely_local_labour_still_appears(app, db):
    """Four riggers and no named lead. The guard used to be `if not names:
    continue`, which only worked because the local lines were IN names —
    splitting them out without moving the guard would have deleted the whole
    call from the client master."""
    show, day, act = _show(db)
    _local(db, act, "Rigger", 4)
    item = _crew_item(show)
    assert item["crew_names"] == []
    assert item["count"] == 4


def test_two_lines_of_one_position_stay_two_lines(app, db):
    """Twelve hanging and six striking are two crews doing two jobs."""
    show, day, act = _show(db)
    _local(db, act, "Lighting Hand", 12, task="Hang / Circuit")
    _local(db, act, "Lighting Hand", 6, task="Catwalk Strike")
    lines = _crew_item(show)["local_lines"]
    assert sorted(l["qty"] for l in lines) == [6, 12]


def test_the_one_line_summary_still_names_both(app, db):
    """`activity` is what a surface holding only this field shows, so nothing
    may vanish from it. The SHAPE is what separates now, not the contents."""
    show, day, act = _show(db)
    _person(db, show, act)
    _local(db, act, "Rigger", 14)
    activity = _crew_item(show)["activity"]
    assert "Ann One" in activity
    assert "14 × Rigger" in activity


# ── What each surface renders ────────────────────────────────────────────

def test_the_master_tab_gives_it_the_local_labour_treatment(app, client, db):
    show, day, act = _show(db)
    _person(db, show, act)
    _local(db, act, "Rigger", 14, task="Pin / Bolt")
    body = client.get("/shows/%d/oss?tab=master" % show.id).get_data(as_text=True)
    assert 'title="local"' in body                      # the LL chip
    assert "border-left:2px solid var(--adi-kind-local);" in body
    assert "repeating-linear-gradient(45deg" in body    # multiples, not people
    # The person gets none of it.
    assert "Ann One" in body


def test_the_master_tab_prints_the_count_in_the_count_column(app, client, db):
    show, day, act = _show(db)
    _local(db, act, "Rigger", 14)
    body = client.get("/shows/%d/oss?tab=master" % show.id).get_data(as_text=True)
    row = body[body.index('class="oss-master-local-row"'):]
    row = row[:row.index("</tr>")]
    assert ">14<" in row.replace(" ", "").replace("\n", "")


def test_the_xlsx_codes_the_line_LL(app, db, tmp_path):
    import openpyxl
    import oss_xlsx
    show, day, act = _show(db)
    _person(db, show, act)
    _local(db, act, "Rigger", 14)
    path = tmp_path / "m.xlsx"
    oss_xlsx.build_workbook(show, entries=[], meal_services=[]).save(path)
    ws = openpyxl.load_workbook(path)["Master Schedule"]

    rows = [[c.value for c in r] for r in ws.iter_rows(min_col=1, max_col=5)]
    local = [r for r in rows if r[3] and "× Rigger" in str(r[3])]
    assert len(local) == 1
    assert local[0][0] == "LL", "the code column is the only channel on paper"
    assert local[0][4] == "14 crew"
    # A person is still a person: no code, no count.
    person = [r for r in rows if r[3] == "Ann One"]
    assert len(person) == 1
    assert not person[0][0]


def test_the_pdf_codes_the_line_LL(app, db):
    pytest.importorskip("pypdf")
    import io

    import pypdf
    from oss_pdf import build_pdf
    show, day, act = _show(db)
    _local(db, act, "Rigger", 14, task="Pin / Bolt")
    buf = io.BytesIO()
    build_pdf(buf, show, [], [])
    buf.seek(0)
    text = "".join(p.extract_text() or "" for p in pypdf.PdfReader(buf).pages)
    assert "Rigger" in text
    assert "LL" in text
