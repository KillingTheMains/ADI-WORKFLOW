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
]


# ── Data migrations (run once, tracked by key) ───────────────────────────────
# Each entry: (key, callable). The callable receives the db session.

DATA_MIGRATIONS = [
    # Example pattern (no real migrations yet):
    # ("2026-06-01-backfill-something", lambda s: s.execute(text("UPDATE ..."))),
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
