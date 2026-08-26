"""Seed the NODA12 canon (persona/offers/prompt/critic/ICP) onto a live run's RunSetup.

Fork-transition Phase 1, Tasks 7-8. Two independent outreach tracks decided by the architect
2026-08-26 (HANDOFF_fork-transition_2026-08-26.md decision C) — two RunSetup profiles on the SAME
persona, not two personas or two instances:

- "consulting": consulting/training companies and independent facilitators — buy NODA12 as a tool
  for their OWN practice. Small orgs/freelancers (icp_max_employees=200).
- "corporate": corporate universities and T&D departments — buy NODA12 for internal programs.
  Larger organizations (icp_min_employees=500). Vacancy radar stays ON for this track: a T&D
  hiring signal ("looking for a learning & development manager") is read as "building out a
  corporate university" (see program_matcher / vacancy_signals wiring — unchanged code, no radar
  edits needed for Phase 1).

This script does NOT create or look up projects/runs by name — it never invents a target.
The run to sync is given explicitly via --run-id (no default). If that run does not exist,
the script prints an error and exits with code 1.

--dry-run is mandatory to run before any write against a live campaign: it writes nothing and
prints a unified diff (difflib) of the DB's current value vs canon for every text field, plus a
before/after line for every scalar field.

Session catalog (OFFERS / TrainingProgram): only 6 sessions, not 16 — Noda12/doc/web-mvp-offer.md
names "16+ готовых сессий серии «Системное мышление»" but only fully describes 3 (Beer Game / SIR
wave / Quarantine Honesty) and names 3 more without detail (Krebs cycle / 2008 credit cascade /
colony economy); backend/saves/*.json confirms ~24 real st_/st2_-prefixed session files exist but
none carry marketing copy (title/description/hook) to seed from — only raw node-graph state. The
other ~80 cards in doc/tabletop-negotiation-scenarios-catalogue.md are an explicit brainstorm
artifact ("НЕ спека и НЕ план"), not shipped product. Seeding fabricated hooks for content that
does not exist would put false claims in front of real prospects via the program matcher — the
catalog grows as real session copy is written, not to hit a number from an earlier planning pass.
Global (training_programs has no project_id/run_id column) — seeding is opt-in via --seed-offers.

Usage:
    cd backend && ./venv/bin/python scripts/seed_noda12_preset.py --run-id 3 --profile consulting --dry-run
    cd backend && ./venv/bin/python scripts/seed_noda12_preset.py --run-id 3 --profile consulting --seed-offers --seed-persona-noda12
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
from app.services.persona_service import NODA12_SLUG, noda12_persona_kwargs  # noqa: E402
from app.services.run_company_ai_fit_service import DEFAULT_FIT_EXCLUSION_RULES  # noqa: E402

# --- Session catalog (6 sessions, see module docstring for why not 16) ---------------------------
# target_pains are phrased as the BUYER's (facilitator's / T&D's) own professional pain, not the
# end-trainee's — program_matcher.py matches these against the reasoning `problem` slot, which is
# about the RECIPIENT (a facilitator/consultant/T&D manager), not about their trainees.

OFFERS: list[dict] = [
    {
        "name": "Пивная игра (bullwhip-эффект)",
        "description": (
            "Классика системной динамики: цепочка поставщик-ритейлер-оптовик-дистрибьютор-завод "
            "на общем экране. Маленькое колебание спроса на глазах группы превращается в шторм "
            "на складах — крючок «почему все склады то пусты, то завалены, хотя спрос почти не "
            "менялся?» (Noda12/doc/web-mvp-offer.md)."
        ),
        "target_pains": [
            "клиенты интеллектуально знают про bullwhip-эффект, но не прочувствовали его на себе",
            "нужен наглядный инструмент для аудита/обучения по цепочкам поставок и управлению запасами",
            "статичные диаграммы и слайды не показывают, как решения на местах раскачивают всю цепь",
        ],
        "audience": "фасилитаторы и консультанты по Lean/TOC/supply chain, T&D-менеджеры логистических компаний",
        "format": "фасилитируемая сессия 45-60 минут, группа 3-8 человек, только браузер",
        "bullets": [
            "работающая модель, не метафора — считающий движок, не мнение ведущего",
            "узкое место находит детектор (Lean/TOC-метрики), не ведущий на глазок",
            "готова к показу сегодня, без физических нод",
        ],
    },
    {
        "name": "SIR-волна (эпидемия как система)",
        "description": (
            "Эпидемия как система: волна, пик, вторая волна на глазах группы. Крючок «почему "
            "меры, принятые „когда стало видно“, всегда опаздывают?» (Noda12/doc/web-mvp-offer.md)."
        ),
        "target_pains": [
            "клиентам/командам трудно на интуитивном уровне понять запаздывание обратной связи в кризисе",
            "решения о вмешательстве принимаются поздно — «когда уже видно», а не по опережающим сигналам",
            "нужен наглядный кейс про цену промедления для риск-менеджмента или антикризисного тренинга",
        ],
        "audience": "консультанты по риск-менеджменту и антикризисному управлению, преподаватели системного мышления",
        "format": "фасилитируемая сессия 45-60 минут, группа 3-8 человек, только браузер",
        "bullets": [
            "видно глазами: узкое место/каскад/запаздывание, а не только в цифрах",
            "разбор по метрикам движка после сессии",
            "готова к показу сегодня, без физических нод",
        ],
    },
    {
        "name": "Карантинная честность (переговорная, 3 игрока)",
        "description": (
            "Переговорная: страны решают, открывать ли границы, глядя на ЗАЯВЛЕННЫЕ цифры "
            "соседей. Крючок «блеф выигрывает раунд — и возвращается вспышкой через пять тиков» "
            "(Noda12/doc/web-mvp-offer.md)."
        ),
        "target_pains": [
            "нужен яркий кейс про цену краткосрочного блефа/недоверия в переговорах и командной работе",
            "тренинги по переговорам и доверию держатся на теории, не хватает ощутимого проигрывания последствий",
            "клиентам трудно увидеть связь между локальным решением и системным откатом позже",
        ],
        "audience": "тренеры по переговорам и лидерству, коучи, фасилитаторы стратегических сессий",
        "format": "фасилитируемая сессия 45-60 минут, малая группа (от 3 человек), только браузер",
        "bullets": [
            "честная механика: выигрыш от блефа виден сразу, расплата — через несколько раундов",
            "живая модель на общем экране, не ролевая игра на словах",
            "готова к показу сегодня, без физических нод",
        ],
    },
    {
        "name": "Цикл Кребса (биохимия как система)",
        "description": (
            "Замкнутый цикл переделов — модель клеточного метаболизма как система потоков и "
            "запасов. Заявлена в числе 16+ готовых сессий серии «Системное мышление» "
            "(Noda12/doc/web-mvp-offer.md); детальный крючок для этой сессии не задокументирован — "
            "уточнить у архитектора перед использованием в рассылке."
        ),
        "target_pains": [
            "преподавателям биологии/биохимии не хватает живой модели вместо статичной диаграммы цикла",
            "нужен нестандартный пример системного мышления за пределами бизнес-кейсов",
        ],
        "audience": "преподаватели биологии, химии, естественных наук; научно-популярные лекторы",
        "format": "фасилитируемая сессия 45-60 минут, малая группа, только браузер",
        "bullets": [
            "тот же движок системной динамики, что и бизнес-кейсы — перенос между доменами",
            "готова к показу сегодня, без физических нод",
        ],
    },
    {
        "name": "Кредитный каскад 2008 (системный риск)",
        "description": (
            "Финансовая заразность/каскад дефолтов как система. Заявлена в числе 16+ готовых "
            "сессий серии «Системное мышление» (Noda12/doc/web-mvp-offer.md); детальный крючок для "
            "этой сессии не задокументирован — уточнить у архитектора перед использованием в рассылке."
        ),
        "target_pains": [
            "клиентам/студентам трудно почувствовать, как локальный дефолт превращается в системный кризис",
            "нужен наглядный кейс про системный риск и взаимосвязанность для финансового/экономического обучения",
        ],
        "audience": "преподаватели экономики и финансов, консультанты по риск-менеджменту",
        "format": "фасилитируемая сессия 45-60 минут, малая группа, только браузер",
        "bullets": [
            "работающая модель каскадного эффекта, не лекция с графиками",
            "готова к показу сегодня, без физических нод",
        ],
    },
    {
        "name": "Экономика колонии (рост при ограниченных ресурсах)",
        "description": (
            "Управление ограниченными ресурсами растущей колонии/поселения. Заявлена в числе 16+ "
            "готовых сессий серии «Системное мышление» (Noda12/doc/web-mvp-offer.md); детальный "
            "крючок для этой сессии не задокументирован — уточнить у архитектора перед "
            "использованием в рассылке."
        ),
        "target_pains": [
            "нужен наглядный кейс про пределы роста и управление ограниченными ресурсами для экономического обучения",
            "статичные модели роста не показывают, где и почему система упирается в потолок",
        ],
        "audience": "преподаватели экономики и менеджмента, консультанты по стратегическому планированию",
        "format": "фасилитируемая сессия 45-60 минут, малая группа, только браузер",
        "bullets": [
            "живая модель ограничения роста, не статичный график",
            "готова к показу сегодня, без физических нод",
        ],
    },
]

# --- Shared identity block (both profiles) --------------------------------------------------------

_ABOUT_US = (
    "About us (NODA12, noda12.com): платформа осязаемого моделирования систем — физические ноды "
    "(тонкие клиенты с тач-экраном, светящиеся трубки-связи) + веб-конструктор + Python-движок "
    "симуляции. Команда собирает модель системы руками на столе или в браузере, жмёт «Пуск» — "
    "ресурсы текут по связям, узкие места и каскады видны глазами, а не в таблице цифр; узкое "
    "место находит детектор (Lean/TOC-метрики), не мнение ведущего. Voice: 'I' — Алексей, "
    "разработчик NODA12, пишет лично, не от лица команды/агентства. Демо доступно СЕГОДНЯ, без "
    "железа: фасилитируемая веб-сессия 45-60 минут на группу 3-8 человек, нужен только браузер."
)

_MEETING_OFFER_NOTE = (
    "Meeting-offer: единственный оффер — бесплатная пилотная сессия с группой получателя в обмен "
    "на короткий бланк обратной связи после (см. NODA12_FINALES_JSON). Не изобретай свой "
    "закрывающий абзац — система дописывает его в код (см. HARD RULE в инструкции генерации)."
)

PROMPT_SETUP_TEXT_CONSULTING = (
    f"{_ABOUT_US}\n\n"
    "What we sell (trek A — консалтингово-тренинговые компании): NODA12 как инструмент "
    "СОБСТВЕННОЙ практики получателя — фасилитатора, бизнес-тренера, консультанта. Получатель "
    "использует готовые сессии (см. каталог программ) в своих стратсессиях, тренингах, воркшопах "
    "для СВОИХ клиентов — не покупает продукт себе в штат, а получает более сильный инструмент "
    "ведения, чем стикеры на вайтборде или статичные диаграммы.\n\n"
    "Target: независимые фасилитаторы, бизнес-тренеры, LSP-практики (LEGO Serious Play), "
    "консультанты по Lean/TOC/цепям поставок, малые консалтинговые компании. Ищи сигналы: анонсы "
    "и отчёты о проведённых фасилитациях/стратсессиях, сертификации, публикации про узкие места/"
    "TOC/Beer Game/системную динамику.\n\n"
    f"{_MEETING_OFFER_NOTE}"
)

PROMPT_SETUP_TEXT_CORPORATE = (
    f"{_ABOUT_US}\n\n"
    "What we sell (trek B — корпуниверситеты и T&D): NODA12 как инструмент программ обучения и "
    "стратегических сессий ВНУТРИ организации получателя. Получатель — руководитель корпоративного "
    "университета или T&D-подразделения — использует готовые сессии (см. каталог программ) для "
    "внутренних тренингов, онбординга руководителей, стратегических воркшопов.\n\n"
    "Target: T&D-руководители, руководители корпоративных университетов, HR-директора крупных "
    "организаций. Ищи сигналы: тендеры/закупки на корпоративное обучение, вакансии T&D/L&D-"
    "менеджеров (сигнал строящегося корпуниверситета — если personalization.vacancy_signals "
    "непусто, это T&D-вакансия, а не признак конкурента), анонсы новых обучающих программ.\n\n"
    f"{_MEETING_OFFER_NOTE}"
)

# Task 6: the AI-fit judge's default worked example ("a training/consulting provider when we sell
# training") could read a trek-A target (itself a training/consulting company) as a same-offer
# competitor instead of a buyer. Not needed for trek B (corporate universities are not providers of
# NODA12's own offer), so only the consulting profile overrides it.
FIT_EXCLUSION_RULES_CONSULTING = (
    "Mark **incorrect** ONLY when:\n"
    "- the company sells a COMPETING systems-simulation/facilitation-hardware product (a peer "
    "platform, not a buyer) — note: a training/consulting/facilitation company is NOT a "
    "competitor here, it is exactly who we sell TO (we sell a tool for their practice, not "
    "training itself); or\n"
    "- it is not a real buyer organization (an individual, a job board, an event page, a "
    "government procurement agency that purchases on behalf of others rather than for itself); or\n"
    "- it clearly cannot have the need the offer addresses per the campaign brief.\n"
    "Otherwise mark **correct**."
)

CANON_TEXT_FIELDS_CONSULTING: dict = {
    "prompt_setup_text": PROMPT_SETUP_TEXT_CONSULTING,
    "sender_signature_html": noda12_persona_kwargs()["signature_html"],
    "fit_exclusion_rules_text": FIT_EXCLUSION_RULES_CONSULTING,
}
CANON_SCALAR_FIELDS_CONSULTING: dict = {
    "language": "Russian",
    "osint_discovery_mode": "api_only",
    "icp_min_employees": 1,
    "icp_max_employees": 200,
    "icp_criteria_json": {"regions": ["Russia"]},
}

CANON_TEXT_FIELDS_CORPORATE: dict = {
    "prompt_setup_text": PROMPT_SETUP_TEXT_CORPORATE,
    "sender_signature_html": noda12_persona_kwargs()["signature_html"],
    # No override: corporate universities are not DEFAULT_FIT_EXCLUSION_RULES's "same offer"
    # competitor case — the default text already works for this track.
    "fit_exclusion_rules_text": DEFAULT_FIT_EXCLUSION_RULES,
}
CANON_SCALAR_FIELDS_CORPORATE: dict = {
    "language": "Russian",
    "osint_discovery_mode": "api_only",
    "icp_min_employees": 500,
    "icp_max_employees": None,
    "icp_criteria_json": {"regions": ["Russia"]},
}


def _canon_fields_for_profile(profile: str) -> tuple[dict, dict]:
    if profile == "consulting":
        return CANON_TEXT_FIELDS_CONSULTING, CANON_SCALAR_FIELDS_CONSULTING
    return CANON_TEXT_FIELDS_CORPORATE, CANON_SCALAR_FIELDS_CORPORATE


def _seed_persona_noda12(db) -> Persona:
    """Upsert the "noda12" Persona row (idempotent by slug)."""
    persona = db.query(Persona).filter(Persona.slug == NODA12_SLUG).first()
    if not persona:
        persona = Persona(slug=NODA12_SLUG)
        db.add(persona)
    for field, value in noda12_persona_kwargs().items():
        if field == "slug":
            continue
        setattr(persona, field, value)
    db.flush()
    return persona


def _seed_offers(db) -> None:
    """Upsert the OFFERS catalog (idempotent by name). Global — not scoped to any project/run."""
    for offer in OFFERS:
        row = db.query(TrainingProgram).filter(TrainingProgram.name == offer["name"]).first()
        if not row:
            row = TrainingProgram(name=offer["name"], status="active")
            db.add(row)
        row.description = offer["description"]
        row.target_pains = offer["target_pains"]
        row.audience = offer["audience"]
        row.format = offer["format"]
        row.bullets = offer["bullets"]
        row.status = "active"
    db.flush()
    print(f"Seeded {len(OFFERS)} offers.")


def _print_text_diff(field: str, old: str | None, new: str | None) -> None:
    old_lines = (old or "").splitlines(keepends=True)
    new_lines = (new or "").splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(old_lines, new_lines, fromfile=f"db:{field}", tofile=f"canon:{field}", lineterm="")
    )
    if diff:
        print(f"--- {field} DIFFERS ---")
        for line in diff:
            print(line)
    else:
        print(f"{field}: identical")


def _print_scalar_diff(field: str, old, new) -> None:
    if old != new:
        print(f"{field}: DB={old!r} -> canon={new!r}")
    else:
        print(f"{field}: identical ({old!r})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync the NODA12 canon onto a run's RunSetup.")
    ap.add_argument("--run-id", type=int, required=True, help="Target run id (no default).")
    ap.add_argument(
        "--profile",
        choices=["consulting", "corporate"],
        required=True,
        help="consulting = trek A (training/consulting companies). corporate = trek B (T&D / corp universities).",
    )
    ap.add_argument(
        "--fields",
        type=str,
        default=None,
        help="Comma-separated RunSetup field names to restrict this sync to. Off by default (syncs the full canon).",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print unified diff of DB vs canon; write nothing.")
    ap.add_argument(
        "--seed-offers", action="store_true", help="Also upsert the OFFERS catalog (TrainingProgram rows)."
    )
    ap.add_argument(
        "--seed-persona-noda12", action="store_true", help="Also upsert the 'noda12' Persona row."
    )
    args = ap.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == args.run_id).first()
        if not run:
            print(f"Run id={args.run_id} not found.", file=sys.stderr)
            sys.exit(1)

        setup = db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
        text_fields, scalar_fields = _canon_fields_for_profile(args.profile)

        allowed_fields: set[str] | None = None
        if args.fields:
            allowed_fields = {f.strip() for f in args.fields.split(",") if f.strip()}
            text_fields = {k: v for k, v in text_fields.items() if k in allowed_fields}
            scalar_fields = {k: v for k, v in scalar_fields.items() if k in allowed_fields}

        if args.dry_run:
            print(
                f"DRY RUN: run_id={run.id} ({run.name!r}); profile={args.profile!r}; "
                f"fields={sorted(allowed_fields) if allowed_fields else 'ALL'}; "
                f"RunSetup {'exists' if setup else 'MISSING (would be created)'}"
            )
            for field, canon_value in text_fields.items():
                old = getattr(setup, field, None) if setup else None
                _print_text_diff(field, old, canon_value)
            for field, canon_value in scalar_fields.items():
                old = getattr(setup, field, None) if setup else None
                _print_scalar_diff(field, old, canon_value)
            if args.seed_offers:
                print(f"offers: would upsert {len(OFFERS)} rows (idempotent by name)")
            if args.seed_persona_noda12:
                existing = db.query(Persona).filter(Persona.slug == NODA12_SLUG).first()
                print(
                    f"persona '{NODA12_SLUG}': "
                    + ("exists, would be updated" if existing else "MISSING (would be created)")
                )
            print("Dry run; no changes.")
            return

        if args.seed_offers:
            _seed_offers(db)

        if args.seed_persona_noda12:
            _seed_persona_noda12(db)
            db.commit()
            print(f"Seeded persona '{NODA12_SLUG}'.")

        if not setup:
            setup = RunSetup(run_id=run.id)
            db.add(setup)
        for field, canon_value in text_fields.items():
            setattr(setup, field, canon_value)
        for field, canon_value in scalar_fields.items():
            setattr(setup, field, canon_value)

        db.commit()
        print(f"Synced RunSetup for run_id={run.id} ({run.name!r}), profile={args.profile!r}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
