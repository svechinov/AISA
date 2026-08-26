"""Pull the server-side Telegram inbox into the Obsidian vault `_inbox` folders (run LOCALLY).

The poller runs on the always-on server and accumulates messages under
``~/ai-biz-os/infra/data/telegram_inbox/<project>/`` (the ./data bind mount). The vault lives on
this laptop, so this script rsyncs those files down (moving them — source is removed on success)
and files each project's items into the matching vault `_inbox`.

Trigger phrase in a session: «разбери telegram inbox».

Запуск (из backend/ или откуда угодно):
    python scripts/pull_telegram_inbox.py                 # обычный прогон
    python scripts/pull_telegram_inbox.py --dry-run       # показать, что бы перенеслось
    python scripts/pull_telegram_inbox.py --host me@srv --remote-path '~/x/telegram_inbox'

Requires rsync + SSH access to the server (see runbook-server for the login).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_HOST = "<user>@<your-server>"
DEFAULT_REMOTE_PATH = "~/ai-biz-os/infra/data/telegram_inbox"

# project (folder under telegram_inbox) → vault subpath for its _inbox, relative to the vault root.
PROJECT_TO_VAULT_INBOX = {
    "AI-Biz-OS": "AI-Biz-OS/_inbox",
    "Content": "Content/_inbox",
    "ReSpam": "ReSpam/_inbox",
    "Общее": "_inbox",
}

# Vault root = the AlexStaff workspace (this repo's parent). backend/scripts → parents[3].
VAULT_ROOT = Path(__file__).resolve().parents[3]


def _target_for(project: str, vault_root: Path) -> Path:
    rel = PROJECT_TO_VAULT_INBOX.get(project, f"_inbox/{project}")
    return vault_root / rel


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull server Telegram inbox into vault _inbox folders.")
    ap.add_argument("--host", default=DEFAULT_HOST, help=f"SSH host (default: {DEFAULT_HOST}).")
    ap.add_argument("--remote-path", default=DEFAULT_REMOTE_PATH, help="Remote telegram_inbox dir.")
    ap.add_argument("--vault-root", default=str(VAULT_ROOT), help="Local vault root.")
    ap.add_argument("--dry-run", action="store_true", help="Show actions without moving/deleting.")
    args = ap.parse_args()

    vault_root = Path(args.vault_root).resolve()
    staging = Path(tempfile.mkdtemp(prefix="tg_inbox_"))

    # rsync down and remove source files on success (a "move"). Trailing slash = contents of the dir.
    rsync = [
        "rsync", "-az", "--remove-source-files",
        f"{args.host}:{args.remote_path}/", f"{staging}/",
    ]
    if args.dry_run:
        rsync.insert(1, "--dry-run")
    print("→", " ".join(rsync))
    try:
        subprocess.run(rsync, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"rsync failed: {exc}", file=sys.stderr)
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    moved = 0
    for project_dir in sorted(p for p in staging.iterdir() if p.is_dir()):
        project = project_dir.name
        target = _target_for(project, vault_root)
        for item in sorted(project_dir.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(project_dir)
            dest = target / rel
            print(f"  {project}/{rel} → {dest}")
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item), str(dest))
            moved += 1

    # Top-level files (siblings of the project dirs) aren't touched by the loop above, so
    # rsync --remove-source-files would delete them from the server with nothing archived —
    # log.jsonl is the message history, worth keeping. status.json is a disposable snapshot
    # (rewritten every few minutes by the backend) — safe to just let it be discarded with staging.
    log_source = staging / "log.jsonl"
    if log_source.is_file():
        log_dest = vault_root / "_inbox" / "telegram-log.jsonl"
        print(f"  log.jsonl → append to {log_dest}")
        if not args.dry_run:
            log_dest.parent.mkdir(parents=True, exist_ok=True)
            with open(log_dest, "a", encoding="utf-8") as dest_fh, open(log_source, encoding="utf-8") as src_fh:
                dest_fh.write(src_fh.read())

    if not args.dry_run:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"done: {moved} file(s) filed into vault _inbox" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
