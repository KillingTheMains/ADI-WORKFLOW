"""
Idempotent SQLite schema migrations for ADI Workflow.

Why this exists
---------------
SQLAlchemy's `db.create_all()` creates missing TABLES, but never modifies
existing tables. When we add a column to a model, the live database still
has the old schema until someone runs ALTER TABLE by hand. That's a chore
and easy to forget.

This module reconciles the live schema with the model on every app startup:
  * Each migration declares "this column should exist on this table".
  * On startup we check PRAGMA table_info and apply any missing ALTERs.
  * Each migration runs at most once per database, even across restarts,
    because the check is "does the column exist yet?" — not a separate
    version tracker.

Add new migrations to MIGRATIONS below. Order doesn't strictly matter for
column adds, but keep them in roughly chronological order for readability.

Future-proofing
---------------
For changes that aren't pure ALTER ADD COLUMN (e.g. backfilling values,
renaming columns, splitting tables), add an entry to DATA_MIGRATIONS with
a unique key plus a callable. The keys we've already applied are tracked
in a tiny `applied_migrations` table.
"""
from sqlalchemy import text, inspect as sa_inspect
from extensions import db


# ── Column-add migrations ────────────────────────────────────────────────────
# Each tuple: (table_name, column_name, column_ddl)
# Idempotent: skipped if the column already exists.

MIGRATIONS = [
    # 2026-05-27 — OSS feature
    ("sub_schedule_entries", "schedule_day_id", "INTEGER REFERENCES schedule_days(id)"),
    ("sub_schedule_entries", "count",            "INTEGER"),
    # 2026-05-27 — OSS optional activity link
    ("sub_schedule_entries", "activity_id",      "INTEGER REFERENCES schedule_activities(id)"),
    # 2026-05-27 — Wristbands tab (per-day extras / override / notes)
    ("schedule_days", "wristband_crew_override", "INTEGER"),
    ("schedule_days", "wristband_extras",        "INTEGER"),
    ("schedule_days", "wristband_notes",         "TEXT"),
    # COMS tables (show_comm_channels, crew_comm_assignments) are created
    # automatically by db.create_all() since they're brand-new tables.
    # 2026-06-30 — Phase A: enriched crew booking
    ("show_crew_assignments", "booking_task",    "VARCHAR(50)"),
    ("show_crew_assignments", "travel_in_date",  "DATE"),
    ("show_crew_assignments", "start_date",      "DATE"),
    ("show_crew_assignments", "end_date",        "DATE"),
    ("show_crew_assignments", "travel_out_date", "DATE"),
    # show_open_slots is a new table → created by db.create_all().
    # 2026-06-30 — Phase A: importer can target a specific show
    ("crew_import_sessions",  "target_show_id",  "INTEGER REFERENCES shows(id)"),
    # 2026-07-01 — Wishlist #3: manual crew roster ordering
    ("crew_members",          "sort_order",         "INTEGER"),
    # 2026-07-01 — Drag-to-reorder on the Show Crew Booking Sheet
    ("show_crew_assignments", "sort_order",         "INTEGER"),
    ("show_open_slots",       "sort_order",         "INTEGER"),
    # 2026-07-01 — Actual hours per crew row (planned vs actual)
    ("crew_rows",             "actual_hours",       "FLOAT"),
    # 2026-06-30 — Phase B: per-crew-per-show travel detail
    ("show_crew_assignments", "hotel_name",         "VARCHAR(200)"),
    ("show_crew_assignments", "hotel_check_in",     "DATE"),
    ("show_crew_assignments", "hotel_check_out",    "DATE"),
    ("show_crew_assignments", "hotel_confirmation", "VARCHAR(100)"),
    ("show_crew_assignments", "hotel_cost",         "FLOAT"),
    ("show_crew_assignments", "arrival_flight",     "VARCHAR(50)"),
    ("show_crew_assignments", "arrival_time",       "VARCHAR(20)"),
    ("show_crew_assignments", "departure_flight",   "VARCHAR(50)"),
    ("show_crew_assignments", "departure_time",     "VARCHAR(20)"),
    ("show_crew_assignments", "itinerary_link",     "VARCHAR(500)"),
    # 2026-07-13 — Start of Day / End of Day anchors (replace Call/Wrap in Day Settings)
    ("schedule_days", "sod", "VARCHAR(20)"),
    ("schedule_days", "eod", "VARCHAR(20)"),
    # 2026-07-18 — #31 designated travel window on the show
    ("shows", "travel_window_start", "DATE"),
    ("shows", "travel_window_end", "DATE"),
    # 2026-08-02 — #48 show artwork (header image on generated paperwork)
    ("shows", "artwork_filename", "VARCHAR(300)"),
    # 2026-08-11 — note 1: tiered section headers on crew calls.
    # header_level defaults to 1, so every one of the 133 headers already in
    # production stays exactly where it is and nothing moves on deploy.
    ("crew_rows", "header_level", "INTEGER DEFAULT 1"),
    ("crew_rows", "company_id", "INTEGER REFERENCES companies(id)"),
    # 2026-08-11 — breaks & meals overhaul. crew_breaks is a NEW TABLE and is
    # created by db.create_all(); these are the columns on existing tables.
    # Every show defaults to uses_new_breaks = 0, so nothing changes on deploy
    # until a show is explicitly switched over.
    ("shows", "uses_new_breaks", "INTEGER DEFAULT 0"),
    ("meal_services", "setup_minutes", "INTEGER DEFAULT 30"),
    ("meal_services", "holdover_minutes", "INTEGER DEFAULT 30"),
    # 2026-08-11 — a standing beverage service is set up relative to the day's
    # SOD, by an amount chosen when it is created, and refreshed on its own
    # interval. Defaults reproduce the previous hard-coded behaviour.
    ("meal_services", "beverage_offset_minutes", "INTEGER DEFAULT -30"),
    ("meal_services", "beverage_interval_minutes", "INTEGER DEFAULT 150"),
    # 2026-08-12 — step 6, the coverage panel. "Feeds no crew break" was
    # always an offered answer on the F&B tab with nowhere to be recorded, so
    # it could not be told apart from an unanswered question. Defaults to 0:
    # every existing service starts as "not asked", which is the truth.
    ("meal_services", "standalone_confirmed", "INTEGER DEFAULT 0"),
]


