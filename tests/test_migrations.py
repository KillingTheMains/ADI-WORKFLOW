"""
Tests for the migrations system.

Migrations run automatically on every app startup and can mutate/delete
data (e.g. `_migrate_fb_entries_to_meal_services` deletes
`SubScheduleEntry` rows after converting them). Getting these wrong is a
direct data-loss risk, so a few tight tests are worth their weight.

Coverage:
- run_migrations() is idempotent (second run is a no-op)
- applied_migrations correctly prevents re-running keyed data migrations
- prune_old_audit_rows deletes only old un-undone entries; recent and
  undone rows are preserved
"""
from datetime import datetime, timedelta

import pytest


# ─── Idempotency ──────────────────────────────────────────────────────────────

def test_run_migrations_second_run_is_noop(db):
    """After a normal boot, running migrations again should apply nothing."""
    from migrations import run_migrations

    # First run may or may not do anything (depends on which migrations
    # were still pending in the freshly-created DB) — either way the
    # second call must be a strict no-op.
    run_migrations(verbose=False)
    applied = run_migrations(verbose=False)
    assert applied == [], f"expected no-op on rerun, got: {applied}"


def test_data_migrations_tracked_in_applied_migrations(db):
    """Every applied data migration should appear in applied_migrations."""
    from migrations import DATA_MIGRATIONS
    from sqlalchemy import text

    keys = {k for k, _ in DATA_MIGRATIONS}
    tracked = {row[0] for row in db.session.execute(
        text("SELECT key FROM applied_migrations")).fetchall()}

    missing = keys - tracked
    assert not missing, (
        f"Data migrations were not marked as applied: {missing}. "
        "run_migrations must record each keyed migration.")


# ─── Audit log retention ──────────────────────────────────────────────────────

def test_prune_old_audit_rows_keeps_recent(db):
    """Rows younger than the cutoff must survive prune()."""
    from models import AuditLog
    from audit import prune_old_audit_rows

    recent = AuditLog(
        table_name="requests",
        row_id=999,
        action="update",
        undone=False,
        timestamp=datetime.utcnow() - timedelta(days=5),
        before_json="{}",
        after_json="{}",
    )
    db.session.add(recent)
    db.session.commit()

    deleted = prune_old_audit_rows(days=90, verbose=False)
    assert deleted == 0
    assert AuditLog.query.filter_by(row_id=999).first() is not None


def test_prune_old_audit_rows_deletes_old_and_undone_true_is_preserved(db):
    """Only rows older than cutoff AND undone=False should be deleted.

    Undone rows are the 'you can redo this' history and must be kept.
    """
    from models import AuditLog
    from audit import prune_old_audit_rows

    old_undone_true = AuditLog(
        table_name="requests", row_id=8001, action="delete",
        undone=True,  # user undone-then-not-yet-redone
        timestamp=datetime.utcnow() - timedelta(days=200),
        before_json="{}", after_json=None,
    )
    old_undone_false = AuditLog(
        table_name="requests", row_id=8002, action="update",
        undone=False,
        timestamp=datetime.utcnow() - timedelta(days=200),
        before_json="{}", after_json="{}",
    )
    db.session.add_all([old_undone_true, old_undone_false])
    db.session.commit()

    deleted = prune_old_audit_rows(days=90, verbose=False)
    assert deleted >= 1
    # Old + undone=True should survive
    assert AuditLog.query.filter_by(row_id=8001).first() is not None
    # Old + undone=False should be gone
    assert AuditLog.query.filter_by(row_id=8002).first() is None


def test_prune_is_idempotent(db):
    """Second run after a successful prune deletes nothing more."""
    from audit import prune_old_audit_rows

    prune_old_audit_rows(days=90, verbose=False)
    deleted_again = prune_old_audit_rows(days=90, verbose=False)
    assert deleted_again == 0
