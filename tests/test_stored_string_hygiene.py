"""Nothing is stored with leading or trailing whitespace, and a time is a time.

Found 2026-09-09 on the production snapshot, three symptoms of one cause:

  * venue 2 is ``'CAESARS FORUM '``, so every call sheet printed
    "CAESARS FORUM , Las Vegas, NV" — a space before the comma, on a document
    that goes to a client;
  * venues 4 and 5 are both ``'Hilton Midtown NY '`` with city
    ``'New York City '`` — a duplicate a name comparison would miss;
  * day 25's label ends in a space and it prints on the show book.

No single route is at fault. Forty routes each do ``f.get("name", "")`` and
none of them strips, so the fix is at the one place every write already passes
through: a ``before_flush`` listener in models.py.

The fourth symptom was different in kind: day 61's Start of Day was the string
``'0600 AM'``, printed verbatim on the show book beside ten days reading
"07:00 - 18:00". Two causes there — Add Day wrote its time fields raw while
Day Settings normalised them, and ``parse_minutes`` did not understand
four-digit military time, so normalising it would have blanked it rather than
fixed it. Both are addressed here.
"""
import datetime as dt

import pytest

from time_utils import hhmm_or_blank, parse_minutes


# ── the listener ────────────────────────────────────────────────────────────

def test_a_trailing_space_never_reaches_the_database(app, db):
    from models import Venue
    v = Venue(name="CAESARS FORUM ", city="Las Vegas", state="NV")
    db.session.add(v)
    db.session.commit()
    assert v.name == "CAESARS FORUM"


def test_leading_space_too(app, db):
    from models import Client
    c = Client(name="  Yellow Hat, Inc.")
    db.session.add(c)
    db.session.commit()
    assert c.name == "Yellow Hat, Inc."


def test_it_fires_on_update_not_only_on_insert(app, db):
    from models import Company
    co = Company(name="Sparks")
    db.session.add(co)
    db.session.commit()

    co.name = "Sparks Live  "
    db.session.commit()
    assert co.name == "Sparks Live"


def test_newlines_and_tabs_count_as_whitespace(app, db):
    from models import Client
    c = Client(name="\n\tYellow Hat\t\n")
    db.session.add(c)
    db.session.commit()
    assert c.name == "Yellow Hat"


def test_internal_spacing_is_left_exactly_as_typed(app, db):
    """Strip, never collapse. Rewriting the middle of someone's text is worse."""
    from models import Show
    s = Show(name="Show Day 1  —  Presenter Rehearsals ")
    db.session.add(s)
    db.session.commit()
    assert s.name == "Show Day 1  —  Presenter Rehearsals"


def test_text_columns_are_stripped_but_keep_their_line_breaks(app, db):
    from models import Client
    c = Client(name="ACME", notes="  line one\nline two  ")
    db.session.add(c)
    db.session.commit()
    assert c.notes == "line one\nline two"


def test_non_string_columns_are_untouched(app, db):
    from models import CrewMember
    m = CrewMember(first_name="Jose", last_name="Mora",
                   rate_standard=45.5, active=True)
    db.session.add(m)
    db.session.commit()
    assert m.rate_standard == 45.5
    assert m.active is True


def test_none_stays_none(app, db):
    from models import Client
    c = Client(name="ACME", notes=None)
    db.session.add(c)
    db.session.commit()
    assert c.notes is None


def test_a_generated_filename_is_never_touched(app, db):
    """Stored names must keep matching the bytes on disk."""
    from models import AgencySetting
    s = AgencySetting.get()
    s.logo_filename = "adi logo .png"
    db.session.commit()
    assert s.logo_filename == "adi logo .png"


# ── military time ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("0600 AM", "06:00"),      # the exact value found on production
    ("0600", "06:00"),
    ("600", "06:00"),
    ("1830", "18:30"),
    ("600 PM", "18:00"),
    ("1200", "12:00"),
    ("0000", "00:00"),
    ("2359", "23:59"),
])
def test_four_digit_times_parse(raw, expected):
    assert hhmm_or_blank(raw) == expected


@pytest.mark.parametrize("raw", ["2400", "0660", "9999", "garbage", ""])
def test_impossible_times_still_refuse(raw):
    assert hhmm_or_blank(raw) == ""


