# AI Biz OS — HANDOFF (полный): эволюция продукта и отказ от «инструмента поиска VOD»

Документ для следующей итерации разработки. Репозиторий: `ai-biz-os/` (backend + frontend + `infra/`).

**Обновление:** март–апрель 2026 · актуальная версия фронтенда — **`frontend/package.json` → `version`** (на момент последней правки handoff: **2.7.2**). **Максимально подробная передача последних инженерных изменений Human UI и загрузки данных:** **§15** (обязательно к прочтению перед правками `AiBizOsHumanUI.jsx`). Старые номера релизов в §12–13 оставлены как история. **§14.7.1** — workspace-lite и индексы; **§14.3** частично устарел как диаграмма — актуальная схема запросов при reload в **§15.3**. Продуктовая линия «не только VOD» (§1–6) без изменений по смыслу.

**Заявленная цель владельца продукта:** система не должна восприниматься и работать как узкоспециализированный инструмент поиска VOD-площадок. Нужна **вертикально-независимая** логика аутриха: разные отрасли (страхование, фестивали, производство игрушек и т.д.) — **разные формулировки задач, роли контактов, шаблоны писем**, без жёсткой привязки к «видеоплатформам» в коде и UX.

Ниже — что уже есть, где зашит VOD, и **как перестраивать логику** без потери полезного каркаса (проект → run → контакты → черновики → трекинг → треды).

---

## 1. Что сохранить как ценность (каркас продукта)

Эти части **не привязаны** к VOD смыслово и их можно оставить как основу:

| Область | Смысл для пользователя |
|--------|-------------------------|
| **Проекты** | Разные кампании / клиентские направления |
| **Runs (волны)** | Отдельный цикл аутриха: сбор → ревью → черновики → отправка |
| **Контакты + ревью** | Одобрение / отклонение / правка перед рассылкой |
| **Черновики писем + отправка** | Подготовка исходящих и учёт статусов |
| **Tracking (события, треды, ответы)** | Жизнь после отправки |
| **Reply drafts, follow-up, reminders, assets, packets** | Работа с ответившими лидами и материалами |

То есть менять нужно в первую очередь **«движок первых шагов»** (кого искать, как формулируется задача для модели, какие шаблоны по умолчанию) и **оболочку формулировок** в UI, а не выкидывать весь run-centered UX.

---

## 2. Архитектура (кратко, для ориентира)

| Слой | Стек |
|------|------|
| API | FastAPI, Pydantic, SQLAlchemy 2.x |
| БД | PostgreSQL (через `DATABASE_URL`) |
| Frontend | React, Vite; основной экран — `frontend/src/pages/AiBizOsHumanUI.jsx`, трекинг — `frontend/src/components/TrackingView.jsx` |
| Контейнеры | `infra/docker-compose.yml` (Postgres, Redis, backend на `:8000`) |

Локальная разработка: фронт `http://localhost:5173`, прокси `/api` → адрес из `frontend/.env.development` (`VITE_API_PROXY_TARGET`, по умолчанию совпадает с бэкендом). Документация API в браузере: `http://localhost:8000/docs`.

Структура каталогов (памятка):

```
ai-biz-os/backend/app/
  api/          — HTTP-роуты
  models/       — таблицы
  repositories/ — доступ к БД
  services/     — бизнес-логика, оркестрация
  workers/      — шаги pipeline (LLM-вызовы для сбора компаний/контактов, генерация черновиков)
```

---

## 3. Текущий pipeline аутриха (как он устроен сейчас)

### 3.1 Регистрация сценария (workflow)

Файл: `backend/app/services/workflow_registry.py`

Сейчас зарегистрирован **один** сценарий с внутренним ключом `vod_outreach` и шагами:

1. `collect_companies` — найти список компаний (имя + сайт)
2. `find_contacts` — по каждой компании найти контакты (роль, email)
3. `validate_contacts` — правила валидации email / дедуп (без LLM)
4. `generate_emails` — сборка текста письма из **шаблонов** + данные контакта

Оркестратор: `backend/app/services/orchestrator.py` — после `validate_contacts` run переводится в состояние ожидания ревью контактов; пользователь в UI одобряет контакты; затем `continue` запускает только `generate_emails`.

### 3.2 Что попадает в первый шаг из формы «New run»

В UI при создании run пользователь вводит минимум:

- **Run name**, **Segment**, **Campaign goal** (обязательные в текущем UI)
- **Notes** (необязательно)

На старт run уходит **текст цели кампании** как основной «смысловой ввод» для первого шага (вместе с возможными правилами из БД). Имя run, заметки и сегмент — в основном для человека и отображения; **сегмент в промпт первого шага сейчас не подмешивается автоматически** (см. раздел про доработки).

### 3.3 Генерация писем (не LLM)

Файл: `backend/app/workers/email_worker.py`

Черновики **не** генерирует нейросеть: подставляются переменные (`имя контакта`, компания, роль и т.д.) в **шаблоны** из таблицы шаблонов или в запасной текст в коде. Типы шаблонов в системе названы в духе «тема/тело для vod outreach» — это **технические ключи**, которые сейчас путают смысл продукта (см. инвентаризацию ниже).

---

## 4. Инвентаризация: где продукт «пахнет VOD»

Ниже — всё, что нужно последовательно нейтрализовать или сделать настраиваемым per project / per scenario.

### 4.1 Жёсткий сценарий и имя в коде

| Место | Что видит разработчик | Рекомендация |
|-------|------------------------|--------------|
| `workflow_registry.py` | Единственный ключ `vod_outreach` | Ввести **нейтральный** базовый сценарий, например `generic_outreach`, или хранить список шагов в БД / конфиге; VOD — один из пресетов, не дефолт смысла продукта |
| `schemas/run.py` | Значение по умолчанию для имени сценария при старте = `vod_outreach` | Сменить дефолт на нейтральный или убрать дефолт, требовать явный выбор в API |
| `frontend/.../AiBizOsHumanUI.jsx` | При **Create run** всегда отправляется сценарий `vod_outreach` | В UI: выбор **типа кампании / сценария** (или наследовать от проекта) |
| Проект при создании | В UI placeholder имени проекта «VOD Outreach» | Заменить на нейтральное («Новый проект» / пусто) |

### 4.2 Тексты задач для модели (шаги «компании» и «контакты»)

| Файл | Суть текста сегодня | Рекомендация |
|------|---------------------|--------------|
| `workers/research_worker.py` | Задача для шага сбора компаний буквально про **VOD platforms** | Строить задачу из **Campaign goal** + опционально **Segment** + **тип сценария**: например «Найди организации, соответствующие цели: …» без отраслевого дефолта |
| `workers/contacts_worker.py` | Задача для поиска людей — **content acquisition / content partnerships** | Параметризовать формулировку ролей под сценарий (пресет или пользовательское поле «Какие роли искать») |

### 4.3 Правила (seed и БД)

Файл: `backend/app/seed_rules.py`

- Правило уровня сценарного: «focus only on legitimate **VOD platforms**»
- Правило шага `find_contacts`: «Prefer **content acquisition**…»

**Рекомендация:** пересобрать сиды под нейтральный сценарий; для отраслевых пресетов — отдельные наборы правил или правила, привязанные к `project.type` / `scenario_id`.

### 4.4 Шаблоны писем (названия и тексты по умолчанию)

