"""
Undo / Redo audit log.

Attaches SQLAlchemy Session event listeners that snapshot every INSERT,
UPDATE, and DELETE on the tables listed in AUDIT_TRACKED_TABLES. For
each mutation we write one AuditLog row containing the pre-change and
post-change state of the row as JSON.

Rows mutated inside the same HTTP request share a `group_id` (a UUID
assigned in a Flask before_request handler), so a single user action
that cascades — e.g. deleting a ScheduleDay which cascades to its
Activities and CrewRows — can be undone as a single unit.

Undo re-applies the pre-change state (or deletes an inserted row, or
recreates a deleted one). Redo reverses the undo.
"""
import json
import uuid
from datetime import date, datetime
from flask import g, has_request_context, request
from sqlalchemy import event, inspect

from extensions import db


# ── Lazy imports ─────────────────────────────────────────────────────────────
# We can't import models at module load time because models.py imports the
# db object from extensions and audit.py gets wired in via app.py after
# models has fully loaded. Do imports inside functions.

def _tracked_tables():
    from models import AUDIT_TRACKED_TABLES
    return AUDIT_TRACKED_TABLES


def _audit_log_cls():
    from models import AuditLog
    return AuditLog


# ── Session-level attributes so we don't audit our own writes ────────────────
# Prevents infinite recursion: when we insert an AuditLog row inside the
# flush handler, we mark the session as "internal" so the handler skips it.

_INTERNAL_FLAG = "_audit_internal"


# ── JSON serialization of a model row ────────────────────────────────────────

def _serialize(obj):
    """Return a plain dict of column-name → JSON-safe value."""
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        elif isinstance(v, bytes):
            v = v.decode("utf-8", errors="replace")
        out[col.name] = v
    return out


def _deserialize(model_cls, data):
    """Turn a serialized dict back into kwargs suitable for a model constructor
    or setattr.

    Parses ISO dates/datetimes back into their Python types, and normalizes
    boolean-column values to Python ``True`` / ``False``.  SQLite stores bools
    as 0/1 and JSON round-trips are usually fine, but a delete-then-undo can
    reconstruct via a mix of ints/strings depending on when the row was
    serialized.  Normalize here so restored rows are always ``bool``."""
    _TRUE  = {True, 1, "1", "true", "TRUE", "True", "t", "T"}
    _FALSE = {False, 0, "0", "false", "FALSE", "False", "f", "F", ""}
    result = {}
    for col in model_cls.__table__.columns:
        if col.name not in data:
            continue
        v = data[col.name]
        if v is not None:
            coltype = str(col.type).upper()
            if "DATETIME" in coltype and isinstance(v, str):
                try:
                    v = datetime.fromisoformat(v)
                except ValueError:
                    pass
            elif "DATE" in coltype and isinstance(v, str):
                try:
                    v = date.fromisoformat(v)
                except ValueError:
                    pass
            elif "BOOL" in coltype:
                # Cover BOOLEAN (SQLAlchemy) and the underlying SQLite storage
                # variants.  Anything not recognized falls through unchanged.
                if v in _TRUE:
                    v = True
                elif v in _FALSE:
                    v = False
        result[col.name] = v
    return result


# ── Locate the model class for a table name ──────────────────────────────────
#
# Called from every audit-log write and every undo/redo entry. The old
# implementation did `dir(models_module)` on every call — O(models) work
# on the hot path. Build a {tablename: class} dict once on first call.

_MODEL_FOR_TABLE_CACHE = None


def _build_model_cache():
    import models as models_module
    m = {}
    for name in dir(models_module):
        cls = getattr(models_module, name)
        if not isinstance(cls, type):
            continue
        tn = getattr(cls, "__tablename__", None)
        if tn:
            m[tn] = cls
    return m


