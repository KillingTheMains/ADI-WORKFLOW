#!/bin/bash
# Finish a deploy whose migration step was killed part-way.
#
# WHY THIS FILE EXISTS (2026-09-04). `deploy.sh` performs TWO full-database
# VACUUMs: the step-1 backup, and the pre-migration snapshot inside
# run_migrations. On PythonAnywhere's free tier each one takes 25-45 MINUTES
# on an 11MB database:
#
#     09-03 deploy: backup 21:59 -> snapshot finished 22:41   (42 min, survived)
#     09-04 deploy: backup 02:27 -> snapshot killed  ~02:51   (24 min, killed)
#
# Re-running deploy.sh after a kill repeats BOTH vacuums, which is another
# ~50 minutes of CPU on a plan that throttles it — and a good chance of being
# killed in the same place. This script does the work that is actually left:
# migrations, then the reload. Nothing else.
#
#   cd ~/adi-workflow
#   git pull
#   bash deploy_finish.sh
#
# ⚠️ ONLY correct when a snapshot of the CURRENT pre-migration state is
# ALREADY on disk. Check before you run it:
#
#   ls -lt ~/backups | head
#
# The newest snapshot must be from the interrupted run — i.e. taken AFTER the
# last time anything changed the data. If it is older than that, use
# deploy.sh and let it take a fresh one, however long that takes.
#
# This is a recovery tool, not the normal path. `deploy.sh` is the normal path
# and it always snapshots.
set -e
cd "$(dirname "$0")"

export DATABASE_URL="${DATABASE_URL:-sqlite:////home/killingthemains/adi_workflow.db}"

# Read by migrations._pre_migration_snapshot. Set HERE and never in deploy.sh.
export SKIP_PRE_MIGRATION_SNAPSHOT=1

PY=venv/bin/python3
[ -x "$PY" ] || PY=python3
echo "== python:   $PY"
echo "== at:       $(git log --oneline -1)"
echo "== snapshot: SKIPPED — relying on the existing one in ~/backups"
echo "== newest backups:"
ls -lt ~/backups 2>/dev/null | head -4 || echo "   (none found)"

echo
echo "== 1/2  migrations"
# COUNTS PRINT HERE. Read them. A count you did not predict is a failure
# signal, not a no-op.
$PY migrations.py

echo
echo "== 2/2  reload the web app"
WSGI=/var/www/killingthemains_pythonanywhere_com_wsgi.py
if [ -f "$WSGI" ]; then
  touch "$WSGI"
  echo "   touched $WSGI"
else
  echo "   $WSGI not found — skipped (not on PythonAnywhere?)"
fi

echo
echo "== DONE  $(git log --oneline -1)"
