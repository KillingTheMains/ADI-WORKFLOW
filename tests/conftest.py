"""
pytest fixtures for ADI Workflow.

Each test gets:
- a fresh Flask app configured against an in-memory SQLite DB
- an application context pushed for the test's duration
- a test client if it needs to make requests

The real ~/.adi_workflow.db is never touched.
"""
import os
import sys

import pytest


# Ensure the repo root is importable regardless of where pytest is invoked from.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


@pytest.fixture
def app():
    """Fresh Flask app per test, backed by in-memory SQLite.

    The audit-log system installs its `after_insert` mapper listeners inside
    a `@app.before_request` hook (`_prime`) — production requests fire it
    automatically, but tests that never hit a request would miss it.
    We push a request context AND fire a bogus GET so `_prime` runs, which
    also seeds ``g.audit_group_id``.
    """
    # Isolate the app under test from the developer's real DB.
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    # No BACKUP_KEY in tests unless a test sets it — /backup-db should 404.
    os.environ.pop("BACKUP_KEY", None)

    # Import lazily so DATABASE_URL is honored on first app creation.
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        # Fire the before_request hook so per-mapper `after_insert` listeners
        # get wired up and `g.audit_group_id` is set.  We use the test client
        # to synthesize a real request cycle.
        app.test_client().get("/")
        yield app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db(app):
    """The SQLAlchemy db handle, already bound to the app-context session."""
    from extensions import db as _db
    return _db