def _model_for_table(table_name):
    global _MODEL_FOR_TABLE_CACHE
    if _MODEL_FOR_TABLE_CACHE is None:
        _MODEL_FOR_TABLE_CACHE = _build_model_cache()
    cls = _MODEL_FOR_TABLE_CACHE.get(table_name)
    if cls is not None:
        return cls
    # Cache miss — a new tracked model may have been added since first
    # populate. Rebuild once so it's found on subsequent calls without
    # forcing every future lookup to rebuild.
    _MODEL_FOR_TABLE_CACHE = _build_model_cache()
    return _MODEL_FOR_TABLE_CACHE.get(table_name)


# ── The event handler ────────────────────────────────────────────────────────

def _log_change(session, obj, action, before=None, after=None, group_id=None):
    """Write one AuditLog row for a mutation."""
    from models import AuditLog
    tname = obj.__table__.name
    rid   = getattr(obj, "id", None)
    if rid is None and action == "insert":
        # Row not yet flushed; grab id after flush via a helper below.
        # For SQLite the id is assigned during flush, not on autoincrement
        # return, so we need to fetch it after add. We do it lazily.
        return
    entry = AuditLog(
        group_id     = group_id,
        table_name   = tname,
        row_id       = rid,
        action       = action,
        before_json  = json.dumps(before) if before is not None else None,
        after_json   = json.dumps(after) if after is not None else None,
        request_path = (request.path if has_request_context() else None),
        label        = _describe(obj, action),
    )
    session.add(entry)


def _describe(obj, action):
    """One-line human-readable summary for the recent-changes UI."""
    tname = obj.__table__.name
    try:
        if tname == "schedule_days":
            return f"{action} day {getattr(obj, 'date', '')} ({getattr(obj, 'label', '') or ''})"
        if tname == "schedule_activities":
            return f"{action} activity: {getattr(obj, 'description', '')[:50]}"
        if tname == "crew_rows":
            return f"{action} crew row (qty={getattr(obj, 'qty', '?')})"
        if tname == "show_crew_assignments":
            return f"{action} crew assignment"
        if tname == "show_open_slots":
            return f"{action} open slot"
        if tname == "sub_schedule_entries":
            return f"{action} OSS {getattr(obj, 'type', '')}"
        if tname == "meal_services":
            return f"{action} meal service: {getattr(obj, 'name', '')}"
        if tname == "meal_service_locations":
            return f"{action} meal location"
        if tname == "shows":
            return f"{action} show: {getattr(obj, 'name', '')}"
    except Exception:
        pass
    return f"{action} {tname}"


def _handle_flush(session, _flush_context, _instances):
    """SQLAlchemy 'before_flush' handler: captures new/dirty/deleted rows."""
    if getattr(session, _INTERNAL_FLAG, False):
        return
    tracked = set(_tracked_tables())
    # Get or generate the group_id for this request
    if has_request_context():
        group_id = getattr(g, "audit_group_id", None) or str(uuid.uuid4())
        g.audit_group_id = group_id
    else:
        group_id = str(uuid.uuid4())

    # Mark that we're now writing internal AuditLog rows so we don't recurse
    setattr(session, _INTERNAL_FLAG, True)
    try:
        # DELETED rows first — capture their pre-delete state
        for obj in list(session.deleted):
            if obj.__table__.name not in tracked:
                continue
            _log_change(session, obj, "delete",
                        before=_serialize(obj), after=None,
                        group_id=group_id)
        # UPDATED rows — compute both before and after
        for obj in list(session.dirty):
            if obj.__table__.name not in tracked:
                continue
            if not session.is_modified(obj, include_collections=False):
                continue
            insp = inspect(obj)
            after = _serialize(obj)
            before = dict(after)  # start with post-change values
            for attr in insp.attrs:
                if not hasattr(attr, "history"):
                    continue
                h = attr.history
                if h.deleted:
                    # SQLAlchemy stores the pre-change value here
                    v = h.deleted[0]
                    if isinstance(v, (date, datetime)):
                        v = v.isoformat()
                    before[attr.key] = v
            _log_change(session, obj, "update",
                        before=before, after=after,
                        group_id=group_id)
        # NEW rows — id isn't assigned yet, defer to after_insert
        for obj in list(session.new):
            if obj.__table__.name not in tracked:
                continue
            # Stash the group_id + snapshot on the object; after_insert
            # picks them up once the id exists.
            obj.__audit_pending__ = {
                "group_id": group_id,
                "after":    _serialize(obj),   # id will still be None here
            }
    finally:
        setattr(session, _INTERNAL_FLAG, False)


