import os
from flask import Blueprint, render_template, send_file, abort, current_app
from models import Show

main_bp = Blueprint("main", __name__)

# A simple secret token — only people who know this URL can download the backup
BACKUP_TOKEN = "adi-backup-ktm-2024"


@main_bp.route("/")
def dashboard():
    shows = Show.query.order_by(Show.show_start.desc()).all()
    return render_template("index.html", shows=shows)


@main_bp.route("/backup/<token>")
def download_backup(token):
    """Download the SQLite database as a backup file.
    URL: /backup/adi-backup-ktm-2024
    """
    if token != BACKUP_TOKEN:
        abort(404)

    db_url = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")

    # Only works for SQLite
    if not db_url.startswith("sqlite:///"):
        abort(400)

    # Strip the sqlite:/// prefix to get the file path
    db_path = db_url.replace("sqlite:///", "")
    db_path = os.path.expanduser(db_path)

    if not os.path.exists(db_path):
        abort(404)

    from datetime import date
    filename = f"adi_workflow_backup_{date.today().isoformat()}.db"

    return send_file(
        db_path,
        as_attachment=True,
        download_name=filename,
        mimetype="application/octet-stream",
    )
