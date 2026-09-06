# Перенос аутрич-инстанса AI-Biz-OS на VPS 194.58.102.98 — ранбук

Дата: 06.09.2026. Ветка: `fork-base` (`70e40c1`). Инстанс — **внутренний инструмент одного
оператора** (Алексей), а не публичный сервис: наружу не открывается ни один порт, доступ идёт
через SSH-туннель. На этой же машине живёт прод NODA12 — он не должен пострадать ничем.

Опорные решения владельца (02.09, память `fg-consulting-status`): один инстанс движка на две
кампании (NODA12 + FG); сначала переезд, все настройки уже на сервере; аутрич слушает 127.0.0.1.

---

## 1. Что уже есть на сервере (проверено 06.09.2026)

| Факт | Значение |
|---|---|
| Хост | reg.ru «Рег.облако», VPS `Purple Uranium` ID 7934903, Москва-3 |
| Доступ | `ssh noda12` → `root@194.58.102.98`, ключ `~/.ssh/noda12_vds`, только по ключу |
| ОС / ядро | Ubuntu 26.04 LTS, `7.0.0-15-generic` |
| CPU / RAM / диск | 2 vCPU · 3909 МБ (свободно ~2,8 ГБ) · 38 ГБ (занято 4,9 ГБ) |
| Swap | **нет** |
| Docker | 29.7.2, Compose v5.5.0 |
| Занятые порты | 22 (sshd), 80 и 443 (`noda12-web-1`, Caddy) |
| Свободны | 8000, 8080 — их и берём, только на 127.0.0.1 |
| Соседи | compose-проект `noda12`: web (Caddy), backend, mosquitto; ~1 ГБ RAM |
| Исходящий SMTP 587 | **открыт** (на старом VDS 95.163.223.186 был закрыт целиком) |
| `api.openai.com` | **403** напрямую |
| `api.tavily.com` | **403** напрямую |
| Node / npm | не установлены (и не нужны: UI собирается внутри образа) |
| Deploy key на сервере | `/root/.ssh/id_ed25519` — read-only ключ репозитория `svechinov/Noda12` |

Ранбук соседа: `C:\Users\user\Projects\Noda12\doc\deploy-runbook.md` — там же порядок работ с
Caddy, DNS и лендингом. **Мы туда не лезем.**

---

## 2. Блокеры — решаются владельцем до запуска

1. **Прокси (жёсткий блокер).** OpenAI и Tavily отдают 403 напрямую; локальный `backend/.env`
   поле `HTTP_PROXY` держит пустым (дома доступ есть без него). Рабочие данные прокси были на
   старом VDS `95.163.223.186` — забрать их из этой сессии не удалось (подключение к старому
   серверу заблокировано политикой). Без прокси инстанс поднимется, UI откроется, но генерация,
   OSINT и обогащение работать не будут.
2. **Как доставлять код.** Ветка `fork-base` **не запушена**: `origin` (`svechinov/AISA`) её не
   знает. Варианты в §3.
3. **Данные.** Локальная `backend/ai_biz_os.db` по сути пуста (3 рана, 191 контакт, персон и
   программ нет — сидеры не гонялись). Живые пилотные данные лежат на старом VDS. По решению
   02.09 сидеры гоняются уже на сервере, то есть база создаётся с нуля; нужно только сказать,
   тащить ли что-нибудь со старого VDS (suppression-лист, контакты пилота).

---

## 3. Доставка кода: два пути

**A. Git (рекомендуется).** Как у соседа: сервер тянет код сам, обновление — `git pull`.
Требуется: запушить `fork-base` в `origin`, завести **отдельный** deploy key (GitHub не даёт
использовать один ключ в двух репозиториях — существующий занят `Noda12`) и алиас в
`/root/.ssh/config`.