| Файл | Проблема | Рекомендация |
|------|----------|--------------|
| `seed_templates.py` | Имена и тексты «Default **VOD** Outreach», ключи `vod_outreach_subject` / `vod_outreach_body` | Переименовать в нейтральные ключи (`outreach_subject` / `outreach_body`) или оставить ключи как legacy + миграция; тексты — без «анимированного сериала» и VOD |
| `email_worker.py`, `replacement_draft_service.py` | Fallback-тексты про **анимированный сериал** и платформу | Нейтральные заготовки или пустые с обязательностью задать шаблон в проекте |
| `reply_draft_service.py` | Могут быть привязки к тем же ключам шаблонов | Унифицировать с новой схемой имён |

**Важно для пользователя:** сейчас **нет экрана в приложении на 5173** для редактирования шаблонов — только страница документации API (`/docs`) или сиды. Для «не VOD» продукта нужен **экран «Шаблоны проекта»** (тема + тело, подсказки по плейсхолдерам вроде «имя контакта»).

### 4.5 Заглушка LLM (stub)

Файл: `backend/app/services/llm_gateway.py`

- Ответы с **Netflix / MUBI / Viaplay** и формулировками про платформу
- Ветвление по подстрокам `"vod platforms"` и т.д.

**Рекомендация:** stub должен возвращать **абстрактные** примеры (Company A/B/C) или читать фикстуру из конфига, чтобы демо не закрепляло VOD в голове у заказчика и тестов.

### 4.6 Скрипты и тесты

| Файл | Замечание |
|------|-----------|
| `backend/scripts/verify_template_emails.py` | Создаёт проекты с `type: "vod"` — обновить под нейтральный тип |
| Поиск по репозиторию `vod` / `VOD` | Пройтись перед релизом и почистить комментарии, строки UI, типы проектов |

### 4.7 Модель проекта (`type`)

В API проект создаётся с полем **тип** (в тестах встречается `vod`). Имеет смысл расширить осмысленными пресетами (`outreach_generic`, `festival`, `insurance`, …) или заменить на **scenario_template_id** без «vod» как центра мира.

---

## 5. Целевая логика продукта (как должно ощущаться в UI)

Пользовательский рассказ (без имён полей БД):

1. Пользователь создаёт **проект** (например «Страховой аутрич Q2»).
2. В проекте задаётся **тип кампании** или **шаблон сценария**: кого мы ищем (покупатели страховок, музыканты, оптовики игрушек — не только видеосервисы).
3. Для проекта (или для каждого run) настраиваются **тексты исходящих писем** — один раз, не правка сотен карточек вручную.
4. **New run** — волна с понятным именем, сегментом рынка и **формулировкой цели**, которая реально влияет на первые автоматические шаги (вместе с выбранным сценарием).
5. Дальнейший **Review workspace**, **Drafts**, **Tracking** остаются тем же продуктом «цикл сделки», а не «поиск площадок».

---

## 6. Предлагаемые фазы работ (для планирования)

### Фаза A — Нейтрализация (минимум, быстрый выигрыш)

- Переименовать пользовательские тексты и дефолты (проект, шаблоны, fallback письма).
- Заменить жёсткие фразы в `research_worker` / `contacts_worker` на формулировки, собранные из **цели кампании** (+ сегмент).
- Обновить `seed_rules` и `seed_templates` на нейтральные.
- Обновить stub LLM на нейтральные примеры.

### Фаза B — Выбор сценария

- Таблица или конфиг **сценариев**: список шагов, дефолтные подсказки для ролей, привязка к правилам и шаблонам.
- UI: при создании проекта или run — выпадающий список сценария.
- API: не хардкодить `vod_outreach` в теле запроса с фронта.

### Фаза C — Шаблоны в продукте

- Экран на 5173: редактирование **темы** и **тела** письма с подсказками подстановок (как в письме обращаться к человеку и компании).
- Опционально: «пересобрать черновики из шаблона» для контактов без отправки.

### Фаза D — Глубокая конфигурация

- Правила и тексты шагов из админки / JSON в БД.
- Разные **схемы выхода** первого шага (не только «компания + сайт»), если появятся B2B/B2C отличия.

---

## 7. Run-centered UI (уже сделано — не ломать смысл)

В `AiBizOsHumanUI` реализованы: шапка **Project / Run / Status**, карточки **Run setup** и **Run performance**, список **Runs**, модалки **New run / Switch run / Close run**, основная навигация (Runs, Contacts, Drafts, …). Статусы отображаются как **Preparing / Ready / Active / Closed**.

Это **не** «инструмент поиска VOD» с точки зрения экрана — но пока **движок шагов и шаблоны** задают VOD-коннотацию. Смена мотива продукта = работы из разделов 4–6.

---

## 8. Точки интеграции для разработчика (шпаргалка файлов)

| Задача | Где смотреть |
|--------|--------------|
| Список шагов сценария | `services/workflow_registry.py` |
| Когда ждать ревью контактов / продолжить | `services/orchestrator.py`, API `POST /runs/{id}/continue` |
| Старт run | `api/runs.py` |
| Первый шаг (поиск организаций) | `workers/research_worker.py` |
| Второй шаг (люди в организациях) | `workers/contacts_worker.py` |
| Черновики исходящих | `workers/email_worker.py`, таблица шаблонов |
| Отображение фазы run в дашборде | `services/run_display_service.py` |
| Главный экран оператора | `frontend/src/pages/AiBizOsHumanUI.jsx` |
| Трекинг после отправки | `frontend/src/components/TrackingView.jsx` |

---

## 9. Старые handoff-файлы

- **`HANDOFF CURSOR.md`** — компактная архитектура, таблицы сущностей, шпаргалка файлов, правила «что не ломать». Подробная расшифровка релиза 2.1.4 — **§12 ниже в этом файле**; в CURSOR синхронизированы сущности и бэклог (§9).
- **`HANDOFF CHATGPT.md`** — доп. заметки; **источник правды по продуктовой смене «VOD → универсальный аутрич»** — этот **`HANDOFF.md` (§1–6, 10–11)**.

---

## 10. Контрольный чек-лист «мы больше не VOD-утилита»

- [ ] В UI нет дефолтного названия проекта «VOD Outreach».
- [ ] При создании run пользователь **видит выбор типа кампании**, а не скрытый один сценарий.
- [ ] Тексты шагов поиска **не** содержат «VOD» / «content acquisition» без выбранного пресета.
- [ ] Шаблоны писем **нейтральные по умолчанию** и редактируются в UI или хотя бы не содержат «анимированный сериал для платформы».
- [ ] Stub/demo данные **не** только Netflix-подобные платформы.
- [ ] Документация для заказчика описывает **универсальный аутрич**, а не каталог стримингов.

---

---

## 11. Реализовано: run = context + master email (март 2026)

- **Модель run** хранит `context_json` (бриф), текст **`master_prompt`** (единый текст брифа для шагов), **`master_email_subject` / `master_email_body`** после шага генерации.
- **New run (UI)** — поля брифа: что предлагаете, кого целите (организации), какие роли, цель аутрича, тон, доп. контекст для ИИ; сценарий по умолчанию **`generic_outreach`** (тот же пайплайн, что и `vod_outreach`).
- **Пайплайн:** `collect_companies` → `find_contacts` → `validate_contacts` → *(пауза на ревью)* → **`generate_master_email_draft`** → **`generate_emails`**. Черновики контактов собираются из **master письма** + подстановки `{{name}}`, `{{company}}` и т.д.; если master нет — запасной путь через старые шаблоны БД.
- **Миграция колонок:** `init_db._ensure_run_outreach_context_columns()`.
- Старые run’ы без брифа: контекст подставляется из прежнего **Campaign goal** в `input_json`, если поля брифа пустые.

---

## 12. Состояние операторского UI и данных на релизе **2.1.4** (март 2026)

Этот раздел описывает **фактическую** реализацию в коде на момент выпуска **2.1.4** (не заменяет §1–6 по продуктовой стратегии, а дополняет handoff для разработчика/оператора).

