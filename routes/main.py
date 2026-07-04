"""
Dashboard + secret-gated SQLite backup download.

Backup design (see Fable 5 review, July 4 2026):
- We run on SQLite. `VACUUM INTO` is the correct way to snapshot a live
  DB without copy-during-write corruption.
- The download route is gated behind BACKUP_KEY (env var) because the
  site has no auth and anyone with a URL can hit it. Without the key
  the route returns 404 to avoid confirming the endpoint exists.
- The scheduled task (backup_sqlite.py) writes dated copies under
  ~/backups/ and prunes to the most recent N (default 14).
"""
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

from flask import (Blueprint, render_template, request, current_app,
                   send_file, abort)

from models import Show


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def dashboard():
    shows = Show.query.order_by(Show.show_start.desc()).all()
    return render_template("index.html", shows=shows)


# ── SQLite backup (VACUUM INTO snapshot) ─────────────────────────────────────

def _sqlite_path_from_uri(uri):
    """Extract the on-disk sqlite file path from a SQLAlchemy URI.

    'sqlite:////home/killingthemains/adi_workflow.db'  →  '/home/killingthemains/adi_workflow.db'
    'sqlite:///~/x.db'                                 →  expanduser'd path
    Returns None if the URI is not a sqlite one (defensive — no backup for
    other backends via this route)."""
    if not uri or not uri.startswith("sqlite:"):
        return None
    # sqlite:///relative or sqlite:////absolute
    path = uri.split("sqlite:///", 1)[-1]
    if path.startswith("/"):
        return path
    return os.path.expanduser("~/" + path) if path.startswith("~") else os.path.abspath(path)


def snapshot_sqlite(db_path, dest_path):
    """VACUUM INTO snapshot from db_path → dest_path.

    Safer than a naive file copy while writes are in flight — SQLite
    guarantees the destination is a consistent snapshot even if the
    source is being written to concurrently.
    """
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    # Remove any stale file at dest — VACUUM INTO refuses to overwrite.
    if os.path.exists(dest_path):
        os.remove(dest_path)
    con = sqlite3.connect(db_path)
    try:
        # Quoted path so filenames with spaces survive; SQLite escapes single-quotes by doubling.
        safe = dest_path.replace("'", "''")
        con.execute(f"VACUUM INTO '{safe}'")
    finally:
        con.close()


@main_bp.route("/backup-db")
def backup_db():
    """Download a fresh VACUUM INTO snapshot of the live SQLite DB.

    Requires ?key=<BACKUP_KEY> matching the BACKUP_KEY env var. Without
    a matching key the route returns 404 (not 401) so the endpoint's
    existence is not confirmed to an unauthed caller.

    If BACKUP_KEY is not set at all we refuse to serve the route entirely
    — you should set it before enabling this feature in prod.
    """
    expected = os.environ.get("BACKUP_KEY", "").strip()
    provided = (request.args.get("key") or "").strip()
    if not expected or not provided or provided != expected:
        abort(404)

    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    db_path = _sqlite_path_from_uri(uri)
    if not db_path or not os.path.exists(db_path):
        current_app.logger.error(
            "backup_db: could not locate sqlite file at %r (uri=%r)", db_path, uri)
        abort(500)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f"adi_workflow_backup_{ts}.db"

    # Snapshot to a temp file, hand to send_file which streams + closes it.
    tmpdir = tempfile.mkdtemp(prefix="adi_backup_")
    dest = os.path.join(tmpdir, fname)
    try:
        snapshot_sqlite(db_path, dest)
    except Exception as e:
        current_app.logger.exception("backup_db: VACUUM INTO failed: %s", e)
        abort(500)

    # send_file will read the file; we don't clean the tmpdir here — PA
    # sweeps /tmp routinely. Local mac: small cost, negligible.
    return send_file(
        dest,
        as_attachment=True,
        download_name=fname,
        mimetype="application/octet-stream",
    )
