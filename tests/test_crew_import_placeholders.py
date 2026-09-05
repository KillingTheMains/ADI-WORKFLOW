"""Note 19 — the importer stops turning placeholders into people.

The importer is the surface that creates crew in bulk, and it was the one
place in the app that did NOT use the app's own definition of "this is not a
person". It hand-rolled:

    (first.upper() == "TBD" or not first) and not last

which knew the literal "TBD" and nothing else. TBA, Unknown, N/A, XXX and Test
were all already sitting in `CrewMember.PLACEHOLDER_NAMES`, checked correctly
by the crew screens and the audit — and imported as real crew members here.
"TBD TBD" got through too, because the test demanded an empty surname. And the
whole check was gated on importing into a show, so a global crew import never
detected a placeholder at all.

This is the fix the capture log calls "cheap, permanent, stops the bleeding",
and it had to land BEFORE the importer is made more permissive: widening the
formats without it widens the hole.
"""
import io

import pytest

from models import CrewMember, Position, Show, ShowOpenSlot, name_is_unnamed_slot
from routes.crew_import import _row_is_slot


def _row(first="", last="", position=""):
    return {"first_name": first, "last_name": last, "position": position}


# ── The shared predicate ─────────────────────────────────────────────────────

@pytest.mark.parametrize("first,last", [
    ("TBD", ""), ("TBD", "TBD"), ("TBA", ""), ("Unknown", ""),
    ("N/A", ""), ("XXX", ""), ("Test", ""), ("First", "Last"),
    ("tbd", ""), ("  TBD  ", ""),
])
def test_these_are_all_stand_ins(first, last):
    """Every one of these imported as a real crew member before this."""
    assert name_is_unnamed_slot(first, last), f"{first!r} {last!r}"


@pytest.mark.parametrize("first,last", [
    ("Ann", "Hand"), ("Larry", "Name"), ("Jo", "Last"), ("Ann", "Testa"),
])
def test_a_real_person_is_still_a_person(first, last):
    """Deliberately strict — it fires only when the WHOLE name is a stand-in,
    so somebody surnamed "Name" or "Last" keeps their name."""
    assert not name_is_unnamed_slot(first, last), f"{first!r} {last!r}"


def test_a_blank_name_is_not_by_itself_a_placeholder():
    """Blank means "no information", not "a stand-in". The importer decides
    from context: blank beside a position is a called slot, blank alone is
    noise."""
    assert not name_is_unnamed_slot("", "")


def test_the_model_and_the_importer_ask_the_same_question(db):
    """One definition. Two definitions is how the importer drifted from the
    rest of the app in the first place."""
    for first, last in [("TBD", ""), ("TBA", "TBA"), ("Ann", "Hand")]:
        cm = CrewMember(first_name=first, last_name=last)
        assert cm.is_unnamed_slot == name_is_unnamed_slot(first, last)


# ── Row classification ───────────────────────────────────────────────────────

def test_a_placeholder_row_is_a_slot():
    assert _row_is_slot(_row("TBD", "", "Rigger"))
    assert _row_is_slot(_row("TBA", "TBA", "Rigger"))


def test_a_nameless_row_with_a_position_is_a_slot():
    """A called position nobody is booked into yet."""
    assert _row_is_slot(_row("", "", "Lighting Hand"))


def test_a_nameless_row_with_no_position_is_not_a_slot():
    """Nothing to make a slot out of — that row is noise, and the parser
    drops it before it ever reaches here."""
    assert not _row_is_slot(_row("", "", ""))


def test_a_real_person_is_not_a_slot():
    assert not _row_is_slot(_row("Ann", "Hand", "Rigger"))


# ── The old test's specific failures, named ──────────────────────────────────

def test_tbd_tbd_no_longer_becomes_a_crew_member():
    """The old check demanded an empty surname, so this was a person called
    "TBD TBD"."""
    assert _row_is_slot(_row("TBD", "TBD", "Rigger"))


@pytest.mark.parametrize("first", ["TBA", "Unknown", "N/A", "XXX", "Test"])
def test_the_other_placeholders_the_old_check_missed(first):
    """All five were already in PLACEHOLDER_NAMES. The importer was the one
    place that did not look."""
    assert _row_is_slot(_row(first, "", "Rigger"))


# ── End to end: upload a file, commit it, see what landed ────────────────────
#
# `routes/crew_import.py` is 638 lines and had NO tests before this. The path
# that creates crew in bulk from an untrusted spreadsheet was the least
# covered code in the app.

