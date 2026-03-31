# AI Biz OS — Handoff (передача разработки)

**Актуальная продуктовая передача и план ухода от логики «только VOD»:** см. корневой **`HANDOFF.md`** в этом же репозитории.

**Операторский UI и схема на релизе 2.1.4** (dead mailbox / send later / вложения через `attached_asset_ids`): раздел **`HANDOFF.md` §12**; фронтенд-версия — `frontend/package.json`.

---

Документ ниже описывает архитектуру, сущности, реализованный функционал, расположение кода и следующий логичный шаг. Репозиторий: `ai-biz-os/` (backend + frontend + infra).

---

## 1. Архитектура (высокий уровень)

| Слой | Технологии | Назначение |
|------|------------|------------|
| **API** | FastAPI, Pydantic, SQLAlchemy 2.x | REST, валидация, ORM |
| **БД** | PostgreSQL (дефолт в `app/config.py`), SQLite возможен через `DATABASE_URL` | Персистентность |
| **Фон / очереди** | Redis в `docker-compose` (URL в `REDIS_URL`) | Инфра под будущие воркеры; часть кода может его не использовать |
| **Frontend** | React, Vite, shadcn-подобные UI-компоненты в `components/ui/` | Human-in-the-loop UI |
| **Инфра** | `infra/docker-compose.yml` | Postgres, Redis, backend-контейнер `:8000` |
| **Схема БД** | `Base.metadata.create_all` + точечные миграции в `app/init_db.py` (`ensure_schema`) | Нет отдельного обязательного Alembic-потока в описанном scope |

**Типичный dev-поток**

- Backend: каталог `backend/`, venv `.venv`, `uvicorn app.main:app --reload` (часто **:8001**, если Docker занял **:8000**).
- Фон без открытого терминала: `backend/scripts/start_uvicorn_bg.sh` / `stop_uvicorn_bg.sh`.
- Frontend: `frontend/`, `npm run dev` → `http://localhost:5173`, запросы на **`/api`** проксируются (см. `frontend/vite.config.js`, переменная **`VITE_API_PROXY_TARGET`** и комментарии в `frontend/.env.development`).

**Важно:** если UI получает **404 Not Found** на новых эндпоинтах, чаще всего прокси бьёт в **старый Docker** на `:8000`, а актуальный код — на локальном uvicorn (**:8001**). Проверка: `curl` на `/openapi.json` обоих портов.

---

## 2. Структура репозитория (где что лежит)

```
ai-biz-os/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, роутеры, CORS, lifespan → ensure_schema
│   │   ├── config.py            # Settings (DATABASE_URL, REDIS_URL, …)
│   │   ├── db.py                # engine, SessionLocal, get_db
│   │   ├── init_db.py           # create_all + ALTER-«миграции» для существующих таблиц
│   │   ├── api/                 # HTTP-роуты (по одному файлу на домен)
│   │   ├── models/              # SQLAlchemy-модели (= таблицы)
│   │   ├── schemas/             # Pydantic request/response
│   │   ├── repositories/        # Доступ к БД (тонкий слой над Session)
│   │   └── services/            # Бизнес-логика, оркестрация
│   ├── requirements.txt
│   ├── Dockerfile
│   └── scripts/
│       ├── start_uvicorn_bg.sh
│       ├── stop_uvicorn_bg.sh
│       └── verify_template_emails.py
├── frontend/
│   ├── src/
│   │   ├── pages/AiBizOsHumanUI.jsx   # Review workspace + навигация в Tracking
│   │   ├── components/TrackingView.jsx # события, треды, reply drafts, follow-ups, reminders, assets, packets, dead mailboxes, queue
│   │   ├── components/DraftAssetAttachmentsField.jsx # выбор assets для email/reply draft
│   │   ├── components/EmailDraftBodyPreview.jsx      # превью: тело, [Signature], [Asset #…]
│   │   └── components/ui/
│   ├── vite.config.js           # proxy /api → VITE_API_PROXY_TARGET или :8000
│   └── .env.development
└── infra/
    └── docker-compose.yml       # postgres, redis, backend:8000
```

---

## 3. Текущие сущности (модели / таблицы)

Ниже — **основные** таблицы и поля уровня «для handoff». Точные колонки — в `backend/app/models/*.py`.

