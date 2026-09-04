"""Note 19, part 2 — "which column is the surname?"

The importer used to answer a file it couldn't read with:

    Couldn't find First Name + Last Name columns, or a single Name column.
    Found headers: ['Ref', 'Personnel', 'Dept']

which is a description of the problem offered as though it were a solution.
Nobody can do anything with it except rename columns in Excel and try again.

These tests hold the replacement: when the guess can't resolve, the upload
stops in a `mapping` state, shows the columns with real values from each, and
takes a correction. Then it goes through exactly the same matching, date
normalisation and preview as a file that parsed straight through — that
sameness is the point, and several tests below exist only to pin it.

Jason's call, 2026-09-04: build it blind rather than collect failing samples
first. A mapping step handles shapes nobody has seen; widening the alias list
only ever handles shapes somebody already sent.
"""
import datetime
import io
import json

import pytest

from models import CrewImportSession, CrewMember
from routes.crew_import import (MAPPABLE_FIELDS, _cell_for_storage,
                                _grid_for_storage, _mapping_is_usable,
                                _rows_from_grid)


# ── The one test that decides whether a file stops or goes through ───────────

@pytest.mark.parametrize("mapping,usable", [
    ({"first_name": 0, "last_name": 1}, True),
    ({"full_name": 3}, True),
    # Both halves, or a whole name. Half a pair is not a name.
    ({"first_name": 0}, False),
    ({"last_name": 1}, False),
    # Recognising plenty of other columns is no help at all — you cannot call
    # somebody by their hotel confirmation number.
    ({"position": 0, "company": 1, "email": 2, "hotel_name": 3}, False),
    ({}, False),
    # A whole-name column rescues a file that only found one half.
    ({"first_name": 0, "full_name": 2}, True),
])
def test_what_counts_as_a_usable_mapping(mapping, usable):
    assert _mapping_is_usable(mapping) is usable


# ── Cells on their way into the session, and back out ────────────────────────

def test_a_real_date_cell_survives_the_round_trip():
    """This is a bug fix, not just a serialisation detail.

    openpyxl hands back a `datetime` for a date-formatted cell. The old parser
    did `str(val)`, which gives "2026-09-08 00:00:00" — a string
    `_parse_loose_date` does not read. So every properly date-formatted Start /
    Travel In / Check Out cell was being dropped on the floor, and only files
    that typed their dates as *text* ever imported them.
    """
    from routes.crew_import import _parse_loose_date
    cell = _cell_for_storage(datetime.datetime(2026, 9, 8, 0, 0))
    assert cell == "2026-09-08"
    assert _parse_loose_date(cell) == datetime.date(2026, 9, 8)


def test_a_plain_date_cell_too():
    assert _cell_for_storage(datetime.date(2026, 9, 8)) == "2026-09-08"


def test_an_empty_cell_is_an_empty_string_not_the_word_none():
    assert _cell_for_storage(None) == ""


def test_a_number_keeps_its_value():
    assert _cell_for_storage(1450) == "1450"


def test_the_stored_grid_is_json_serialisable():
    grid = [("Name", "Start"), ("Ann Smith", datetime.datetime(2026, 9, 8))]
    stored = _grid_for_storage(grid)
    assert json.loads(json.dumps(stored)) == [["Name", "Start"],
                                              ["Ann Smith", "2026-09-08"]]


def test_the_stored_grid_is_bounded():
    """A 40,000-row export should not become a 40,000-row blob in a TEXT
    column. The mapping screen only ever shows the first few rows anyway."""
    grid = [tuple(f"c{c}" for c in range(200)) for _ in range(5000)]
    stored = _grid_for_storage(grid)
    assert len(stored) == 500
    assert len(stored[0]) == 60


# ── Rebuilding rows from a corrected mapping ─────────────────────────────────

