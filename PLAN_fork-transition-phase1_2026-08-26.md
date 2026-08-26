# Переход на форк-базу — план Фазы 1 (движок аутрича NODA12)

## Вводный блок

Фаза 1 перехода на базу форка партнёра (дист `AI-Biz-OS-dist-2026-08-18.zip`). Основание —
`HANDOFF_fork-transition_2026-08-26.md` (решение архитектора: переходить, не ассимилировать) плюс
разведка кодовой базы диста, проведённая планирующей сессией 26.08 (её находки — ниже, они
существенно расширили скоуп относительно handoff).

**Что закрывает фаза:** движок поднят на форк-базе, отвязан от идентичности AlexStaff настолько,
чтобы генерировать письма NODA12, засеян двумя пресетами (трек А — консалтинг/тренинг, трек Б —
корпуниверситеты/T&D), развёрнут отдельным инстансом, транспорт проверен отправкой себе, первые
волны собраны и ждут ревью архитектора.

**Что фаза НЕ закрывает:** EU/US-вектор, мультитенант-слой, Alembic, редизайн фронта, миграцию
FG-трека. Полный список — «Вне фазы».

**Команда тестов:** `cd backend && python -m pytest` (обязательно `cd backend` — конфига pytest в
репо нет, `sys.path` берётся из cwd; сам `pytest` в `requirements.txt` отсутствует, ставится
отдельно).

---

## Ключевые находки разведки (почему скоуп шире handoff)

Три места делают генерацию письма NODA12 **физически невозможной** на дефолтной базе, и одно —
выкашивает целевую выборку ещё до генерации:

1. **`hard_rules_gate.py:80`** — `_WHO_WE_ARE_RE = re.compile(r"(?:we[''`]?re|we\s+are)\s+alexstaff|мы\s*[—-]?\s*alexstaff")`.
   Детерминированный гейт требует буквального «AlexStaff» во втором абзаце. Любое письмо NODA12
   получает `hard_rule_violation` и не проходит валидацию.
2. **`outreach_email_pipeline.py:254-306`** — `NO_VACANCY_OPENERS` / `NO_VACANCY_MIDDLE`:
   рекрутинговый текст «кто мы» (кейсы Broken Sun, Helio Games) захардкожен в коде пайплайна,
   а не в персоне.
3. **`email_validation_service.py:64-70`** — `email_kind_for()` выводит контракт генерации из
   `vacancy_signals.open_roles`. Нет сигнала ⇒ `no_vacancy` ⇒ LLM-рубрика вкуса **отключается
   целиком**, а письмо обязано побайтово воспроизвести §2.3-шаблон из п.2. Для трека А (радар
   вакансий не применим) это означает: **все письма пойдут шаблонным рекрутинговым путём**.
4. **`run_company_ai_fit_service.py:39-41`** — судья помечает `incorrect`, если компания —
   «COMPETITOR / provider of the SAME offer (e.g. a training/consulting provider when we sell
   training)». **Это ровно ЦА трека А**: для NODA12 тренинговая компания — покупатель инструмента.
   Без правки судья отсеет всю выборку трека А, а `enrich_crm_data` даже не соберёт по ней досье.

Хорошие новости, снижающие объём:

- **Оба незакрытых пункта нашего июньского аудита в форке починены**, причём фикс auto-enrich несёт
  прямую ссылку на нас: `orchestrator.py:429` — «audit 2026-06-16 #4». Фабрикация досье закрыта
  тремя слоями (`search_service.py:110-119` → `tavily_osint.py:12-13,48-52` → `osint_worker.py:167-174`).
  Из плана эти пункты снимаются; остаётся только дописать отсутствующие тесты.
- **`critic_canon.py` (23 строки) — почти универсальная B2B-SDR-рубрика**, 3 рекрутинговых
  упоминания. Правится точечно.
- **`RunSetup` уже является контейнером пресета** (`models/run_setup.py`): `prompt_setup_text`,
  `critic_canon_text`, 5 промптов, `language`, `sender_signature_html`, `icp_*`. А
  `_canon_fields_for_profile()` (`scripts/seed_alexstaff_preset.py:267-298`) — готовый механизм
  профилей (`cyprus` / `us` / `anastasia`), в который треки А и Б ложатся без новой архитектуры.
