# ADI Workflow

Custom Flask web app for **ADI Productions** — replaces spreadsheets and
disconnected docs with a single platform for show scheduling, crew
rosters, booking/travel logistics, on-site production support (F&B,
COMS, wristbands), and an in-app feature-request / bug-report board.

**Live:** https://killingthemains.pythonanywhere.com
**GitHub:** https://github.com/KillingTheMains/ADI-WORKFLOW

Two active humans use it: **Jason Bielsker** (developer/owner) and
**Larry Kargol** (the AV production professional who runs shows with it
daily).

---

## Tech at a glance

| Layer | Choice |
|---|---|
| Language / framework | Python 3.9 (local) / 3.10 (PA), Flask 3.0.3 |
| DB | SQLite (`~/.adi_workflow.db` local, `/home/killingthemains/adi_workflow.db` live) |
| ORM | Flask-SQLAlchemy 3.1.1 |
| Frontend | Bootstrap 5, vanilla JS, Jinja2, SortableJS |
| Excel export | openpyxl 3.1.5 |
| PDF | Browser Print-to-PDF via `@media print` CSS (formerly WeasyPrint — removed because PA can't install its native deps) |
| Hosting | PythonAnywhere free tier |
| Auth | None. Site is publicly accessible (small trusted team). |

---

## Working on it

**Source of truth:** the Google Drive folder
`01 - ADI_AI Upgrade/08 - Claude Cowork/adi-workflow/`. Edit files there.

**Local running copy:** `~/.adi-workflow/`. rsynced from Drive, this is
the git working copy, this is what a local `python app.py` reads. Local
server lives at `http://localhost:8080` (managed by launchd).

**Deploy:** `cd ~/adi-workflow && git pull && touch /var/www/killingthemains_pythonanywhere_com_wsgi.py`
in the PA Bash console. Details in [DEPLOY.md](./DEPLOY.md).

**Please read [DEPLOY.md](./DEPLOY.md) before installing packages or
running backups on PA.** Two production 500s have been caused by
the `pip3.10 --user` vs. venv trap.

---

## Structure

```
adi-workflow/
├── app.py                  App factory, blueprint registration, seed funcs,
│                            security headers, migration-error banner
├── extensions.py           SQLAlchemy db object
├── models.py               All database models
├── migrations.py           Column-add + data migrations (idempotent, run on
│                            every startup). Includes pre-migration VACUUM
│                            INTO snapshot.
├── audit.py                Undo/redo audit log — SQLAlchemy event listeners,
│                            group-by-request-UUID, dependency-aware restore
├── backup_sqlite.py        Standalone VACUUM INTO backup script (paid PA
│                            scheduled task; free tier: use /backup-db instead)
├── routes/
│   ├── main.py             Dashboard + /backup-db (secret-gated)
│   ├── shows.py            Show CRUD + Duplicate Show
│   ├── schedule.py         Day editor, day templates, Day Settings guard
│   ├── crew.py             Master crew roster
│   ├── show_crew.py        Per-show crew — booking, travel, contact sheet
│   ├── crew_import.py      XLSX bulk importer (booking + travel)
│   ├── oss.py              On-Site Schedule — F&B, COMS, wristbands
│   ├── audit_routes.py     Recent Activity + undo/redo
│   └── requests_routes.py  Requests board + /requests.json + attachments
├── templates/
│   ├── base.html           Layout, sidebar, shared autosave JS
│   ├── shows/, schedule/, crew/, oss/, requests/, audit/
├── tests/
│   ├── conftest.py         In-memory SQLite fixtures
│   ├── test_audit.py       Undo/redo round-trip guarantees
│   ├── test_migrations.py  Idempotency + retention
│   └── test_smoke.py       GET-request health suite (pre-deploy check)
├── static/
├── DEPLOY.md               Deploy runbook + gotchas
├── CHANGELOG.md            Pending Deploy / Deployed by-feature log
└── requirements.txt / requirements-dev.txt
```

---

## Safety systems

- **Undo/redo audit log** captures every insert/update/delete on 13
  tracked tables. Grouped by request UUID so cascaded ops (delete a day
  → cascade to activities + crew rows) undo as one unit. Accessed via
  the **Recent Activity** sidebar link.
- **Pre-migration snapshot** — before any pending data migration runs,
  `run_migrations()` writes a full DB snapshot to
  `~/backups/pre-migration-<ts>.db` via `VACUUM INTO`.
- **Migration failure banner** — if `run_migrations()` throws on startup
  the failure is captured and surfaced as a red banner on every page.
  No more silent boot into a half-migrated DB.
- **Blueprint import resilience** — each route module is imported in its
  own try/except. One broken import → one dead nav link, not a dead
  site. Yellow banner surfaces the failure.
- **Audit log retention** — rows older than 90 days with `undone=False`
  are pruned on startup so the safety-net table cannot fill PA's disk.
- **Security headers** — `X-Frame-Options`, `X-Content-Type-Options`,
  `Referrer-Policy`, and HSTS set via `@app.after_request`.
- **Day Settings date guard** — server-side rename detection with a bold
  warning flash, plus a template `data-date-guard` marker that the
  autosave JS hard-refuses to touch. Two independent layers on the 9/9
  data-loss failure mode.

---

## Testing

```bash
~/.adi-workflow/venv/bin/pip install -r requirements-dev.txt
~/.adi-workflow/venv/bin/pytest -v
```

Test suites:
- `test_audit.py` — insert/update/delete/redo round-trips, including
  BOOLEAN restore. Two `undo_group` cascade tests are `xfail` pending a
  fixture refactor (see xfail reason strings).
- `test_migrations.py` — `run_migrations()` idempotency, applied
  tracking, retention prune correctness.
- `test_smoke.py` — every top-level route returns 200. Would have caught
  the July 2 blueprint outage before deploy.
