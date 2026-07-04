"""
Route smoke tests — the "does the site still boot?" pre-deploy check.

Would have caught the July 2 blueprint outage (BuildError on url_for in
base.html) before it reached Larry. Every route in the parametrized list
is hit with GET; anything other than 200/302 fails the test.

Meant to be cheap and comprehensive. Do NOT put behavior assertions in
here — that's what the per-feature tests are for. This one just says
"the app boots and every top-level page renders."
"""
import pytest


def _mint_a_show(db):
    """Create the minimum data every show-scoped route needs."""
    from models import Show, ScheduleDay, Client, Venue
    from datetime import date

    client = Client(name="Smoke Test Client")
    venue = Venue(name="Smoke Test Venue", city="Testville", state="CA")
    db.session.add_all([client, venue])
    db.session.flush()
    show = Show(
        name="Smoke Test Show",
        code="SMKE26",
        status="Planning",
        client_id=client.id,
        venue_id=venue.id,
        show_start=date(2026, 9, 8),
        show_end=date(2026, 9, 17),
    )
    db.session.add(show)
    db.session.flush()
    day = ScheduleDay(show_id=show.id, date=date(2026, 9, 10), phase="Load In")
    db.session.add(day)
    db.session.commit()
    return show.id, day.id


# ─── Top-level pages ──────────────────────────────────────────────────────────

# Routes that don't need any pre-seeded show data
_STATIC_ROUTES = [
    "/",
    "/requests",
    "/requests.json",
    "/activity",
    "/crew/",
    "/shows/",
    "/shows/new",
]


@pytest.mark.parametrize("path", _STATIC_ROUTES)
def test_static_route_returns_ok(client, path):
    r = client.get(path)
    assert r.status_code in (200, 302), (
        f"{path} → {r.status_code} (expected 200 or 302). "
        f"body head: {r.data[:120]!r}"
    )


# ─── Show-scoped pages ────────────────────────────────────────────────────────

_SHOW_SCOPED_ROUTES = [
    "/shows/{show_id}",
    "/shows/{show_id}/edit",
    "/shows/{show_id}/schedule",
    "/shows/{show_id}/schedule/{day_id}",
    "/shows/{show_id}/crew",
    "/shows/{show_id}/crew/travel",
    "/shows/{show_id}/crew/travel/print",
    "/shows/{show_id}/crew/contact-sheet",
    "/shows/{show_id}/oss",
]


@pytest.mark.parametrize("path_tpl", _SHOW_SCOPED_ROUTES)
def test_show_scoped_route_returns_ok(client, db, path_tpl):
    show_id, day_id = _mint_a_show(db)
    path = path_tpl.format(show_id=show_id, day_id=day_id)
    r = client.get(path)
    assert r.status_code in (200, 302), (
        f"{path} → {r.status_code} (expected 200 or 302). "
        f"body head: {r.data[:120]!r}"
    )


# ─── Security headers on the dashboard (guards against Batch 3 regression) ───

def test_security_headers_are_set(client):
    r = client.get("/")
    for h in ("X-Frame-Options", "X-Content-Type-Options",
              "Referrer-Policy", "Strict-Transport-Security"):
        assert h in r.headers, f"missing {h}"


# ─── Backup route is gated ────────────────────────────────────────────────────

def test_backup_route_404_without_key(client):
    r = client.get("/backup-db")
    assert r.status_code == 404, (
        "Backup route must return 404 when BACKUP_KEY is unset or the "
        "?key= param is missing — leaking existence of the endpoint is bad.")