| Сущность | Таблица | Ключевые связи / поля |
|----------|---------|------------------------|
| **Project** | `projects` | Проекты кампаний |
| **Run** | `runs` | Запуск воркфлоу под `project_id` |
| **Step** | `steps` | Шаги выполнения по `run_id` |
| **Rule** | `rules` | Правила (scope, контент) |
| **Template** | `templates` | Шаблоны писем |
| **Contact** | `contacts` | Контакт в контексте `run_id`, review, `email_health`, `source_json` (в т.ч. replacement) |
| **EmailDraft** | `email_drafts` | Исходящий драфт outreach, отправка, tracking; **`attached_asset_ids`** (JSON список id из библиотеки `Asset`) |
| **EmailEvent** | `email_events` | События (sent, replied, bounce, dead_mailbox, …) |
| **EmailThread** | `email_threads` | Тред переписки: `run_id`, `contact_id`, `draft_id`, `classification` (+ confidence, reason) |
| **EmailMessage** | `email_messages` | Сообщения в треде (inbound/outbound) |
| **ReplyDraft** | `reply_drafts` | Черновик ответа: `run_id`, `thread_id`, `contact_id`, `reply_type`, subject/body, review, send; **`attached_asset_ids`** |
| **ResearchTask** | `research_tasks` | **Технические** задачи: replacement, enrichment, поиск (не путать с follow-up) |
| **FollowUpTask** | `follow_up_tasks` | **Sales next actions**: типы `reply_to_interested`, `send_more_info`, `follow_up_later`, `close_thread` |
| **Reminder** | `reminders` | Напоминания, опционально привязка к `follow_up_task_id`, `remind_at`, статусы scheduled/triggered/… |
| **Asset** | `assets` | Глобальная библиотека материалов (`asset_type`, url/file_path, status) |
| **AssetPacket** | `asset_packets` | Пакет материалов по `run_id`, опц. `thread_id`, `contact_id`, **`reply_draft_id` (nullable)**, `packet_json` |

---

## 4. Связи и потоки данных (концептуально)

```
Project ──< Run ──< Step
              ├──< Contact ──< EmailDraft ──> EmailEvent
              │                    └──> EmailThread ──< EmailMessage
              │                         └── classification (reply_classifier / inbox)
              ├──< ReplyDraft (ответ на thread)
              ├──< ResearchTask  ←── replacement / enrichment (отдельный lifecycle)
              ├──< FollowUpTask  ←── ручное «next action» из классификации треда
              ├──< Reminder      ←── ручно из follow-up; не автопайплайн
              └──< AssetPacket   ←── build из thread (need_more_info / interested) из библиотеки Asset

Asset (global) ──embedded in── AssetPacket.packet_json.assets[]  (копия/снимок ссылок на asset_id)

EmailDraft / ReplyDraft ──> attached_asset_ids[]  (ссылки на id в `assets`; **отдельно** от пакета; миграция `_ensure_drafts_attached_asset_ids_columns` в `init_db.py`)

FollowUpTask ≠ ResearchTask  (разные таблицы, разный UI и смысл)
ReplyDraft ≠ AssetPacket      (письмо vs структурированный пакет; связь reply_draft_id пока не обязательна)
Draft.attached_asset_ids ≠ AssetPacket  (ручной список вложений в UI vs собранный пакет; при отправке нужно явно **мержить** в пайплайне, см. §9)
```

**Сводка по run:** `app/services/run_summary_service.py` → `GET /sending/runs/{run_id}/summary` (счётчики по контактам, драфтам, событиям, тредам, reply drafts, follow-up, reminders, asset packets).

---

## 5. Что уже реализовано (по доменам)

### 5.1 Outreach и трекинг

- Генерация/редактура/review контактов и email drafts, отправка (батч и single).
- События трекинга, mock-сценарии (bounce, dead mailbox, replied) — `app/api/tracking.py`, `email_tracking_service.py`.
- Inbox mock receive — `app/api/inbox.py`, `inbox_service.py`.

### 5.2 Треды, классификация ответов, reply drafts

- Треды и сообщения: `email_threads`, `email_messages`, API в `app/api/email_threads.py`.
- Классификация треда (interested, need_more_info, ask_later, not_interested, unclear) — сервисы уровня `reply_classifier.py` (интеграция в поток после inbound).
- Reply drafts: генерация по thread, review, edit, отправка — `reply_drafts.py`, `reply_draft_service.py`, `reply_sender.py`.