# ── Data migrations (run once, tracked by key) ───────────────────────────────
# Each entry: (key, callable). The callable receives the db session.

def _migrate_fb_entries_to_meal_services(session):
    """
    Phase C: convert existing SubScheduleEntry rows of type='F&B' into
    MealService + MealServiceLocation. Each old entry becomes one meal
    service with one location, preserving activity_id, time, count, and
    notes. Old entries are deleted after conversion.
    """
    from models import (SubScheduleEntry, MealService, MealServiceLocation,
                        ScheduleActivity)

    def _guess_kind(name):
        if not name:
            return "other"
        n = name.upper()
        if "BREAKFAST" in n: return "breakfast"
        if "LUNCH"     in n: return "lunch"
        if "DINNER"    in n: return "dinner"
        if "BEVERAGE"  in n or "COFFEE" in n or "SNACK" in n:
            return "beverages" if "BEVERAGE" in n or "COFFEE" in n else "snack"
        return "other"

    old = SubScheduleEntry.query.filter_by(type="F&B").all()
    for e in old:
        # Determine display time — linked activity's time takes precedence,
        # else the entry's own free-form time.
        eff_time = None
        if e.activity_id:
            act = ScheduleActivity.query.get(e.activity_id)
            if act:
                eff_time = act.time
        eff_time = eff_time or e.time

        svc = MealService(
            show_id         = e.show_id,
            schedule_day_id = e.schedule_day_id,
            activity_id     = e.activity_id,
            name            = (e.activity or "Meal service"),
            kind            = _guess_kind(e.activity),
            is_recurring    = False,
            notes           = e.notes,
            sort_order      = e.sort_order or 0,
        )
        session.add(svc)
        session.flush()   # get svc.id
        session.add(MealServiceLocation(
            meal_service_id = svc.id,
            location_name   = None,        # single-location legacy → unnamed
            start_time      = eff_time,
            end_time        = None,
            headcount       = e.count,
            notes           = None,
        ))
        session.delete(e)
    session.commit()