- **Русский поддержан на уровне пресета**: `RunSetup.language="Russian"` переключает ru-ветки
  (`outreach_email_pipeline.py:175,323,404,683`).

---

## Решения, зафиксированные диалогом с архитектором

- **A. База = форк-дист 18.08.** Переход, не ассимиляция. Наша ветка `refactor/dead-code-cleanup`
  и `main` устаревают; наша дельта после 16.06 ≈ 0.
- **B. Партнёрство.** Сухоруков — друг и партнёр по взаимному обмену технологическими решениями;
  использование легитимно, наши последующие наработки открыты ему. Запросить доступ к его git.
- **C. Два трека аутрича параллельно** — А (консалтингово-тренинговые компании) и Б
  (корпуниверситеты, T&D). Реализация — два пресета Run, не два инстанса.
- **D. Изоляция от Alex Staff** — отдельный инстанс по их «консьерж»-модели; мультитенант-слой не
  строить.
- **E. Транспорт** — старт на Gmail API OAuth; домен noda12.com через RU-ESP вторым провайдером
  позже; верификатор SMTP.BZ.
- **F. Векторы** — РФ сейчас, EU/US после локализации NODA12.
- **G. Открыто (за архитектором):** судьба FG-трека; хостинг NODA12-инстанса.

## Проектные решения плана (приняты планировщиком, архитектор может отклонить)

- **H. Идентичность отправителя выносится в данные персоны, а не разветвляется по slug.**
  Новые поля `personas`: `who_we_are_json`, `no_signal_openers_json`, `who_we_are_match_json`.
  Код читает персону, при пустом значении падает на текущие константы. Причина: это ровно то, что
  предписывает их же дизайн-док мультитенантности (`docs/multitenancy-personas-handoff-2026-07-18.md`),
  до чего они не дошли, — значит доработка возвращается партнёру как вклад, а не как форк-дивергенция.
  **Жёсткое ограничение: письма персон `alexey`/`stepan`/`anastasia` не меняются ни на байт**
  (их правило, наследуем; проверяется регресс-тестом по образцу `test_persona_finale_regression.py`).
- **I. Контракт `email_kind` получает пресетный переключатель, а не переписывается.**
  Новое поле персоны `no_signal_template_enabled` (default `True` = текущее поведение). Для NODA12
  `False`: письма без интент-сигнала идут обычным LLM-путём с рубрикой вкуса, а не вербатим-шаблоном.
  Семантика поля `vacancy_signals` не переименовывается — для трека Б это буквально вакансии T&D.
- **J. Правило «кто конкурент» у AI-fit-судьи параметризуется через `RunSetup`** (новое поле
  `fit_exclusion_rules_text`, дефолт = текущий текст `run_company_ai_fit_service.py:39-44`).
  Дублируется явной формулировкой в `prompt_setup_text` пресетов. Причина: одной формулировки оффера
  недостаточно — захардкоженный пример «training/consulting provider» слишком силён.
- **K. Тестовая опора — фикстура пустой БД.** Снапшота `backend/ai_biz_os_realrun.db` в дисте нет
  (`.gitignore:32-37`), поэтому 26 тест-файлов на фикстуре `db` уходят в `pytest.skip`
  (`conftest.py:34`) — верифицировать план нечем. Добавляем `fresh_db` по образцу
  `test_geo_segment_service.py:37-52` (`Base.metadata.create_all` + `pkgutil` обход моделей).
  Существующую фикстуру `db` не трогаем.
- **L. Радар вакансий в треке А выключен** (`VACANCY_RADAR_ENABLED=0` на уровне рана-пресета), в
  треке Б включён и используется как T&D-сигнал без правки кода радара.

---

## File Structure (новые файлы)

