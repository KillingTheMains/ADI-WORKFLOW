"""Note 19 — reading crew documents that are not shaped the way we'd like.

Before this, `_parse_xlsx` did two things that made a whole class of real
files unreadable:

  * it took `rows[0]` as the header, so a workbook with a title row, a blank
    spacer or a merged banner above the headers failed outright — a very
    ordinary shape for something a vendor sends;
  * it required a recognised First Name AND Last Name column, so a single
    "Name" column could not be expressed at all.

Jason's call, 2026-09-04: build this blind rather than waiting for sample
failing files, so it handles shapes nobody has seen.

The name splitting is a HEURISTIC and these tests are written to say so. It
will be wrong on some real names. That is survivable precisely because the
importer stops at a preview and lets a person disagree — auto-detection alone
is wrong eventually and silently; auto-detection plus a confirmable guess
fails safely.
"""
import io

import pytest

from routes.crew_import import (_find_header_row, _map_columns,
                                split_person_name)


# ── Splitting one name string ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,first,last", [
    # A comma means surname-first. Unambiguous, and common in exports.
    ("Smith, Ann", "Ann", "Smith"),
    ("SMITH, ANN", "ANN", "SMITH"),
    ("Smith , Ann", "Ann", "Smith"),
    # The ordinary case.
    ("Ann Smith", "Ann", "Smith"),
    # Middle names read as part of the given name — ADI's own paperwork
    # convention, and the surname is what has to be right.
    ("Ann Marie Smith", "Ann Marie", "Smith"),
    # A particle pulls everything after it into the surname. Without this the
    # surname is "Berg", which is worse than useless on a call sheet.
    ("Ann Van Der Berg", "Ann", "Van Der Berg"),
    ("Jo de la Cruz", "Jo", "de la Cruz"),
    # A suffix is not a surname.
    ("Ann Smith Jr.", "Ann", "Smith Jr."),
    ("Ann Smith III", "Ann", "Smith III"),
    # One token is a first name with no surname recorded.
    ("Cher", "Cher", ""),
    # Nothing in, nothing out.
    ("", "", ""),
    ("   ", "", ""),
    # Whitespace is not information.
    ("  Ann   Smith  ", "Ann", "Smith"),
])
def test_split_person_name(raw, first, last):
    assert split_person_name(raw) == (first, last)


def test_a_single_token_name_is_not_mistaken_for_a_placeholder():
    """"Cher" must stay a person. The placeholder guard and the splitter have
    to agree, or a one-name crew member becomes an open slot."""
    from models import name_is_unnamed_slot
    first, last = split_person_name("Cher")
    assert not name_is_unnamed_slot(first, last)


def test_the_splitter_is_a_guess_not_an_authority():
    """Stated as a test so nobody later mistakes it for a specification.
    "Ann O'Brien Smith" splits to a surname of "Smith", which may well be
    wrong — O'Brien Smith could be the whole surname. There is no way to know
    from the string, which is exactly why a human confirms in the preview."""
    assert split_person_name("Ann O'Brien Smith") == ("Ann O'Brien", "Smith")


# ── Finding the header row ───────────────────────────────────────────────────

def test_the_header_is_usually_the_first_row():
    rows = [("First Name", "Last Name", "Position"), ("Ann", "Hand", "Rigger")]
    assert _find_header_row(rows)[0] == 0


def test_a_title_row_above_the_header_no_longer_breaks_the_file():
    """The shape that used to fail outright."""
    rows = [
        ("MCDC26 CREW LIST", None, None),
        (None, None, None),
        ("First Name", "Last Name", "Position"),
        ("Ann", "Hand", "Rigger"),
    ]
    assert _find_header_row(rows)[0] == 2


def test_ties_go_to_the_earliest_row():
    """A real header sits above its data. A later row scoring the same is more
    likely to be data that happens to look like one."""
    rows = [("Name", "Position"), ("Name", "Position")]
    assert _find_header_row(rows)[0] == 0


def test_a_file_with_no_recognisable_header_scores_zero():
    """Zero is the signal that the mapping step is needed — not a crash."""
    rows = [("col1", "col2"), ("x", "y")]
    idx, score = _find_header_row(rows)
    assert score == 0


def test_only_the_top_of_the_sheet_is_scanned():
    """A row deep in the data that happens to look like a header must not win
    — that would silently discard everything above it."""
    rows = [("First Name", "Last Name")] + [("Ann", "Hand")] * 20 \
        + [("First Name", "Last Name", "Position", "Company", "Email")]
    assert _find_header_row(rows)[0] == 0


# ── The whole thing, end to end ──────────────────────────────────────────────

def _xlsx(rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload(client, app, rows, show=None, follow_redirects=True):
    from flask import url_for
    with app.test_request_context():
        url = url_for("crew_import.upload")
    data = {"file": (_xlsx(rows), "crew.xlsx")}
    if show is not None:
        data["target_show_id"] = str(show.id)
    return client.post(url, data=data, content_type="multipart/form-data",
                       follow_redirects=follow_redirects)


def test_a_single_name_column_is_now_readable(app, client, db):
    """`COLUMN_ALIASES` had no whole-name entry at all, so this file was
    refused outright."""
    r = _upload(client, app, [
        ("Name", "Position"),
        ("Smith, Ann", "Rigger"),
        ("Jo Van Der Berg", "Rigger"),
    ])
    body = r.get_data(as_text=True)
    assert "Couldn&#39;t find" not in body and "Couldn't find" not in body
    assert "Ann" in body and "Smith" in body
    assert "Van Der Berg" in body


def test_a_title_row_above_the_headers_is_now_readable(app, client, db):
    r = _upload(client, app, [
        ("MCDC26 CREW LIST", None, None),
        (None, None, None),
        ("First Name", "Last Name", "Position"),
        ("Ann", "Hand", "Rigger"),
    ])
    body = r.get_data(as_text=True)
    assert "Couldn't find" not in body
    assert "Ann" in body


def test_explicit_columns_beat_the_split(app, client, db):
    """A file with BOTH a Name column and real first/last columns must use the
    explicit pair — it is always more reliable than a guess."""
    r = _upload(client, app, [
        ("Name", "First Name", "Last Name", "Position"),
        ("WRONG, WRONG", "Ann", "Hand", "Rigger"),
    ])
    body = r.get_data(as_text=True)
    assert "Ann" in body and "Hand" in body
    assert "WRONG" not in body


def test_a_file_with_no_name_columns_at_all_now_asks_instead_of_refusing(app, client, db):
    """This test used to assert the opposite, and said so: "Refusing is still
    right when there is genuinely nothing to read."

    That was wrong, and part 2 of note 19 is the correction. Refusing was never
    right — it just looked right while the only alternative on the table was
    guessing harder. A file whose columns we cannot recognise is not a file we
    cannot read; it is a file we have to ask about. The assertion is inverted
    on purpose, not relaxed: the demand is now stronger, because "went to the
    mapping screen" is a specific place, where "said Couldn't find" was only
    the absence of progress.
    """
    from models import CrewImportSession
    r = _upload(client, app, [("Widget", "Colour"), ("thing", "red")],
                follow_redirects=False)
    assert "/mapping" in r.headers["Location"]
    assert CrewImportSession.query.one().status == "mapping"