def _seed_position_prompter(session):
    """Add 'Prompter' to the master Position list if it's not there yet."""
    from models import Position
    from sqlalchemy import func
    existing = Position.query.filter(
        func.lower(Position.title) == "prompter"
    ).first()
    if existing:
        return
    session.add(Position(
        title="Prompter", department="Video", type="specialty",
        union_eligible=False,
    ))
    session.commit()


def _backfill_travel_dates_from_hotel(session):
    """Travel page now uses the shared Travel In / Travel Out dates for
    check-in / check-out (single source of truth with the Booking Sheet).
    Carry over any dates that were previously entered only in the old
    hotel_check_in / hotel_check_out fields so nothing is lost."""
    from models import ShowCrewAssignment
    rows = ShowCrewAssignment.query.filter(
        (ShowCrewAssignment.hotel_check_in.isnot(None)) |
        (ShowCrewAssignment.hotel_check_out.isnot(None))
    ).all()
    for a in rows:
        if a.travel_in_date is None and a.hotel_check_in is not None:
            a.travel_in_date = a.hotel_check_in
        if a.travel_out_date is None and a.hotel_check_out is not None:
            a.travel_out_date = a.hotel_check_out
    session.commit()


def _backfill_sod_eod_from_call_wrap(session):
    """Start of Day / End of Day anchors replace Call / Wrap in Day Settings.
    Seed the new anchors from the existing call_time / wrap_time so current
    shows aren't blank after the switch. Only fills where sod/eod are still
    empty; the legacy call_time/wrap_time columns are retained (Smart Breaks
    still reads them until it's re-anchored to crew starts)."""
    from models import ScheduleDay
    rows = ScheduleDay.query.filter(
        (ScheduleDay.call_time.isnot(None)) | (ScheduleDay.wrap_time.isnot(None))
    ).all()
    for d in rows:
        if not d.sod and d.call_time:
            d.sod = d.call_time
        if not d.eod and d.wrap_time:
            d.eod = d.wrap_time
    session.commit()


def _normalise_stored_times_to_24h(session):
    """Rewrite every stored time as zero-padded 24-hour 'HH:MM'.

    The app accumulated two formats: <input type="time"> wrote "13:00", while
    the seeded day templates and the break builder wrote "1:00 PM". That
    mixture caused two live bugs:
      * an <input type="time"> silently renders a BLANK box for a 12-hour
        value — and on the autosaving F&B rows that blank posted straight back
        and wiped the stored time;
      * string-compared sort keys put "1:00 PM" after "18:00", sinking
        afternoon items to the bottom of the day.
    Values that don't parse are left exactly as they are rather than guessed.
    """
    from models import (ScheduleActivity, ScheduleDay, SubScheduleEntry,
                        MealServiceLocation, DayTemplate)
    import json as _json
    from time_utils import hhmm_or_blank

    def _fix(obj, field):
        current = getattr(obj, field, None)
        if not current:
            return 0
        canonical = hhmm_or_blank(current)
        if canonical and canonical != current:
            setattr(obj, field, canonical)
            return 1
        return 0

    changed = 0
    for act in ScheduleActivity.query.all():
        changed += _fix(act, "time")
    for e in SubScheduleEntry.query.all():
        changed += _fix(e, "time")
    for loc in MealServiceLocation.query.all():
        changed += _fix(loc, "start_time") + _fix(loc, "end_time")
    for d in ScheduleDay.query.all():
        changed += (_fix(d, "sod") + _fix(d, "eod")
                    + _fix(d, "call_time") + _fix(d, "wrap_time"))

    # Templates are the ongoing SOURCE of 12-hour data — rewrite the payloads
    # so freshly generated days stop reintroducing it.
    for tpl in DayTemplate.query.all():
        try:
            raw = _json.loads(tpl.activities_json or "[]")
        except Exception:
            continue
        fixed, dirty = [], False
        for pair in raw:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                fixed.append(pair)
                continue
            canonical = hhmm_or_blank(pair[0]) or pair[0]
            dirty = dirty or canonical != pair[0]
            fixed.append([canonical, pair[1]])
        if dirty:
            tpl.activities_json = _json.dumps(fixed)
            changed += 1

    session.commit()
    print(f"[migration] normalised {changed} time value(s) to 24-hour HH:MM")