### 12.1 Версия и границы системы

| Компонент | Значение |
|-----------|----------|
| **Frontend** | `frontend/package.json` → **`2.1.4`** |
| **Backend** | без отдельного поля версии в репозитории; контракт API = код в `backend/app/` |
| **Точка входа UI** | `frontend/src/pages/AiBizOsHumanUI.jsx` — дашборд проект/run, **Review workspace** (Contacts + Drafts), навигация в Tracking |
| **Tracking** | `frontend/src/components/TrackingView.jsx` — вкладки событий, тредов, reply drafts, follow-ups, reminders, assets, packets, dead mailboxes, queue |

### 12.2 Данные: вложения драфтов через библиотеку **Asset**

Добавлен единый источник правды для «что прикреплено к письму» на уровне черновика (без загрузки файлов в модалку — только выбор из **`/assets`**).

| Таблица | Колонка | Тип | Смысл |
|---------|---------|-----|--------|
| `email_drafts` | `attached_asset_ids` | JSON-массив (список int), `NOT NULL`, default `[]` | Исходящие драфты (outreach) |
| `reply_drafts` | `attached_asset_ids` | то же | Черновики ответов |

- **Миграция:** `init_db.py` → **`_ensure_drafts_attached_asset_ids_columns()`** (SQLite: `TEXT NOT NULL DEFAULT '[]'`; Postgres: `JSONB NOT NULL DEFAULT '[]'`). Выполняется при старте приложения из **`ensure_schema()`** в lifespan (`main.py`).
- **Нормализация:** `backend/app/utils/attached_asset_ids.py` — дедуп по id, порядок сохраняется, невалидные элементы отбрасываются.
- **API read:** поле **`attached_asset_ids`** входит в **`EmailDraftRead`** / **`ReplyDraftRead`** (Pydantic `field_validator` → нормализация).
- **API write:** **`PATCH /email-drafts/{id}/edit`** и **`PATCH /reply-drafts/{id}/edit`** принимают опциональное тело **`attached_asset_ids: number[]`**. `null`/отсутствие ключа = не менять список (для edit-репозитория передаётся явно с фронта при Save).

**Важно (бэклог отправки):** логика **`reply_sender.build_reply_send_payload`** и исходящий **`email_sender`** **пока не мержат** `ReplyDraft.attached_asset_ids` / `EmailDraft.attached_asset_ids` в реальные MIME-вложения поверх существующего пайплайна **asset packet**. Превью reply по-прежнему опирается на пакет и `resolve_sendable_attachments`. Следующей итерацией: объединить «packet + draft.attached_asset_ids» без дубликатов `asset_id` и продумать лимиты.

### 12.3 Frontend: компоненты и потоки

| Файл | Назначение |
|------|------------|
| **`DraftAssetAttachmentsField.jsx`** | Кнопка «Assets» со скрепкой, раскрывающийся список всех ассетов с чекбоксами, чипы `[Asset #id]` с удалением; экспорт **`normalizeAttachedAssetIds`** |
| **`EmailDraftBodyPreview.jsx`** | Превью тела: HTML/plain; блок под текстом с одним пунктиром — **`[Signature]`** (если у run задана подпись) и сразу под ней строка **`[Asset #…]`** при непустом **`attachedAssetIds`** |

**Review workspace — исходящий драфт (`Edit email draft`):**

- Модальное окно: subject, **`EmailDraftRichTextEditor`**, **`DraftAssetAttachmentsField`**.
- При **открытии** редактора дополнительно вызывается **`GET /assets`**, чтобы список библиотеки не зависел от устаревшего кэша (авто-`loadRunDetails` каждые 3 с только при **`selectedRun.status === "running"`**).
- Save: `PATCH` с `subject`, `body`, **`attached_asset_ids`**.

**Tracking — reply draft (`Edit reply draft`):**

- Тот же **`DraftAssetAttachmentsField`**; список ассетов приходит из **`load()`** Tracking (в т.ч. интервал 3 с).
- Save: `PATCH` с **`attached_asset_ids`**.

**Превью в списках:** карточки исходящих драфтов в Review и reply drafts в Tracking передают в **`EmailDraftBodyPreview`** проп **`attachedAssetIds`**, чтобы подпись и ассеты были видны **до** отправки.

### 12.4 Review workspace — поведение контактов и драфтов

**Контакты (`contactCardClass`, `renderContactCard`):**

- При **`email_health` ∈ {`dead_mailbox`, `bounced`}:** красная рамка (**`border-2`**, те же оттенки, что блок Dead mailboxes), иконка **`CircleAlert`**, красный бейдж со значением health, **скрыты** обычные **`StatusBadge`** по статусу/review (визуально «не валиден/не одобрен» для оператора). Для **`dead_mailbox`** **нет** кнопок **Edit** и **Reject** (и режим правки закрывается при обновлении данных, если контакт стал dead mailbox).
- Остальные статусы: зелёная/нейтральная рамка **`border-2`** согласно review (см. общий sweep рамок в §12.5).

**Исходящие драфты:**

- Жизненный цикл трекинга: **`SendLifecycleBadge`** по **`tracking_status ?? status`**.
- Если **`dead_mailbox`:** только кнопка **`Delete`**; **`DELETE /email-drafts/{id}`** разрешён **только** при **`tracking_status == "dead_mailbox"`** (очистка мёртвых черновиков из Review).
- **Send later:** вторичная кнопка с иконкой **`Clock`**; записывает **`review_status: approved`** и **`review_notes: "send_later"`** (константа на фронте). Обычный **Approve** шлёт ревью **без** этого поля → **`review_notes`** сбрасывается в `null` на бэкенде. На карточке показывается янтарный бейдж **Send later** с часами.

**Событийные тосты:** удалены глобальные «успешные» строки (`actionNote`) в Tracking — остаётся только **`error`** для ошибок.

### 12.5 Tracking — вкладки и визуальная логика

**Навигация (`MAIN_NAV` в Human UI):** пункт **«Reply drafts»** (регистр как в продукте); маппинг на внутренний таб Tracking **`replies`**.

**Events:**

- Группировка событий по **`draft_id`**; фильтр по типу события.
- Если последнее событие в цепочке — **`dead_mailbox`**, вся карточка группы подсвечивается «красным контуром»; шаг **`dead_mailbox`** использует **`CircleAlert`** и **`border-2`** в тон контактам.

**Threads:**

- Карточка треда с **`linkedDraft` с lifecycle `dead_mailbox`** **или** контакт с **`email_health === "dead_mailbox"`** — оформление как у problem-contact + бейдж **`dead_mailbox`**.

**Оформление карточек:** унифицирована толщина обводки **`border-2`** для основных карточек секций и списков (Review, Tracking, модалки — по дизайн-решению 2.1.x).

**Dead mailboxes (текст):** в описании вкладки указано создавать replacement-задачу через **Re-search queue** (не обещаем кнопку на той же карточке как единственный путь).

**Reply drafts — редактирование:** инлайн textarea убран в пользу модалки с **`EmailDraftRichTextEditor`** (как у исходящих драфтов).

### 12.6 Деплой и Git

- **Локальный деплой:** `scripts/deploy-local.sh` — `docker compose build/up` backend, **`npm run build`** фронта; финальный **`npm run dev`** держит терминал — для CI/одноразового деплоя обычно выполняют только build + compose.
- **Push на GitHub:** у части окружений **`git@github.com`** падает с **`Permission denied (publickey)`** — нужен настроенный SSH-ключ или HTTPS + token; теги **`v2.1.3`**, **`v2.1.4`** могут существовать только локально до успешного `git push`.

