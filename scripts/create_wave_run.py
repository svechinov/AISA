"""Завести ран новой волны штатным путём — POST /runs/{run_id}/clone-wave (B-545), не прямым
INSERT в БД. Копирует run_setup (промпты, ICP, язык, подпись) исходного рана и персону; новый ран
встаёт в status="needs_review" и НЕ запускает workflow — под ручной набор контактов.

Прецедент 17-18.08: ран 6 «Волна 2 — партия 1» завели прямым INSERT, скопировав status='active'
у соседнего рана — UI показывал «готовится» без рабочей кнопки продолжения, починка съела три
диагностических захода и ручной UPDATE. См. docs/runbook-sending.md, раздел «Как завести ран новой
волны», и AI-Biz-OS-backlog.md B-545.

Пример запуска:
    VDS_HOST=... GLOBAL_PASSWORD=... python3 scripts/create_wave_run.py \\
        --from-run 4 --name "Волна 2 — партия 1" --persona anastasia --language Russian

    # Сначала посмотреть, что будет создано, ничего не отправляя:
    python3 scripts/create_wave_run.py --from-run 4 --name "Волна 2 — партия 1" --dry-run
"""

import argparse
import os

import requests

VDS_HOST = os.environ.get("VDS_HOST", "<your-server-ip>")


def create_wave_run(from_run: int, name: str, persona: str | None, language: str | None,
                     notes: str | None, dry_run: bool) -> None:
    payload = {"name": name}
    if persona:
        payload["persona_slug"] = persona
    if language:
        payload["language"] = language
    if notes:
        payload["notes"] = notes

    if dry_run:
        print(f"[dry-run] POST /runs/{from_run}/clone-wave — ничего не отправлено")
        print(f"[dry-run] Тело запроса: {payload}")
        print(
            "[dry-run] Из исходного рана скопируется: run_setup целиком (prompt_setup_text, "
            "critic_canon_text, osint_prompt, reasoning_prompt, draft_prompt, "
            "company_search_prompt, deep_osint_prompt, osint_discovery_mode, "
            "sender_signature_html, icp_min/max_employees, icp_criteria_json), workflow_name, "
            "контекст (offer/target/goal/tone/notes), master_prompt, а также email_style_mode; "
            "персона — из --persona либо из исходного рана. Новый ран получит "
            "status='needs_review' и workflow запущен НЕ будет.",
        )
        return

    url = f"http://{VDS_HOST}/api/runs/{from_run}/clone-wave"
    headers = {"Authorization": f"Bearer {os.environ.get('GLOBAL_PASSWORD', '')}"}

    print(f"Клонирую ран {from_run} -> {payload}...")
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    if r.status_code >= 400:
        print(f"Ошибка {r.status_code}: {r.text}")
        return

    data = r.json()
    print(f"Создан ран id={data['id']} name={data['name']!r} status={data['status']}")
    print(f"  Персона: {data.get('persona_slug') or '—'}")
    print(f"  Ящик отправки: {data.get('mailbox_email') or '—'}")
    print(f"  Язык: {data.get('language')}")
    if data.get("warnings"):
        print("  Предупреждения:")
        for w in data["warnings"]:
            print(f"    - {w}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Завести ран новой волны штатным путём (B-545).")
    parser.add_argument("--from-run", type=int, required=True, help="id исходного рана")
    parser.add_argument("--name", type=str, required=True, help="имя нового рана")
    parser.add_argument("--persona", type=str, default=None, help="slug персоны (по умолчанию — персона исходного рана)")
    parser.add_argument("--language", type=str, default=None, help="язык (по умолчанию — язык исходного run_setup)")
    parser.add_argument("--notes", type=str, default=None, help="заметки нового рана")
    parser.add_argument("--dry-run", action="store_true", help="напечатать, что будет создано, ничего не отправляя")
    args = parser.parse_args()

    create_wave_run(args.from_run, args.name, args.persona, args.language, args.notes, args.dry_run)