def _correct_agency_primary_colour(session):
    """Move the agency primary colour onto the real brand navy.

    The old default (#071B34) was sampled out of a logo PNG before Larry's
    brand package was available. The authoritative value is Midnight #0B2545,
    stated identically in three places including a machine-readable token file.

    Only rewrites a value that is still one of the known-wrong colours — if
    anyone has deliberately picked something, it is left alone.
    """
    import brand
    from models import AgencySetting

    changed = 0
    for row in AgencySetting.query.all():
        current = (row.primary_hex or "").upper()
        if not current or current in {h.upper() for h in brand.LEGACY_HEXES}:
            row.primary_hex = brand.PRIMARY
            changed += 1
    session.commit()
    print(f"[migration] agency primary colour corrected on {changed} row(s)")


def _tidy_crew_name_whitespace(session):
    """Strip and collapse whitespace in stored crew names.

    A trailing space is not cosmetic here: it rendered one crew member as
    "First  Last" with a double gap, and made two otherwise-identical
    placeholder records look like two different people. The model now
    normalises on write; this cleans up what is already stored.

    Reports any record that looks like a placeholder rather than a person —
    those inflate call headcounts on schedules and client exports — but does
    NOT delete or rename them. That is a judgement call, not a migration.
    """
    from models import CrewMember

    changed, flagged = 0, []
    for member in CrewMember.query.all():
        for field in ("first_name", "last_name"):
            current = getattr(member, field, None)
            if isinstance(current, str):
                tidy = " ".join(current.split())
                if tidy != current:
                    setattr(member, field, tidy)
                    changed += 1
        if member.looks_like_placeholder:
            flagged.append(f"#{member.id} {member.full_name!r}")
    session.commit()
    print(f"[migration] tidied whitespace in {changed} crew name field(s)")
    if flagged:
        print("[migration] placeholder-looking crew (left alone, review "
              "manually): " + ", ".join(flagged))


def _unlink_breaks_from_standing_services(session):
    """A crew break is never fed BY a standing beverage service.

    The backfill classified a break linked to a beverage service as Not
    Provided — correctly, since a beverage table feeds nobody AT a break — but
    still wrote that service into `meal_service_id`. That leaves a break saying
    "Not Provided" while carrying a service pointer, which contradicts itself:
    the service then shows a "Feeds" link to a break it does not feed, and
    derives a headcount from it.

    THE FIRST VERSION OF THIS TESTED `is_recurring` ALONE AND FOUND NOTHING.
    Every beverage service on MCDC26 is a legacy row converted from the old
    F&B model, so `is_recurring` is False and the only evidence is the kind or
    the name. `classify()` had always read all three; this repair read one.
    That is exactly the drift `breaks.is_beverage_service` now exists to
    prevent, and it is why this runs again under a new key.

    Clears the pointer only. No break, service, activity or headcount is
    touched, and a break genuinely fed by a MEAL service is left alone.
    """
    from breaks import is_beverage_service
    from models import CrewBreak, MealService
    rows = (session.query(CrewBreak)
            .join(MealService, CrewBreak.meal_service_id == MealService.id)
            .all())
    hit = [cb for cb in rows if is_beverage_service(cb.meal_service)]
    for cb in hit:
        cb.meal_service_id = None
    print(f"[migration] unlinked {len(hit)} crew break(s) from standing "
          "beverage services (a beverage table feeds nobody at a break)")


