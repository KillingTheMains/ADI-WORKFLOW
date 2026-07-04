#!/usr/bin/env python3
"""
Scheduled SQLite backup for ADI Workflow.

Designed to be wired up as a PythonAnywhere Scheduled Task:

    ~/adi-workflow/venv/bin/python ~/adi-workflow/backup_sqlite.py

Behavior:
- Snapshots the live SQLite DB (via VACUUM INTO — safe under concurrent writes)
  to a dated file under ~/backups/
- Retains the most recent RETENTION_DAYS (default 14) daily snapshots and
  deletes older ones
- Idempotent — running twice on the same day overwrites the day's snapshot,
  it doesn't accumulate multiple per-day copies
- Prints a one-line summary to stdout (PA emails scheduled-task output)

Env vars honored:
  DATABASE_URL   — same sqlite:///... URI the app uses. Defaults to
                    /home/killingthemains/adi_workflow.db if not set.
  BACKUP_DIR     — defaults to ~/backups
  RETENTION_DAYS — defaults to 14

This script is deliberately stand-alone: no Flask imports, no app context,
no sqlalchemy — just stdlib. If Flask is broken, backups still run.
"""
import os
import re
import sys
import sqlite3
from datetime import datetime, timezone


DEFAULT_DB_PATH = "/home/killingthemains/adi_workflow.db"
DEFAULT_BACKUP_DIR = os.path.expanduser("~/backups")
DEFAULT_RETENTION_DAYS = 14

FNAME_PATTERN = re.compile(r"^adi_workflow_(\d{8})\.db$")


def _sqlite_path_from_uri(uri):
    if not uri or not uri.startswith("sqlite:"):
        return None
    path = uri.split("sqlite:///", 1)[-1]
    if path.startswith("/"):
        return path
    return os.path.expanduser("~/" + path) if path.startswith("~") else os.path.abspath(path)


def resolve_db_path():
    uri = os.environ.get("DATABASE_URL", "").strip()
    p = _sqlite_path_from_uri(uri) if uri else None
    return p or DEFAULT_DB_PATH


def snapshot(db_path, dest_path):
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    if os.path.exists(dest_path):
        os.remove(dest_path)
    con = sqlite3.connect(db_path)
    try:
        safe = dest_path.replace("'", "''")
        con.execute(f"VACUUM INTO '{safe}'")
    finally:
        con.close()


def prune(backup_dir, retention_days):
    """Delete adi_workflow_YYYYMMDD.db files older than the newest N days."""
    if not os.path.isdir(backup_dir):
        return []
    dated = []
    for name in os.listdir(backup_dir):
        m = FNAME_PATTERN.match(name)
        if not m:
            continue
        dated.append((m.group(1), os.path.join(backup_dir, name)))
    dated.sort(reverse=True)  # newest first, YYYYMMDD sorts correctly
    removed = []
    for _, path in dated[retention_days:]:
        try:
            os.remove(path)
            removed.append(path)
        except OSError as e:
            print(f"  (could not prune {path}: {e})", file=sys.stderr)
    return removed


def main():
    db_path = resolve_db_path()
    backup_dir = os.environ.get("BACKUP_DIR", "").strip() or DEFAULT_BACKUP_DIR
    try:
        retention = int(os.environ.get("RETENTION_DAYS", "").strip()
                        or DEFAULT_RETENTION_DAYS)
    except ValueError:
        retention = DEFAULT_RETENTION_DAYS

    if not os.path.exists(db_path):
        print(f"[backup] FAIL: DB file not found at {db_path}", file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = os.path.join(backup_dir, f"adi_workflow_{today}.db")

    try:
        snapshot(db_path, dest)
    except Exception as e:
        print(f"[backup] FAIL: VACUUM INTO failed: {e}", file=sys.stderr)
        return 1

    size_mb = os.path.getsize(dest) / (1024 * 1024)
    removed = prune(backup_dir, retention)

    print(f"[backup] OK: {dest} ({size_mb:.2f} MB), "
          f"retention={retention}d, pruned={len(removed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
