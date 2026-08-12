"""Reading a break's length out of its own name (2026-08-12).

Found by the coverage panel on its first run against production: ALL 91 crew
breaks on the three live shows sat on the 60-minute house default, including
ones literally named "MORNING BREAK — 15 min". `recover_duration` only ever
read a `RETURN FROM` row and no live show has any, and `_base_label` was
STRIPPING the "— 15 min" text to pair breaks with those markers — so the
answer was in the string and nothing looked at it.

Consequence, before this: a fifteen-minute coffee printed as 10:30–11:30 on
the day page, the call sheet and the client master, and `break_export_text`
rendered it "MORNING BREAK — 15 min — 60 Minutes" — contradicting itself in a
single line on a document that goes to a client.

The line this must not cross: reading a STATED number is not guessing from a
keyword. A break being called COFFEE says nothing about how long it is.
"""
import pytest

from breaks import break_export_text, duration_from_label


@pytest.mark.parametrize("label,minutes,cleaned", [
    ("MORNING BREAK — 15 min", 15, "MORNING BREAK"),
    ("AFTERNOON BREAK — 15 min", 15, "AFTERNOON BREAK"),
    ("LUNCH BREAK — 30 min", 30, "LUNCH BREAK"),
    ("BEVERAGE BREAK — 15 min", 15, "BEVERAGE BREAK"),
    ("LUNCH BREAK — 60 min", 60, "LUNCH BREAK"),
    # the real spellings seen on production
    ("MORNING BREAK - 15 mins", 15, "MORNING BREAK"),
    ("LUNCH BREAK — 45 minutes", 45, "LUNCH BREAK"),
    ("LUNCH BREAK – 30 minute", 30, "LUNCH BREAK"),
])
def test_a_stated_length_is_read_and_the_label_tidied(label, minutes, cleaned):
    assert duration_from_label(label) == (minutes, cleaned)


@pytest.mark.parametrize("label", [
    # A number in the MIDDLE is not reliably the duration.
    "LUNCH BREAK — 60 minute NOT PROVIDED",
    # The crew stamp is a time, not a length.
    "COFFEE BREAK — 08:00 CREW",
    "COFFEE BREAK — 8:00 AM CREW",
    "AFTERNOON BREAK — 08:00 CREW — On the Run",
    # Nothing stated at all. THIS is the one that matters: a break called
    # COFFEE must not be guessed at 15 minutes. That inference is the bug the
    # whole overhaul exists to remove.
    "COFFEE BREAK",
    "AFTERNOON BREAK",
    "LUNCH",
    "",
    None,
])
def test_nothing_is_inferred_when_nothing_is_stated(label):
    assert duration_from_label(label) == (None, label)


def test_an_absurd_number_is_refused(app):
    """Nine hours is not a break; it is somebody's phone number or a typo."""
    assert duration_from_label("LUNCH BREAK — 540 min") == (
        None, "LUNCH BREAK — 540 min")
    assert duration_from_label("BREAK — 0 min") == (None, "BREAK — 0 min")


def test_a_label_that_is_only_a_duration_keeps_itself(app):
    """Stripping would leave an empty label, which reads as nothing at all."""
    assert duration_from_label("— 15 min") == (15, "— 15 min")


def test_the_printed_line_stops_contradicting_itself(app):
    """Before: 'MORNING BREAK — 15 min — 60 Minutes'."""
    minutes, cleaned = duration_from_label("MORNING BREAK — 15 min")
    assert break_export_text(cleaned, minutes) == "MORNING BREAK — 15 Minutes"


# ── the migration ───────────────────────────────────────────────────────────

def _fixture(db, code, rows):
    """rows: [(label, stored_duration), ...] on one day."""
    import datetime as dt
    from models import CrewBreak, ScheduleActivity, ScheduleDay, Show
    show = Show(name="Dur", code=code, uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8),
                      sod="07:00", eod="18:00")
    db.session.add(day); db.session.flush()
    out = []
    for i, (label, dur) in enumerate(rows):
        act = ScheduleActivity(day_id=day.id, time="10:%02d" % i,
                               description=label)
        db.session.add(act); db.session.flush()
        cb = CrewBreak(show_id=show.id, activity_id=act.id, label=label,
                       duration_minutes=dur, catered="unconfirmed")
        db.session.add(cb); db.session.flush()
        out.append(cb)
    db.session.commit()
    return show, out


def test_the_migration_corrects_the_default_and_tidies_the_label(app, db):
    from migrations import _break_durations_from_labels
    show, (cb,) = _fixture(db, "DU01", [("MORNING BREAK — 15 min", 60)])
    _break_durations_from_labels(db.session)
    db.session.commit()
    assert cb.duration_minutes == 15
    assert cb.label == "MORNING BREAK"


def test_a_hand_set_duration_is_never_overwritten(app, db):
    """A break somebody has already set is their ANSWER. A data migration that
    overwrites a human's edit is worse than the bug it fixes."""
    from migrations import _break_durations_from_labels
    show, (cb,) = _fixture(db, "DU02", [("MORNING BREAK — 15 min", 30)])
    _break_durations_from_labels(db.session)
    db.session.commit()
    assert cb.duration_minutes == 30       # untouched
    assert cb.label == "MORNING BREAK"     # still tidied


def test_a_break_with_nothing_stated_keeps_its_default(app, db):
    from migrations import _break_durations_from_labels
    show, (cb,) = _fixture(db, "DU03", [("COFFEE BREAK — 08:00 CREW", 60)])
    _break_durations_from_labels(db.session)
    db.session.commit()
    assert cb.duration_minutes == 60
    assert cb.label == "COFFEE BREAK — 08:00 CREW"


def test_the_migration_is_repeatable(app, db):
    """Run twice, same answer. The label is already tidy the second time, so
    there is nothing left to read and nothing moves."""
    from migrations import _break_durations_from_labels
    show, (cb,) = _fixture(db, "DU04", [("LUNCH BREAK — 30 min", 60)])
    for _ in range(2):
        _break_durations_from_labels(db.session)
        db.session.commit()
    assert (cb.duration_minutes, cb.label) == (30, "LUNCH BREAK")


def test_the_backfill_now_reads_the_label_too(app, db):
    """So a future re-run does not put the 60s straight back."""
    import datetime as dt
    from break_backfill import recover_duration
    from models import ScheduleActivity, ScheduleDay, Show
    show = Show(name="Dur", code="DU05", uses_new_breaks=True)
    db.session.add(show); db.session.flush()
    day = ScheduleDay(show_id=show.id, date=dt.date(2026, 9, 8))
    db.session.add(day); db.session.flush()
    act = ScheduleActivity(day_id=day.id, time="10:30",
                           description="MORNING BREAK — 15 min")
    db.session.add(act); db.session.commit()
    assert recover_duration(day, act) == 15
