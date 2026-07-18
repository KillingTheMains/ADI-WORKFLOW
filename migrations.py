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


DATA_MIGRATIONS = [
    ("2026-06-30-fb-v2-migrate-entries", _migrate_fb_entries_to_meal_services),
    ("2026-07-02-add-prompter-position", _seed_position_prompter),
    ("2026-07-04-backfill-travel-dates-from-hotel", _backfill_travel_dates_from_hotel),
    ("2026-07-13-backfill-sod-eod-from-call-wrap", _backfill_sod_eod_from_call_wrap),
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