```
backend/
  app/services/sender_identity.py        # NEW: резолвер блоков идентичности из персоны (Task 4)
  scripts/seed_noda12_preset.py          # NEW: персона NODA12 + 2 профиля + каталог сессий (Task 7,8)
  tests/
    conftest.py                          # MOD: + фикстура fresh_db (Task 2)
    test_sender_identity_noda12.py       # NEW: блоки из персоны, фоллбэк, регресс AlexStaff (Task 4)
    test_email_kind_no_signal_toggle.py  # NEW: переключатель контракта (Task 5)
    test_fit_exclusion_rules.py          # NEW: правило конкурента из RunSetup (Task 6)
    test_seed_noda12_preset.py           # NEW: идемпотентность, оба профиля (Task 8)
    test_auto_enrich_on_continue.py      # NEW: закрывает дыру регресса (Task 2)
infra/
  docker-compose.noda12.yml              # NEW: второй инстанс (Task 9)
  data-noda12/.env                       # NEW: вне git, chmod 700 (Task 9)
```

---

## Task 1: Форк-база в репозиторий

**Goal.** Дист становится веткой нашего репозитория, с которой ведётся вся дальнейшая работа.

**Шаги.**
1. Ветка `fork-base` от текущего `main` (`f28e25c`). Наши три коммита чистки (`9d000b9`, `d65f6db`,
   `10513be`) в неё **не берём** — они выпиливают Gmail/Apollo, которые в форке живое ядро.
2. Развернуть дист поверх рабочего дерева, удалив прежнее содержимое `backend/`, `frontend/`,
   `infra/`, `scripts/`. Мусор диста не тащить: `backend/500` (пустая cookie-jar от curl).
3. Один vendor-коммит: `vendor: fork dist 2026-08-18 (Alex Staff, partner exchange)`. В теле —
   происхождение, дата, отсутствие git-истории, ссылка на этот план.
4. Наши `AUDIT_2026-06-16.md`, `HANDOFF_*`, `PLAN_*` — отдельным коммитом (сейчас untracked).
5. Когда партнёр даст доступ: `git remote add partner <url>`, `git fetch partner` — дальше синки
   штатные. До этого remote не заводить.

**Acceptance.**
- `git log --oneline -3` показывает vendor-коммит и коммит доков.
- `cd backend && python -c "import app.main"` — без ошибок.
- `cd backend && python -m pytest -q` — прогон завершается; зафиксировать в отчёте точное число
  `passed` / `skipped` как базовую линию (ожидается много skipped из-за отсутствия снапшота —
  это ожидаемо и лечится Task 2).

---

## Task 2: Тестовая опора — фикстура чистой БД

**Goal.** Появляется способ верифицировать всё последующее: тесты, не зависящие от отсутствующего
прод-снапшота. Плюс закрываются две дыры регресса, найденные разведкой.

**Файлы.** `backend/tests/conftest.py:26-48` (дописать, не трогая `db`),
`backend/tests/test_auto_enrich_on_continue.py` (новый).

**Реализация — фикстура (образец `test_geo_segment_service.py:37-52`):**
```python
@pytest.fixture()
def fresh_db(tmp_path):
    """Empty SQLite with the full schema — for tests that must not depend on the prod snapshot
    (absent from the dist). Every model is imported explicitly, else SQLAlchemy registers only
    the tables that happened to be imported (same reason as init_db.py:8-50)."""
    import pkgutil, importlib
    import app.models as models_pkg
    from app.db import Base
    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{name}")
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
```

**Тест 1 — bootstrap чистой БД** (закрывает latent-баг из нашего аудита): после `create_all` в
`fresh_db` присутствуют `system_settings`, `smtp_accounts`, `sending_policies`, `send_queue`,
`suppression_list`, `personas`, `excluded_companies`.