def test_rows_come_out_the_same_shape_a_recognised_file_produces():
    grid = [
        ("Ref", "Personnel", "Dept"),
        ("A1", "Smith, Ann", "Rigging"),
        ("A2", "Bo Chen", "Audio"),
    ]
    rows = _rows_from_grid(grid, {"full_name": 1, "position": 2}, 0)
    assert [(r["first_name"], r["last_name"], r["position"]) for r in rows] == [
        ("Ann", "Smith", "Rigging"),
        ("Bo", "Chen", "Audio"),
    ]


def test_row_numbers_still_point_at_the_spreadsheet_row():
    """`n` is what the preview shows and what the commit form keys on, so it
    has to keep meaning "the row you'd find in Excel", header offset and all."""
    grid = [
        ("Crew list 2026", None),
        (None, None),
        ("Name", "Position"),
        ("Ann Smith", "Rigger"),
    ]
    rows = _rows_from_grid(grid, {"full_name": 0, "position": 1}, 2)
    assert [r["n"] for r in rows] == [4]


def test_a_short_row_does_not_blow_up():
    grid = [("Name", "Position"), ("Ann Smith",)]
    rows = _rows_from_grid(grid, {"full_name": 0, "position": 1}, 0)
    assert rows[0]["position"] == ""


def test_a_genuinely_empty_row_is_dropped_but_a_nameless_slot_is_not():
    grid = [
        ("Name", "Position"),
        ("", ""),
        ("", "Rigger"),
    ]
    rows = _rows_from_grid(grid, {"full_name": 0, "position": 1}, 0)
    assert len(rows) == 1
    assert rows[0]["position"] == "Rigger"


# ── End to end through the routes ────────────────────────────────────────────

def _xlsx(rows, headers):
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


def _upload(client, app, rows, headers, filename="vendor.xlsx"):
    from flask import url_for
    with app.test_request_context():
        upload_url = url_for("crew_import.upload")
    r = client.post(upload_url,
                    data={"file": (_xlsx(rows, headers), filename)},
                    content_type="multipart/form-data")
    assert r.status_code in (301, 302), r.get_data(as_text=True)[:400]
    return r


UNREADABLE = (["Ref", "Personnel", "Dept"],
              [("A1", "Smith, Ann", "Rigging"),
               ("A2", "Bo Chen", "Audio")])


def test_an_unreadable_file_lands_on_the_mapping_screen_not_an_error(app, client, db):
    headers, rows = UNREADABLE
    r = _upload(client, app, rows, headers)
    assert "/mapping" in r.headers["Location"]
    session = CrewImportSession.query.one()
    assert session.status == "mapping"


def test_nothing_is_created_while_a_file_sits_in_mapping(app, client, db):
    before = CrewMember.query.count()
    headers, rows = UNREADABLE
    _upload(client, app, rows, headers)
    assert CrewMember.query.count() == before


def test_the_mapping_screen_shows_the_columns_and_real_values(app, client, db):
    headers, rows = UNREADABLE
    r = _upload(client, app, rows, headers)
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    # The header names, so a person can find the column…
    assert "Personnel" in page
    # …and values out of it, because a column called "Ref" is only knowable
    # from what is in it.
    assert "Smith, Ann" in page
    # Every field they can point at.
    assert "Last name" in page


def test_correcting_the_mapping_gets_you_to_the_preview(app, client, db):
    from flask import url_for
    headers, rows = UNREADABLE
    r = _upload(client, app, rows, headers)
    sid = CrewImportSession.query.one().id
    with app.test_request_context():
        map_url = url_for("crew_import.mapping", sid=sid)

    r2 = client.post(map_url, data={"header_idx": "0",
                                    "col_0": "", "col_1": "full_name",
                                    "col_2": "position"})
    assert r2.status_code in (301, 302)
    assert "/preview" in r2.headers["Location"]

    session = CrewImportSession.query.get(sid)
    assert session.status == "pending"
    assert [(x["first_name"], x["last_name"]) for x in session.rows] == [
        ("Ann", "Smith"), ("Bo", "Chen")]


