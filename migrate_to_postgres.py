#!/usr/bin/env python3
"""
migrate_to_postgres.py
Run this ONCE on your local Mac to move data from local SQLite → Supabase PostgreSQL.

Usage:
    python migrate_to_postgres.py
"""
import os, sys, sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Get Supabase connection string ─────────────────────────────────────────
db_url = os.environ.get("DATABASE_URL") or input(
    "Paste your Supabase connection string\n"
    "(Settings → Database → URI, replace [YOUR-PASSWORD]): "
).strip()

os.environ["DATABASE_URL"] = db_url
os.environ["SECRET_KEY"] = "migration-temp"

from app import create_app
from extensions import db

TABLES_IN_ORDER = [
    "clients",
    "venues",
    "companies",
    "positions",
    "crew_members",
    "shows",
    "show_crew_assignments",
    "production_phases",
    "day_templates",
    "schedule_days",
    "schedule_activities",
    "crew_rows",
]

def migrate():
    sqlite_path = os.path.expanduser("~/.adi_workflow.db")
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite database not found at {sqlite_path}")
        sys.exit(1)

    print(f"\nReading from: {sqlite_path}")
    print("Connecting to Supabase PostgreSQL...\n")

    app = create_app()
    with app.app_context():
        print("✓ Connected to Supabase and created tables\n")

        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for table in TABLES_IN_ORDER:
            try:
                cur.execute(f"SELECT * FROM {table}")
                rows = cur.fetchall()
                if not rows:
                    print(f"  - {table}: (empty, skipping)")
                    continue

                cols = [d[0] for d in cur.description]
                cols_sql = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join(f":{c}" for c in cols)

                inserted = 0
                for row in rows:
                    record = dict(zip(cols, tuple(row)))
                    try:
                        db.session.execute(
                            db.text(
                                f'INSERT INTO "{table}" ({cols_sql}) '
                                f"VALUES ({placeholders}) "
                                f"ON CONFLICT DO NOTHING"
                            ),
                            record,
                        )
                        inserted += 1
                    except Exception as row_err:
                        db.session.rollback()
                        print(f"    ⚠ row skipped in {table}: {row_err}")

                db.session.commit()
                print(f"  ✓ {table}: {inserted} rows migrated")

            except Exception as e:
                db.session.rollback()
                print(f"  ✗ {table}: {e}")

        conn.close()
        print("\n✅ Migration complete!")
        print("Next: update your PythonAnywhere WSGI file with the DATABASE_URL and reload.")

if __name__ == "__main__":
    migrate()
