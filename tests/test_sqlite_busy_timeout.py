"""SQLite gets a write-lock timeout long enough to survive a live deploy.

The 2026-09-04 deploy of `4e883f9` failed on `database is locked`. The seed
itself was fine — it ran and reported its predicted counts — but the commit
carrying both the new rows AND the applied_migrations row could not get the
write lock, six seconds after starting. Six seconds is Python's sqlite3
default busy timeout of five, plus change.

SQLite allows exactly one writer. This app writes an audit row on every
request, so deploying against a site anyone is touching means the write lock is
being taken over and over. Five seconds is not long enough to wait for a gap.

The engine options block already existed but only fired for MySQL and
Postgres — SQLite, the backend actually in production, got nothing.
"""
import os

import pytest


def _uri_options(monkeypatch, uri):
    """Build an app against `uri` and return its engine options."""
    monkeypatch.setenv("DATABASE_URL", uri)
    from app import create_app
    monkeypatch.setenv("SKIP_DB_STARTUP", "1")
    app = create_app()
    return app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})


def test_sqlite_waits_for_the_write_lock(monkeypatch):
    """The regression. Without this the default is five seconds and a deploy
    against a live site loses the race."""
    opts = _uri_options(monkeypatch, "sqlite:///:memory:")
    assert opts.get("connect_args", {}).get("timeout", 0) >= 30


def test_the_two_branches_do_not_blur(monkeypatch):
    """SQLite gets a busy timeout; MySQL/Postgres get pool_pre_ping and
    pool_recycle for PythonAnywhere's ~300s idle disconnect. Different
    problems, different fixes, and the sqlite branch must not pick up the
    server-database options by accident.

    Asserted from the sqlite side only: the MySQL branch cannot be built here
    because `pymysql` is a production-only dependency and is not in the local
    venv. Testing it would mean importorskip, which on this machine is a test
    that never runs — worse than an honest one-sided assertion."""
    opts = _uri_options(monkeypatch, "sqlite:///:memory:")
    assert "pool_pre_ping" not in opts
    assert "pool_recycle" not in opts


def test_the_running_app_actually_uses_it(app):
    """Config that never reaches the engine is decoration. This asserts the
    real connection honours it rather than trusting the config dict."""
    from extensions import db
    with app.app_context():
        row = db.session.execute(
            db.text("PRAGMA busy_timeout")).scalar()
    # sqlite3's `timeout` parameter is seconds; the pragma reports ms.
    assert row >= 30000, f"busy_timeout is {row}ms — the deploy race is back"
