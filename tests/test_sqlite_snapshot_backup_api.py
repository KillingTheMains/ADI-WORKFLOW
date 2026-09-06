"""The snapshot uses SQLite's online backup API, writes a fresh file, and
verifies it — and the deploy's step-1 backup can stand in for the
pre-migration snapshot only when it is recent and reads back clean.

Added 2026-09-06 after VACUUM INTO hung on two deploys in two days (three
hours on 09-05, forty-three minutes on 09-06) and on the second day wrote a
file that could not even be read. `.backup` took ten seconds on the same
database. These tests pin the three properties that made the API path safe:

1. the copy is a real, complete, readable database;
2. it is never written INTO an existing file (fresh temp name, then rename);
3. reuse of the deploy backup is strict — stale or unreadable means a fresh
   snapshot, never a skip.
"""
import os
import sqlite3
import time

import pytest

import backup_sqlite
from migrations import _pre_migration_snapshot

PENDING = [("2026-09-06-example", lambda s: None)]


@pytest.fixture(autouse=True)
def _clean_env():
    for k in ("SKIP_PRE_MIGRATION_SNAPSHOT", "ADI_SNAPSHOT_REUSE"):
        os.environ.pop(k, None)
    yield
    for k in ("SKIP_PRE_MIGRATION_SNAPSHOT", "ADI_SNAPSHOT_REUSE"):
        os.environ.pop(k, None)


def _make_db(path, rows=50):
    con = sqlite3.connect(path)
    con.execute("create table t (id integer primary key, v text)")
    con.executemany("insert into t (v) values (?)", [(f"row {i}",) for i in range(rows)])
    con.commit()
    con.close()


def test_snapshot_is_a_complete_readable_copy(tmp_path):
    src = tmp_path / "live.db"
    _make_db(str(src), rows=123)
    dest = tmp_path / "backups" / "copy.db"
    backup_sqlite.snapshot(str(src), str(dest))
    assert dest.exists()
    con = sqlite3.connect(str(dest))
    assert con.execute("select count(*) from t").fetchone()[0] == 123
    assert con.execute("pragma integrity_check").fetchone()[0] == "ok"
    con.close()
    assert backup_sqlite.verify(str(dest)) == "ok"


def test_snapshot_never_writes_into_the_existing_file(tmp_path, monkeypatch):
    """The 09-06 hang was a second backup onto the SAME file name. The
    destination must be replaced by rename, not opened for writing."""
    src = tmp_path / "live.db"
    _make_db(str(src))
    dest = tmp_path / "copy.db"
    dest.write_bytes(b"stale bytes")
    opened = []
    real_connect = sqlite3.connect

    def spy(path, *a, **kw):
        opened.append(str(path))
        return real_connect(path, *a, **kw)

    monkeypatch.setattr(backup_sqlite.sqlite3, "connect", spy)
    backup_sqlite.snapshot(str(src), str(dest))
    assert str(dest) not in opened[:2], "destination was opened for the copy"
    assert backup_sqlite.verify(str(dest)) == "ok"
    assert not [p for p in os.listdir(tmp_path) if ".part-" in p], "temp file left behind"


def test_snapshot_no_longer_uses_vacuum():
    """VACUUM INTO is the thing that hung. It must not come back quietly."""
    import inspect
    import migrations
    for mod in (backup_sqlite, migrations):
        src = inspect.getsource(mod)
        assert 'execute(f"VACUUM' not in src and 'execute("VACUUM' not in src, mod.__name__


@pytest.fixture
def file_db_app(app, tmp_path):
    """The shared app fixture runs on :memory:, and the snapshot rightly
    refuses a source it cannot find on disk. Point it at a real file."""
    live = tmp_path / "live.db"
    _make_db(str(live))
    prev = app.config["SQLALCHEMY_DATABASE_URI"]
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{live}"
    yield app
    app.config["SQLALCHEMY_DATABASE_URI"] = prev


def test_deploy_backup_is_reused_when_fresh_and_clean(file_db_app, tmp_path, capsys):
    app = file_db_app
    reuse = tmp_path / "adi_workflow_today.db"
    _make_db(str(reuse))
    os.environ["ADI_SNAPSHOT_REUSE"] = str(reuse)
    with app.app_context():
        _pre_migration_snapshot(PENDING)
    out = capsys.readouterr().out
    assert "pre-snapshot reused" in out
    assert "2026-09-06-example" in out
    assert "pre-snapshot saved" not in out


def test_stale_deploy_backup_is_not_reused(file_db_app, tmp_path, capsys, monkeypatch):
    app = file_db_app
    monkeypatch.setenv("HOME", str(tmp_path))  # the fresh snapshot lands in ~/backups
    reuse = tmp_path / "adi_workflow_old.db"
    _make_db(str(reuse))
    old = time.time() - 3 * 3600
    os.utime(str(reuse), (old, old))
    os.environ["ADI_SNAPSHOT_REUSE"] = str(reuse)
    with app.app_context():
        _pre_migration_snapshot(PENDING)
    out = capsys.readouterr().out
    assert "NOT reused" in out
    assert "min old" in out
    assert "pre-snapshot saved" in out
    assert os.listdir(tmp_path / "backups")


def test_unreadable_deploy_backup_is_not_reused(file_db_app, tmp_path, capsys, monkeypatch):
    """The 09-06 file: present, right size, unreadable. Must fall through."""
    app = file_db_app
    monkeypatch.setenv("HOME", str(tmp_path))
    reuse = tmp_path / "adi_workflow_bad.db"
    reuse.write_bytes(b"not a database" * 1000)
    os.environ["ADI_SNAPSHOT_REUSE"] = str(reuse)
    with app.app_context():
        _pre_migration_snapshot(PENDING)
    out = capsys.readouterr().out
    assert "NOT reused" in out
    assert "failed verification" in out
    assert "pre-snapshot saved" in out


def test_deploy_sh_names_its_backup_for_reuse():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "deploy.sh")) as fh:
        text = fh.read()
    assert "ADI_SNAPSHOT_REUSE" in text
    assert "SKIP_PRE_MIGRATION_SNAPSHOT" not in text
