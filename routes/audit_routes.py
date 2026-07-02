"""
Undo/Redo activity feed.

Routes:
  GET  /activity              — recent activity page (all shows)
  POST /activity/undo/<id>    — undo a single audit entry
  POST /activity/redo/<id>    — redo a single audit entry
  POST /activity/undo-group/<group_id>   — undo an entire group
  POST /activity/redo-group/<group_id>   — redo an entire group
"""
from collections import OrderedDict
from flask import (Blueprint, render_template, redirect, url_for, flash, request)
from extensions import db
from models import AuditLog
from audit import undo_entry, redo_entry, undo_group, redo_group

audit_bp = Blueprint("audit", __name__)


@audit_bp.route("/activity")
def recent():
    """List recent audit entries, grouped by request (group_id)."""
    limit = int(request.args.get("limit", "100"))
    entries = (AuditLog.query
               .order_by(AuditLog.id.desc())
               .limit(limit)
               .all())
    # Group by group_id so a cascaded operation shows as one item
    groups = OrderedDict()
    for e in entries:
        key = e.group_id or f"single-{e.id}"
        if key not in groups:
            groups[key] = {
                "group_id":  e.group_id,
                "timestamp": e.timestamp,
                "path":      e.request_path,
                "entries":   [],
                "all_undone": True,
                "any_undone": False,
            }
        groups[key]["entries"].append(e)
        if e.undone:
            groups[key]["any_undone"] = True
        else:
            groups[key]["all_undone"] = False
    return render_template("audit/recent.html",
                           groups=list(groups.values()))


@audit_bp.route("/activity/undo/<int:entry_id>", methods=["POST"])
def undo_one(entry_id):
    e = AuditLog.query.get_or_404(entry_id)
    if undo_entry(e):
        flash(f"Undone: {e.label or e.action}.", "success")
    else:
        flash("Nothing to undo (already undone or unable to reverse).", "info")
    return redirect(url_for("audit.recent"))


@audit_bp.route("/activity/redo/<int:entry_id>", methods=["POST"])
def redo_one(entry_id):
    e = AuditLog.query.get_or_404(entry_id)
    if redo_entry(e):
        flash(f"Redone: {e.label or e.action}.", "success")
    else:
        flash("Nothing to redo.", "info")
    return redirect(url_for("audit.recent"))


@audit_bp.route("/activity/undo-group/<group_id>", methods=["POST"])
def undo_grp(group_id):
    n = undo_group(group_id)
    flash(f"Undone {n} change{'s' if n != 1 else ''} from that action.",
          "success" if n else "info")
    return redirect(url_for("audit.recent"))


@audit_bp.route("/activity/redo-group/<group_id>", methods=["POST"])
def redo_grp(group_id):
    n = redo_group(group_id)
    flash(f"Redone {n} change{'s' if n != 1 else ''}.",
          "success" if n else "info")
    return redirect(url_for("audit.recent"))
