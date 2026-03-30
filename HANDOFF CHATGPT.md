# AI Biz OS — FULL HANDOFF DOCUMENT

---

# 1. OVERVIEW

AI Biz OS — это модульная система для управления outreach-коммуникациями с AI-поддержкой.

Ключевая идея:
Система НЕ автоматизирует действия скрыто. Она помогает, но все решения принимает пользователь.

---

# 2. CORE PRINCIPLES (КРИТИЧНО)

1. Никакой скрытой автоматизации
2. Все действия только через явные API/UI
3. Каждая сущность — отдельная зона ответственности
4. Нельзя объединять сущности
5. Дедупликация обязательна
6. История должна быть воспроизводимой
7. Никаких “магических” авто-действий

---

# 3. HIGH-LEVEL ARCHITECTURE

Слои системы:

1. Outreach Layer
2. Replacement Layer
3. Inbox Layer
4. Classification Layer
5. Reply Layer
6. Follow-up Layer
7. Scheduling Layer
8. Assets Layer

---

# 4. ENTITIES (ПОЛНЫЙ СПИСОК)

## 4.1 Core

### projects
- id
- name

### runs
- id
- project_id
- status

### contacts
- id
- run_id
- email
- name
- company
- status

---

## 4.2 Outreach

### email_drafts
- id
- contact_id
- run_id
- subject
- body
- status (draft / approved / sent)

---

## 4.3 Replacement

### research_tasks
- id
- contact_id
- run_id
- status (open / running / completed / failed / no_result)

---

## 4.4 Inbox

### email_threads
- id
- contact_id
- run_id
- classification
- classification_confidence
- classification_reason

### email_messages
- id
- thread_id
- direction (inbound / outbound)
- body
- created_at

---

## 4.5 Reply Layer

### reply_drafts
- id
- thread_id
- contact_id
- run_id
- subject
- body
- status (draft / approved / sent)

⚠️ ВАЖНО:
ПОКА НЕТ:
- asset_packet_id (будет добавлено)

---

## 4.6 Follow-up

### follow_up_tasks
- id
- thread_id
- contact_id
- run_id
- task_type
- status (open / in_progress / completed / cancelled)
- due_at

---

## 4.7 Scheduling

### reminders
- id
- follow_up_task_id (nullable)
- thread_id (nullable)
- contact_id
- run_id
- status (scheduled / triggered / snoozed / completed / cancelled)
- remind_at

---

## 4.8 Assets

### assets
- id
- type (deck / screener / website / catalog / etc)
- url

### asset_packets
- id
- thread_id
- contact_id
- run_id
- packet_type
- status (draft / approved / sent / archived)
- packet_json

---

# 5. ENTITY RELATIONSHIPS

- run → contacts (1:N)
- contact → email_threads (1:N)
- thread → email_messages (1:N)
- thread → reply_drafts (1:N)
- thread → follow_up_tasks (1:N)
- follow_up_task → reminders (1:N)
- thread → asset_packets (1:N)

---

# 6. IMPLEMENTED FUNCTIONALITY

## 6.1 Outreach
- генерация email_drafts
- approve / send
- дедуп

---

## 6.2 Replacement
- dead mailbox detection
- research_tasks lifecycle
- создание нового contact
- generate replacement drafts (endpoint)
- send replacement drafts (endpoint)

---

## 6.3 Inbox
- threads создаются при отправке
- messages inbound/outbound
- mock reply
- обновление thread

---

## 6.4 Classification
- rule-based классификация
- сохранение в thread

---

## 6.5 Reply drafts
- генерация
- редактирование
- approve
- send

---

## 6.6 Follow-up
- create next action
- дедуп
- статусы

---

## 6.7 Reminders
- create reminder
- snooze
- trigger_due_reminders
- дедуп

---

## 6.8 Assets / Packets
- asset library
- packet generation
- дедуп packet
- packet status lifecycle

---

# 7. FILE STRUCTURE

## Models
app/models/
- email_thread.py
- email_message.py
- reply_draft.py
- follow_up_task.py
- reminder.py
- asset.py
- asset_packet.py

## Repositories
app/repositories/
- *_repo.py

## Services
app/services/
- reply_draft_service.py
- reply_sender.py
- follow_up_service.py
- reminder_service.py
- reminder_scheduler.py
- asset_packet_service.py
- replacement_worker.py

## API
app/api/
- reply_drafts.py
- follow_up_tasks.py
- reminders.py
- asset_packets.py
- inbox.py

## Schemas
app/schemas/
- *.py

---

# 8. CURRENT STATE

Система уже:

- отправляет outreach
- принимает ответы
- классифицирует
- генерирует reply
- управляет задачами
- ставит reminders
- формирует asset packets

НО:

❗ reply_draft НЕ связан с asset_packet

---

# 9. CRITICAL CONSTRAINTS (НЕ ТРОГАТЬ)

❗ Replacement:
- всегда новый contact

❗ Не объединять:
- drafts
- reply_drafts
- tasks
- reminders
- packets

❗ Не добавлять:
- авто-send
- авто-create
- авто-trigger

❗ Не ломать:
- дедуп
- API контракты

---

# 10. NEXT STEP

# Attach packet to reply draft

---

## 10.1 Цель

Связать reply_draft с asset_packet

---

## 10.2 DB CHANGE

reply_drafts:

Добавить поле:

asset_packet_id (nullable FK → asset_packets.id)

---

## 10.3 RULES

- только 1 packet на draft
- packet должен:
  - иметь тот же thread_id
  - иметь тот же run_id
- packet не должен быть archived

---

## 10.4 REPOSITORY

Метод:

attach_asset_packet_to_reply_draft(draft_id, packet_id)

---

## 10.5 API

POST /reply-drafts/{id}/attach-packet

Body:
{
  "asset_packet_id": "..."
}

---

## 10.6 VALIDATION

Проверить:

- draft существует
- packet существует
- совпадает thread_id
- совпадает run_id
- packet.status != archived

---

## 10.7 UI

Reply Draft:
- кнопка Attach packet
- список packet текущего thread
- отображение attached packet

Thread modal:
- отображение attached packet

---

## 10.8 BEHAVIOR

- attach вручную
- не создавать packet автоматически
- не менять текст письма

---

# 11. NEXT AFTER THAT

# Packet-aware reply sending

(будет следующим этапом)

---

# 12. FINAL NOTE

После этого шага система переходит от:

"AI пишет письмо"

к:

"AI управляет коммуникацией + материалами"

Это ключевой переход архитектуры.