**Тест 2 — авто-запуск enrich** (`test_auto_enrich_on_continue.py`; сейчас регресс не покрыт ничем —
`AUTO_ENRICH_DISABLED` и `continue_workflow_after_review` не встречаются в тестах):
```python
"""Регресс на фикс audit 2026-06-16 #4 (orchestrator.py:429-435): enrich_crm_data должен
запускаться автоматически перед генерацией. Без теста возврат к ручному режиму пройдёт незамеченным.
0 tokens: STEP_HANDLERS застабены."""
def test_continue_runs_enrich_before_generation(monkeypatch, fresh_db):
    calls = []
    monkeypatch.setattr(orch, "execute_step", lambda db, rid, name: calls.append(name))
    ...
    assert calls.index("enrich_crm_data") < calls.index("generate_emails")

def test_auto_enrich_disabled_env_skips_it(monkeypatch, fresh_db):
    monkeypatch.setenv("AUTO_ENRICH_DISABLED", "1")
    ...
    assert "enrich_crm_data" not in calls
```

**Acceptance.** Оба теста зелёные; `pytest -q` не даёт новых skip; базовая линия из Task 1 не
ухудшилась.

---

## Task 3: Гигиена и деконтаминация чужих значений

**Goal.** Воспроизводимая сборка и ни одного чужого дефолта, способного увести данные не туда.

**Файлы и правки.**
1. `backend/requirements.txt` — запинить все версии (сейчас 0 вхождений `==`); удалить пакеты с
   нулём импортов: `litellm`, `headroom-ai`, `redis`, `tenacity`, `openpyxl`. `alembic` оставить
   только если планируется миграция на него (сейчас не планируется — удалить). Добавить `pytest`.
2. `backend/.env.example` — досыпать 45 живых переменных, которых в нём нет. Полный список — в
   отчёте разведки; критичные: `YANDEX_SEARCH_API_KEY`, `YANDEX_FOLDER_ID`, `TAVILY_API_KEY`,
   `SEARCH_PROVIDER_PRIORITY`, `EMAIL_PROVIDER`, `SEND_QUEUE_INTERVAL_SECONDS`,
   `EMAIL_VERIFIER_*`, `DADATA_API_KEY`, `TELEGRAM_*`, `GLOBAL_PASSWORD`, `HTTP_PROXY`,
   `VACANCY_RADAR_ENABLED`, `OSINT_MAX_COMPANIES`, `GMAIL_ACCOUNT__<SLUG>`, `CAN_SPAM_POSTAL_ADDRESS`.
3. `backend/app/config.py:145-149` — `TELEGRAM_OWNER_CHAT_ID` имеет захардкоженный **чужой** chat id
   `"90016189"`. Дефолт → `""`. Это единственная правка в этой задаче, меняющая поведение их
   инстанса, — согласовать с партнёром при возврате изменений (у них значение приедет из `.env`).
4. Удалить `backend/500`.

**Acceptance.** `pip install -r requirements.txt` в чистом venv проходит; `pytest -q` не хуже
базовой линии; `grep -c '==' requirements.txt` равен числу строк с пакетами; `grep -r
'90016189' backend/app` пусто.

---

## Task 4: Идентичность отправителя — из кода в персону (ядро фазы)

**Goal.** Блоки «кто мы», их языковые варианты и правило структурной проверки перестают быть
константами и становятся данными персоны. Письма AlexStaff не меняются ни на байт.

**Новый модуль** `backend/app/services/sender_identity.py` — резолверы с фоллбэком:
```python
def who_we_are_block(persona, lang: str) -> str
def no_signal_opener(persona, lang: str, *, peer_to_peer: bool) -> str
def who_we_are_pattern(persona) -> re.Pattern[str]
```
Каждый читает соответствующее поле персоны; при пустом/`None` возвращает текущую константу
дословно — так персоны без новых полей ведут себя байт-в-байт как сегодня.

**Новые колонки `personas`** (+ идемпотентный `_ensure_*` в `init_db.py` по образцу соседних):
`who_we_are_json` (`{lang: text}`), `no_signal_openers_json` (`{lang: {founder|other: text}}`),
`who_we_are_match_json` (`{"patterns": [...]}` — для HARD RULE-проверки структуры).