### 12.7 Краткий чек-лист для следующего разработчика

- [ ] После pull: перезапустить backend (или `init_db` / `ensure_schema`), чтобы применились **`attached_asset_ids`**.
- [ ] Проверить **`VITE_API_PROXY_TARGET`** vs реальный порт backend (Docker **8000** vs локальный uvicorn **8001** — см. `HANDOFF CURSOR.md`).
- [ ] Не смешивать **`research_tasks`** и **`follow_up_tasks`**.
- [ ] Реализовать использование **`attached_asset_ids`** в **`email_sender`** / доработать **`build_reply_send_payload`** при необходимости реальных вложений.
- [ ] Продолжить нейтрализацию VOD по §4–6 приоритетно для продуктовой линии.

---

## 13. Релиз **2.4.0** (март 2026) — подробный handoff

Ориентир версии: **`frontend/package.json` → `2.4.0`**. Backend по-прежнему без единого поля версии в коде; схема БД расширяется через **`app/init_db.py` → `ensure_schema()`** при старте приложения.

### 13.1 Продуктовый смысл релиза

- **Наблюдаемость после отправки:** фоновая (или ручная) синхронизация с Gmail подтягивает треды, входящие сообщения и признаки bounce/dead mailbox, чтобы оператор видел актуальную переписку и доставку без ручного обновления только из моков.
- **Обзор контактов и трекинга:** вкладки с счётчиками и единая логика «активные / проблемные / без email» в Review contacts и в Tracking (Threads, Events), меньше шума в UI (убраны лишние плейсхолдеры и фильтры).

### 13.2 Backend: Gmail sync и сообщения

| Область | Файлы / точки входа |
|--------|----------------------|
| **Фоновый цикл** | `app/main.py` — при `GMAIL_SYNC_INTERVAL_SECONDS > 0` в lifespan создаётся задача, вызывающая `sync_gmail_all_open_runs` с интервалом из настроек. |
| **Сервис синка** | `app/services/gmail_tracking_sync_service.py` — импорт тредов/сообщений, обработка bounce и dead mailbox в связке с драфтами и контактами. |
| **Gmail API** | `app/services/gmail_oauth.py` — конфигурация клиента; получение полных данных сообщений/тредов при необходимости. |
| **Идемпотентность** | `app/models/gmail_processed_message.py`, `app/repositories/gmail_processed_repo.py`, таблица **`gmail_processed_messages`** — не обрабатывать одно и то же письмо дважды (`provider_message_id` + `kind`). Создание таблицы: **`init_db._ensure_gmail_processed_messages_table()`**. |
| **Сообщения в треде** | `app/models/email_message.py`, **`rfc_message_id`** на `email_messages` — нормализованный RFC Message-ID для дедупа и цепочки; миграция: **`init_db._ensure_email_messages_rfc_message_id_column()`**. |
| **Репозиторий писем** | `app/repositories/email_message_repo.py`, `app/services/gmail_inbox_import_service.py` — запись/обновление сообщений при импорте. |
| **Отправка** | `app/services/email_sender.py`, `app/services/reply_sender.py` — обогащение исходящих RFC Message-ID где применимо (согласованность с трекингом). |
| **HTTP** | `app/api/gmail_sync.py` — ручной триггер синка (если фон отключён: `GMAIL_SYNC_INTERVAL_SECONDS=0`). |
| **Конфиг** | `app/config.py` — **`GMAIL_SYNC_INTERVAL_SECONDS`** (по умолчанию **120**; **0** = только ручной вызов API). См. также **`backend/.env.example`**. |

**Чек-лист после деплоя 2.4.0:** перезапустить backend, убедиться что `ensure_schema` отработал (логи при старте), при необходимости выполнить точечный `POST` на gmail-sync из `/docs`.

### 13.3 Frontend: Review contacts (`AiBizOsHumanUI.jsx`)

- **Вкладки** (компактные кнопки, по центру): **Pending**, **Approved**, **Rejected** (серый `neutral`), **Bounced**, **Dead mailbox**, **No email** — с динамическими счётчиками `(n)` по текущему поиску.
- **Корзина (bucket)** контакта: сначала `email_health` (dead_mailbox, bounced), затем отсутствие email с `@`, затем `review_status` (включая отдельную вкладку **Rejected**).
- **Группировка по компании:** одна шапка компании только если у контактов совпадают и ключ компании (имя + сайт), и **`review_status`** — нельзя склеить pending и approved в одной карточке.
- **Бейджи компании в карточке:** без изменений — зелёный **Pending** (outreach «в полёте» по трекингу sent/replied) vs **No touch**.

### 13.4 Frontend: Tracking — Threads и Events (`TrackingView.jsx`)

**Threads**

- Вкладки **Active / Bounced / Dead mailbox** с **счётчиками**; стиль как у Review; строка вкладок в **`CardContent`**, сразу над списком тредов.
- **Бейдж Inbound:** показывается, если в `runMessages` для данного `thread_id` **последнее** по времени сообщение имеет **`direction === "inbound"`**, и тред не помечен как bounced/dead mailbox. Данные обновляются при периодическом `load()` (интервал 3 с). Пока входящее не импортировано в API — бейджа нет.
- Плейсхолдер-бейдж **«—»** для пустой **`classification`** треда **убран** — классификация не подставляется визуально, пока её нет.

**Events**

- Те же три **вкладки** с **счётчиками**; группы событий фильтруются по «корзине доставки», вычисляемой из драфта + контакта + при необходимости последнего события в цепочке (dead имеет приоритет над bounced).
- **Выпадающий фильтр по типу события удалён** — список строится по всем событиям run; уточнение только через вкладки Active / Bounced / Dead mailbox.

### 13.5 Прочие изменения в дереве (сводка по незакоммиченным до релиза файлам)

Помимо sync и Tracking, в 2.4.0 вошли правки по драфтам, ассетам (CDN/R2, вложения), run API/display, `setup`, тестовым/локальным скриптам — **см. коммит и diff тега `v2.4.0`**. Для точной перечислимости используйте:

```bash
git show v2.4.0 --stat
```

### 13.6 GitHub и теги

- Репозиторий: **`https://github.com/PavelMuntyan/AI-Biz-OS.git`**
- Релиз помечается тегом **`v2.4.0`**; после `git push origin main --tags` тег доступен на GitHub.

### 13.7 Чек-лист для следующего разработчика (2.4.0)

- [ ] Проверить **`GOOGLE_*`** refresh token и **`GMAIL_SYNC_INTERVAL_SECONDS`** на среде.
- [ ] После обновления БД: наличие **`gmail_processed_messages`** и колонки **`email_messages.rfc_message_id`**.
- [ ] **Review contacts:** понимание bucket-порядка и группировки по `review_status`.
- [ ] **Threads / Events:** вкладки и счётчики согласованы с фильтрами списка; Events без старого dropdown.
- [ ] Прокси фронта **`VITE_API_PROXY_TARGET`** совпадает с портом живого backend.

### 13.8 Релиз **2.6.0** (март 2026) — ускорение Human UI

- **Backend:** `GET /runs/{id}/workspace-lite`, составные индексы в **`init_db._ensure_run_scoped_performance_indexes()`** (применяются при старте backend).
- **Frontend:** поллинг merge’ит lite в полный workspace; в фазе Preparing остаётся полный `/workspace`; на lite-пути нет **`/sending/global-performance`**.
- Подробности и перечень индексов: **§14.7.1**. Тег релиза: **`v2.6.0`**.

### 13.9 Релиз **2.7.0** (март 2026)

