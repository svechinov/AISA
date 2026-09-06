"""Пресет FG-Consulting: персона + матрица «отрасль × рамка письма» (Фаза 2, Task 5).

Кампания FG — экспортная (решение B владельца 02.09.2026): движок генерирует письма, менеджеры FG
рассылают их вручную. Две рамки письма проверяются A/B (решение C):

- Рамка 1 (точная): ревю отрасли + «у вас на предприятии» → ОДНО решение. Матчер программ
  работает штатно, лимит объёма — дефолтный канон движка.
- Рамка 2 (широкая): ревю отрасли → веер актуальных программ (вкусное название + одно
  предложение). Матчер ВЫКЛЮЧЕН (иначе подменит слот solution одной программой), лимит объёма
  повышен до FRAME2_MAX_WORDS.

Матрица задаётся аргументами --industry <slug> --frame 1|2, а не десятью перечисленными
профилями: отраслей пять, рамки две, и перечисление плодило бы копипасту.

КОНТЕНТ FG ВЛИВАЕТСЯ ПО ОТРАСЛЯМ. Сейчас в INDUSTRY_CONTENT одна отрасль — chemicals (химия;
материал теста «КуйбышевАзот» от 03.09.2026, docs/FG-test-KuybyshevAzot-*); остальные четыре ждут
материалов клиента. Неизвестный slug собирает пресет с плейсхолдерами, помеченными
PLACEHOLDER_MARKER, и такой прогон требует явного --allow-placeholders — защита от утечки болванок
в письма реальным людям (прецедент noda12: 6 честных сессий вместо 16 заявленных). Новая отрасль
вливается добавлением ключа в INDUSTRY_CONTENT, без правок механики.

⚠️ Закрывающий абзац персоны FG остаётся плейсхолдером (вопрос Г5 к клиенту — дословный текст CTA,
persona_service.py:439): черновики любой отрасли физически несут маркер, пока FG его не пришлёт.
Отраслевой контент этого не снимает — он закрывает только тело письма.

Usage:
    cd backend && venv/Scripts/python.exe scripts/seed_fg_preset.py --run-id 7 --industry metallurgy --frame 1 --dry-run
    cd backend && venv/Scripts/python.exe scripts/seed_fg_preset.py --run-id 7 --industry metallurgy --frame 2 --allow-placeholders --seed-persona-fg
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.init_db import ensure_schema  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.models.run_setup import RunSetup  # noqa: E402
from app.models.training_program import TrainingProgram  # noqa: E402
from app.services.persona_service import FG_CONTENT_PENDING, FG_SLUG, fg_persona_kwargs  # noqa: E402
from app.services.run_company_ai_fit_service import DEFAULT_FIT_EXCLUSION_RULES  # noqa: E402

PLACEHOLDER_MARKER = FG_CONTENT_PENDING

# Потолок авторской части для рамки-2 (run_setups.max_authored_words). Оценка: 5 программ по
# ~20 слов (название + одно предложение) + ревю отрасли ~80 + хук ~25 + связки. Правится здесь
# одной константой — движок про это число ничего не знает.
FRAME2_MAX_WORDS = 280

# Отраслевой контент FG: ключ — slug отрасли, значение — {"label", "review", "programs"}, где
# programs — [{"name", "pitch", опц. "pains", опц. "bullets"}]. Пополняется по мере получения
# материалов от FG — механика сидера при этом не меняется.
#
# ⚠️ НИ ОДНОГО длинного тире («—», «–») в этих текстах. Названия и питчи программ попадают в тело
# письма рамки-2 дословно, а HARD RULE 15 (hard_rules_gate._check_em_dash) бракует черновик
# целиком за один такой символ — независимо от того, авторский это текст или цитата из каталога.
# Отсюда «Из инженера в руководители» вместо заголовка программы «Из инженера — в руководители»
# в docs/FG-test-KuybyshevAzot-5-programs.
INDUSTRY_CONTENT: dict[str, dict] = {
    # Химия. Ревю и веер программ — материал синтетического теста «КуйбышевАзот» (02-03.09.2026),
    # вариант 2 «классическая упаковка»; горизонт свежести ревю ~полгода (решение F владельца).
    "chemicals": {
        "label": "Химическая промышленность",
        "review": (
            "2026 год химическая отрасль проходит под знаком работы на эффективность. Цены на "
            "продукцию волатильны и задаются внешними рынками, себестоимость привязана к сырью, "
            "экспорт не растёт, конкуренция сместилась на внутренний рынок. Одновременно "
            "отрасль остаётся среди самых кадрово-дефицитных: опытные специалисты уходят, "
            "инженерный рынок перегрет, работник выбирает работодателя, а автоматизация и "
            "ИИ-агенты переходят из пилотов в рабочую практику. Преимущество даёт не масштаб, "
            "а качество управления: скорость решений, сильные линейные руководители, умение "
            "продавать ценность вместо скидки и способность растить руководителей из своих."
        ),
        "programs": [
            {
                "name": "«Решения под давлением»",
                "pitch": (
                    "управленческая команда держит короткий цикл решений при волатильных ценах "
                    "и падающей марже вместо затяжных согласований"
                ),
                "pains": [
                    "затяжные согласования управленческих решений",
                    "волатильные цены и падающая маржа",
                    "спор служб на позициях вместо разговора на цифрах",
                ],
                "bullets": [
                    "различать обратимые и необратимые решения и назначать каждому свою скорость",
                    "держать сценарные развилки по ценам и сырью с заранее прописанными ходами",
                    "проводить совещание-решение за 30 минут: записка вместо доклада, роли, "
                    "протокол на одной странице",
                ],
            },
            {
                "name": "«Мастер как лидер»",
                "pitch": (
                    "начальники смен и мастера получают инструменты ежедневного руководства: "
                    "постановка задачи, контроль, обратная связь, удержание людей"
                ),
                "pains": [
                    "текучесть рабочих на сменах",
                    "мастер делает работу за подчинённых вместо управления",
                    "конфликты и нарушения дисциплины на смене",
                ],
                "bullets": [
                    "ставить задачу по принципу «покажи, расскажи, сделай» и проверять понимание",
                    "выбирать уровень контроля под готовность работника",
                    "замечать индикаторы ухода и удерживать людей разговором, а не только деньгами",
                ],
            },
            {
                "name": "«Команда без раскачки»",
                "pitch": (
                    "управленческая команда за два дня согласовывает приоритеты, роли и стыки "
                    "между службами на своём материале, а не на учебных кейсах"
                ),
                "pains": [
                    "серые зоны ответственности между службами",
                    "конфликты на стыках подразделений",
                    "долгое слаживание новой управленческой команды",
                ],
                "bullets": [
                    "договориться о 3-5 приоритетах года и критериях успеха",
                    "зафиксировать, кто решает, кто делает и кого спрашивают",
                    "выстроить ритм управления: совещания, отчётность, эскалация за 24/48 часов",
                ],
            },
            {
                "name": "«Ценностные переговоры в B2B»",
                "pitch": (
                    "коммерческая служба переходит от переговоров о скидке к переговорам о "
                    "ценности и держит позицию под давлением закупщика"
                ),
                "pains": [
                    "переговоры сводятся к скидке",
                    "давление профессионального закупщика",
                    "потеря маржи и доли у клиента",
                ],
                "bullets": [
                    "считать ценность в деньгах клиента и вести расчёт вместе с ним",
                    "отвечать на тактики закупщика по алгоритму, а не скидкой",
                    "вести торг по лестнице уступок: уступка только в обмен",
                ],
            },
            {
                "name": "«Из инженера в руководители»",
                "pitch": (
                    "кадровый резерв проходит переход из позиции эксперта в позицию "
                    "руководителя и получает базовый управленческий цикл"
                ),
                "pains": [
                    "назначение сильного инженера руководителем",
                    "кадровый резерв без управленческой подготовки",
                    "год раскачки после назначения",
                ],
                "bullets": [
                    "перейти от логики «сделаю лучше сам» к логике «результат делает команда»",
                    "делегировать по уровням полномочий и возвращать обратное делегирование",
                    "давать обратную связь вперёд и вести коучинговый разговор",
                ],
            },
        ],
    },
}

_ABOUT_FG = (
    "About us (FG-Consulting): консалтинг и корпоративное обучение для предприятий. Мы глубоко "
    "в теме отрасли получателя: письмо опирается на короткое ревю актуальной ситуации в его "
    "отрасли, а не на общие слова о развитии персонала."
)

_EXPORT_CHANNEL_NOTE = (
    "Канал: письмо отправляет менеджер FG со своего ящика вручную. НЕ пиши подпись, прощание и "
    "свой закрывающий абзац — закрывающий абзац система дописывает в код, подпись ставит менеджер."
)

# Решение E владельца (02.09): персональный минихук допустим ТОЛЬКО при ярком недавнем поводе.
# Формулировка живёт здесь, в draft_prompt пресета; дефолтный промпт движка
# (outreach_email_pipeline.py:439, «если person_osint непусто — обязан начать с личного хука»)
# не трогаем — он общий с партнёром.
_MINIHOOK_RULE = (
    "- Личный минихук уместен ТОЛЬКО при ярком недавнем поводе по конкретному человеку "
    "(его выступление, интервью, публикация, назначение за последние месяцы). Нет такого "
    "повода - начинай прямо с отраслевого ревю, НЕ выдумывай личную деталь и не пересказывай "
    "общую информацию о компании как личный повод.\n"
)

_COMMON_RULES = (
    "- Пиши по-русски, как один человек другому: простые слова, без маркетинговых оборотов.\n"
    "- Не используй длинное тире в тексте, который пишешь сам (канон движка, HARD RULE 15).\n"
    "- Тема письма обязана содержать название компании получателя (HARD RULE 6).\n"
    f"{_EXPORT_CHANNEL_NOTE}\n"
)

DRAFT_PROMPT_FRAME1 = (
    "Ты пишешь одно холодное B2B-письмо от лица FG-Consulting.\n\n"
    "Структура письма (рамка 1, точная):\n"
    "1. [опционально] личный минихук - по правилу ниже.\n"
    "2. Короткое ревю ситуации в отрасли получателя из блока Campaign / prompt setup: 2-3 "
    "предложения, показывающие, что мы в теме.\n"
    "3. Переход «у вас на предприятии»: как эта отраслевая ситуация выглядит на его участке.\n"
    "4. ОДНО решение - программа из слота solution внутреннего reasoning. Передай её суть "
    "своими словами (что даёт), не называй внутреннее название программы.\n\n"
    "Правила:\n"
    f"{_MINIHOOK_RULE}"
    "- Ровно одно решение. Не перечисляй несколько программ - это другая рамка письма.\n"
    f"{_COMMON_RULES}"
)

DRAFT_PROMPT_FRAME2 = (
    "Ты пишешь одно холодное B2B-письмо от лица FG-Consulting.\n\n"
    "Структура письма (рамка 2, широкая):\n"
    "1. [опционально] личный минихук - по правилу ниже.\n"
    "2. Короткое ревю ситуации в отрасли получателя из блока Campaign / prompt setup: 2-3 "
    "предложения, показывающие, что мы в теме.\n"
    "3. Веер программ: перечисли программы из блока Campaign / prompt setup - у каждой "
    "вкусное название и РОВНО одно предложение о содержании. Списком, без воды.\n\n"
    "Правила:\n"
    f"{_MINIHOOK_RULE}"
    "- Ревю отрасли перескажи своими словами применительно к этому получателю, а не копируй "
    "формулировку из блока Campaign - письма этой волны не должны быть похожи друг на друга.\n"
    "- Названия и описания программ бери ТОЛЬКО из блока Campaign, ничего не добавляй от себя.\n"
    f"{_COMMON_RULES}"
)


def industry_block(industry: str) -> tuple[str, bool]:
    """Отраслевой блок для prompt_setup_text и флаг «это плейсхолдер».

    Известная отрасль -> реальные ревю и программы из INDUSTRY_CONTENT. Неизвестная -> помеченные
    плейсхолдеры: сидер не выдумывает за клиента ни ревю, ни названия программ."""
    content = INDUSTRY_CONTENT.get(industry)
    if not content:
        return (
            f"Industry: {industry}\n"
            f"Отраслевое ревю: {PLACEHOLDER_MARKER} короткое ревю ситуации в отрасли "
            f"'{industry}' - ждём материалы FG.\n"
            f"Программы отрасли: {PLACEHOLDER_MARKER} список программ (название + одно "
            f"предложение) для отрасли '{industry}' - ждём материалы FG.",
            True,
        )
    programs = "\n".join(f"- {p['name']}: {p['pitch']}" for p in content["programs"])
    return (
        f"Industry: {industry} ({content['label']})\n"
        f"Отраслевое ревю: {content['review']}\n"
        f"Программы отрасли:\n{programs}",
        False,
    )


def canon_fields(industry: str, frame: int) -> tuple[dict, dict]:
    """Текстовые и скалярные поля RunSetup для пары (отрасль, рамка)."""
    block, _is_placeholder = industry_block(industry)
    text_fields = {
        "prompt_setup_text": f"{_ABOUT_FG}\n\n{block}\n\n{_EXPORT_CHANNEL_NOTE}",
        "draft_prompt": DRAFT_PROMPT_FRAME1 if frame == 1 else DRAFT_PROMPT_FRAME2,
        # Экспортный канал: подпись ставит менеджер. Пустая строка ещё и блокирует отправку
        # движком (email_sender.validate_outbound_draft_sendable) - это желаемое свойство.
        "sender_signature_html": "",
        # У FG покупатель - предприятие отрасли, а конкурент - другой провайдер обучения:
        # дефолтное правило судьи описывает ровно это, override не нужен (в отличие от NODA12).
        "fit_exclusion_rules_text": DEFAULT_FIT_EXCLUSION_RULES,
    }
    scalar_fields = {
        "language": "Russian",
        "osint_discovery_mode": "api_only",
        # Рамка-1 - матчер подбирает одно решение; рамка-2 сама перечисляет программы.
        "program_match_enabled": frame == 1,
        # Рамка-1 - канон движка (NULL); рамка-2 - повышенный потолок под веер.
        "max_authored_words": None if frame == 1 else FRAME2_MAX_WORDS,
        # ICP-фильтр по численности выключен: первая волна идёт по готовой выгрузке базы FG,
        # firmographics-провайдера у нас нет (см. aibizos-pilot-findings).
        "icp_min_employees": None,
        "icp_max_employees": None,
        "icp_criteria_json": {"regions": ["Russia"]},
    }
    return text_fields, scalar_fields


def has_placeholders(text_fields: dict) -> bool:
    """Есть ли в собранном каноне хоть один помеченный плейсхолдер."""
    return any(PLACEHOLDER_MARKER in (v or "") for v in text_fields.values())


def _seed_persona_fg(db) -> Persona:
    """Upsert строки персоны "fg" (идемпотентно по slug)."""
    persona = db.query(Persona).filter(Persona.slug == FG_SLUG).first()
    if not persona:
        persona = Persona(slug=FG_SLUG)
        db.add(persona)
    for field, value in fg_persona_kwargs().items():
        if field == "slug":
            continue
        setattr(persona, field, value)
    db.flush()
    return persona


def seed_offers(db, industry: str, persona_id: int) -> int:
    """Upsert программ отрасли в каталог (идемпотентно по name), со скоупом на персону FG.

    Рамке-1 нужен непустой каталог: матчер выбирает из него одно решение. Плейсхолдер-отрасль
    сеет одну помеченную строку - механика проверяема, а болванка видна невооружённым глазом."""
    content = INDUSTRY_CONTENT.get(industry)
    if not content:
        programs = [{
            "name": f"{PLACEHOLDER_MARKER} программа отрасли '{industry}'",
            "pitch": f"{PLACEHOLDER_MARKER} описание ждёт материалов FG.",
        }]
    else:
        programs = content["programs"]
    for program in programs:
        row = db.query(TrainingProgram).filter(TrainingProgram.name == program["name"]).first()
        if not row:
            row = TrainingProgram(name=program["name"], status="active")
            db.add(row)
        row.description = program["pitch"]
        # Боли и буллеты — из контента отрасли, если он размечен: матчер рамки-1 выбирает
        # программу по слоту problem, а одинаковые target_pains у всех пяти строк делают выбор
        # случайным. Фоллбэк (плейсхолдер-отрасль, неразмеченный контент) — прежнее поведение.
        row.target_pains = program.get("pains") or [f"отраслевая ситуация: {industry}"]
        row.audience = "руководители предприятий отрасли и их HR/T&D"
        row.format = "программа обучения FG-Consulting"
        row.bullets = program.get("bullets") or [program["pitch"]]
        row.status = "active"
        row.persona_id = persona_id
    db.flush()
    return len(programs)


def apply_canon(db, run, industry: str, frame: int, *, allow_placeholders: bool) -> RunSetup:
    """Записать канон (отрасль, рамка) на RunSetup рана. Плейсхолдеры без явного разрешения -
    выход с кодом 2 и без единой записи в БД."""
    text_fields, scalar_fields = canon_fields(industry, frame)
    if has_placeholders(text_fields) and not allow_placeholders:
        print(
            f"Отказ: канон для отрасли '{industry}' состоит из плейсхолдеров "
            f"({PLACEHOLDER_MARKER}) - контент FG ещё не получен. Прогон с болванками возможен "
            f"только с явным --allow-placeholders (и только на тестовом ране).",
            file=sys.stderr,
        )
        sys.exit(2)

    setup = db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
    if not setup:
        setup = RunSetup(run_id=run.id)
        db.add(setup)
    for field, value in {**text_fields, **scalar_fields}.items():
        setattr(setup, field, value)
    db.flush()
    return setup


def _print_text_diff(field: str, old: str | None, new: str | None) -> None:
    diff = list(
        difflib.unified_diff(
            (old or "").splitlines(keepends=True), (new or "").splitlines(keepends=True),
            fromfile=f"db:{field}", tofile=f"canon:{field}", lineterm="",
        )
    )
    if diff:
        print(f"--- {field} DIFFERS ---")
        for line in diff:
            print(line)
    else:
        print(f"{field}: identical")


def _print_scalar_diff(field: str, old, new) -> None:
    print(f"{field}: DB={old!r} -> canon={new!r}" if old != new else f"{field}: identical ({old!r})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Синхронизировать канон FG на RunSetup рана.")
    ap.add_argument("--run-id", type=int, required=True, help="Целевой ран (без дефолта).")
    ap.add_argument("--industry", type=str, required=True, help="Slug отрасли (ключ INDUSTRY_CONTENT).")
    ap.add_argument("--frame", type=int, choices=[1, 2], required=True,
                    help="1 = точная рамка (матчер, дефолтный лимит); 2 = веер программ.")
    ap.add_argument("--dry-run", action="store_true", help="Показать диф, ничего не писать.")
    ap.add_argument("--allow-placeholders", action="store_true",
                    help="Разрешить запись канона с плейсхолдерами (контент FG ещё не получен).")
    ap.add_argument("--seed-persona-fg", action="store_true", help="Также upsert строки персоны 'fg'.")
    ap.add_argument("--seed-offers", action="store_true",
                    help="Также upsert программ этой отрасли в каталог (нужно рамке 1).")
    args = ap.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == args.run_id).first()
        if not run:
            print(f"Run id={args.run_id} not found.", file=sys.stderr)
            sys.exit(1)

        text_fields, scalar_fields = canon_fields(args.industry, args.frame)
        setup = db.query(RunSetup).filter(RunSetup.run_id == run.id).first()

        if args.dry_run:
            print(
                f"DRY RUN: run_id={run.id} ({run.name!r}); industry={args.industry!r}; "
                f"frame={args.frame}; placeholders={has_placeholders(text_fields)}; "
                f"RunSetup {'exists' if setup else 'MISSING (would be created)'}"
            )
            for field, value in text_fields.items():
                _print_text_diff(field, getattr(setup, field, None) if setup else None, value)
            for field, value in scalar_fields.items():
                _print_scalar_diff(field, getattr(setup, field, None) if setup else None, value)
            print("Dry run; no changes.")
            return

        persona = db.query(Persona).filter(Persona.slug == FG_SLUG).first()
        if args.seed_persona_fg or persona is None:
            persona = _seed_persona_fg(db)
            print(f"Seeded persona '{FG_SLUG}'.")
        if args.seed_offers:
            count = seed_offers(db, args.industry, persona_id=persona.id)
            print(f"Seeded {count} offer(s) for industry {args.industry!r}, persona_id={persona.id}.")

        apply_canon(db, run, args.industry, args.frame, allow_placeholders=args.allow_placeholders)
        if run.persona_id != persona.id:
            run.persona_id = persona.id
        db.commit()
        print(
            f"Synced RunSetup for run_id={run.id} ({run.name!r}); industry={args.industry!r}; "
            f"frame={args.frame}; persona_id={persona.id}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
