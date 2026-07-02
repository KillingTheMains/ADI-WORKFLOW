"""
Requests board — the "ADI Build Notes" replacement.

Jason and Larry track feature requests, bug reports, and questions here.
Everything is inline-editable, filterable, and audit-tracked (undoable).

Routes:
  GET  /requests                     — main board
  POST /requests/add                 — create a new request
  POST /requests/<id>/edit           — inline-edit any field
  POST /requests/<id>/delete         — remove a request
  POST /requests/<id>/status         — quick status change (button)
  POST /requests/reorder             — drag-to-reorder within a status
"""
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify)
from extensions import db
from models import (Request as ReqModel,
                    REQUEST_PRIORITIES, REQUEST_STATUSES,
                    REQUEST_CATEGORIES, REQUEST_STATUS_LABELS)

requests_bp = Blueprint("requests_bp", __name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _clean(val, allowed, default=None):
    """Return val if it's in allowed, else default."""
    if val is None:
        return default
    val = val.strip() if isinstance(val, str) else val
    return val if val in allowed else default


def _apply_field(req, field, raw):
    """Update req.field from a raw form value. Returns True if changed."""
    if field == "title":
        v = (raw or "").strip()
        if not v:
            return False
        if req.title != v:
            req.title = v
            return True
    elif field == "description":
        v = (raw or "").strip() or None
        if req.description != v:
            req.description = v
            return True
    elif field == "notes":
        v = (raw or "").strip() or None
        if req.notes != v:
            req.notes = v
            return True
    elif field == "requested_by":
        v = (raw or "").strip() or None
        if req.requested_by != v:
            req.requested_by = v
            return True
    elif field == "commit_ref":
        v = (raw or "").strip() or None
        if req.commit_ref != v:
            req.commit_ref = v
            return True
    elif field == "category":
        v = _clean(raw, REQUEST_CATEGORIES, req.category)
        if req.category != v:
            req.category = v
            return True
    elif field == "priority":
        v = _clean(raw, REQUEST_PRIORITIES, req.priority)
        if req.priority != v:
            req.priority = v
            return True
    elif field == "status":
        v = _clean(raw, REQUEST_STATUSES, req.status)
        if v and req.status != v:
            req.status = v
            # Auto-stamp deployed_at when a request enters "deployed"
            if v == "deployed" and not req.deployed_at:
                req.deployed_at = datetime.utcnow()
            return True
    return False


# ── main board ───────────────────────────────────────────────────────────────

@requests_bp.route("/requests")
def index():
    # Filters
    f_status   = request.args.get("status", "")
    f_priority = request.args.get("priority", "")
    f_category = request.args.get("category", "")
    f_by       = request.args.get("by", "")
    q          = ReqModel.query

    if f_status in REQUEST_STATUSES:
        q = q.filter(ReqModel.status == f_status)
    if f_priority in REQUEST_PRIORITIES:
        q = q.filter(ReqModel.priority == f_priority)
    if f_category in REQUEST_CATEGORIES:
        q = q.filter(ReqModel.category == f_category)
    if f_by:
        q = q.filter(ReqModel.requested_by.ilike(f"%{f_by}%"))

    # Order: status priority (open work first), then priority, then sort_order,
    # then most-recently-updated first.
    status_rank = {s: i for i, s in enumerate(
        ["requested", "in_progress", "ready_to_test", "deferred", "deployed"])}
    prio_rank = {p: i for i, p in enumerate(REQUEST_PRIORITIES)}

    all_reqs = q.all()
    all_reqs.sort(key=lambda r: (
        status_rank.get(r.status, 99),
        prio_rank.get(r.priority, 99),
        r.sort_order or 0,
        -(r.updated_at.timestamp() if r.updated_at else 0),
    ))

    # Counts for the top bar
    counts = {s: 0 for s in REQUEST_STATUSES}
    for r in ReqModel.query.all():
        if r.status in counts:
            counts[r.status] += 1

    # Distinct requesters for filter dropdown
    people = sorted({r.requested_by for r in ReqModel.query.all()
                     if r.requested_by})

    return render_template(
        "requests/index.html",
        requests_list=all_reqs,
        counts=counts,
        people=people,
        priorities=REQUEST_PRIORITIES,
        statuses=REQUEST_STATUSES,
        status_labels=REQUEST_STATUS_LABELS,
        categories=REQUEST_CATEGORIES,
        filters={"status": f_status, "priority": f_priority,
                 "category": f_category, "by": f_by},
    )


# ── create ───────────────────────────────────────────────────────────────────

@requests_bp.route("/requests/add", methods=["POST"])
def add():
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("A title is required to create a request.", "warning")
        return redirect(url_for("requests_bp.index"))

    r = ReqModel(
        title=title,
        description=(request.form.get("description") or "").strip() or None,
        category=_clean(request.form.get("category"),
                        REQUEST_CATEGORIES, "feature"),
        priority=_clean(request.form.get("priority"),
                        REQUEST_PRIORITIES, "P2"),
        status=_clean(request.form.get("status"),
                      REQUEST_STATUSES, "requested"),
        requested_by=(request.form.get("requested_by") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
    )
    db.session.add(r)
    db.session.commit()
    flash(f"Added request: “{title[:60]}”.", "success")
    return redirect(url_for("requests_bp.index",
                            status=request.args.get("status", ""),
                            priority=request.args.get("priority", "")))


# ── inline edit ──────────────────────────────────────────────────────────────

@requests_bp.route("/requests/<int:req_id>/edit", methods=["POST"])
def edit(req_id):
    """Inline edit — handles any subset of fields present on the form.

    Uses "field-present" semantics: only fields actually in request.form are
    considered (so partial autosave POSTs don't wipe unrelated columns).
    """
    r = ReqModel.query.get_or_404(req_id)
    changed_any = False
    for field in ("title", "description", "notes", "requested_by",
                  "commit_ref", "category", "priority", "status"):
        if field in request.form:
            if _apply_field(r, field, request.form.get(field)):
                changed_any = True
    if changed_any:
        r.updated_at = datetime.utcnow()
        db.session.commit()
    # If XHR autosave, return JSON. Else redirect.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "changed": changed_any,
                        "status": r.status, "priority": r.priority})
    return redirect(url_for("requests_bp.index"))