**Точки правки:**
| Файл:строка | Что сейчас | Что станет |
|---|---|---|
| `hard_rules_gate.py:80` | `_WHO_WE_ARE_RE` с «alexstaff» | `who_we_are_pattern(persona)`; функция гейта получает `persona` |
| `hard_rules_gate.py:200` | текст ошибки с «We're AlexStaff - ...» | нейтральная формулировка |
| `outreach_email_pipeline.py:282-306` | `NO_VACANCY_MIDDLE` | `who_we_are_block(persona, lang)` |
| `outreach_email_pipeline.py:254-280` | `NO_VACANCY_OPENERS` | `no_signal_opener(persona, lang, peer_to_peer=...)` |
| `email_validation_service.py:141-143` | `_OPENER_SENTENCES` | сборка из персоны + фоллбэк |

**Тесты** (`test_sender_identity_noda12.py`), TDD — до реализации:
1. *Регресс AlexStaff*: для персоны `alexey` без новых полей `who_we_are_block` возвращает
   `NO_VACANCY_MIDDLE["ru"]`/`["en"]` **дословно**, `who_we_are_pattern` матчит их эталонное тело.
2. *Персона NODA12*: с заполненными полями возвращаются её блоки; `who_we_are_pattern` матчит тело
   NODA12 и **не** требует «AlexStaff».
3. *HARD RULE-гейт*: тело NODA12 со своим блоком во втором абзаце не даёт `hard_rule_violation`;
   оно же без блока — даёт.

**Acceptance.** Три теста зелёные; существующие `test_hard_rules_gate_b273.py`,
`test_email_validation_b063.py`, `test_email_validation_b077.py`, `test_persona_finale_regression.py`
остаются зелёными без правок (доказательство байт-в-байт неизменности).

---

## Task 5: Контракт `email_kind` — пресетный переключатель

**Goal.** Письма NODA12 без интент-сигнала идут обычным LLM-путём с рубрикой вкуса, а не вербатим-
шаблоном.

**Файлы.** `email_validation_service.py:64-70` (`email_kind_for`), `:454,489-491`
(`validate_outbound_email`), `outreach_email_pipeline.py:490-504,761,766`,
`api/email_drafts.py:370`. Новая колонка `personas.no_signal_template_enabled` (Boolean,
default `True`).

**Реализация.** Сигнатура `email_kind_for(personalization, persona=None)`. Когда
`persona.no_signal_template_enabled` равно `False`, функция всегда возвращает `EMAIL_KIND_VACANCY`
(контракт «обычное письмо с рубрикой»), независимо от `open_roles`. В пайплайне
(`outreach_email_pipeline.py:490-504`) при выключенном шаблоне не подставляется
`_no_vacancy_block` и не добавляется HARD RULE «не называть должностей».

**Тесты** (`test_email_kind_no_signal_toggle.py`):
1. Персона по умолчанию + пустые `vacancy_signals` ⇒ `no_vacancy` (текущее поведение сохранено).
2. Персона NODA12 (`no_signal_template_enabled=False`) + пустые сигналы ⇒ `vacancy`, рубрика вкуса
   применяется, `_check_no_vacancy_conformance` не вызывается.
3. Персона NODA12 + непустые `open_roles` (трек Б, T&D-вакансия) ⇒ `vacancy`, хук обязан назвать
   роль (правило `outreach_email_pipeline.py:437-438` работает как прежде).

**Acceptance.** Три теста зелёные; `test_email_validation_b077.py` и `test_critic_canon_b077.py`
зелёные без правок.

---

## Task 6: AI-fit-судья — правило исключения из данных

**Goal.** Судья перестаёт браковать тренинговые/консалтинговые компании и корпуниверситеты, которые
для NODA12 — покупатели.

**Файлы.** `run_company_ai_fit_service.py:29-53` (сборка промпта), новая колонка
`run_setups.fit_exclusion_rules_text` (Text, nullable) + `_ensure_*` в `init_db.py`.

**Реализация.** Абзац «Mark **incorrect** ONLY when: …» (`:39-44`) выносится в константу
`DEFAULT_FIT_EXCLUSION_RULES`; промпт берёт `run_setup.fit_exclusion_rules_text` при непустом
значении, иначе константу. Для NODA12 текст задаётся в пресетах (Task 8) и явно постановляет:
покупатель — тренинговая/консалтинговая компания и корпоративный университет; конкурент — поставщик
аналогичного симуляционного оборудования или платформы бизнес-симуляций.