### 5.3 Replacement / research (технические задачи)

- `research_tasks`: поиск замены, enrichment, очередь — `research_tasks.py`, `replacement_*`, `research_task_runner.py` и др.
- UI: вкладки Dead mailboxes, Re-search queue в `TrackingView.jsx`.

### 5.4 Follow-up tasks (sales actions)

- Модель `FollowUpTask`, репозиторий, сервис `follow_up_service.py` (маппинг классификации → тип задачи, дедуп по thread+типу).
- API: list по run/thread, ручное `create-next-action`, PATCH статуса — `app/api/follow_up_tasks.py`.
- **Нет** автосоздания задачи при классификации — только явная кнопка в UX.

### 5.5 Reminders

- Модель `Reminder`, repo, `reminder_service.py` (создание от follow-up с дедупом «активного» напоминания), `reminder_scheduler.py` (ручной `trigger-due` → scheduled/snoozed с прошедшим `remind_at` → triggered).
- API: `app/api/reminders.py`.
- **Нет** фонового cron — только POST `trigger-due` и UI.

### 5.6 Assets и asset packets

- Глобальная библиотека `Asset`; run/thread-специфичный `AssetPacket` с `packet_json` (контакт + список вложенных описаний assets).
- Сборка пакета: `asset_packet_service.build_asset_packet_for_thread` — только `need_more_info` / `interested`, дедуп по thread + packet_type при draft/approved, выбор активных assets по типам из ТЗ.
- API: `app/api/assets.py`, `app/api/asset_packets.py`.
- UI: вкладки Assets, Packets; в thread modal — Build info/interested packet; Approve/Archive packet.
- **Draft-level вложения (2.1.4):** колонки **`attached_asset_ids`** на `email_drafts` и `reply_drafts`; нормализация `utils/attached_asset_ids.py`; в edit-PATCH обоих типов драфтов; в Human UI и Tracking — компонент **`DraftAssetAttachmentsField`**, превью **`EmailDraftBodyPreview`** (`[Asset #n]` под `[Signature]`). Отправка MIME по этим id **ещё не сквозная** — см. §9.
- **Нет** автопривязки packet → reply draft и автосмены `sent` при отправке письма.

### 5.7 Frontend

- **Review workspace:** **`AiBizOsHumanUI.jsx`** — контакты и исходящие email drafts, Approve / Send later (часы, `review_notes: "send_later"`), dead mailbox стили и ограничения (Delete драфта только при `tracking_status == dead_mailbox`), Edit с rich text + вложения из Assets.
- **Tracking:** **`TrackingView.jsx`** — Events, Threads, Reply drafts (модалка редактирования как у outreach), Next actions, Reminders, Assets, Packets, Dead mailboxes, Re-search queue; единый `border-2` для карточек; подсветка dead mailbox по цепочкам событий и тредам; убраны успешные toast `actionNote`.
- Версия пакета фронта: **`package.json` → 2.3.0** (смотреть при handoff).

### 5.8 Инфра и запуск

- `infra/docker-compose.yml`: Postgres, Redis, backend.
- Локальный backend в фоне: `backend/scripts/start_uvicorn_bg.sh`.

---

## 6. Ключевые файлы по темам (шпаргалка)

| Тема | Файлы |
|------|--------|
| Точка входа API | `backend/app/main.py` |
| Схема БД | `backend/app/init_db.py` + `models/*` |
| Агрегированная сводка run | `backend/app/services/run_summary_service.py`, `api/sending.py` |
| Follow-up | `models/follow_up_task.py`, `repositories/follow_up_task_repo.py`, `services/follow_up_service.py`, `api/follow_up_tasks.py` |
| Reminders | `models/reminder.py`, `repositories/reminder_repo.py`, `services/reminder_service.py`, `services/reminder_scheduler.py`, `api/reminders.py` |
| Assets / packets | `models/asset.py`, `models/asset_packet.py`, `repositories/asset_repo.py`, `repositories/asset_packet_repo.py`, `services/asset_packet_service.py`, `api/assets.py`, `api/asset_packets.py` |
| Draft-level asset ids | `utils/attached_asset_ids.py`, `init_db._ensure_drafts_attached_asset_ids_columns`, `models/email_draft.py`, `models/reply_draft.py`, `api/email_drafts.py`, `api/reply_drafts.py`, репозитории драфтов |
| Reply drafts | `models/reply_draft.py`, `api/reply_drafts.py`, `services/reply_draft_service.py`, `reply_sender.py` |
| Human UI / превью драфтов | `pages/AiBizOsHumanUI.jsx`, `components/DraftAssetAttachmentsField.jsx`, `components/EmailDraftBodyPreview.jsx` |
| Research / replacement | `models/research_task.py`, `api/research_tasks.py`, `services/replacement_*.py`, `research_task_runner.py` |
| Tracking UI | `frontend/src/components/TrackingView.jsx` |
| Proxy dev API | `frontend/vite.config.js`, `frontend/.env.development` |