- **Run setup:** вместо трёх карточек шагов (Collect / Find / Validate) — график **`RunSetupHourlySendsChart`**: почасовые отправки за последние 24 ч (UTC), outreach + reply; поле **`hourly_sends_24h`** в **`RunWorkspaceRead`** и **`RunWorkspaceLiteRead`**, расчёт **`hourly_send_counts_24h_utc`** в **`run_display_service`**; **`setup_steps`** в workspace остаётся пустым массивом.
- **Setup gate:** **`SetupRequiredGate`** — блокировка до `llm_configured && cdn_configured`, маскировка ключей и поочерёдные зелёные галочки после **`GET /setup/status`**; таймаут запроса статуса.
- Прочие правки UI/UX из итерации (Runs, Continue outreach timeout и т.д.) — по истории коммита. Тег: **`v2.7.0`**.

---

---

## 14. Технический справочник (структура, процессы, данные, производительность)

Раздел для следующей итерации и для консультаций с моделями ИИ: **как устроен код**, **какие процессы живут параллельно**, **почему UI может ощущаться «тяжёлым»**, **куда копать для глобального ускорения**. Репозиторий: `ai-biz-os/` внутри рабочего дерева (например `freeman-lab/ai-biz-os`).

### 14.1 Карта системы (слои)

| Слой | Реализация | Примечание |
|------|------------|------------|
| HTTP API | FastAPI, роутеры в `backend/app/api/*.py` | Префиксы: `/runs`, `/contacts`, `/projects`, … см. `main.py` |
| БД | SQLAlchemy 2.x, модели `backend/app/models/` | PostgreSQL по умолчанию (`DATABASE_URL`); SQLite возможен |
| Схема | `init_db.ensure_schema()` в **lifespan** (`main.py`) | Нет обязательного Alembic; точечные `_ensure_*` ALTER |
| Бизнес-логика | `backend/app/services/`, `repositories/` | Оркестрация пайплайна: `orchestrator.py` |
| LLM / шаги воркфлоу | `backend/app/workers/` | `research_worker`, `contacts_worker`, `email_worker` |
| Фон Gmail | `asyncio` task в lifespan | `GMAIL_SYNC_INTERVAL_SECONDS` из `config.py` (0 = только ручной sync) |
| Frontend | React + Vite, главная страница `frontend/src/pages/AiBizOsHumanUI.jsx` | Прокси `/api` → `VITE_API_PROXY_TARGET` |
| Контейнеры | `infra/docker-compose.yml` | Postgres, Redis, backend :8000 |

### 14.2 Дерево каталогов (рабочая структура)

```
ai-biz-os/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI, CORS, include_router, lifespan → ensure_schema + Gmail loop
│   │   ├── config.py            # Settings (DATABASE_URL, GMAIL_SYNC_INTERVAL_SECONDS, …)
│   │   ├── db.py                # engine, SessionLocal, get_db
│   │   ├── init_db.py           # create_all + _ensure_* миграции колонок/таблиц
│   │   ├── api/
│   │   │   ├── projects.py
│   │   │   ├── runs.py          # CRUD run, workspace, companies, start/continue/restart, prompt/signature patch
│   │   │   ├── steps.py
│   │   │   ├── contacts.py
│   │   │   ├── contact_analyzer.py
│   │   │   ├── email_drafts.py
│   │   │   ├── email_events.py
│   │   │   ├── email_threads.py
│   │   │   ├── reply_drafts.py
│   │   │   ├── sending.py       # отправка, summary run
│   │   │   ├── tracking.py
│   │   │   ├── inbox.py
│   │   │   ├── gmail_sync.py
│   │   │   ├── oauth_google.py
│   │   │   ├── setup.py
│   │   │   ├── assets.py
│   │   │   ├── asset_packets.py
│   │   │   ├── follow_up_tasks.py
│   │   │   ├── reminders.py
│   │   │   ├── research_tasks.py
│   │   │   ├── rules.py
│   │   │   └── templates.py
│   │   ├── models/              # SQLAlchemy: run, contact, email_draft, email_thread, …
│   │   ├── schemas/             # Pydantic request/response
│   │   ├── repositories/      # CRUD и выборки по сессии
│   │   ├── services/          # доменная логика, трекинг, Gmail, display, orchestrator helpers
│   │   ├── workers/           # шаги пайплайна (collect/find/validate/emails)
│   │   └── utils/
│   ├── scripts/               # утилиты (uvicorn bg, wipe, токены, …)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/AiBizOsHumanUI.jsx   # Review workspace, run switch, loadRunDetails bundle
│   │   ├── components/
│   │   │   ├── TrackingView.jsx       # Events/Threads/… + load() each 3s
│   │   │   ├── EmailDraftRichTextEditor.jsx  # TipTap
│   │   │   ├── DraftAssetAttachmentsField.jsx
│   │   │   └── ui/
│   │   └── lib/
│   ├── vite.config.js
│   └── package.json
├── infra/
│   └── docker-compose.yml
└── scripts/
    └── deploy-local.sh          # compose + npm build (см. комментарии в проекте)
```

### 14.3 Дерево процессов и потоков выполнения (runtime)

**Актуальная схема HTTP для Human UI после 2.7.x** — **§15.3** (ниже в этом файле `loadRunDetails` использует **workspace-lite**, списки контактов/черновиков — по разделу; дерево в этом подразделе оставлено как обзор и частично историческое).

Ниже — логическое «дерево», а не обязательно отдельные OS-процессы на каждый узел.

```
[Оператор: браузер]
  └─ React (Vite dev или статика nginx)
       └─ Human UI (AiBizOsHumanUI.jsx)
            ├─ fetch → /api/* (прокси на backend)
            ├─ loadRunDetails(runId): параллельно (типично):
            │     GET /runs/:id
            │     GET /steps/run/:id
            │     GET /contacts/run/:id
            │     GET /email-drafts/run/:id
            │     GET /runs/:id/workspace    ← полный агрегат (смена run, явный refresh, фон после PATCH)
            │        или GET /runs/:id/workspace-lite  ← облегчённый (poll в фазах Ready/Active/Closed)
            │     GET /assets               ← глобальная библиотека (не scoped на run)
            │     GET /asset-packets/run/:id
            │     затем GET /sending/global-performance (не вызывается на пути workspace-lite)
            ├─ Периодический poll loadRunDetails (интервал зависит от workspace.display_phase):
            │     Active ~8s, Ready ~20s, Preparing ~45s, иначе ~60s; пауза если вкладка hidden
            │     Preparing → полный /workspace (актуальные setup_summary/setup_steps); иначе → /workspace-lite + merge в state
            └─ Навигация в TrackingView
                 └─ load() по интервалу 3s (пока компонент смонтирован)
[Backend: uvicorn / Docker]
  └─ FastAPI
       ├─ HTTP handlers → Session (SQLAlchemy) → repositories/services
       ├─ Lifespan (старт):
       │     ensure_schema()
       │     optional: asyncio.create_task(_gmail_background_sync_loop)
       │        └─ каждые GMAIL_SYNC_INTERVAL_SECONDS: SessionLocal → sync_gmail_all_open_runs(db)
       └─ Долгие запросы: POST /runs/start, restart, continue (синхронный run_workflow / continue_workflow в том же worker-процессе)
[Gmail API]  ← только при настроенных GOOGLE_* и sync (фон или POST /gmail-sync)
[PostgreSQL]
[Redis]      ← в compose; не все пути кода обязаны использовать
```

**Важно для диагностики «всё тормозит»:** Human UI и Tracking одновременно могут генерировать **много параллельных HTTP** и **конкурировать за один пул соединений БД** на бэкенде; плюс фоновый Gmail sync держит открытую сессию и делает сетевые вызовы.