```bash
# на сервере
ssh-keygen -t ed25519 -f /root/.ssh/id_ed25519_aibizos -N ""
cat /root/.ssh/id_ed25519_aibizos.pub   # -> GitHub svechinov/AISA -> Settings -> Deploy keys (без write)
cat >> /root/.ssh/config <<'EOF'
Host github-aibizos
  HostName github.com
  User git
  IdentityFile /root/.ssh/id_ed25519_aibizos
  IdentitiesOnly yes
EOF
mkdir -p /opt/ai-biz-os && cd /opt/ai-biz-os
git clone --branch fork-base git@github-aibizos:svechinov/AISA.git app
```

**B. Rsync с ноутбука** (если пуш ветки нежелателен). Медленнее в сопровождении, зато ничего не
уезжает на GitHub:

```bash
rsync -az --delete \
  --exclude '.git' --exclude 'venv' --exclude 'node_modules' --exclude '*.db' \
  --exclude 'infra/data' --exclude 'docs' \
  /c/Users/user/AI-Biz-OS/ noda12:/opt/ai-biz-os/app/
```

---

## 4. Порядок работ

### 4.0. Swap 2 ГБ (до первой сборки)

Сборка UI (`npm ci` + `vite build`) берёт ~1–1,5 ГБ и все ядра. Свободно ~2,8 ГБ, но сосед в этот
момент может собираться сам — своп снимает риск OOM-kill и стоит только диска.

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -m
```

### 4.1. Код на сервере

По §3 (A или B). Ожидаемая раскладка: `/opt/ai-biz-os/app` — репозиторий, `fork-base`.

### 4.2. Секреты и база

```bash
mkdir -p /opt/ai-biz-os/app/infra/data
cd /opt/ai-biz-os/app/infra
cp data/.env.example data/.env
chmod 600 data/.env
nano data/.env          # заполнить: GLOBAL_PASSWORD, SECRET_KEY, OPENAI_API_KEY, HTTP_PROXY, TAVILY_API_KEY
```

`SECRET_KEY` — `openssl rand -hex 32`. `DATABASE_URL` в шаблоне уже указывает на
`/app/data/ai_biz_os.db`: база появится сама при первом старте (идемпотентные `_ensure_*` из
`init_db.py`, включая три поля Фазы 2 — отдельных миграций не нужно).

### 4.3. Запуск

```bash
cd /opt/ai-biz-os/app/infra
docker compose -f docker-compose.vps.yml up -d --build
docker compose -f docker-compose.vps.yml ps        # backend и ui в Up
docker compose -f docker-compose.vps.yml logs --tail=50 backend
```

Первая сборка небыстрая: `pip install` (pandas, cryptography) плюс `npm ci` + `vite build`
(локально сборка фронта заняла 1 мин 21 с на более сильной машине).

### 4.4. Смок — гейт переезда

```bash
# 1. Бэкенд отвечает
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health

# 2. UI отдаёт SPA и разворачивает /api на том же origin
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/health

# 3. Прокси действительно работает (без него следующая строка вернёт 403)
docker compose -f docker-compose.vps.yml exec backend \
  python -c "import os,httpx;p=os.environ.get('HTTP_PROXY') or None;print(httpx.get('https://api.openai.com/v1/models',proxy=p,timeout=20).status_code)"
# ожидаем 401 (ключ не передан) — это значит, что до OpenAI дошли; 403 = прокси не работает

# 4. Схема доехала: три поля Фазы 2 на месте
docker compose -f docker-compose.vps.yml exec backend \
  python -c "import sqlite3;c=sqlite3.connect('/app/data/ai_biz_os.db');print([r[1] for r in c.execute('PRAGMA table_info(run_setups)') if r[1] in ('max_authored_words','program_match_enabled')]);print([r[1] for r in c.execute('PRAGMA table_info(training_programs)') if r[1]=='persona_id'])"

# 5. Сосед не задет
curl -s -o /dev/null -w '%{http_code}\n' https://app.noda12.com/hub
docker ps --format '{{.Names}} {{.Status}}'
free -m
```

### 4.5. Операционные шаги после переезда

По решению владельца 02.09 они делаются **здесь**, а не на локальной базе:

```bash
cd /opt/ai-biz-os/app/backend