---

## 7. Текущее состояние разработки

- Функциональность выше описана как **реализованная в кодовой базе** на момент составления handoff.
- **Тесты:** отдельного полного e2e-набора в описании не фиксировалось; проверка — через `/docs`, curl и UI Tracking.
- **Версионирование БД:** преимущественно `create_all` + ручные `ALTER` в `init_db.py`; при смене моделей на проде нужна дисциплина (Alembic или миграции по аналогии с `_ensure_*`).

---

## 8. Что не трогать без веской причины

1. **Не смешивать `research_tasks` с follow-up логикой** — follow-up живёт в `follow_up_tasks` и отдельных API/UI.
2. **Не вешать автомагию** там, где в ТЗ явно требовались ручные шаги: автосоздание follow-up, автосоздание reminders, автотриггер reminders при загрузке страницы, автопривязка asset packet к reply draft, автосмена `asset_packets.status` на `sent` при отправке — **пока не делалось намеренно**.
3. **`app/init_db.py`** — аккуратно с порядком и условиями миграций; не ломать существующие `_ensure_*` без понимания боевых БД.
4. **Разделение слоёв:** `reply_draft` = текст письма; `asset_packet` = структурированный пакет; **`attached_asset_ids`** на драфте = отдельный явный список вложений из библиотеки. Три источника не смешивать в одном поле без явного merge при отправке.
5. **Порт 8000 vs 8001** — документировать для команды: Docker vs локальный uvicorn, иначе «ложные» 404.

---

## 9. Следующие шаги (бэклог после 2.1.4)

### 9.1 Отправка: **merge `attached_asset_ids` в MIME**

Сейчас оператор видит в превью `[Asset #…]` и сохраняет id в БД, но **`email_sender`** (исходящий outreach) и **`reply_sender.build_reply_send_payload`** должны **явно добавить** файлы по id из `email_drafts.attached_asset_ids` / `reply_drafts.attached_asset_ids` к уже существующей логике **asset packet** (`resolve_sendable_attachments` и т.д.), с дедупом по `asset_id` и осмысленными лимитами размера.

### 9.2 **Attach packet to reply draft**

Цель: явно связать **`AssetPacket`** с конкретным **`ReplyDraft`**, не ломая ручной характер слоя. Это **отдельная** задача от 9.1 (packet vs draft-level ids).

1. **Данные** — в `AssetPacket` уже есть **`reply_draft_id`** (FK, nullable):
   - API: `PATCH /asset-packets/{id}` с установкой `reply_draft_id` **или** `POST /asset-packets/{id}/attach-reply-draft` с телом `{ "reply_draft_id": … }`.
   - Валидация: тот же `run_id`, согласованный `thread_id`/`contact_id` с выбранным reply draft.
2. **Сервис** — `update_asset_packet`: проставить `reply_draft_id`, опционально метаданные в `packet_json`.
3. **UI** — в `TrackingView` на карточке reply draft / packet: Attach / Detach, взаимные badges.
4. **Не делать без ТЗ** — авто-подстановка тела из packet в LLM; авто `sent` на packet при отправке reply.

### 9.3 Git

На некоторых машинах **`git push`** к GitHub падает по SSH (`Permission denied (publickey)`); до настройки ключа теги остаются локальными.

---

## 10. Контакты / владение

При передаче новому разработчику приложить: актуальный `DATABASE_URL`, политику деплоя Docker vs bare metal, и договорённость о **порте backend**, с которым совпадает `VITE_API_PROXY_TARGET`.

---

*Документ сгенерирован для передачи контекста; при существенных изменениях кода обновляйте разделы 3–6 и 9. Расширенное описание релиза 2.1.4 — **`HANDOFF.md` §12**.*
