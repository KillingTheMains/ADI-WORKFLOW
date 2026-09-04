"""The pre-migration snapshot has an opt-in escape hatch, and it is loud.

Added 2026-09-04 after a real deploy failure. The snapshot is a VACUUM INTO of
the whole database; on PythonAnywhere's free tier it took 24 minutes on an 11MB
database and the process was killed before it finished. The deploy could not
complete — and the thing the snapshot protects against had not yet happened.
A safety measure that makes the operation impossible stops being one.

What these tests actually guard is that it stays OPT-IN and stays NOISY. The
failure mode worth fearing is not "somebody skipped a snapshot on purpose", it
is "the skip quietly became the default and nobody noticed until they needed
the undo".
"""
import os

import pytest

from migrations import _pre_migration_snapshot

PENDING = [("2026-09-04-example", lambda s: None)]


@pytest.fixture(autouse=True)
def _clean_env():
    """Never leak the switch between tests — that is exactly how a skip
    becomes the silent default."""
    prev = os.environ.pop("SKIP_PRE_MIGRATION_SNAPSHOT", None)
    yield
    os.environ.pop("SKIP_PRE_MIGRATION_SNAPSHOT", None)
    if prev is not None:
        os.environ["SKIP_PRE_MIGRATION_SNAPSHOT"] = prev


def test_it_snapshots_by_default(app, capsys):
    """No env var, no skip. The default path must never be the fast one."""
    with app.app_context():
        _pre_migration_snapshot(PENDING)
    out = capsys.readouterr().out
    assert "SNAPSHOT SKIPPED" not in out


def test_the_switch_skips_it(app, capsys):
    os.environ["SKIP_PRE_MIGRATION_SNAPSHOT"] = "1"
    with app.app_context():
        _pre_migration_snapshot(PENDING)
    assert "PRE-MIGRATION SNAPSHOT SKIPPED" in capsys.readouterr().out


def test_skipping_says_what_it_is_about_to_apply(app, capsys):
    """A skipped snapshot has to name the migrations it is leaving unprotected
    — that list is what somebody restores against by hand."""
    os.environ["SKIP_PRE_MIGRATION_SNAPSHOT"] = "1"
    with app.app_context():
        _pre_migration_snapshot(PENDING)
    out = capsys.readouterr().out
    assert "2026-09-04-example" in out
    assert "no automatic undo" in out


def test_only_the_exact_value_skips(app, capsys):
    """"true", "yes" and "0" must NOT skip. A near-miss that silently disabled
    the backup would be the worst possible outcome of adding this switch."""
    for value in ("0", "true", "yes", "", "TRUE"):
        os.environ["SKIP_PRE_MIGRATION_SNAPSHOT"] = value
        with app.app_context():
            _pre_migration_snapshot(PENDING)
        out = capsys.readouterr().out
        assert "SNAPSHOT SKIPPED" not in out, value


def test_deploy_sh_never_sets_it(app):
    """The normal deploy path must always snapshot. If this ever goes red,
    somebody has made the recovery tool's behaviour the default."""
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "deploy.sh")) as fh:
        assert "SKIP_PRE_MIGRATION_SNAPSHOT" not in fh.read()


def test_deploy_finish_sh_does_set_it(app):
    """...and the recovery tool must, or it is just a slower deploy.sh."""
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "deploy_finish.sh")) as fh:
        body = fh.read()
    assert "export SKIP_PRE_MIGRATION_SNAPSHOT=1" in body
    assert "migrations.py" in body