def _handle_after_insert(mapper, connection, target):
    """SQLAlchemy 'after_insert' — the row's id is now assigned."""
    pending = getattr(target, "__audit_pending__", None)
    if pending is None:
        return
    tname = target.__table__.name
    if tname not in _tracked_tables():
        return
    from models import AuditLog
    after = pending["after"]
    after["id"] = target.id   # patch in the freshly-assigned id
    # Insert directly via the connection (session is mid-flush)
    connection.execute(
        AuditLog.__table__.insert().values(
            group_id     = pending["group_id"],
            timestamp    = datetime.utcnow(),
            table_name   = tname,
            row_id       = target.id,
            action       = "insert",
            before_json  = None,
            after_json   = json.dumps(after),
            undone       = False,
            request_path = (request.path if has_request_context() else None),
            label        = _describe(target, "insert"),
        )
    )


# ── Public wiring ────────────────────────────────────────────────────────────

def install_audit_listeners(app):
    """Hook the event listeners into SQLAlchemy's session lifecycle."""
    session = db.session
    event.listen(session, "before_flush", _handle_flush)

    # after_insert is per-mapper. Register lazily on tracked classes.
    @app.before_request
    def _prime():
        # Ensure listeners are attached to every model class. Idempotent —
        # SQLAlchemy will refuse duplicate registrations, wrapped in a try.
        for tname in _tracked_tables():
            cls = _model_for_table(tname)
            if not cls:
                continue
            if not getattr(cls, "_audit_after_insert_wired", False):
                event.listen(cls, "after_insert", _handle_after_insert)
                cls._audit_after_insert_wired = True
        # Set a fresh group_id per request
        g.audit_group_id = str(uuid.uuid4())


# ── Retention: cap unbounded audit-log growth ────────────────────────────────

# Default: keep 90 days of un-undone history. Undone rows are kept regardless
# of age because they carry the "you can redo this" affordance and are rare.
AUDIT_RETENTION_DAYS_DEFAULT = 90


def prune_old_audit_rows(days=AUDIT_RETENTION_DAYS_DEFAULT, verbose=True):
    """Delete AuditLog rows older than `days` where undone=False.

    On PA's ~512 MB disk quota, the audit log — which stores the full
    before/after JSON of every mutation — will grow without bound. This
    caps it. Undone rows are preserved so redo history stays intact.

    Idempotent, safe to run every startup. Returns the number of rows
    deleted (0 if the cutoff catches nothing).
    """
    from datetime import timedelta
    from models import AuditLog
    from extensions import db

    cutoff = datetime.utcnow() - timedelta(days=int(days))
    q = AuditLog.query.filter(AuditLog.timestamp < cutoff,
                              AuditLog.undone == False)  # noqa: E712
    n = q.count()
    if n == 0:
        if verbose:
            print(f"[audit] prune: 0 rows older than {days}d (nothing to do)")
        return 0
    # Use bulk delete — we intentionally do NOT audit-track this operation
    # (a self-pruning audit would loop forever). The pre-migration
    # snapshot in migrations.py protects against catastrophic mistakes.
    q.delete(synchronize_session=False)
    db.session.commit()
    if verbose:
        print(f"[audit] prune: deleted {n} rows older than {days}d")
    return n