def test_the_corrected_file_commits_like_any_other(app, client, db):
    """The whole point of routing both paths through `_finalise_parsed`: a file
    that needed its columns pointed out is not a second-class import."""
    from flask import url_for
    headers, rows = UNREADABLE
    _upload(client, app, rows, headers)
    sid = CrewImportSession.query.one().id
    with app.test_request_context():
        map_url = url_for("crew_import.mapping", sid=sid)
        commit_url = url_for("crew_import.commit", sid=sid)
    client.post(map_url, data={"header_idx": "0", "col_1": "full_name",
                               "col_2": "position"})
    client.post(commit_url, data={"decision_2": "add", "decision_3": "add"},
                follow_redirects=True)
    assert CrewMember.query.filter_by(last_name="Smith").one().first_name == "Ann"


def test_a_mapping_with_no_name_in_it_is_refused_and_asks_again(app, client, db):
    from flask import url_for
    headers, rows = UNREADABLE
    _upload(client, app, rows, headers)
    sid = CrewImportSession.query.one().id
    with app.test_request_context():
        map_url = url_for("crew_import.mapping", sid=sid)

    r = client.post(map_url, data={"header_idx": "0", "col_2": "position"})
    assert r.status_code == 200                      # re-rendered, not redirected
    assert CrewImportSession.query.get(sid).status == "mapping"
    assert "something to call people" in r.get_data(as_text=True)


def test_two_columns_pointed_at_the_same_field_do_not_fight(app, client, db):
    """First column wins; the later one is ignored rather than silently
    overwriting. A person mis-clicking a dropdown should not get a surprise."""
    from flask import url_for
    _upload(client, app, [("A1", "Smith, Ann", "Rigging")],
            ["Ref", "Personnel", "Dept"])
    sid = CrewImportSession.query.one().id
    with app.test_request_context():
        map_url = url_for("crew_import.mapping", sid=sid)
    client.post(map_url, data={"header_idx": "0", "col_1": "full_name",
                               "col_2": "full_name"})
    session = CrewImportSession.query.get(sid)
    assert (session.rows[0]["first_name"], session.rows[0]["last_name"]) == ("Ann", "Smith")


def test_the_header_row_can_be_corrected_too(app, client, db):
    """A title row above the headings is handled automatically, but a file
    where the guess picks wrong needs a way out that isn't Excel."""
    from flask import url_for
    r = _upload(client, app,
                [(None, None), ("Ref", "Personnel"), ("A1", "Smith, Ann")],
                ["Crew list 2026", None])
    sid = CrewImportSession.query.one().id
    with app.test_request_context():
        map_url = url_for("crew_import.mapping", sid=sid)
    client.post(map_url, data={"header_idx": "2", "col_1": "full_name"})
    session = CrewImportSession.query.get(sid)
    assert [(x["first_name"], x["last_name"]) for x in session.rows] == [("Ann", "Smith")]


def test_a_readable_file_never_sees_the_mapping_screen(app, client, db):
    """The mapping step is a fallback. Adding it must not put a step in front
    of the files that already worked."""
    r = _upload(client, app, [("Ann", "Smith", "Rigger")],
                ["First Name", "Last Name", "Position"])
    assert "/preview" in r.headers["Location"]
    assert CrewImportSession.query.one().status == "pending"


def test_visiting_mapping_for_a_finished_session_does_not_reopen_it(app, client, db):
    from flask import url_for
    _upload(client, app, [("Ann", "Smith", "Rigger")],
            ["First Name", "Last Name", "Position"])
    sid = CrewImportSession.query.one().id
    with app.test_request_context():
        map_url = url_for("crew_import.mapping", sid=sid)
    r = client.get(map_url)
    assert r.status_code in (301, 302)
    assert "/preview" in r.headers["Location"]


def test_every_mappable_field_is_a_real_field(app, client, db):
    """A dropdown option that isn't a key the row builder understands would
    silently do nothing — the worst kind of wrong."""
    from routes.crew_import import COLUMN_ALIASES
    for value, label in MAPPABLE_FIELDS:
        assert label
        if value:
            assert value in COLUMN_ALIASES, value


def test_the_ignore_option_is_first_and_selected_by_default(app, client, db):
    assert MAPPABLE_FIELDS[0][0] == ""
