#!/usr/bin/env python3
"""
One-time data copy: SQLite  ->  MySQL (or any SQLAlchemy target).  Board: MySQL migration.

Usage (on PythonAnywhere, after creating the MySQL DB + installing PyMySQL):
    cd ~/adi-workflow && source venv/bin/activate
    SOURCE_SQLITE_PATH=~/adi_workflow.db \
    DATABASE_URL='mysql+pymysql://USER:PASS@HOST/USER$DBNAME' \
    SKIP_DB_STARTUP=1 python migrate_sqlite_to_mysql.py

Safe & re-runnable:
  * Reads the SOURCE SQLite file; never modifies it (instant rollback = keep it).
  * Copies through the model-typed tables (db.metadata) so SQLite's string-stored
    datetimes/booleans convert to proper values the MySQL driver formats correctly.
  * Clears each target table first, so a failed run can just be re-run.
  * Verifies source vs target row counts and exits non-zero on any mismatch.
"""
import os
import sys

os.environ.setdefault("SKIP_DB_STARTUP", "1")  # never let create_app touch the DB here

from sqlalchemy import create_engine, text, select, func, inspect as sa_inspect, Table, MetaData
from app import create_app
from extensions import db
from migrations import _ensure_tracking_table

SRC = os.environ.get("SOURCE_SQLITE_PATH")
if not SRC or not os.path.exists(SRC):
    sys.exit(f"ERROR: SOURCE_SQLITE_PATH not found: {SRC!r}")
if not os.environ.get("DATABASE_URL"):
    sys.exit("ERROR: set DATABASE_URL to the TARGET database")

app = create_app()
src_engine = create_engine(f"sqlite:///{os.path.abspath(SRC)}")

with app.app_context():
    tgt = db.engine
    is_mysql = tgt.dialect.name == "mysql"
    print(f"Source : sqlite:///{os.path.abspath(SRC)}")
    print(f"Target : {tgt.url}  (dialect: {tgt.dialect.name})")
    print("-" * 66)

    # 1) Build the full schema on the target from the models + tracking table.
    db.create_all()
    _ensure_tracking_table()

    src_insp = sa_inspect(src_engine)
    report = []

    if is_mysql:
        with tgt.begin() as c:
            c.execute(text("SET FOREIGN_KEY_CHECKS=0"))

    # 2) Copy every model table in FK-dependency order, model-typed both ends.
    with src_engine.connect() as sconn:
        for tbl in db.metadata.sorted_tables:
            if not src_insp.has_table(tbl.name):
                report.append((tbl.name, 0, 0, "skip (absent in source)"))
                continue
            rows = [dict(r._mapping) for r in sconn.execute(tbl.select())]
            with tgt.begin() as c:
                c.execute(tbl.delete())
                if rows:
                    c.execute(tbl.insert(), rows)
            with tgt.connect() as c:
                n = c.execute(select(func.count()).select_from(tbl)).scalar()
            report.append((tbl.name, len(rows), n,
                           "OK" if len(rows) == n else "*** MISMATCH ***"))

    # 3) Carry over the applied_migrations keys so data migrations don't re-run.
    #    (Copy keys only; applied_at defaults — the timestamp is immaterial.)
    if src_insp.has_table("applied_migrations"):
        am = Table("applied_migrations", MetaData(), autoload_with=tgt)
        with src_engine.connect() as sconn:
            src_keys = [r[0] for r in sconn.execute(text("SELECT key FROM applied_migrations"))]
        with tgt.connect() as c:
            have = {r[0] for r in c.execute(select(am.c.key))}
        todo = [{"key": k} for k in src_keys if k not in have]
        if todo:
            with tgt.begin() as c:
                c.execute(am.insert(), todo)
        report.append(("applied_migrations", len(src_keys),
                       len(have) + len(todo), "OK"))

    if is_mysql:
        with tgt.begin() as c:
            c.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    # 4) Report
    print(f"{'table':<34}{'source':>8}{'target':>8}  status")
    print("-" * 66)
    bad = 0
    for name, s, t, status in report:
        if "MISMATCH" in status:
            bad += 1
        print(f"{name:<34}{s:>8}{t:>8}  {status}")
    print("-" * 66)
    if bad:
        sys.exit(f"FAILED: {bad} table(s) mismatched — target left as-is, re-run after investigating.")
    print("SUCCESS: all tables copied and row counts match.")