**Тесты** (`test_fit_exclusion_rules.py`, LLM застабен по образцу `test_program_matcher.py:38-49`):
1. Пустое поле ⇒ в промпт уходит дефолтный текст дословно (регресс AlexStaff).
2. Заполненное поле ⇒ в промпте наш текст, дефолтного нет.
3. Промпт по-прежнему содержит оффер из `get_prompt_setup_text` и бриф (не сломали сборку).

**Acceptance.** Три теста зелёные; `test_fit_override_and_validate.py` зелёный без правок.

---

## Task 7: Персона NODA12 и каталог сессий

**Goal.** В БД появляется отправитель NODA12 и оффер-каталог, на который опирается матчер.

**Файлы.** `backend/scripts/seed_noda12_preset.py` (новый, по образцу `seed_alexstaff_preset.py`),
данные персоны — в `app/services/persona_service.py` (**не** в `scripts/`: каталог не попадает в
Docker-образ, `Dockerfile:8`; это их задокументированная грабля).

**Содержимое персоны `noda12`:** `display_name`, `self_intro`, `signature_html` (без чужих ссылок),
`timezone` (МСК), `languages_json` (`ru` первым), `primary_mailbox_email`, `finales_json`
(CTA — приглашение на демо-сессию), новые поля из Task 4/5 (`who_we_are_json`,
`no_signal_openers_json`, `who_we_are_match_json`, `no_signal_template_enabled=False`).

**Каталог сессий.** 16 сессий из `Noda12/doc/web-mvp-offer.md` в `training_programs` через
`_seed_offers`-подобную функцию (образец `seed_alexstaff_preset.py:395-409`, идемпотентность по
`name`). Формат записи — существующий: `name / description / target_pains / audience / format /
bullets`. Крючки-приоритеты: «Пивная игра», «SIR-волна», «Карантинная честность».
`target_pains` формулировать на языке боли покупателя («команда не видит, где затор»,
«решения принимаются по интуиции»), иначе матчер (`program_matcher.py`, порог
`PROGRAM_MATCH_MIN_FIT=55`) не свяжет их с проблемой из reasoning.

**Acceptance.** Прогон скрипта на `fresh_db` создаёт персону и 16 программ; повторный прогон не
плодит дублей (проверить счётчиками); `get_run_persona` для рана с `persona_id` персоны NODA12
возвращает её, а не `alexey`.

---

## Task 8: Два профиля пресета — треки А и Б

**Goal.** Один скрипт синхронизирует канон на `run_setups` конкретного рана в двух вариантах.

**Файлы.** `backend/scripts/seed_noda12_preset.py` — механика `_canon_fields_for_profile(profile)`
скопирована из `seed_alexstaff_preset.py:267-298`; аргументы `--run-id N`, `--profile
consulting|corporate`, `--dry-run` (unified diff, ничего не пишет), `--fields`.

**Профиль `consulting` (трек А).** `language="Russian"`; `prompt_setup_text` — оффер «инструмент
вашей практики» (комплект + сессии для их клиентов), формулировка исключений по Task 6;
`fit_exclusion_rules_text`; `icp_*` — малые организации и ИП (нижняя граница низкая, верхняя ~200);
`icp_criteria_json` — регионы РФ, ключевые слова консалтинга/фасилитации/тренингов; радар вакансий
выключен (решение L).

**Профиль `corporate` (трек Б).** `language="Russian"`; `prompt_setup_text` — оффер для
корпоративного университета/T&D (инструмент программ обучения и стратсессий); `icp_min_employees`
≈ 500; `icp_criteria_json` — регионы РФ, отраслевые ОКВЭД-исключения по вкусу; радар вакансий
включён и работает как T&D-сигнал без правки кода.

**Тесты** (`test_seed_noda12_preset.py`):
1. `--dry-run` ничего не пишет в БД (счётчики до/после совпадают), но печатает диф.
2. Оба профиля пишут разные `prompt_setup_text` и разные `icp_*` на один и тот же ран.
3. Повторный прогон идемпотентен.

