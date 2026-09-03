"""Note 15 — the Client Database, 2026-09-03.

Jason: "Where are the Client Names stored? ... We want the ability to remove
clients from this list."

They live in `clients`. The reason none could be removed is that there was no
client management surface anywhere in the app — a client is created as a side
effect of building a show and after that nothing could edit or delete it. This
is the screen Position and Company already had.

The tests that matter here are the SAFETY ones, not the CRUD ones:

  · a client with shows cannot be hard-deleted (nothing cascades, SQLite
    reuses row ids, and deleting show 5 in August left 216 orphan rows by
    exactly that route);
  · hiding a client never disturbs a show already using it — including the
    edit form, which must still offer the hidden client it points at.
"""
import pytest

from extensions import db as _db
from models import Client, Show


def _client(db, name="Acme Events", active=True):
    c = Client(name=name, is_active=active)
    db.session.add(c)
    db.session.commit()
    return c


def _show(db, client, name="Test Show", code="TS1"):
    s = Show(name=name, code=code, client_id=client.id)
    db.session.add(s)
    db.session.commit()
    return s


# ── The gap that prompted this ───────────────────────────────────────────────

def test_the_client_page_exists_at_all(client, db):
    """It did not, which was the whole finding."""
    assert client.get("/clients").status_code == 200


def test_a_client_can_be_created_from_the_page(client, db):
    client.post("/clients/new", data={"name": "Northwind"},
                follow_redirects=True)
    assert Client.query.filter_by(name="Northwind").count() == 1


def test_a_client_can_be_edited(client, db):
    c = _client(db)
    client.post(f"/clients/{c.id}/edit",
                data={"name": "Acme Events Ltd", "email": "a@b.com"},
                follow_redirects=True)
    assert _db.session.get(Client, c.id).name == "Acme Events Ltd"


# ── Duplicates ───────────────────────────────────────────────────────────────

def test_a_case_insensitive_duplicate_is_refused(client, db):
    """`clients.name` has no unique index — the same gap `positions.title`
    carries. Two clients differing only in case is how one client becomes two
    in every count that groups by client."""
    _client(db, "Acme Events")
    client.post("/clients/new", data={"name": "ACME EVENTS"},
                follow_redirects=True)
    assert Client.query.count() == 1


def test_a_hidden_client_still_blocks_a_duplicate(client, db):
    """Otherwise hiding one and re-adding it silently makes two."""
    _client(db, "Acme Events", active=False)
    client.post("/clients/new", data={"name": "Acme Events"},
                follow_redirects=True)
    assert Client.query.count() == 1


# ── Hiding: reversible, and invisible to existing work ───────────────────────

def test_hiding_a_client_removes_it_from_the_new_show_picker(client, db):
    c = _client(db, "Hidden Co")
    assert b"Hidden Co" in client.get("/shows/new").data
    client.post(f"/clients/{c.id}/toggle", follow_redirects=True)
    assert b"Hidden Co" not in client.get("/shows/new").data


def test_hiding_is_reversible(client, db):
    c = _client(db)
    client.post(f"/clients/{c.id}/toggle", follow_redirects=True)
    assert _db.session.get(Client, c.id).is_active is False
    client.post(f"/clients/{c.id}/toggle", follow_redirects=True)
    assert _db.session.get(Client, c.id).is_active is True


def test_hiding_does_not_touch_the_shows(client, db):
    c = _client(db)
    s = _show(db, c)
    client.post(f"/clients/{c.id}/toggle", follow_redirects=True)
    assert _db.session.get(Show, s.id).client_id == c.id


def test_the_edit_form_still_offers_a_hidden_client_its_show_uses(client, db):
    """THE ONE THAT MATTERS. Without this, opening an old show whose client was
    later hidden drops the selection, and saving clears a client nobody meant
    to touch."""
    c = _client(db, "Quietly Hidden")
    s = _show(db, c)
    client.post(f"/clients/{c.id}/toggle", follow_redirects=True)
    assert b"Quietly Hidden" in client.get(f"/shows/{s.id}/edit").data


# ── Deleting: guarded ────────────────────────────────────────────────────────

def test_a_client_with_shows_cannot_be_deleted(client, db):
    """Nothing cascades, PRAGMA foreign_keys is never set, and SQLite reuses
    row ids — so a later client can inherit this one's shows."""
    c = _client(db)
    _show(db, c)
    client.post(f"/clients/{c.id}/delete", follow_redirects=True)
    assert _db.session.get(Client, c.id) is not None


def test_the_refusal_is_explained_not_silent(client, db):
    c = _client(db)
    _show(db, c)
    body = client.post(f"/clients/{c.id}/delete", follow_redirects=True).data
    assert b"cannot be deleted" in body


def test_an_unused_client_can_be_deleted(client, db):
    c = _client(db, "Never Used")
    client.post(f"/clients/{c.id}/delete", follow_redirects=True)
    assert _db.session.get(Client, c.id) is None


def test_the_delete_button_is_not_even_offered_when_in_use(client, db):
    c = _client(db, "Busy Client")
    _show(db, c)
    body = client.get("/clients").data
    assert f"/clients/{c.id}/delete".encode() not in body
