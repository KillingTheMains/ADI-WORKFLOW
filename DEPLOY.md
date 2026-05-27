# Deploying ADI Workflow

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