**Acceptance.** Три теста зелёные; на тестовом ране трека А `POST` генерации даёт письмо, которое
проходит `hard_rules_gate` и получает оценку рубрики (не шаблонный путь) — доказательство, что
Task 4+5+6 сомкнулись.

---

## Task 9: Отдельный инстанс NODA12

**Goal.** Движок работает изолированно от FG/AlexStaff-данных.

**Файлы.** `infra/docker-compose.noda12.yml` (копия `docker-compose.server.yml` с правками),
`infra/data-noda12/.env` (вне git, chmod 700).

**Правки compose** (иначе Compose пересоздаст контейнеры соседнего инстанса):
`name: ai-biz-os-noda12`; `container_name: ai-biz-os-noda12-backend` / `-ui`; порты хоста
`127.0.0.1:8010:8000` и `127.0.0.1:8090:80`; том `./data-noda12:/app/data` (внутриконтейнерный путь
и `AI_BIZ_OS_DOTENV=/app/data/.env` не трогать); `TZ` — московская.

**Обязательные значения `data-noda12/.env`** (помнить: `.env` грузится с `override=True` и
**перебивает** блок `environment` из compose):
- `DATABASE_URL=sqlite:////app/data/noda12.db`
- `GMAIL_SEND_AS_EMAIL` — **задать до первого старта**: `init_db.py:142` сеет дефолтную политику
  отправки на этот адрес, иначе в чистую БД сядет политика для чужого `alex@alexstaff.agency`
- `OAUTH_STATE_SECRET` — задать явно (иначе выводится из `DATABASE_URL`, `gmail_oauth.py:83-87`)
- `GLOBAL_PASSWORD`, `HTTP_PROXY` (LLM из РФ), `SEND_QUEUE_INTERVAL_SECONDS` — **не 0**, иначе
  воркер очереди выключен и письма копятся (`config.py:87`)
- `YANDEX_SEARCH_API_KEY` + `YANDEX_FOLDER_ID` (перенести с нашего VDS), `SEARCH_PROVIDER_PRIORITY=yandex,tavily`
- `TELEGRAM_*` — свои значения либо не задавать вовсе
- `APP_ENV` — оставить не-production на время настройки OAuth, иначе запись refresh-токена из API
  запрещена (`env_bootstrap.py:249-250`)

**Первый старт.** `ensure_schema()` на чистой БД создаёт все таблицы (`init_db.py:1344` +
явные импорты моделей `:8-50`). Проверить `GET /ready` (200 только когда схема и роуты готовы;
до этого API отдаёт 503, не 404). Затем прогнать `seed_noda12_preset.py` (Task 7, 8) — **персоны на
чистой БД не сидятся сами**, `personas` создаётся пустой.

**Acceptance.** Оба контейнера подняты, `GET /ready` = 200, `GET /sending/policies` показывает
политику на наш ящик (а не на `alex@alexstaff.agency`), в БД есть персона NODA12 и 16 программ,
соседний инстанс (если запущен) не затронут.

---

## Task 10: Транспорт и отправка себе

**Goal.** Доказано, что письмо физически уходит и возвращается.

**Шаги** (по `docs/runbook-sending.md:17-50`):
1. Google Cloud: OAuth-клиент, redirect URI `{origin}/api/oauth/google/callback`.
2. Авторизация — либо `POST /oauth/google/start` из UI (путь обходит AuthMiddleware,
   `main.py:255-258`; callback сам шлёт проверочное письмо и ищет его поиском, и лишь при успехе
   сохраняет токен — `gmail_oauth.py:872-911`), либо CLI
   `cd backend && python scripts/fetch_google_refresh_token.py` (порт 8765).
3. `GET /setup/status` ⇒ `gmail_send_ready: true`, `gmail_send_as_email` — наш адрес.
4. Тестовая отправка себе: `backend/scripts/send_test_draft_to_self.py --source <draft_id>`
   (клонирует черновик, подменяет получателя, гонит штатным `send_one_draft`).