### 14.4 Пайплайн аутриха (логика шагов)

Регистр воркфлоу: `backend/app/services/workflow_registry.py` — ключи `vod_outreach` и `generic_outreach` с одинаковым списком шагов:

1. `collect_companies` — `workers/research_worker.py`
2. `find_contacts` — `workers/contacts_worker.py`
3. `validate_contacts` — там же
4. *(пауза: ревью контактов в UI)*
5. `generate_master_email_draft` — `workers/email_worker.py`
6. `generate_emails` — `workers/email_worker.py`

Оркестратор: `backend/app/services/orchestrator.py` — таблица `STEP_HANDLERS`, запись шагов в `steps`, merge компаний/контактов из `output_json`, после `validate_contacts` ожидание действия пользователя; продолжение через API **continue** (см. `api/runs.py`).

### 14.5 Ключевые HTTP-траектории UI

| Действие | Типичные эндпоинты |
|----------|-------------------|
| Смена проекта | `GET /runs/project/:projectId`, затем `loadRunDetails` для выбранного run |
| Любое «освежить run» | полный бандл как в §14.3 |
| Список карточек run | `enrich_run_for_card` на каждый run: несколько запросов/агрегаций на run (см. `run_display_service.py`) |
| Workspace strip в шапке | **`GET /runs/:id/workspace`** (полный): `get_run_display_phase`, `get_run_setup_summary`, `setup_steps_for_run`, `get_run_performance_rows`, `get_conversations_snapshot`. **`GET /runs/:id/workspace-lite`**: `build_run_workspace_lite` — фаза, message, performance и conversations без **`get_run_summary`** и без **`setup_steps_for_run`**; клиент мерджит lite в предыдущий полный объект (`mergeWorkspaceLiteInto`), чтобы setup-карточка не обнулялась |
| Tracking | отдельные эндпоинты (threads, events, reply drafts, …) по реализации `TrackingView.load()` |
| Gmail | фон: `sync_gmail_all_open_runs`; ручной: `gmail_sync` router |

### 14.6 Почему ощущается медленно «даже при маленьких данных»

Возможные причины **не только объём строк**, а **число round-trip и тяжесть агрегатов**:

1. **Лавина запросов с фронта:** один `loadRunDetails` = много параллельных GET + отдельно `global-performance`; при поллинге и открытой Tracking — ещё циклы каждые 3s.
2. **Тяжёлый workspace:** `get_run_setup_summary` опирается на `get_run_summary` и доп. подсчёты по контактам/шагам; несколько обходов таблиц на один запрос.
3. **Список runs:** для каждой карточки `enrich_run_for_card` → снова summary, steps, счётчики — при росте числа run линейно растёт число запросов (N×паттерн).
4. **Глобальный `GET /assets`:** при каждом полном refresh тянется вся библиотека ассетов, даже если для экрана нужен поднабор.
5. **Клиент:** тяжёлое монтирование TipTap (`EmailDraftRichTextEditor`), большой JSX-файл Human UI — основной поток; часть UX уже смягчена отложенным mount в модалке подписи (см. историю коммитов вокруг Signature setup).
6. **Сеть/прокси:** несовпадение порта Docker 8000 vs локальный uvicorn 8001 даёт ощущение «зависло» или старый API.
7. **Таймауты клиента:** `API_TIMEOUT_MS` по умолчанию 25s в `AiBizOsHumanUI.jsx`; для части операций заданы увеличенные таймауты (старты run, retry LLM, бандл после save setup). Прерывание по таймауту без явного баннера при «console-only» классификации ошибок выглядело как «ничего не произошло» — при разборе логов смотреть `setUiError` / `isConsoleOnlyApiFailure`.

Рекомендация для профилирования: в браузере **Network** (waterfall при одном действии), на сервере **логирование длительности** или `EXPLAIN ANALYZE` для самых частых SELECT.

### 14.7 Направления глобального ускорения (чек-лист для ИИ/архитектора)

Сгруппировано по слоям; можно комбинировать.

**Backend / БД**

- Свести **N запросов в 1–2**: один «run dashboard」 read-model (материализованное представление или кэш по `run_id`, инвалидируемый при изменении контактов/драфтов/событий).
- Облегчить **`GET /runs/project/{id}`**: один запрос с JOIN/подзапросами или batch `get_run_summary` для списка id вместо `enrich_run_for_card` per row.
- Разделить **`/workspace`** на лёгкий и тяжёлый — **см. §14.7.1 (п.4, внедрено):** `workspace-lite` + полный путь на Preparing и после действий пользователя.
- **`/assets`:** пагинация, фильтр по проекту/run если продуктово допустимо; или ETag/`If-None-Match`.
- Индексы на **foreign keys** и частые фильтры — **см. §14.7.1 (п.5, внедрено):** составные индексы под типовые `run_id + статус/тип` и `project_id + id` для списка run.
- Пул соединений SQLAlchemy и **не держать** долгие транзакции на время Gmail HTTP.
- Вынести **Gmail sync** в отдельный worker-процесс/Celery (если появится), чтобы не делить event loop и пул с API.

**Frontend**

- Уменьшить частоту poll Tracking (3s → адаптивно, или только при фокусе вкладки / после пользовательского действия).
- Не вызывать полный `loadRunDetails` при каждом мелком действии; инкрементальные PATCH + локальный merge state (уже частично для prompt/signature save).
- **Разбить** `AiBizOsHumanUI.jsx` на подмодули (не ускорит БД, но ускорит сборку и сопровождение).
- Virtualize длинные списки контактов/драфтов.

**Инфра**

- Postgres на том же хосте, что API, в dev; в prod — ближе к приложению, SSD.
- Connection pooling (PgBouncer) при множествах воркеров uvicorn.

### 14.7.1 Внедрено: пункты 4–5 плана ускорения (март 2026)

**П.4 — разделение workspace (lite / full).**

| Слой | Детали |
|------|--------|
| API | `GET /runs/{run_id}/workspace-lite` → схема **`RunWorkspaceLiteRead`** (`schemas/run.py`): `display_phase`, `setup_state_message`, `performance`, `conversations` — без полного merge **`RunRead`** и без **`get_run_summary`** / **`setup_steps_for_run`** в этом ответе. |
| Сервис | `run_display_service.py`: **`build_run_workspace_lite`**, **`get_run_display_phase_lite`**, **`get_run_performance_lite`**, **`get_conversations_lite`**, вспомогательные COUNT-запросы и **`setup_state_message_from_phase`**. |
| Frontend | `AiBizOsHumanUI.jsx`: **`mergeWorkspaceLiteInto`**, опция **`loadRunDetails(..., { workspace: "lite" \| "full" })`**; полный bundle по умолчанию (**`refreshRunDetailsInBackground`**, смена run и т.д.). |
| Poll | Интервалы без изменений по смыслу §14.3. **Preparing** — каждый тик **полный** `/workspace` (свежие **setup_summary** / **setup_steps**). **Ready / Active / Closed** — **`/workspace-lite`**; **`GET /sending/global-performance`** на этом пути не вызывается. |

**П.5 — составные индексы под run-scoped запросы.**

При старте приложения **`init_db.ensure_schema()`** вызывает **`_ensure_run_scoped_performance_indexes()`** (файл **`backend/app/init_db.py`**). Индексы создаются идемпотентно (`CREATE INDEX IF NOT EXISTS`), только если таблица уже есть:

