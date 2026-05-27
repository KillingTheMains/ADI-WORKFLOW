#!/usr/bin/env python3
"""
backup_db.py
Scheduled daily backup — dumps MySQL to ~/backups/adi_workflow_YYYY-MM-DD.sql
Set this up as a PythonAnywhere scheduled task:
    ~/adi-workflow/venv/bin/python ~/adi-workflow/backup_db.py
"""
import os, subprocess, datetime

MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
DATE = datetime.date.today().isoformat()
BACKUP_DIR = os.path.expanduser("~/backups")
BACKUP_FILE = os.path.join(BACKUP_DIR, f"adi_workflow_{DATE}.sql")

os.makedirs(BACKUP_DIR, exist_ok=True)

cmd = [
    "mysqldump",
    "--host=killingthemains.mysql.pythonanywhere-services.com",
    "--user=killingthemains",
    f"--password={MYSQL_PASSWORD}",
    "killingthemains$adi_workflow",
]

with open(BACKUP_FILE, "w") as f:
    result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)

if result.returncode == 0:
    size = os.path.getsize(BACKUP_FILE)
    print(f"✅ Backup saved: {BACKUP_FILE} ({size:,} bytes)")

    # Keep only the 14 most recent backups
    files = sorted([
        f for f in os.listdir(BACKUP_DIR) if f.startswith("adi_workflow_")
    ])
    for old in files[:-14]:
        os.remove(os.path.join(BACKUP_DIR, old))
        print(f"  Removed old backup: {old}")
else:
    print(f"❌ Backup failed: {result.stderr}")