def _break_durations_from_labels(session):
    """Read the length out of a break's own name, where it says one.

    The backfill only ever recovered a duration from a matching `RETURN FROM`
    row. None of the three live shows has any, so all 91 crew breaks took the
    60-minute house default — including breaks literally named "MORNING BREAK
    — 15 min". A fifteen-minute coffee printed as 10:30–11:30 on the day page,
    the call sheet and the client master, and `break_export_text` rendered it
    as "MORNING BREAK — 15 min — 60 Minutes", contradicting itself in one line.

    TWO guards, both deliberate:

    * **Only where the stored duration is still the house default.** A break
      somebody has already set by hand is their answer, not a gap, and a data
      migration that overwrites a human's edit is worse than the bug.
    * **Only a clean trailing "— N min".** `breaks.duration_from_label` will
      not read a fragment out of the middle of a label. "COFFEE BREAK — 08:00
      CREW" keeps its 60 minutes and gets reported, because a break being
      CALLED coffee is not evidence of how long it is — that inference is the
      exact bug this whole overhaul exists to remove.

    The label is tidied at the same time, since the suffix was only ever there
    because the model had nowhere else to put the number. That also repairs
    the day page's grouping: `group_breaks` groups by label, so two sittings
    reading "...— 15 min" and "..." were two periods rather than one.
    """
    from breaks import DEFAULT_SERVICE_MINUTES, duration_from_label
    from models import CrewBreak
    fixed = relabelled = 0
    for cb in session.query(CrewBreak).all():
        minutes, cleaned = duration_from_label(cb.label)
        if minutes is None:
            continue
        if cleaned != cb.label:
            cb.label = cleaned
            relabelled += 1
        if (cb.duration_minutes == DEFAULT_SERVICE_MINUTES
                and minutes != DEFAULT_SERVICE_MINUTES):
            cb.duration_minutes = minutes
            fixed += 1
    left = [cb for cb in session.query(CrewBreak).all()
            if cb.duration_minutes == DEFAULT_SERVICE_MINUTES
            and duration_from_label(cb.label)[0] is None]
    print(f"[migration] break durations read from labels: {fixed} corrected, "
          f"{relabelled} label(s) tidied, {len(left)} still on the 60-minute "
          "default with nothing in the label to read")


DATA_MIGRATIONS = [
    ("2026-06-30-fb-v2-migrate-entries", _migrate_fb_entries_to_meal_services),
    ("2026-07-02-add-prompter-position", _seed_position_prompter),
    ("2026-07-04-backfill-travel-dates-from-hotel", _backfill_travel_dates_from_hotel),
    ("2026-07-13-backfill-sod-eod-from-call-wrap", _backfill_sod_eod_from_call_wrap),
    # 2026-08-02 — sweep up any legacy F&B entries created AFTER the original
    # v2 conversion (before add_entry/clone were guarded). Same conversion, new
    # key so it runs once more across every show. Safe no-op if none remain.
    ("2026-08-02-fb-v2-reconvert-stragglers", _migrate_fb_entries_to_meal_services),
    # 2026-08-07 — one canonical time format. Run the F&B sweep once more
    # FIRST (any legacy entry still present is invisible on the F&B tab),
    # then normalise every stored time to 24-hour HH:MM.
    ("2026-08-07-fb-v2-reconvert-stragglers-2", _migrate_fb_entries_to_meal_services),
    ("2026-08-07-normalise-times-to-24h", _normalise_stored_times_to_24h),
    # 2026-08-09 — the real ADI brand navy, from Larry's brand token file.
    ("2026-08-09-agency-primary-midnight", _correct_agency_primary_colour),
    # 2026-08-09 — tidy stored crew-name whitespace and report any
    # placeholder-looking records for manual review.
    ("2026-08-09-tidy-crew-name-whitespace", _tidy_crew_name_whitespace),
    # 2026-08-11 — repair the backfill's over-eager linking. See the function.
    ("2026-08-11-unlink-breaks-from-standing-services",
     _unlink_breaks_from_standing_services),
    # 2026-08-11 — and again, because the first pass tested `is_recurring`
    # alone and matched none of the legacy beverage services it was written
    # for. New key so it re-runs; same function, now using the one shared
    # predicate. A no-op wherever the first pass already did the job.
    ("2026-08-11-unlink-breaks-from-beverage-services-v2",
     _unlink_breaks_from_standing_services),
    # 2026-08-12 — the backfill never read the length out of a break's own
    # name, and no live show has the RETURN FROM rows it DID read, so all 91
    # breaks sat on the 60-minute default. See the function.
    ("2026-08-12-break-durations-from-labels", _break_durations_from_labels),
]


# ── Internals ────────────────────────────────────────────────────────────────

