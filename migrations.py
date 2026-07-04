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
from sqlalchemy import text
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


DATA_MIGRATIONS = [
    ("2026-06-30-fb-v2-migrate-entries", _migrate_fb_entries_to_meal_services),
    ("2026-07-02-add-prompter-position", _seed_position_prompter),
    ("2026-07-04-backfill-travel-dates-from-hotel", _backfill_travel_dates_from_hotel),
]


# ── Internals ────────────────────────────────────────────────────────────────

def _column_exists(table, col):
    rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def _table_exists(table):
    rows = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": table},
    ).fetchall()
    return bool(rows)


def _ensure_tracking_table():
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS applied_migrations (
            key TEXT PRIMARY KEY,
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
    for key, fn in DATA_MIGRATIONS:
        if _already_applied(key):
            continue
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