# ── Undo / Redo core ─────────────────────────────────────────────────────────

def undo_entry(entry):
    """Reverse a single AuditLog entry. Returns True if applied."""
    from models import AuditLog
    if entry.undone:
        return False
    Model = _model_for_table(entry.table_name)
    if Model is None:
        return False

    # Suppress logging while we apply the undo — otherwise the undo would
    # itself get logged and duplicate the recent-activity view.
    session = db.session
    setattr(session, _INTERNAL_FLAG, True)
    try:
        if entry.action == "insert":
            obj = db.session.get(Model, entry.row_id)
            if obj is not None:
                db.session.delete(obj)
        elif entry.action == "delete":
            data = json.loads(entry.before_json or "{}")
            kwargs = _deserialize(Model, data)
            obj = Model(**kwargs)
            db.session.add(obj)
        elif entry.action == "update":
            obj = db.session.get(Model, entry.row_id)
            if obj is None:
                # Row was later deleted — nothing to update
                return False
            data = json.loads(entry.before_json or "{}")
            deserialized = _deserialize(Model, data)
            for k, v in deserialized.items():
                if k == "id":
                    continue
                setattr(obj, k, v)
        entry.undone = True
        db.session.commit()
        return True
    finally:
        setattr(session, _INTERNAL_FLAG, False)


def redo_entry(entry):
    """Reverse an undo. Returns True if applied."""
    if not entry.undone:
        return False
    Model = _model_for_table(entry.table_name)
    if Model is None:
        return False

    session = db.session
    setattr(session, _INTERNAL_FLAG, True)
    try:
        if entry.action == "insert":
            data = json.loads(entry.after_json or "{}")
            kwargs = _deserialize(Model, data)
            obj = Model(**kwargs)
            db.session.add(obj)
        elif entry.action == "delete":
            obj = db.session.get(Model, entry.row_id)
            if obj is not None:
                db.session.delete(obj)
        elif entry.action == "update":
            obj = db.session.get(Model, entry.row_id)
            if obj is None:
                return False
            data = json.loads(entry.after_json or "{}")
            deserialized = _deserialize(Model, data)
            for k, v in deserialized.items():
                if k == "id":
                    continue
                setattr(obj, k, v)
        entry.undone = False
        db.session.commit()
        return True
    finally:
        setattr(session, _INTERNAL_FLAG, False)


def undo_group(group_id):
    """Undo every entry in a group. Deletes are undone FIRST so parents
    exist before children are recreated."""
    from models import AuditLog
    entries = (AuditLog.query
               .filter_by(group_id=group_id, undone=False)
               .order_by(AuditLog.id.desc())
               .all())
    # Order for undo:
    #   deletes: recreate parents first → schedule_days before activities
    #            before crew_rows
    #   updates + inserts: no ordering constraint really; reverse-chronological
    parent_order = {
        "shows":                    0,
        "requests":                 0,
        "schedule_days":            1,
        "production_phases":        1,
        "schedule_activities":      2,
        "meal_services":            2,
        "sub_schedule_entries":     2,
        "show_crew_assignments":    2,
        "show_open_slots":          2,
        "show_dietary_notes":       2,
        "request_attachments":      2,
        "meal_service_locations":   3,
        "crew_rows":                3,
    }
    def _key(e):
        # For delete undos, restore parents first (low order); for others,
        # keep reverse chronological
        return (parent_order.get(e.table_name, 99) if e.action == "delete" else 99,
                -e.id)
    entries.sort(key=_key)
    n = 0
    for e in entries:
        if undo_entry(e):
            n += 1
    return n


def redo_group(group_id):
    """Redo every previously-undone entry in a group."""
    from models import AuditLog
    entries = (AuditLog.query
               .filter_by(group_id=group_id, undone=True)
               .order_by(AuditLog.id.asc())
               .all())
    n = 0
    for e in entries:
        if redo_entry(e):
            n += 1
    return n
