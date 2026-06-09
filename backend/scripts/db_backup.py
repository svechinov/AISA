#!/usr/bin/env python3
"""Consistent daily backup of the live SQLite DB (includes WAL via the sqlite backup API).

Plain `cp ai_biz_os.db` misses uncommitted WAL data, so we use Connection.backup().
Keeps the last RETAIN backups, logs to stdout (cron redirects to a logfile).

Intended to run on the VDS via cron:
  0 3 * * * root /var/www/AI-Biz-OS/backend/venv/bin/python3 \
      /var/www/AI-Biz-OS/backend/scripts/db_backup.py >> /var/log/aibizos-backup.log 2>&1
"""
import datetime
import glob
import os
import sqlite3
import sys

DB_PATH = os.environ.get("AIBIZOS_DB", "/var/www/AI-Biz-OS/backend/ai_biz_os.db")
BACKUP_DIR = os.environ.get("AIBIZOS_BACKUP_DIR", "/var/backups/aibizos")
RETAIN = int(os.environ.get("AIBIZOS_BACKUP_RETAIN", "14"))


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"[backup] ERROR: DB not found at {DB_PATH}", flush=True)
        return 1
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"ai_biz_os_{ts}.db")

    src = sqlite3.connect(DB_PATH)
    try:
        out = sqlite3.connect(dst)
        try:
            src.backup(out)  # consistent snapshot incl. WAL
        finally:
            out.close()
    finally:
        src.close()

    size = os.path.getsize(dst)
    print(f"[backup] {datetime.datetime.now().isoformat()} OK -> {dst} ({size} bytes)", flush=True)

    # Rotation: keep the most recent RETAIN files
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "ai_biz_os_*.db")))
    removed = 0
    for f in files[:-RETAIN] if RETAIN > 0 else []:
        try:
            os.remove(f)
            removed += 1
        except OSError as e:
            print(f"[backup] WARN: could not remove {f}: {e}", flush=True)
    if removed:
        print(f"[backup] rotated: removed {removed} old backup(s), retain={RETAIN}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
