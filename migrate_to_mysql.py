#!/usr/bin/env python3
"""
migrate_to_mysql.py
Run this ONCE on PythonAnywhere to move data from SQLite → MySQL.

Usage:
    python migrate_to_mysql.py
"""
import os, sys, sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Prompt for MySQL password ──────────────────────────────────────────────
pw = os.environ.get("MYSQL_PASSWORD") or input("Enter your PythonAnywhere MySQL password: ").strip()
mysql_url = f"mysql+pymysql://killingthemains:{pw}@killingthemains.mysql.pythonanywhere-services.com/killingthemains$adi_workflow"
os.environ["DATABASE_URL"] = mysql_url
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
    sqlite_path = os.path.expanduser("~/adi_workflow.db")
    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite database not found at {sqlite_path}")
        sys.exit(1)

    app = create_app()
    with app.app_context():
        print("✓ Connected to MySQL and created tables")

        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for table in TABLES_IN_ORDER:
            try:
                cur.execute(f"SELECT * FROM {table}")
                rows = cur.fetchall()
                if not rows:
                    print(f"  - {table}: (empty)")
                    continue

                cols = [d[0] for d in cur.description]
                cols_sql = ", ".join(f"`{c}`" for c in cols)
                placeholders = ", ".join(f":{c}" for c in cols)

                inserted = 0
                for row in rows:
                    record = dict(zip(cols, tuple(row)))
                    try:
                        db.session.execute(
                            db.text(
                                f"INSERT IGNORE INTO `{table}` ({cols_sql}) "
                                f"VALUES ({placeholders})"
                            ),
                            record,
                        )
                        inserted += 1
                    except Exception as row_err:
                        print(f"    ⚠ row skipped in {table}: {row_err}")

                db.session.commit()
                print(f"  ✓ {table}: {inserted} rows")

            except Exception as e:
                db.session.rollback()
                print(f"  ✗ {table}: {e}")

        conn.close()
        print("\n✅ Migration complete — reload your web app!")

if __name__ == "__main__":
    migrate()