def _xlsx(rows, headers=("First Name", "Last Name", "Position")):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _import(client, app, db, rows, show=None):
    """Upload, then commit every row as `add`. Returns the commit response."""
    from flask import url_for
    with app.test_request_context():
        upload_url = url_for("crew_import.upload")
    data = {"file": (_xlsx(rows), "crew.xlsx")}
    if show is not None:
        data["target_show_id"] = str(show.id)

    r = client.post(upload_url, data=data, content_type="multipart/form-data")
    assert r.status_code in (301, 302), r.get_data(as_text=True)[:400]
    sid = int(r.headers["Location"].rstrip("/").split("/")[-2])

    # Data starts on spreadsheet row 2.
    decisions = {f"decision_{i}": "add" for i in range(2, 2 + len(rows) + 2)}
    with app.test_request_context():
        commit_url = url_for("crew_import.commit", sid=sid)
    return client.post(commit_url, data=decisions, follow_redirects=True)


def _show(db):
    s = Show(name="Import Show", code=f"IM{Show.query.count() + 1}")
    db.session.add(s); db.session.commit()
    return s


def test_placeholders_do_not_become_crew_members(app, client, db):
    """THE ONE THAT MATTERS. Five of these six imported as real people."""
    before = CrewMember.query.count()
    _import(client, app, db, [
        ("TBD", "", "Rigger"),
        ("TBA", "", "Rigger"),
        ("Unknown", "", "Rigger"),
        ("N/A", "", "Rigger"),
        ("XXX", "", "Rigger"),
        ("TBD", "TBD", "Rigger"),
    ], show=_show(db))
    assert CrewMember.query.count() == before


def test_they_become_open_slots_on_the_show_instead(app, client, db):
    show = _show(db)
    _import(client, app, db, [("TBA", "", "Rigger")], show=show)
    assert ShowOpenSlot.query.filter_by(show_id=show.id).count() == 1


def test_a_global_import_skips_them_rather_than_creating_people(app, client, db):
    """The old check only ran when importing INTO A SHOW, so a global crew
    import never detected a placeholder at all. There is no show to hang an
    open slot on, so the only safe answer is to skip — and say so."""
    before = CrewMember.query.count()
    r = _import(client, app, db, [("TBD", "", "Rigger")])
    assert CrewMember.query.count() == before
    assert "unnamed slots skipped" in r.get_data(as_text=True)


def test_real_people_still_import(app, client, db):
    """The guard has to let actual crew through, including one surnamed
    "Last"."""
    before = CrewMember.query.count()
    _import(client, app, db, [
        ("Ann", "Hand", "Rigger"),
        ("Jo", "Last", "Rigger"),
    ], show=_show(db))
    assert CrewMember.query.count() == before + 2


def test_a_row_with_a_position_and_no_name_is_no_longer_discarded(app, client, db):
    """It used to be dropped at parse time — a called slot vanishing silently
    on import, which also made half of commit()'s TBD branch dead code."""
    show = _show(db)
    _import(client, app, db, [("", "", "Lighting Hand")], show=show)
    assert ShowOpenSlot.query.filter_by(show_id=show.id).count() == 1


def test_a_completely_empty_row_is_still_dropped(app, client, db):
    show = _show(db)
    _import(client, app, db, [("", "", "")], show=show)
    assert ShowOpenSlot.query.filter_by(show_id=show.id).count() == 0


def test_the_preview_says_which_rows_are_slots(app, client, db):
    """Auto-detection alone is wrong eventually and silently. Auto-detection
    plus a guess a human can see and disagree with fails safely."""
    from flask import url_for
    show = _show(db)
    with app.test_request_context():
        upload_url = url_for("crew_import.upload")
    r = client.post(upload_url,
                    data={"file": (_xlsx([("TBD", "", "Rigger"),
                                          ("Ann", "Hand", "Rigger")]),
                                   "crew.xlsx"),
                          "target_show_id": str(show.id)},
                    content_type="multipart/form-data",
                    follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "OPEN SLOT" in body
    assert "placeholder name" in body


def test_a_position_title_in_the_name_column_is_flagged_not_rerouted(app, client, db):
    """"Lighting Hand" is not a placeholder NAME — no list of stand-ins will
    ever catch it. It is a position title in the wrong column, so it gets a
    warning for a human rather than a silent reroute: a real person could in
    principle be called anything."""
    from flask import url_for
    from models import Position as _P, find_normalised
    if find_normalised(_P.query.all(), "Lighting Hand", attr="title") is None:
        db.session.add(_P(title="Lighting Hand", department="Lighting"))
    db.session.commit()
    show = _show(db)
    with app.test_request_context():
        upload_url = url_for("crew_import.upload")
    r = client.post(upload_url,
                    data={"file": (_xlsx([("Lighting", "Hand", "")]),
                                   "crew.xlsx"),
                          "target_show_id": str(show.id)},
                    content_type="multipart/form-data",
                    follow_redirects=True)
    assert "position title, not a name" in r.get_data(as_text=True)