5. Ответить на письмо из своего ящика; через ~2 минуты ответ обязан появиться в Tracking
   (`GMAIL_SYNC_INTERVAL_SECONDS=120`).
6. Тестовый контакт/черновик удалить.

**Прогрев.** Оставить рампу как засеяна (`start=5`, `step_per_week=5`, `cap=25`); `started_on` —
дата реального старта волны, не раньше.

**Acceptance.** Письмо получено, не в спаме, подпись на месте, вёрстка цела; ответ подтянулся в
Tracking; в `send_queue` элемент в состоянии `sent`.

---

## Task 11: Первые волны обоих треков

**Goal.** Готовые к ревью черновики, а не отправленные письма.

**Трек А.** Ран с профилем `consulting`; источники — Yandex-OSINT по анонсам фасилитаций,
LSP-сертификациям, публикациям Lean/TOC; 20–30 адресатов. Крючок оффера — «Пивная игра».
**Трек Б.** Ран с профилем `corporate`; источники — `POST /company-sources/run/{id}/extract-tenders`
(тендеры на обучение) + радар T&D-вакансий; первая выборка.

Оба рана: `POST /runs/start` → ревью выборки → `POST /runs/{id}/continue` (здесь автоматически
отработает `enrich_crm_data`, затем генерация). Черновики **не аппрувить**: approve/edit = немедленная
автопостановка в очередь, отдельной кнопки «отправить» нет.

**Acceptance.** По каждому треку: выборка прошла ICP+AI-fit без ложных отказов по ЦА (проверить
`ai_fit_reason` глазами — это прямая проверка Task 6 на живых данных); досье не пустые; черновики
сгенерированы, прошли `hard_rules_gate` и получили оценку рубрики ≥20/25; ни один не в очереди.

---

## Гейт фазы

1. `cd backend && python -m pytest -q` — все зелёные, новых skip нет; новые тесты Task 2/4/5/6/8
   присутствуют и проходят.
2. Регресс-доказательство неизменности: тесты AlexStaff-персон (`test_persona_finale_regression.py`,
   `test_hard_rules_gate_b273.py`, `test_email_validation_b063/b077.py`) зелёные **без правок** —
   значит наши доработки можно вернуть партнёру.
3. Инстанс NODA12 поднят, `GET /ready` = 200, данные изолированы.
4. Тестовая отправка себе прошла, ответ подтянулся в Tracking.
5. По обоим трекам есть черновики, ожидающие ревью архитектора; ни одного отправленного письма.

## Вне фазы

EU/US-вектор и локализация; мультитенант-слой; Alembic вместо 32 `_ensure_*`; редизайн фронта
(их B-028); переезд на домен noda12.com + RU-ESP вторым провайдером; подключение верификатора
SMTP.BZ; перепрофилирование радара под T&D-специфику (в Фазе 1 он работает как есть); миграция
FG-трека; починка глобального пароля как токена (терпимо, пока порты слушают только 127.0.0.1);
любая реальная отправка холодных писем.

## Self-Review notes

- **Риск №1 — «пресет не сомкнулся».** Task 4, 5, 6 независимы по коду, но письмо NODA12 пройдёт
  только если сработали все три. Поэтому acceptance Task 8 требует сквозной генерации: это
  единственная точка, где расхождение вскроется до волн.
- **Риск №2 — расхождение с партнёром.** Все правки сделаны как «данные + фоллбэк на текущую
  константу», кроме дефолта `TELEGRAM_OWNER_CHAT_ID` (Task 3). Это осознанная цена: иначе наш
  инстанс шлёт уведомления в чужой чат.
- **Риск №3 — `workflow_registry.py` расходится с фактическим порядком исполнения** (в реестре
  `enrich_crm_data` перед `validate_contacts`, в рантайме — сильно после; спасает спец-кейс
  `orchestrator.py:311-317`). В Фазе 1 не трогаем, но при любой правке шагов помнить.
- **Не проверено планом:** реальная доставляемость с непрогретого ящика; поведение матчера на
  16 сессиях (порог 55 может потребовать калибровки после первых писем) — это материал Фазы 2.