| Имя | Таблица | Колонки |
|-----|---------|---------|
| `ix_email_drafts_run_status_sent_at` | `email_drafts` | `(run_id, status, sent_at)` |
| `ix_email_drafts_run_review_status` | `email_drafts` | `(run_id, review_status)` |
| `ix_reply_drafts_run_status_sent_at` | `reply_drafts` | `(run_id, status, sent_at)` |
| `ix_email_events_run_event_type` | `email_events` | `(run_id, event_type)` |
| `ix_email_threads_run_classification` | `email_threads` | `(run_id, classification)` |
| `ix_steps_run_step_name` | `steps` | `(run_id, step_name)` |
| `ix_contacts_run_review_status` | `contacts` | `(run_id, review_status)` |
| `ix_contacts_run_status` | `contacts` | `(run_id, status)` |
| `ix_runs_project_id_id` | `runs` | `(project_id, id)` |

Одиночные индексы на FK из моделей SQLAlchemy остаются; перечисленные индексы усиливают фильтры в **`run_display_service`**, репозиториях шагов/контактов/драфтов и выборку run по проекту.

### 14.8 Связь с продуктовыми разделами выше

- Нейтрализация VOD и сценарии — по-прежнему **§1–6, §10–11**.
- Операторский UI, Gmail, вкладки — **§12–13** (версии релизов в тексте исторические; актуальный номер пакета — **`package.json`**).
- Краткая шпаргалка файлов — **`HANDOFF CURSOR.md`** (обновлять при изменении схемы и критичных потоков §14).
- **Актуальная схема загрузки Human UI после итераций 2.7.x** — **§15** (дополняет и в части диаграмм **заменяет** устаревшие формулировки §14.3 про «полный `/workspace` в каждом loadRunDetails»).

---

## 15. Максимальный технический handoff: Human UI (март–апрель 2026), версия фронта **2.7.2+**

Раздел для следующего разработчика или ИИ-агента: **точное** описание того, как сейчас устроены запросы, state, гонки и исправления багов в **`frontend/src/pages/AiBizOsHumanUI.jsx`** (далее **Human UI**). Без этого легко снова ввести регрессии «кэш + refreshing…», «черновики исчезают после генерации», «после reload список не обновляется пока не сменишь вкладку».

### 15.1 Где «источник правды» и версия

| Что | Где смотреть |
|-----|----------------|
| Версия npm-пакета фронта | `frontend/package.json` → поле **`version`** (пример: **2.7.2**) |
| Репозиторий на GitHub | `https://github.com/PavelMuntyan/AI-Biz-OS.git` |
| Главный экран оператора | `frontend/src/pages/AiBizOsHumanUI.jsx` (~6000+ строк; основная логика загрузки run, контактов, черновиков, метрик) |
| Снимки в `localStorage` для офлайн-оболочки | `frontend/src/lib/humanUiSnapshot.js` — `snapshotReadRunCards`, `snapshotWriteRunCards`, `snapshotMergeWriteRunPanelLite`, `snapshotReadInnerTabCounts`, … |
| Трекинг (отдельный тяжёлый экран) | `frontend/src/components/TrackingView.jsx` — собственный `load()`, интервалы, разделение static vs live poll (см. историю коммитов вокруг производительности) |

### 15.2 Цели последних изменений (продукт ↔ инженерия)

1. **Не блокировать UI** длинным **`GET /runs/{id}/workspace`** при каждом заходе: этот эндпоинт в ответе отдаёт **`RunWorkspaceRead`**, который **расширяет полный `RunRead`** (в т.ч. тяжёлый `context_json` / master prompt) **плюс** агрегаты setup/performance — дорого на больших run.
2. **Загружать списки по разделу**: на вкладке **Contacts** — в основном данные контактов; на **Drafts** — черновики; **не** тянуть оба списка одним эффектом без нужды (раньше дублировался жирный dual-fetch).
3. **Устранить гонки**: параллельные `GET /contacts/run` и `GET /email-drafts/run` завершались в разном порядке → последний ответ со **старым** состоянием перезаписывал React state → «исчезли» черновики / неверные счётчики.
4. **Не затирать уже пришедшие списки** при позднем старте **`loadRunDetails`** (см. **§15.5**).

### 15.3 Актуальное дерево HTTP при выборе run / reload (Human UI)

Упрощённо, **после** правок (устаревшая часть §14.3, где везде фигурировал полный `/workspace` в одном бандле с контактами, **не** отражает текущий код):

```
[Проект выбран, run выбран]
  └─ Эффект проекта (selectedProject): GET /runs/project/:pid → setRunsList, setSelectedRun, snapshot
       └─ await loadRunDetails(targetId, runRow)   // см. §15.4

[Параллельно, после первого рендера с selectedRun.id]
  └─ Эффект «раздел» (selectedRun.id, mainNav):
       ├─ mainNav ∈ {contacts, contact-analyzer}
       │    → refreshRunContactsOnly(rid)   → GET /contacts/run/:rid
       └─ mainNav === "drafts"
            → refreshRunDraftsOnly(rid)      → GET /email-drafts/run/:rid

[Пока есть pending генерации исходящих черновиков LLM]
  └─ Эффект poll: каждые 2.5s → refreshRunContactsAndDrafts(rid)
       → параллельно GET /contacts/run + GET /email-drafts/run (нужны оба: детект появления draft по contact_id)

[Метрики run без полного workspace]
  └─ refreshRunMetricsOnly по интервалу (фаза run): GET /runs/:id/workspace-lite + GET /sending/global-performance
```

**Companies** (вкладка `mainNav === "companies"`): **отдельный** эффект — **`GET /runs/{id}/companies`** — не проходит через `loadRunDetails` и не смешивается с контактами/черновиками Human UI.

### 15.4 Функция `loadRunDetails` — что именно запрашивается сейчас

Файл: **`AiBizOsHumanUI.jsx`**, функция **`loadRunDetails(runId, runRowHint, options)`**.

| Этап | HTTP | Назначение |
|------|------|------------|
| Синхронно в начале | (нет сети) | Обновление **`runLoadTargetRef`**, условная очистка списков при **смене run** или **`includeLists: true`** (см. §15.5) |
| Параллельно | **`GET /runs/{rid}`** | Полный объект run (**`RunRead`**) — бриф, контекст, подпись и т.д. |
| Параллельно | **`GET /steps/run/{rid}`** | Шаги pipeline |
| Далее (после применения run+steps в state) | **`GET /runs/{rid}/workspace-lite`** | **Не** полный **`/workspace`** — только **`RunWorkspaceLiteRead`**: фаза, setup_summary, performance, conversations, hourly_sends_24h (см. `backend/app/api/runs.py`, `run_display_service.build_run_workspace_lite`) |
| Если `options.includeLists === true` | + параллельно с lite в втором `Promise.all` | **`GET /contacts/run/{rid}`**, **`GET /email-drafts/run/{rid}`** (полный бандл при restart/continue/new run) |
| После успешной сборки workspace | **fire-and-forget** | **`GET /sending/global-performance`** — не блокирует return `loadRunDetails` |

**Сборка объекта `workspace` в React state:** хелпер **`workspaceFromLiteApi(lite, runId)`** (рядом с **`mergeWorkspaceLiteInto`** в том же файле): из ответа lite строится объект с полем **`id: rid`**, чтобы условия вида `workspace?.id === selectedRun.id` в шапке оставались истинными.

**`snapshotWriteRunCards(rid, ws)`** вызывается с этим объектом — в snapshot попадают только поля, которые пишет **`humanUiSnapshot.js`** (display_phase, setup_summary, performance, …).

### 15.5 Очистка state при `loadRunDetails` — критическое правило (регрессии)

Переменная **`switchingRun`**:

- **`true`** только если **`prevTarget != null`** и **`Number(prevTarget) !== rid`** — то есть реальный **переход на другой run**.
- **`false`** при **`prevTarget == null`** (первый вызов `loadRunDetails` в сессии для данного старта эффекта).