# ── quick status buttons ─────────────────────────────────────────────────────

@requests_bp.route("/requests/<int:req_id>/status", methods=["POST"])
def set_status(req_id):
    r = ReqModel.query.get_or_404(req_id)
    new_status = _clean(request.form.get("status"),
                        REQUEST_STATUSES, r.status)
    if new_status and new_status != r.status:
        r.status = new_status
        r.updated_at = datetime.utcnow()
        if new_status == "deployed" and not r.deployed_at:
            r.deployed_at = datetime.utcnow()
        db.session.commit()
    return redirect(url_for("requests_bp.index",
                            status=request.args.get("status", ""),
                            priority=request.args.get("priority", "")))


# ── delete ───────────────────────────────────────────────────────────────────

@requests_bp.route("/requests/<int:req_id>/delete", methods=["POST"])
def delete(req_id):
    r = ReqModel.query.get_or_404(req_id)
    title = r.title
    db.session.delete(r)
    db.session.commit()
    flash(f"Deleted request: “{title[:60]}”. Undo via Recent Activity.",
          "info")
    return redirect(url_for("requests_bp.index"))


# ── drag-to-reorder ──────────────────────────────────────────────────────────

@requests_bp.route("/requests/reorder", methods=["POST"])
def reorder():
    """Body: {"ids": [12, 7, 3, ...]}  — sets sort_order in that sequence."""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    for i, rid in enumerate(ids):
        r = ReqModel.query.get(int(rid))
        if r:
            r.sort_order = i
    db.session.commit()
    return jsonify({"ok": True, "count": len(ids)})