def _column_exists(table, col):
    insp = sa_inspect(db.engine)
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def _table_exists(table):
    return sa_inspect(db.engine).has_table(table)


def _ensure_tracking_table():
    # VARCHAR(190), not TEXT: MySQL can't make a TEXT column a PRIMARY KEY
    # without a prefix length, and 190 stays under the utf8mb4 index limit.
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS applied_migrations (
            key VARCHAR(190) PRIMARY KEY,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    db.session.commit()


def _already_applied(key):
    rows = db.session.execute(
        text("SELECT 1 FROM applied_migrations WHERE key=:k"), {"k": key}
    ).fetchall()
    return bool(rows)


def _mark_applied(key):
    db.session.execute(
        text("INSERT INTO applied_migrations (key) VALUES (:k)"), {"k": key}
    )
    db.session.commit()


# ── Public entrypoint ────────────────────────────────────────────────────────

def run_migrations(verbose=True):
    """
    Apply any pending migrations. Safe to run on every app start.
    Returns the list of (description, action) tuples that were applied.
    """
    applied = []
    _ensure_tracking_table()

    # 1. Column adds
    for table, col, ddl in MIGRATIONS:
        if not _table_exists(table):
            # The table itself doesn't exist yet — db.create_all() will create
            # it with the current model definition (which already includes
            # this column), so the ALTER is unnecessary.
            continue
        if _column_exists(table, col):
            continue
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        db.session.commit()
        msg = f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"
        applied.append(("column_add", msg))
        if verbose:
            print(f"[migration] {msg}")

    # 2. Data migrations
    # If ANY are pending, take a pre-migration DB snapshot first. Data
    # migrations can mutate/delete rows (e.g. _migrate_fb_entries_to_meal_services
    # deletes SubScheduleEntry rows after converting them). If one half-fails
    # or produces bad data, we want the pre-state on disk to restore from.
    pending = [(k, fn) for (k, fn) in DATA_MIGRATIONS if not _already_applied(k)]
    if pending:
        try:
            _pre_migration_snapshot(pending, verbose=verbose)
        except Exception as e:
            # Never let backup failure block startup — log and continue.
            # A backup that failed is worse than no migration, but not
            # worse than a broken app.
            if verbose:
                print(f"[migration] WARNING: pre-migration snapshot failed: {e}")

    for key, fn in pending:
        try:
            fn(db.session)
            _mark_applied(key)
            applied.append(("data", key))
            if verbose:
                print(f"[migration] data:{key} applied")
        except Exception as e:
            db.session.rollback()
            if verbose:
                print(f"[migration] data:{key} FAILED: {e}")
            raise

    return applied


# ── Pre-migration snapshot ───────────────────────────────────────────────────

def _pre_migration_snapshot(pending, verbose=True):
    """VACUUM INTO a snapshot of the live DB before any pending data migration
    runs. Path: ~/backups/pre-migration-<ISO ts>.db

    Cheap insurance — only fires when data migrations actually have work to do.
    Uses only stdlib (sqlite3) so nothing here can pull in a broken dep.
    """
    import os
    import sqlite3
    from datetime import datetime, timezone
    from flask import current_app

    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:"):
        # Only SQLite understands VACUUM INTO in this form. If we ever move
        # off SQLite, this branch turns into a no-op (which is safe: the
        # pre-migration snapshot is a defense, not a correctness requirement).
        if verbose:
            print("[migration] snapshot skipped (non-sqlite backend)")
        return

    path = uri.split("sqlite:///", 1)[-1]
    if path and not path.startswith("/"):
        path = os.path.abspath(path)
    if not path or not os.path.exists(path):
        if verbose:
            print(f"[migration] snapshot skipped (source DB not found at {path!r})")
        return

    backup_dir = os.path.expanduser("~/backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(backup_dir, f"pre-migration-{ts}.db")

    con = sqlite3.connect(path)
    try:
        safe = dest.replace("'", "''")
        con.execute(f"VACUUM INTO '{safe}'")
    finally:
        con.close()

    if verbose:
        pending_keys = ", ".join(k for k, _ in pending)
        print(f"[migration] pre-snapshot saved: {dest}  (before applying: {pending_keys})")