# NODA12: персона + 6 сессий каталога, чтобы у строк проставился persona_id.
# --profile обязателен: consulting = трек A, corporate = трек B.
python scripts/seed_noda12_preset.py --run-id <ID> --profile consulting --dry-run
python scripts/seed_noda12_preset.py --run-id <ID> --profile consulting --seed-persona-noda12 --seed-offers

# FG: персона + отраслевой ран. chemicals — единственная залитая отрасль,
# --allow-placeholders ей больше не нужен (коммит 70e40c1).
python scripts/seed_fg_preset.py --run-id <ID> --industry chemicals --frame 1 --dry-run
python scripts/seed_fg_preset.py --run-id <ID> --industry chemicals --frame 1 --seed-persona-fg --seed-offers
python scripts/seed_fg_preset.py --run-id <ID> --industry chemicals --frame 2
```

Раны заводятся в UI (или API) до прогона сидера — сидер требует существующий `--run-id`.

⚠️ Закрывающий абзац персоны FG — плейсхолдер `[FG-CONTENT PENDING]` до ответа клиента на Г5:
черновики будут физически содержать маркер. Это защита, а не дефект; экспортировать такие письма
менеджерам нельзя.

---

## 5. Доступ оператора

Публичного адреса нет. С ноутбука:

```bash
ssh -L 8080:127.0.0.1:8080 noda12
```

и открыть `http://localhost:8080` — вход по `GLOBAL_PASSWORD`. Порт 8000 пробрасывать не нужно:
UI ходит в API через свой же origin (`/api`, `infra/nginx-ui.conf`).

---

## 6. Обновление

```bash
cd /opt/ai-biz-os/app && git pull        # либо rsync по §3B
cd infra && docker compose -f docker-compose.vps.yml up -d --build
```

Правки в `Caddyfile` соседа не требуются никогда — у нас его нет.

---

## 7. Эксплуатация

- **Логи**: `docker compose -f docker-compose.vps.yml logs -f backend`
- **Бэкап базы** (SQLite копируется целиком; экспорт черновиков лежит рядом):
  ```bash
  cp /opt/ai-biz-os/app/infra/data/ai_biz_os.db /root/aibizos-$(date +%F).db
  ```
  Бэкап-крон на этой машине не заведён — сделать отдельным шагом (у AI-Biz-OS бэкапов прода нет
  исторически, см. память `aibizos-current-decisions`).
- **Экспорт черновиков для менеджеров FG**. Путь внутри `data/` выбран намеренно: это
  bind-каталог, файл сразу оказывается на хосте, `docker cp` не нужен.
  ```bash
  # на сервере
  docker compose -f docker-compose.vps.yml exec backend \
    python scripts/export_run_drafts.py --run-id <ID> --out /app/data/exports/run<ID>.xlsx
  # с ноутбука
  scp noda12:/opt/ai-biz-os/app/infra/data/exports/run<ID>.xlsx .
  ```
  Без `--out` файл ляжет в `/app/exports/` внутри контейнера и исчезнет с пересборкой.

---

## 8. Чего мы намеренно не делаем

- **Не трогаем Caddy, DNS и лендинг NODA12.** Ни нового сайт-блока, ни A-записи: аутрич живёт на
  127.0.0.1. Откат переезда = `docker compose down` в своём каталоге, сосед этого не замечает.
- **Не поднимаем Postgres и Redis** — пилот на SQLite, Redis кодом не используется
  (`infra/docker-compose.yml` с ними — локальный, не серверный).
- **Не настраиваем транспорт почты.** Канал FG экспортный: движок генерирует, менеджеры шлют
  сами. То, что на этом сервере открыт 587-й порт, — задел для холодного канала, не задача фазы.
- **Не переносим старый VDS 95.163.223.186 целиком.** Там июньский код до форка; ценность
  представляют только данные, и вопрос о них открыт (§2.3).
