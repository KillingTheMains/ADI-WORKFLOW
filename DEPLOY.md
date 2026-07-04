# Deploying ADI Workflow

## Traps that have already bitten us — read first

**1. Installing packages on PA: use the venv's pip, not `pip3.10 --user`.**

The Flask app on PA runs from a virtualenv at
`/home/killingthemains/adi-workflow/venv/`. Packages installed with
`pip3.10 install --user <pkg>` land in `~/.local/lib/...` where the venv
can't see them — the module still shows `ModuleNotFoundError` when Flask
imports it. This bit us with `openpyxl` twice (July 2–3) and caused two
production 500s for Larry.

**The only correct install command on PA is:**
```bash
~/adi-workflow/venv/bin/pip install -r ~/adi-workflow/requirements.txt
```
or for a single package:
```bash
~/adi-workflow/venv/bin/pip install <package>==<version>
```

**2. `backup_db.py` in the repo is DEAD CODE — do not use it.**

It shells out to `mysqldump` against a MySQL host. The app runs on SQLite.
That script has never produced a valid backup. The real backup story is:
- Manual: `GET /backup-db?key=<BACKUP_KEY>` downloads a fresh
  `VACUUM INTO` snapshot. Set `BACKUP_KEY` as an env var (see WSGI file).
- Automatic: `backup_sqlite.py` is the standalone script for a scheduled
  task — but requires paid PA. On free tier, use the manual download.
- Pre-migration: `run_migrations()` takes a `VACUUM INTO` snapshot to
  `~/backups/pre-migration-<ts>.db` automatically whenever a data
  migration is pending. Free.

**3. Environment variables live in the PA WSGI file (free tier).**

If the PA Web tab doesn't show an "Environment variables" section
(happens on some free-tier accounts), edit the WSGI file directly:
`/var/www/killingthemains_pythonanywhere_com_wsgi.py`. Add lines like:
```python
os.environ['SECRET_KEY'] = 'a-long-random-string-from-secrets-token-urlsafe'
os.environ['BACKUP_KEY'] = 'a-different-long-random-string'
```
Save the file, then click Reload on the Web tab.

---

## TL;DR — one command to go live

Open the **PythonAnywhere → Bash console** and paste:

```bash
cd ~/adi-workflow && git pull && touch /var/www/killingthemains_pythonanywhere_com_wsgi.py
```

That's it. The `touch` triggers a web app reload, and on reload the app
auto-applies any pending schema migrations. No more manual `ALTER TABLE`s.

If for any reason `touch` doesn't pick up the reload (rare), open the
**Web tab** on PA and click **Reload**.

---

## Workflow

1. We work on features in Cowork sessions. Code lives in:
   - **Source of truth:** Google Drive folder (`08 - Claude Cowork/adi-workflow/`)
   - **Local running copy:** `~/.adi-workflow/`
   - **GitHub:** `https://github.com/KillingTheMains/ADI-WORKFLOW`
   - **Live site:** `https://killingthemains.pythonanywhere.com`

2. After every push to GitHub, [CHANGELOG.md](./CHANGELOG.md) gets an entry
   under **Pending Deploy** describing what's about to ship.

3. When you're ready to push to production, run the one-liner above. The
   Pending entries move to **Deployed** with the date.

---

## How auto-migrations work

`migrations.py` declares the desired schema as a list of `(table, column, ddl)`
tuples. On every app startup it:

1. Connects to the live SQLite DB
2. Checks `PRAGMA table_info` per table
3. Runs `ALTER TABLE` for any missing column
4. Skips anything that's already there (so it's safe to run on every start)

For migrations that aren't simple column-adds (backfills, renames),
add an entry to `DATA_MIGRATIONS` with a unique key. A tracking table
`applied_migrations` prevents them from running twice.

---

## Safer rsync (Google Drive → local)

The original rsync command in the project brief uses `--delete` without
excludes for files that live only in the local checkout. The safer
version, used in current Cowork sessions:

```bash
rsync -av --delete \
  --exclude='.git/' \
  --exclude='venv/' \
  --exclude='instance/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.gitignore' \
  --exclude='backup_db.py' \
  --exclude='migrate_to_postgres.py' \
  --exclude='migrate_to_mysql.py' \
  --exclude='seed_data.sql' \
  --exclude='wsgi.py' \
  "/Users/jasonbielsker/Library/CloudStorage/GoogleDrive-jason@killingthemains.com/.shortcut-targets-by-id/1B8-JuyJsJRQCiwmIZg6kuhSPmVG8Hq83/01 - ADI_AI Upgrade/08 - Claude Cowork/adi-workflow/" \
  "/Users/jasonbielsker/.adi-workflow/"
```

The excludes are needed because those files exist in the GitHub repo
but not in the Google Drive source.

---

## Rolling back

If a deploy goes sideways:

```bash
cd ~/adi-workflow
git log --oneline -5                       # find the last good commit
git reset --hard <commit-sha>
touch /var/www/killingthemains_pythonanywhere_com_wsgi.py
```

The auto-migrations don't roll back schema changes automatically —
if a previous deploy added a column, that column stays even after a
code rollback. SQLite is tolerant of extra columns the model no
longer references, so this is usually harmless.
