#!/usr/bin/env python3
"""
Scheduled SQLite backup for ADI Workflow.

Designed to be wired up as a PythonAnywhere Scheduled Task:

    ~/adi-workflow/venv/bin/python ~/adi-workflow/backup_sqlite.py

Behavior:
- Snapshots the live SQLite DB with SQLite's ONLINE BACKUP API (safe under
  concurrent writes) to a dated file under ~/backups/

  Why the backup API and not VACUUM INTO (2026-09-06): on PythonAnywhere's
  free tier VACUUM INTO of an 11 MB database took 25-45 minutes when it
  worked, hung twice in two days with single-digit CPU seconds burned, and
  on 09-06 produced a file that could not even be READ. `.backup` finished in
  about ten seconds on the same database. The API copies pages; it does not
  rebuild the file, so there is nothing for a throttled host to choke on.

  Two more rules learned the same day:
  * always write to a FRESH file name, then rename into place — a second
    backup onto an existing file name hung and left a -journal behind;
  * verify the copy (`pragma integrity_check`) before calling it a backup.
    A file on disk is not a backup until it has been read back.
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


def verify(path):
    """Read the snapshot back. Returns the integrity_check result ("ok" when
    good). A snapshot that cannot be read is not a snapshot — 09-06's vacuum
    output blocked a sixteen-byte read until `timeout` killed it."""
    con = sqlite3.connect(path)
    try:
        return con.execute("pragma integrity_check").fetchone()[0]
    finally:
        con.close()


def snapshot(db_path, dest_path):
    """Copy the live database to `dest_path` with the online backup API.

    Always writes a FRESH temp file beside the destination, verifies it, then
    renames it into place. Never writes into an existing file — that is the
    shape that hung on 2026-09-06. The rename is atomic, so a reader never
    sees a half-written destination either.
    """
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    tmp = f"{dest_path}.part-{os.getpid()}"
    if os.path.exists(tmp):
        os.remove(tmp)
    src = sqlite3.connect(db_path, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        # pages=256 lets the source's writers in between steps; the live web
        # app writes an audit row on every request and must not be locked out.
        src.backup(dst, pages=256)
    finally:
        dst.close()
        src.close()
    result = verify(tmp)
    if result != "ok":
        try:
            os.remove(tmp)
        finally:
            raise RuntimeError(f"snapshot failed integrity_check: {result}")
    if os.path.exists(dest_path):
        os.remove(dest_path)
    os.replace(tmp, dest_path)
    return dest_path


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
        print(f"[backup] FAIL: snapshot failed: {e}", file=sys.stderr)
        return 1

    size_mb = os.path.getsize(dest) / (1024 * 1024)
    removed = prune(backup_dir, retention)

    print(f"[backup] OK: {dest} ({size_mb:.2f} MB, integrity ok), "
          f"retention={retention}d, pruned={len(removed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
