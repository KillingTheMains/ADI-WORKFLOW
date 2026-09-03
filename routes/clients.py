"""The Client Database — note #15, 2026-09-03.

Jason, in the meeting: "Where are the Client Names stored? ... We want the
ability to remove clients from this list."

The answer to the first half was that they live in `clients`, and the answer to
the second half was that NOTHING could remove them, because there was no client
management surface anywhere in the app. A client is created as a side effect of
building a show (`shows.new`, from `new_client_name`) and after that it exists
forever. That is why the "Add existing Client" dropdown only ever grew — every
typo and every one-off is still in it.

This is the screen `Position` and `Company` already had and `Client` never got.

DEACTIVATE, DO NOT DELETE, is the whole design:

  · `shows.client_id` references this table and NOTHING cascades.
  · `PRAGMA foreign_keys` is never set, so SQLite will not stop you.
  · SQLite REUSES row ids, so a later client can inherit a deleted one's
    shows.

Deleting show 5 in August left 216 orphan rows by exactly that route. So a
hard delete is offered only when a client has no shows at all; everything else
deactivates, which drops it out of the picker while leaving every existing show
rendering correctly.

MERGE is deliberately not built yet. It is what Larry will want the moment he
sees `Acme` and `Acme Inc.` in one list, but it moves show rows between
clients, and that is a data migration wearing a button. Worth doing properly,
separately, with counts.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from extensions import db
from models import Client

clients_bp = Blueprint("clients", __name__)


def _apply_form(client, f):
    """Returns (ok, message). Name is the only required field."""
    name = (f.get("name") or "").strip()
    if not name:
        return False, "A client needs a name."

    # Case-insensitive duplicate check across the WHOLE table, active or not.
    # Two clients differing only in case is how one client becomes two in
    # every count that groups by client — the same trap `positions.title`
    # already carries. Checked here because there is still no unique index.
    clash = (Client.query
             .filter(db.func.lower(Client.name) == name.lower())
             .filter(Client.id != (client.id or -1))
             .first())
    if clash:
        state = "" if clash.is_active else " (inactive — reactivate it instead)"
        return False, f"“{clash.name}” is already in the client list{state}."

    client.name    = name
    client.contact = (f.get("contact") or "").strip() or None
    client.email   = (f.get("email")   or "").strip() or None
    client.phone   = (f.get("phone")   or "").strip() or None
    client.address = (f.get("address") or "").strip() or None
    client.notes   = (f.get("notes")   or "").strip() or None
    return True, ""


@clients_bp.route("/clients")
def index():
    clients = Client.query.order_by(Client.name).all()
    # Show count drives what the row is allowed to offer, so it is computed
    # once here rather than per button in the template.
    usage = {c.id: c.show_count for c in clients}
    return render_template("clients/index.html", clients=clients, usage=usage)


@clients_bp.route("/clients/new", methods=["POST"])
def create():
    client = Client()
    ok, msg = _apply_form(client, request.form)
    if not ok:
        flash(msg, "warning")
        return redirect(url_for("clients.index"))
    db.session.add(client)
    db.session.commit()
    flash(f"“{client.name}” added.", "success")
    return redirect(url_for("clients.index"))


@clients_bp.route("/clients/<int:client_id>/edit", methods=["POST"])
def edit(client_id):
    client = Client.query.get_or_404(client_id)
    ok, msg = _apply_form(client, request.form)
    if not ok:
        flash(msg, "warning")
        return redirect(url_for("clients.index"))
    db.session.commit()
    flash(f"“{client.name}” updated.", "success")
    return redirect(url_for("clients.index"))


@clients_bp.route("/clients/<int:client_id>/toggle", methods=["POST"])
def toggle(client_id):
    """Deactivate or reactivate. This is the ordinary way to remove a client
    from the dropdown — it is reversible and it cannot orphan anything."""
    client = Client.query.get_or_404(client_id)
    client.is_active = not client.is_active
    db.session.commit()
    if client.is_active:
        flash(f"“{client.name}” is back in the list.", "success")
    else:
        n = client.show_count
        tail = f" Its {n} show(s) are untouched." if n else ""
        flash(f"“{client.name}” hidden from the list.{tail}", "success")
    return redirect(url_for("clients.index"))


@clients_bp.route("/clients/<int:client_id>/delete", methods=["POST"])
def delete(client_id):
    """Permanent, and ONLY when nothing points at it.

    The guard is the point. Refusing here is not politeness — a client with
    shows cannot be deleted safely while nothing cascades and ids get reused.
    """
    client = Client.query.get_or_404(client_id)
    n = client.show_count
    if n:
        flash(f"“{client.name}” is used by {n} show(s), so it cannot be "
              f"deleted. Hide it instead — the shows keep their client.",
              "warning")
        return redirect(url_for("clients.index"))
    name = client.name
    db.session.delete(client)
    db.session.commit()
    flash(f"“{name}” deleted. It had no shows.", "success")
    return redirect(url_for("clients.index"))