**Почему так:** эффект раздела (§15.3) может **уже** завершить **`GET /contacts/run`** и выставить **`contacts` + `contactsListReadyRunId`** **до** того, как асинхронный **`loadRunDetails`** (после `await` на список проектов) выполнит свою **синхронную** начальную очистку. Раньше при **`prevTarget == null`** списки **всегда** обнулялись → пользователь видел «cached … refreshing» до смены вкладки. Теперь при первом заходе **не** сбрасываются контакты/черновики/флаги готовности, если это не смена run и не **`includeLists`**.

При **`includeLists: true`** (restart, continue, create run с полным бандлом) списки **по-прежнему** очищаются в отдельной ветке — ожидается полная перезагрузка списков с сервера.

### 15.6 Три функции обновления списков и два счётчика гонок

Все в **`AiBizOsHumanUI.jsx`**:

| Функция | GET | Когда вызывается |
|---------|-----|------------------|
| **`refreshRunContactsOnly(runId)`** | только **`/contacts/run`** | Вход на **Contacts** или **Contact analyzer** |
| **`refreshRunDraftsOnly(runId)`** | только **`/email-drafts/run`** | Вход на **Drafts** |
| **`refreshRunContactsAndDrafts(runId)`** | оба параллельно | Poll при генерации исходящих; после approve контакта/review драфта/отправки и т.д., где нужны оба списка |

**Защита от устаревших ответов:** два ref — **`contactsListFetchSeqRef`**, **`draftsListFetchSeqRef`**.

- В **dual**-функции в начале: **`c = ++contactsListFetchSeqRef`**, **`d = ++draftsListFetchSeqRef`**; перед **`setContacts`/`setDrafts`** проверка **`c === current && d === current`**.
- В **single**-функции инкрементируется только соответствующий ref.

Так **старый** ответ «только контакты» не может перезаписать черновики после **нового** bundle-запроса и наоборот.

### 15.7 Гидратация Review (когда показывается «настоящий» список vs кэш)

- **`contactsReviewHydrated`**: на вкладках контактов true, если **`contactsListReadyRunId === Number(selectedRun.id)`** (после успешного GET контактов для этого run).
- **`draftsReviewHydrated`**: на Drafts true, если **`draftsListReadyRunId === Number(selectedRun.id)`**.

**`refreshRunContactsAndDrafts`** после успеха выставляет **оба** флага — иначе после approve оставалась «негидратированная» ветка UI.

**Счётчики вкладок** (**Pending review**, **Approved**, …): **`mergeDraftReviewSnap` / `mergeContactReviewSnap`** — если live уже содержит данные (сумма > 0 для драфтов), **предпочитаются live** счётчики, чтобы stale snapshot из **`snapshotReadInnerTabCounts`** не затирал актуальные числа.

### 15.8 Черновики: approve / PATCH и сравнение id

**`reviewDraft(id, …)`** после **`PATCH /email-drafts/{id}/review`** обновляет массив через **`Number(d.id) === Number(id)`** — JSON может отдавать id как number или string; строгое **`===`** ломало merge.

После успеха вызываются **`refreshRunContactsAndDrafts`**, **`refreshRunMetricsOnly`** — по согласованности с сервером.

### 15.9 Плейсхолдеры «Generating email…»

Состояние **`pendingOutboundDraftByContactId`**: ключи по **`Number(contactId)`**. Эффект при изменении **`drafts`** снимает pending, если **`drafts.some(d => Number(d.contact_id) === cid)`**.

**`contactsAwaitingOutboundDraftPlaceholder`**: проверка **`pendingOutboundDraftByContactId[Number(c.id)]`** и множество **`draftContactIds`** через **`Number`** — единообразие типов.

### 15.10 Что остаётся «тяжёлым» на reload

- **`GET /runs/{id}`** по-прежнему возвращает **полный run** (включая большой **`context_json`** при длинном брифе). Облегчение этого — **отдельная** задача API (например **`RunCardRead`** / урезанный GET для дашборда).
- **`GET /runs/{id}/workspace`** (полный) **намеренно не** вызывается в стандартном **`loadRunDetails`** после изменений §15 — если где-то в коде ещё ожидается полный workspace со **всеми** полями **`RunRead`**, встроенными в объект workspace, это нужно искать по репозиторию (**`grep /workspace`**).

### 15.11 Матрица типичных симптомов → что проверить

| Симптом | Вероятная причина | Куда смотреть |
|---------|-------------------|----------------|
| «Showing cached … — refreshing…» бесконечно | Не выставлен **`contactsListReadyRunId` / `draftsListReadyRunId`** после успешного GET | Эффект раздела, **`refreshRun*`** |
| После reload контакты пустые до смены вкладки | Снова включили очистку списков при **`prevTarget == null`** в **`loadRunDetails`** | §15.5 |
| Черновики пропали после генерации | Гонка ответов без dual-seq или перезапись **`setDrafts`** старым массивом | §15.6 |
| Approve драфта — спиннер и нет изменений | **`d.id === id`** без **`Number()`** | §15.8 |
| Долгий TTFB на run | Полный **`GET /runs/:id`** или БД | §15.10, профилирование backend |

### 15.12 Константы таймаутов (фрагмент)

В **`AiBizOsHumanUI.jsx`** (имена могут слегка отличаться — сверять по файлу):

- **`API_TIMEOUT_MS`** — общий дефолт для `api()`.
- **`POLL_METRICS_TIMEOUT_MS`** — refresh списков и метрик.
- **`LOAD_RUN_DETAILS_BUNDLE_TIMEOUT_MS`** — тяжёлые операции (restart и т.д.).

### 15.13 Связь с backend (эндпоинты для handoff)

| Метод | Путь | Схема / примечание |
|-------|------|---------------------|
| GET | `/runs/{run_id}` | `RunRead` |
| GET | `/runs/{run_id}/workspace` | `RunWorkspaceRead` — **тяжёлый**, не используется в стандартном `loadRunDetails` после §15 |
| GET | `/runs/{run_id}/workspace-lite` | `RunWorkspaceLiteRead` |
| GET | `/runs/{run_id}/companies` | `RunCompaniesRead` |
| GET | `/contacts/run/{run_id}` | список контактов |
| GET | `/email-drafts/run/{run_id}` | список исходящих черновиков |
| GET | `/sending/global-performance` | агрегаты по всем run |

### 15.14 Чек-лист для следующего разработчика (после §15)

- [ ] Прочитать **`workspaceFromLiteApi`**, **`mergeWorkspaceLiteInto`**, три **`refreshRun*`**.
- [ ] Не возвращать **`GET /workspace`** в **`loadRunDetails`** без явной причины и замера.
- [ ] Любой новый параллельный fetch контактов/черновиков — продумать **seq**-гарды.
- [ ] После изменений — прогнать сценарии: **reload → Contacts**, **reload → Drafts**, **approve 5 контактов → генерация → Drafts**.
- [ ] Обновить **`HANDOFF CURSOR.md`**, если менялись эндпоинты или схемы §15.13.

---

*Версия документа: март–апрель 2026 — **§15** (Human UI: workspace-lite в `loadRunDetails`, списки по разделам, dual-seq, гидратация, id-фиксы; фронт **2.7.2+** см. **`frontend/package.json`**); **§13.10 / §13.9** — исторические релизы; **§14.7.1** — workspace-lite на бэкенде и индексы. Диаграмма **§14.3** частично устарела — опираться на **§15.3**. Синхронизируйте **`HANDOFF CURSOR.md`** при изменении схемы БД, API и потоков §14–15.*
