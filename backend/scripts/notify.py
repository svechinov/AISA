"""Send a Telegram notification into a project's forum topic (replaces the manual curl in runbooks).

Reads TELEGRAM_* from the same .env the app loads. Routing lives in app.services.telegram_notify:
a mapped project → its topic in the supergroup; unknown/None project → owner DM.

Запуск из backend/:
    ./venv/bin/python scripts/notify.py "AI-Biz-OS" "волна 2 отправлена: Belka №3, Mundfish №6"
    ./venv/bin/python scripts/notify.py --owner "быстрый пинг в личку"   # без топика, прямо в DM
    echo "многострочный текст" | ./venv/bin/python scripts/notify.py "Content" -   # текст из stdin
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.env_bootstrap import load_env_from_file  # noqa: E402

load_env_from_file()

from app.services import telegram_notify  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a Telegram notification into a project topic.")
    ap.add_argument("project", nargs="?", default=None, help="Project name (topic). Omit or use --owner for DM.")
    ap.add_argument("text", help="Message text, or '-' to read from stdin.")
    ap.add_argument("--owner", action="store_true", help="Force delivery to the owner DM (ignore project topic).")
    ap.add_argument("--parse-mode", default=None, help="Telegram parse_mode (e.g. MarkdownV2, HTML).")
    args = ap.parse_args()

    text = sys.stdin.read().strip() if args.text == "-" else args.text
    if not text:
        print("empty message; nothing sent", file=sys.stderr)
        return 2

    project = None if args.owner else args.project
    ok = telegram_notify.send(project, text, parse_mode=args.parse_mode)
    if ok:
        target = "owner DM" if project is None else f"topic «{project}»"
        print(f"sent → {target}")
        return 0
    print("send failed (check token / TELEGRAM_* config; see logs)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