@pytest.mark.parametrize("raw,expected", [
    ("8", "08:00"),
    ("8:00", "08:00"),
    ("13:00", "13:00"),
    ("1:00 PM", "13:00"),
    ("7:30 p.m.", "19:30"),
    ("6:00 PM (doors)", "18:00"),
])
def test_everything_that_parsed_before_still_parses_the_same(raw, expected):
    """The new pattern is anchored and runs second — it reinterprets nothing."""
    assert hhmm_or_blank(raw) == expected


# ── the Add Day route ───────────────────────────────────────────────────────

def test_add_day_normalises_its_time_fields(app, client, db):
    """This route wrote them raw, which is how "0600 AM" got stored."""
    from models import Show, ScheduleDay

    show = Show(name="Add Day Show")
    db.session.add(show)
    db.session.commit()

    r = client.post("/shows/%d/schedule/add-day" % show.id, data={
        "date": "2026-09-18",
        "label": "Heavy Equipment Pick Up ",
        "sod": "0600 AM",
        "eod": "12:00",
        "call_time": "630",
        "wrap_time": "",
    }, follow_redirects=True)
    assert r.status_code == 200

    day = ScheduleDay.query.filter_by(show_id=show.id).one()
    assert day.sod == "06:00"
    assert day.eod == "12:00"
    assert day.call_time == "06:30"
    assert day.label == "Heavy Equipment Pick Up"     # and the listener ran


# ── the migrations ──────────────────────────────────────────────────────────

def test_the_strip_migration_cleans_what_is_already_stored(app, db):
    from migrations import _strip_whitespace_from_stored_strings
    from models import Venue
    from sqlalchemy import text

    v = Venue(name="ok", city="ok")
    db.session.add(v)
    db.session.commit()
    # Go around the listener the way existing production data did.
    db.session.execute(
        text("UPDATE venues SET name = :n, city = :c WHERE id = :i"),
        {"n": "CAESARS FORUM ", "c": "Las Vegas ", "i": v.id})
    db.session.commit()
    db.session.expire_all()

    _strip_whitespace_from_stored_strings(db.session)

    db.session.expire_all()
    fresh = db.session.get(Venue, v.id)
    assert fresh.name == "CAESARS FORUM"
    assert fresh.city == "Las Vegas"


def test_both_new_migrations_are_registered():
    from migrations import DATA_MIGRATIONS
    keys = [k for k, _fn in DATA_MIGRATIONS]
    assert "2026-09-09-strip-whitespace-from-stored-strings" in keys
    assert "2026-09-09-normalise-times-including-military" in keys
    # the time pass must run after the strip: a trailing space can stop a
    # value parsing, and then it would be left alone again.
    assert (keys.index("2026-09-09-normalise-times-including-military")
            > keys.index("2026-09-09-strip-whitespace-from-stored-strings"))


def test_the_audit_log_is_never_tidied(app, db):
    """It records what the data WAS — trailing space and all.

    The log's `label` and before/after payloads are a description of a change,
    not a value anyone typed. Rewriting them would make the log disagree with
    the change it is describing. Measured when this landed: 484 of the 555
    values the first version of the strip would have rewritten were audit rows.
    """
    from models import AuditLog
    entry = AuditLog(table_name="venues", row_id=2, action="update",
                     label="update venue: CAESARS FORUM ",
                     before_json='{"name": "CAESARS FORUM "}')
    db.session.add(entry)
    db.session.commit()
    assert entry.label == "update venue: CAESARS FORUM "
    assert entry.before_json == '{"name": "CAESARS FORUM "}'


def test_the_strip_migration_leaves_the_audit_log_alone(app, db):
    from migrations import _strip_whitespace_from_stored_strings
    from models import AuditLog
    from sqlalchemy import text

    entry = AuditLog(table_name="venues", row_id=2, action="update", label="ok")
    db.session.add(entry)
    db.session.commit()
    db.session.execute(text("UPDATE audit_log SET label = :l WHERE id = :i"),
                       {"l": "insert activity: Furniture Delivery ", "i": entry.id})
    db.session.commit()
    db.session.expire_all()

    _strip_whitespace_from_stored_strings(db.session)

    db.session.expire_all()
    assert db.session.get(AuditLog, entry.id).label == "insert activity: Furniture Delivery "
