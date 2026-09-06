#!/bin/bash
# Deploy — run this on the PythonAnywhere Bash console after a `git pull`.
#
# WHY THIS FILE EXISTS (2026-09-03). The deploy used to be a long one-line
# shell command pasted into the PA browser console. Long pasted lines BREAK
# that console — it stops responding, prints nothing, and swallows everything
# typed afterwards. Several deploys "did nothing" for exactly that reason and
# it took four attempts to work out that the command was never executing.
#
# So the rule is now: the console only ever receives SHORT commands, and
# anything with quoting, environment variables or several steps lives here.
#
#   cd ~/adi-workflow
#   git pull
#   bash deploy.sh
#
# Three short lines, nothing to mangle.
set -e
cd "$(dirname "$0")"

# The app reads DATABASE_URL. Omitting it on a migration-bearing deploy has
# caused two outages, so it is defaulted here rather than left to the paste.
export DATABASE_URL="${DATABASE_URL:-sqlite:////home/killingthemains/adi_workflow.db}"

# The venv, because the system python cannot see Flask. Falls back so this
# script still runs somewhere without one.
PY=venv/bin/python3
[ -x "$PY" ] || PY=python3
echo "== python: $PY"
echo "== at:     $(git log --oneline -1)"

echo
echo "== 1/3  backup (online backup API -> ~/backups; about ten seconds on 11 MB)"
$PY backup_sqlite.py
# The step-1 backup doubles as the pre-migration snapshot when it is fresh and
# reads back clean (migrations._pre_migration_snapshot verifies both). One
# copy per deploy instead of two.
export ADI_SNAPSHOT_REUSE="$HOME/backups/adi_workflow_$(date -u +%Y%m%d).db"

echo
echo "== 2/3  migrations"
# migrations.py delegates to app.run_db_startup(), which forces
# SKIP_DB_STARTUP off so the work happens and the COUNTS PRINT HERE.
# Read them. A count you did not predict is a failure signal, not a no-op.
$PY migrations.py

echo
echo "== 3/3  reload the web app"
WSGI=/var/www/killingthemains_pythonanywhere_com_wsgi.py
if [ -f "$WSGI" ]; then
  touch "$WSGI"
  echo "   touched $WSGI"
else
  echo "   $WSGI not found — skipped (not on PythonAnywhere?)"
fi

echo
echo "== DONE  $(git log --oneline -1)"
