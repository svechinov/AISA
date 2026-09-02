# FG-трек и движковые доработки — план Фазы 2 (движок аутрича)

> **Для исполняющей сессии.** Задачи идут блоками `Task N`; шаги внутри — чекбоксы
> (`- [ ]`), каждый шаг = одно действие на 2–5 минут. TDD: тест пишется и запускается
> ДО реализации. Коммит — последний шаг каждой задачи. Режим исполнения (та же сессия /
> субагенты) выбирает архитектор при запуске.

**Цель фазы.** Три движковые доработки в основной ветке `fork-base` (настраиваемый лимит
объёма письма, скоуп каталога программ по персоне, XLSX-экспорт черновиков рана) + пресет
FG (персона + матрица «отрасль × рамка» с контент-плейсхолдерами) + упразднение `track/fg`.

**Архитектура.** Все три доработки — паттерном «данные + фоллбэк»: новое nullable-поле,
NULL = сегодняшнее поведение байт-в-байт, значение = новое. Ни одна не разветвляется по
slug персоны и не трогает дефолтные промпты движка — поэтому все три возвращаемы партнёру
черри-пиком. FG-пресет — данные поверх этих полей, кода не добавляет.

**Стек.** Python 3.12, FastAPI, SQLAlchemy 2.0 (SQLite), pytest 9. Новая зависимость:
`openpyxl` (возврат, см. находку разведки №1).

---

## Вводный блок

Фаза 2 форк-перехода. Основание: `HANDOFF_fg-phase2_2026-09-02.md` (Fable-концепт-сессия
30.08–02.09.2026, все развилки закрыты владельцем 02.09) и `PLAN_fork-transition-phase1_2026-08-26.md`
(Tasks 1–8 сделаны и приняты — не переделывать). Ветка работы — `fork-base`.

Фаза закрывает движковый кусок FG-трека и общие доработки движка, нужные обеим кампаниям
(NODA12 и FG) на одном инстансе. Вне фазы: Task 9 (инстанс — ждёт сервера), Task 10
(транспорт Gmail — исключён владельцем 02.09), Task 11 (волны), контент FG.

---

## Решения, зафиксированные архитектором (не переоткрывать)

Выжимка из handoff, раздел «Ключевые решения» — все от 02.09.2026, владелец.

- **A. Один инстанс движка, две кампании** (NODA12 + FG). Оператор ближайшие 1–2 мес — Алексей.
  Отсюда: скоуп каталога обязателен, `track/fg` упраздняется, `seed_fg_preset.py` — в основной ветке.
- **B. Экспортный канал:** движок генерирует, менеджеры FG отправляют вручную со своих ящиков.
  Черновики НЕ аппрувить (approve = автопостановка в очередь). Цикл «ревью → экспорт».
- **C. Две рамки письма (A/B):** Рамка‑1 точная (одно решение, матчер), Рамка‑2 широкая
  (веер «название + предложение»). Сплит выборки отрасли между двумя ранами.
- **D. Лимит объёма — настраиваемый,** фоллбэк на текущие 120–140/180 байт-в-байт.
- **E. Минихук — только при крутом OSINT-поводе,** через `draft_prompt` пресета, не через код.
- **F. Свежесть отраслевых ревю — горизонт ~полгода;** актуализация — операционка, не код.
- **G. Письма персон AlexStaff не меняются ни на байт.** Доказательство —
  `test_persona_finale_regression.py`, `test_hard_rules_gate_b273.py`, `test_email_validation_b063.py`,
  `test_email_validation_b077.py` зелёные **без правок**.
- **H. Task 10 вне фазы;** Task 9 ждёт сервера.

Отвергнутые альтернативы (не «улучшать» обратно): отдельный FG-инстанс; мультитенант-слой;
правка глобального дефолт-промпта под минихук; сеяние выдуманного контента ради числа.

---

## Проектные решения плана (приняты планировщиком, архитектор может отклонить)

- **I. Лимит объёма живёт в `run_setups.max_authored_words`** (Integer, nullable), как и
  рекомендовал handoff. Почему не в персоне: лимит меняется между рамками A/B на ОДНОЙ персоне FG
  (Рамка‑1 — дефолт, Рамка‑2 — повышенный), а рамка — свойство рана. Персона осталась бы
  вынуждена расщепиться на две ради одного числа.
- **J. Текст ошибки при NULL воспроизводится дословно** («…is about 120-140 words in 3 short
  paragraphs — this one has N.»), при заданном лимите — нейтральный («…must stay under N words…»).
  Причина: «120–140» — целевой диапазон под потолок 180; переносить его на чужой потолок значит
  выдумывать диапазон, которого никто не задавал. Дословность фоллбэка проверяется существующим
  `test_hard_rules_gate_b273.py::test_overlong_body_flagged` (он ассертит подстроку «120-140 words»).
- **K. Скоуп каталога — `training_programs.persona_id`** (nullable FK → `personas.id`,
  `ondelete="SET NULL"`). NULL = «виден всем». Фильтр в матчере применяется **только когда
  вызывающий передал `persona_id`** — вызов без него (прямые/юнит-вызовы) видит весь каталог,
  как сегодня.
- **L. Выключатель матчера — `run_setups.program_match_enabled`** (Boolean, nullable).
  NULL/True = матчер работает (фоллбэк). False = `_apply_program_match` возвращает None до
  единого LLM-вызова. Порог `PROGRAM_MATCH_MIN_FIT` не трогаем — нужен выключатель, не крутилка.
- **M. Экспорт — скрипт `backend/scripts/export_run_drafts.py`, XLSX через `openpyxl` напрямую**
  (не через pandas): нужен контроль ширины колонок и `wrap_text` для тела письма, а pandas всё
  равно потребовал бы тот же openpyxl движком. Эндпоинт и UI-кнопка — вне фазы (решение handoff).
- **N. Матрица FG — аргументы `--industry <slug> --frame 1|2`,** не 10 перечисленных профилей.
  Тексты отраслей живут в словаре `INDUSTRY_CONTENT`, который на старте ПУСТ: неизвестный slug
  собирает пресет с плейсхолдерами `[FG-CONTENT PENDING: …]`, и такой прогон требует явного
  `--allow-placeholders`. Контент FG вливается позже добавлением ключей в словарь — без правок
  механики и без переоткрытия плана.
- **O. Подпись FG пустая (`sender_signature_html=""`).** Это не только «менеджер клеит свою» —
  это структурный замок: `email_sender.validate_outbound_draft_sendable:86-87` отказывает в
  отправке рана без подписи, и тот же чокпоинт стоит в `sending_gates.evaluate_gates`. Экспортный
  канал получает гарантию «ни одного письма не отправлено» из кода, а не из дисциплины оператора.
- **P. Рамка‑2: `max_authored_words = 280`.** Оценка: 5 программ × ~20 слов (название + одно
  предложение) + отраслевое ревю ~80 + хук ~25 + связки. Число — одна константа
  `FRAME2_MAX_WORDS` в сидере; правится без правки движка.
- **Q. FG использует `DEFAULT_FIT_EXCLUSION_RULES` без override.** Покупатель FG — предприятие
  отрасли, конкурент — другой провайдер обучения/консалтинга: это ровно то, что дефолтный текст и
  формулирует. Override нужен был NODA12 (там тренинговая компания — покупатель), у FG обратная
  конфигурация.
- **R. ICP-фильтр по численности у FG выключен** (`icp_min_employees=None`, `icp_max_employees=None`,
  `icp_criteria_json={"regions": ["Russia"]}`). Первая волна FG идёт по готовой выгрузке базы —
  фильтровать по размеру нечего и нечем (firmographics-провайдер не подключён, см.
  `aibizos-pilot-findings`).

---

## Ключевые находки разведки (что план обязан учесть)

1. **`openpyxl` отсутствует в venv, а импорт XLSX его требует.** `app/api/import_crm.py:31`
   вызывает `pd.read_excel(...)`, которому нужен движок openpyxl; пакет выпилен коммитом гигиены
   `d289d1b` по числу прямых импортов — но он был живой ТРАНЗИТИВНОЙ зависимостью pandas.
   Проверено: `venv/Scripts/python.exe -c "import openpyxl"` → `ModuleNotFoundError`. Значит
   импорт CRM-выгрузки сейчас падает на проде при первом же .xlsx. Task 4 чинит это попутно
   (возврат пином) — и это ещё один кандидат на возврат партнёру.
2. **Ограничение объёма в промпте генерации сформулировано в предложениях, не в словах**
   (`outreach_email_pipeline.py:460` — «4-8 sentences total»). Слова живут только в гейте
   (`hard_rules_gate.py:207-209`). Следствие: для Рамки‑2 достаточно своего `draft_prompt`
   (своя структура и свой счёт) плюс поднятого потолка гейта — дефолтный промпт движка не трогаем.
3. **`rs.draft_prompt` заменяет весь task-блок целиком** (`outreach_email_pipeline.py:423`), а
   код после этого всё равно дописывает: запрет писать закрывающий абзац, no-vacancy-блок (у FG
   не сработает — `no_signal_template_enabled=False`) и языковое требование. Значит структура
   обеих рамок и минихук-критерий (решение E) укладываются в данные пресета буквально, а
   дефолтный хук-блок (`:439`) остаётся общим с партнёром.
4. **Пустая подпись = запрет отправки** (см. решение O) — проверяемое свойство, а не пожелание.
5. **Риск peer-similarity в Рамке‑2.** `email_validation_service.py:33` — порог 0.88 по Jaccard
   на множествах слов; письма одной отрасли делят ревю и веер программ, различаясь хуком.
   Арифметика (≈120 общих слов, ~25+25 уникальных) даёт ≈0.7 — под порогом, но запас невелик.
   Митигация в плане: `draft_prompt` Рамки‑2 требует пересказать ревю своими словами под
   конкретного получателя. Наблюдать на первой реальной волне (операционка, не код фазы).
6. **Упразднение `track/fg` безопасно:** `git worktree list` → `.worktrees/fg` на `efe731f`,
   `git -C .worktrees/fg status --porcelain` пуст, `git log fork-base..track/fg` = один коммит
   (`docs(fg): anchor the dormant FG child track`), remote-ветки нет.
7. **`EmailDraft` уже денормализует `company` и `to_email`** (`app/models/email_draft.py:15-16`,
   заполняются в `email_draft_repo.create_email_draft`) — экспорту не нужен join к `contacts`
   ради этих двух полей; join нужен только за должностью контакта.

---

## File Structure

```
backend/
  app/
    models/
      run_setup.py                    # MOD: + max_authored_words, program_match_enabled (Task 1, 3)
      training_program.py             # MOD: + persona_id (Task 2)
    init_db.py                        # MOD: + 3 _ensure_* и их вызовы (Task 1, 2, 3)
    services/
      hard_rules_gate.py              # MOD: _check_length/check_hard_rules параметризованы (Task 1)
      run_context_service.py          # MOD: + get_max_authored_words (Task 1)
      email_validation_service.py     # MOD: + max_authored_words сквозным параметром (Task 1)
      outreach_email_pipeline.py      # MOD: 3 вызова валидации + гейт/скоуп матчера (Task 1, 2, 3)
      program_matcher.py              # MOD: + persona_id-фильтр каталога (Task 2)
      persona_service.py              # MOD: + fg_persona_kwargs и её константы (Task 5)
    api/
      email_drafts.py                 # MOD: вызов валидации с лимитом (Task 1)
  scripts/
    seed_noda12_preset.py             # MOD: _seed_offers проставляет persona_id (Task 2)
    seed_fg_preset.py                 # NEW: персона FG + матрица industry × frame (Task 5)
    export_run_drafts.py              # NEW: XLSX-экспорт черновиков рана (Task 4)
  requirements.txt                    # MOD: + openpyxl пином (Task 4)
  exports/                            # NEW: дефолтный каталог выгрузок (в .gitignore)
  tests/
    test_max_authored_words.py        # NEW (Task 1)
    test_program_catalog_persona_scope.py  # NEW (Task 2)
    test_program_match_toggle.py      # NEW (Task 3)
    test_export_run_drafts.py         # NEW (Task 4)
    test_seed_fg_preset.py            # NEW (Task 5)
    test_fg_frames_seam.py            # NEW (Task 6)
.gitignore                            # MOD: + backend/exports/ (Task 4)
```

---

## Task 1: Настраиваемый лимит объёма письма

**Goal.** Потолок авторской части перестаёт быть константой и приезжает из пресета рана.
При NULL — сегодняшнее поведение и сегодняшний текст ошибки дословно.

**Файлы.**
- Modify: `backend/app/models/run_setup.py:48` (после `fit_exclusion_rules_text`)
- Modify: `backend/app/init_db.py:946-956` (образец `_ensure_run_setups_fit_exclusion_rules_column`), `:1377`
- Modify: `backend/app/services/hard_rules_gate.py:206-232`
- Modify: `backend/app/services/run_context_service.py:239-246` (после `get_critic_canon_text`)
- Modify: `backend/app/services/email_validation_service.py:465-475`, `:566-572`
- Modify: `backend/app/services/outreach_email_pipeline.py:768-772`, `:840-843`, `:871-875`
- Modify: `backend/app/api/email_drafts.py:369-374`
- Test: `backend/tests/test_max_authored_words.py` (новый)

- [ ] **Шаг 1: Написать падающий тест**

Создать `backend/tests/test_max_authored_words.py`:

```python
"""Фаза 2, Task 1: настраиваемый потолок авторской части письма.

NULL в run_setups.max_authored_words = сегодняшнее поведение ДОСЛОВНО (180 слов и текст ошибки
про «120-140 words»); заданное значение поднимает потолок и меняет текст на нейтральный — «120-140»
это целевой диапазон под потолок 180, переносить его на чужой лимит значит выдумывать диапазон.
0 tokens: гейт детерминирован, критик застаблен."""

from __future__ import annotations

import app.services.hard_rules_gate as g
import app.services.outreach_email_pipeline  # noqa: F401 — регистрирует ORM-модели (mapper config)
from app.services.run_context_service import get_max_authored_words


def _body(word_count: int) -> str:
    """Тело, у которого авторская часть — ровно word_count слов (строка приветствия не считается)."""
    return "Hi Steve,\n\n" + " ".join(["word"] * word_count)


# --- Гейт: фоллбэк ------------------------------------------------------------------------------

def test_default_limit_and_wording_are_unchanged():
    issues = g.check_hard_rules("Hiring at Gardens", _body(200), company_name="Gardens")
    assert any(
        "HARD RULE 4:" in i["detail"] and "120-140 words" in i["detail"] and "has 200" in i["detail"]
        for i in issues
    ), issues


def test_none_is_the_same_as_not_passing_it():
    a = g.check_hard_rules("Hiring at Gardens", _body(200), company_name="Gardens")
    b = g.check_hard_rules("Hiring at Gardens", _body(200), company_name="Gardens", max_authored_words=None)
    assert a == b


# --- Гейт: заданный лимит -----------------------------------------------------------------------

def test_raised_limit_lets_a_longer_body_through():
    issues = g.check_hard_rules(
        "Hiring at Gardens", _body(240), company_name="Gardens", max_authored_words=280,
    )
    assert not any("HARD RULE 4:" in i["detail"] for i in issues), issues


def test_raised_limit_still_catches_the_essay():
    issues = g.check_hard_rules(
        "Hiring at Gardens", _body(320), company_name="Gardens", max_authored_words=280,
    )
    assert any(
        "HARD RULE 4:" in i["detail"] and "under 280 words" in i["detail"] for i in issues
    ), issues


def test_lowered_limit_is_honored_too():
    issues = g.check_hard_rules(
        "Hiring at Gardens", _body(150), company_name="Gardens", max_authored_words=100,
    )
    assert any("under 100 words" in i["detail"] for i in issues), issues


# --- Резолвер из RunSetup -----------------------------------------------------------------------

class _RS:
    def __init__(self, value):
        self.max_authored_words = value


class _Run:
    def __init__(self, rs):
        self.run_setup = rs


def test_get_max_authored_words_reads_the_run_setup():
    assert get_max_authored_words(_Run(_RS(280))) == 280


def test_get_max_authored_words_is_none_when_unset_or_absurd():
    assert get_max_authored_words(_Run(_RS(None))) is None
    assert get_max_authored_words(_Run(_RS(0))) is None
    assert get_max_authored_words(_Run(_RS("не число"))) is None
    assert get_max_authored_words(_Run(None)) is None
    assert get_max_authored_words(None) is None


# --- Сквозная проводка через валидацию -----------------------------------------------------------

def test_validate_outbound_email_threads_the_limit(monkeypatch):
    """Письмо на 240 слов: с дефолтом — hard_rule_violation, с лимитом 280 — чисто."""
    import app.services.email_validation_service as evs
    import app.services.llm_gateway as gw

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(
        gw, "complete_prompt_json_object",
        lambda prompt, task_kind=None, cache_prefix=None: {
            "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
            "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
        },
    )
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])

    body = _body(240)
    strict = evs.validate_outbound_email(
        "Hiring at Gardens", body, {"vacancy_signals": None}, [],
        email_kind="vacancy", company_name="Gardens",
    )
    assert any(i["code"] == "hard_rule_violation" for i in strict["issues"]), strict["issues"]

    relaxed = evs.validate_outbound_email(
        "Hiring at Gardens", body, {"vacancy_signals": None}, [],
        email_kind="vacancy", company_name="Gardens", max_authored_words=280,
    )
    assert not any(i["code"] == "hard_rule_violation" for i in relaxed["issues"]), relaxed["issues"]
```

- [ ] **Шаг 2: Запустить тест — убедиться, что падает**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_max_authored_words.py -q
```

Ожидание: FAIL — `TypeError: check_hard_rules() got an unexpected keyword argument 'max_authored_words'`
и `ImportError: cannot import name 'get_max_authored_words'`.

- [ ] **Шаг 3: Параметризовать гейт**

В `backend/app/services/hard_rules_gate.py` заменить `_check_length` и сигнатуру `check_hard_rules`:

```python
def _check_length(paragraphs: list[str], max_words: int | None = None) -> list[dict[str, str]]:
    """HARD RULE 4. `max_words=None` — канон AlexStaff дословно (потолок 180, формулировка про
    целевые 120-140). Заданный лимит приходит из пресета кампании (run_setups.max_authored_words):
    формулировка тогда нейтральная — «120-140» это диапазон ПОД потолок 180, и переносить его на
    чужой потолок значило бы выдумать диапазон, которого кампания не задавала."""
    limit = _MAX_AUTHORED_WORDS if max_words is None else int(max_words)
    words = sum(len(p.split()) for p in paragraphs)
    if words <= limit:
        return []
    if max_words is None:
        return [_issue("4", f"the body you write is about 120-140 words in 3 short paragraphs — this one has {words}.")]
    return [_issue("4", f"the body you write must stay under {limit} words — this one has {words}.")]
```

И в `check_hard_rules`: добавить параметр и передать его вниз.

```python
def check_hard_rules(
    subject: str,
    body: str,
    *,
    company_name: str | None = None,
    fixed_blocks: list[str] | None = None,
    check_structure: bool = True,
    max_authored_words: int | None = None,
) -> list[dict[str, str]]:
```

В докстринге дописать абзац:

```
    `max_authored_words` is the campaign's own ceiling for HARD RULE 4 (run_setups.max_authored_words).
    None keeps the canon default (180) and its verbatim wording — a run that never sets the field
    behaves byte-for-byte as before.
```

В теле функции строку `issues += _check_length(paragraphs)` заменить на:

```python
        issues += _check_length(paragraphs, max_authored_words)
```

- [ ] **Шаг 4: Убедиться, что регресс гейта не сломан**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_email_validation_b063.py tests/test_hard_rules_gate_b273.py -q
```

Ожидание: PASS без правок — правка `_check_length` не затронула канонный путь.

Новый файл `test_max_authored_words.py` на этом шаге ещё НЕ собирается: `get_max_authored_words`
импортируется на уровне модуля и пока не существует, поэтому pytest даёт `ERROR collecting` по
всему файлу (частичного «5 из 8 PASS» не бывает — упавший импорт в начале файла валит его сбор
целиком, а без `--continue-on-collection-errors` обрывает и весь запуск). Поэтому файл в команду
выше не включён; он проверяется в шаге 10, после реализации резолвера. Второй файл в команде —
`test_email_validation_b063.py` — нужен не ради покрытия, а чтобы `test_hard_rules_gate_b273.py`
не шёл в процессе первым: в изоляции он падает на несвязанной pre-existing хрупкости
(строковый `relationship("TemplateVariable")` в `app/models/template.py` резолвится только если
класс уже импортирован). Это не дефект фазы.

- [ ] **Шаг 5: Добавить колонку в модель**

В `backend/app/models/run_setup.py` после `fit_exclusion_rules_text`:

```python
    # Фаза 2, Task 1 (решение D владельца 02.09): потолок авторской части письма для этой кампании
    # (HARD RULE 4, hard_rules_gate._check_length). NULL = канон AlexStaff дословно — 180 слов и
    # формулировка про целевые 120-140. Свойство ФОРМАТА кампании, не отправителя: одна и та же
    # персона ведёт рамку с одним решением (дефолт) и рамку-веер (повышенный лимит).
    max_authored_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Шаг 6: Добавить идемпотентную миграцию**

В `backend/app/init_db.py` — новая функция рядом с `_ensure_run_setups_fit_exclusion_rules_column`:

```python
def _ensure_run_setups_max_authored_words_column() -> None:
    """Фаза 2, Task 1: per-run потолок HARD RULE 4. NULL на всех существующих ранах = 180 дословно."""
    insp = inspect(engine)
    if "run_setups" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_setups")}
    if "max_authored_words" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE run_setups ADD COLUMN max_authored_words INTEGER"))
```

И вызов в `ensure_schema()` сразу после `_ensure_run_setups_fit_exclusion_rules_column()`:

```python
    _ensure_run_setups_max_authored_words_column()
```

- [ ] **Шаг 7: Добавить резолвер**

В `backend/app/services/run_context_service.py` после `get_critic_canon_text`:

```python
def get_max_authored_words(run) -> int | None:
    """Потолок авторской части письма для рана (`run_setups.max_authored_words`, Фаза 2 Task 1).

    None — поле не задано, битое или бессмысленное (<=0): вызывающий (validate_outbound_email)
    падает на канонный дефолт hard_rules_gate._MAX_AUTHORED_WORDS. Ран без пресета ведёт себя
    ровно как до появления поля."""
    rs = getattr(run, "run_setup", None)
    if rs is None:
        return None
    raw = getattr(rs, "max_authored_words", None)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
```

- [ ] **Шаг 8: Прокинуть лимит через валидацию**

В `backend/app/services/email_validation_service.py` — в сигнатуру `validate_outbound_email`
(после `company_name`):

```python
    max_authored_words: int | None = None,
```

В докстринг — абзац после описания `company_name`:

```
    max_authored_words (Фаза 2, Task 1): потолок HARD RULE 4 для этой кампании
    (run_context_service.get_max_authored_words). None = канонные 180 слов и их дословная
    формулировка — вызывающие, которые поле не прокидывают, сохраняют прежнее поведение.
```

И в вызов гейта (`:566`) добавить аргумент:

```python
    hard_rule_issues = check_hard_rules(
        subject or "",
        bod,
        company_name=(company_name or "").strip() or company_name_from_personalization(personalization),
        fixed_blocks=_fixed_finale_blocks_cached(persona),
        check_structure=not is_no_vacancy,
        max_authored_words=max_authored_words,
    )
```

- [ ] **Шаг 9: Прокинуть лимит из четырёх вызывающих**

В `backend/app/services/outreach_email_pipeline.py`:

1) Импорт (`:34-38`) — дописать имя в существующий блок:

```python
from app.services.run_context_service import (
    build_master_prompt_text,
    get_critic_canon_text,
    get_effective_context,
    get_max_authored_words,
)
```

2) Первый вызов (`:768`, после `critic_canon = get_critic_canon_text(run)`) — добавить строку
   до вызова и аргумент в вызов:

```python
    max_authored_words = get_max_authored_words(run)
    val = validate_outbound_email(
        subject, body, pers, peer_bodies, email_kind=email_kind, critic_canon=critic_canon,
        persona=persona, expected_finale_variants=expected_finale_variants,
        company_name=(contact.company or "").strip() or None,
        max_authored_words=max_authored_words,
    )
```

3) Вызов в retry-цикле (`:840`):

```python
        val = validate_outbound_email(
            subject, body, pers, peer_bodies, email_kind=email_kind, critic_canon=critic_canon,
            persona=persona, company_name=(contact.company or "").strip() or None,
            max_authored_words=max_authored_words,
        )
```

4) Вызов в `build_template_fallback_meta` (`:871`):

```python
    val = validate_outbound_email(
        subject, body, pers, peer_bodies,
        email_kind=email_kind_for(pers, persona), critic_canon=get_critic_canon_text(run),
        persona=persona, company_name=(contact.company or "").strip() or None,
        max_authored_words=get_max_authored_words(run),
    )
```

В `backend/app/api/email_drafts.py` — локальный импорт (`:356`) заменить на

```python
        from app.services.run_context_service import get_critic_canon_text, get_max_authored_words
```

— и дописать аргумент в вызов (`:369`):

```python
            val = validate_outbound_email(
                payload.subject, payload.body, pers, peers,
                email_kind=email_kind_for(pers, persona), critic_canon=get_critic_canon_text(run),
                persona=persona,
                company_name=(contact.company or "").strip() or None,
                max_authored_words=get_max_authored_words(run),
            )
```

- [ ] **Шаг 10: Прогнать тесты задачи и регресс**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_max_authored_words.py tests/test_hard_rules_gate_b273.py tests/test_email_validation_b063.py tests/test_email_validation_b077.py tests/test_persona_finale_regression.py tests/test_noda12_preset_seam.py -q
```

Ожидание: все PASS, ни одной правки в старых тестах.

- [ ] **Шаг 11: Коммит**

```bash
git add backend/app/models/run_setup.py backend/app/init_db.py backend/app/services/hard_rules_gate.py backend/app/services/run_context_service.py backend/app/services/email_validation_service.py backend/app/services/outreach_email_pipeline.py backend/app/api/email_drafts.py backend/tests/test_max_authored_words.py && git commit -m "feat(gate): per-run ceiling for HARD RULE 4 (NULL = 180 words verbatim)"
```

**Acceptance.** Восемь новых тестов зелёные; `test_hard_rules_gate_b273.py`,
`test_email_validation_b063.py`, `test_email_validation_b077.py`,
`test_persona_finale_regression.py` зелёные **без правок** (решения D и G).

---

## Task 2: Скоуп каталога программ по персоне

**Goal.** Программа каталога принадлежит персоне; матчер видит только программы персоны рана
плюс глобальные (NULL). Инстанс без персонных каталогов ведёт себя байт-в-байт как сегодня.

**Файлы.**
- Modify: `backend/app/models/training_program.py:36` (после `asset_id`)
- Modify: `backend/app/init_db.py` (новый `_ensure_*` + вызов)
- Modify: `backend/app/services/program_matcher.py:64-90`
- Modify: `backend/app/services/outreach_email_pipeline.py:556-598` (`_apply_program_match`)
- Modify: `backend/scripts/seed_noda12_preset.py` (`_seed_offers`, аргументы, докстринг)
- Test: `backend/tests/test_program_catalog_persona_scope.py` (новый)

- [ ] **Шаг 1: Написать падающий тест**

Создать `backend/tests/test_program_catalog_persona_scope.py`:

```python
"""Фаза 2, Task 2: каталог программ скоупится по персоне.

Семантика NULL — «виден всем»: инстанс партнёра, где persona_id ни у одной строки не проставлен,
получает тот же каталог, что и до фазы. Наши сидеры обязаны проставлять persona_id всегда —
иначе на одном инстансе матчер подставит FG-адресату сессию NODA12. 0 tokens: LLM застаблен."""

from __future__ import annotations

import app.services.program_matcher as pm
from app.models.persona import Persona
from app.models.training_program import TrainingProgram


def _two_personas(fresh_db):
    a = Persona(slug="scope-a", display_name="A")
    b = Persona(slug="scope-b", display_name="B")
    fresh_db.add_all([a, b])
    fresh_db.flush()
    return a, b


def _catalog(fresh_db, persona_a, persona_b):
    own = TrainingProgram(name="Своя программа", target_pains=["боль А"], bullets=["б"],
                          persona_id=persona_a.id)
    alien = TrainingProgram(name="Чужая программа", target_pains=["боль Б"], bullets=["б"],
                            persona_id=persona_b.id)
    shared = TrainingProgram(name="Общая программа", target_pains=["общая боль"], bullets=["б"],
                             persona_id=None)
    fresh_db.add_all([own, alien, shared])
    fresh_db.commit()
    return own, alien, shared


def _stub(monkeypatch, program_id):
    calls = {}

    def fake(prompt, task_kind=None):
        calls["prompt"] = prompt
        return {"program_id": program_id, "fit_score": 90, "solution_text": "S", "rationale": "r"}

    monkeypatch.setattr(pm, "complete_prompt_json_object", fake)
    return calls


def test_persona_sees_its_own_and_global_but_not_alien(fresh_db, monkeypatch):
    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    calls = _stub(monkeypatch, own.id)

    match = pm.match_program(fresh_db, problem="боль А", persona_id=a.id)

    assert match and match["program_id"] == own.id
    assert "Своя программа" in calls["prompt"]
    assert "Общая программа" in calls["prompt"]
    assert "Чужая программа" not in calls["prompt"]


def test_no_persona_id_keeps_the_whole_catalog(fresh_db, monkeypatch):
    """Фоллбэк: вызов без persona_id (партнёрский инстанс, прямые вызовы) видит весь каталог."""
    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    calls = _stub(monkeypatch, own.id)

    pm.match_program(fresh_db, problem="боль А")

    assert "Своя программа" in calls["prompt"]
    assert "Чужая программа" in calls["prompt"]
    assert "Общая программа" in calls["prompt"]


def test_alien_program_id_from_the_model_is_refused(fresh_db, monkeypatch):
    """Даже если LLM вернёт id вне выборки — матч не собирается (программа не найдена в списке)."""
    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    _stub(monkeypatch, alien.id)

    assert pm.match_program(fresh_db, problem="боль А", persona_id=a.id) is None


def test_pipeline_passes_the_run_persona_into_the_matcher(fresh_db, monkeypatch):
    """_apply_program_match резолвит персону рана сам — вызывающему пайплайну ничего не менять."""
    import app.services.outreach_email_pipeline as oep
    from app.repositories.project_repo import create_project
    from app.repositories.run_repo import create_run

    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    captured = {}

    def fake_match(db, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(pm, "match_program", fake_match)

    proj = create_project(fresh_db, name="ScopeTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = a.id
    fresh_db.commit()

    oep._apply_program_match(fresh_db, run, {"problem": "боль А"}, {})

    assert captured["persona_id"] == a.id


def test_seed_noda12_offers_stamp_the_persona(fresh_db):
    """Наш сидер обязан проставлять persona_id — включая повторный прогон по уже засеянным строкам."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_noda12_preset as seed

    legacy = TrainingProgram(name=seed.OFFERS[0]["name"], target_pains=["x"], bullets=["y"])
    fresh_db.add(legacy)
    fresh_db.commit()
    assert legacy.persona_id is None

    persona = seed._seed_persona_noda12(fresh_db)
    seed._seed_offers(fresh_db, persona_id=persona.id)
    fresh_db.commit()

    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == len(seed.OFFERS)  # существующая строка обновлена, не продублирована
    assert all(r.persona_id == persona.id for r in rows)
```

- [ ] **Шаг 2: Запустить тест — убедиться, что падает**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_program_catalog_persona_scope.py -q
```

Ожидание: FAIL — `TypeError: 'persona_id' is an invalid keyword argument for TrainingProgram`.

- [ ] **Шаг 3: Добавить колонку в модель**

В `backend/app/models/training_program.py` после `asset_id`:

```python
    # Фаза 2, Task 2: чей это каталог. NULL = «виден всем» — инстанс без персонных каталогов
    # (партнёрский) ведёт себя байт-в-байт как до фазы. Наши сидеры проставляют persona_id
    # ВСЕГДА: на одном инстансе с двумя кампаниями глобальная строка означала бы, что матчер
    # может подставить FG-адресату сессию NODA12.
    persona_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

- [ ] **Шаг 4: Добавить идемпотентную миграцию**

В `backend/app/init_db.py` рядом с прочими `_ensure_*`:

```python
def _ensure_training_programs_persona_id_column() -> None:
    """Фаза 2, Task 2: скоуп каталога по персоне. NULL на всех существующих строках = «виден всем»,
    поэтому доработка не меняет поведение инстанса, где персонных каталогов нет."""
    insp = inspect(engine)
    if "training_programs" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("training_programs")}
    if "persona_id" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE training_programs ADD COLUMN persona_id INTEGER"))
```

Вызов в `ensure_schema()` — сразу после `_ensure_personas_no_signal_template_column()`:

```python
    _ensure_training_programs_persona_id_column()
```

- [ ] **Шаг 5: Отфильтровать каталог в матчере**

В `backend/app/services/program_matcher.py`: добавить импорт `or_` из sqlalchemy —

```python
from sqlalchemy import or_
```

— в сигнатуру `match_program` (после `language`) добавить параметр:

```python
    persona_id: int | None = None,
```

— в докстринг дописать:

```
    persona_id (Фаза 2, Task 2): каталог сужается до программ ЭТОЙ персоны плюс глобальных
    (persona_id IS NULL). None = фильтр не применяется, виден весь каталог — поведение до фазы.
```

— и заменить выборку:

```python
        query = db.query(TrainingProgram).filter(TrainingProgram.status == "active")
        if persona_id is not None:
            query = query.filter(
                or_(TrainingProgram.persona_id == persona_id, TrainingProgram.persona_id.is_(None))
            )
        programs = query.order_by(TrainingProgram.id.asc()).all()
        if not programs:
            return None
```

- [ ] **Шаг 6: Резолвить персону рана в пайплайне**

В `backend/app/services/outreach_email_pipeline.py`, в `_apply_program_match` — после
`rs = getattr(run, "run_setup", None)` и перед вызовом `match_program`:

```python
        # Фаза 2, Task 2: матчер видит каталог персоны рана + глобальные строки (persona_id IS
        # NULL). Персона резолвится почти всегда — ран без persona_id падает на строку alexey, —
        # так что фильтр обычно ВКЛЮЧЁН, и неизменность поведения держится не на его отсутствии, а
        # на семантике NULL: пока каталог не размечен по персонам (инстанс партнёра), выборка
        # возвращает ровно те же строки. id=None бывает лишь у in-memory-фоллбэка alexey — когда
        # строки персоны нет в БД вовсе (юнит-вызовы без сидера).
        persona = get_run_persona(db, run)
        match = match_program(
            db,
            problem=problem,
            dossier=pers.get("osint_dossier") or "",
            person_osint=pers.get("person_osint"),
            vacancy_signals=pers.get("vacancy_signals"),
            language=getattr(rs, "language", "English"),
            persona_id=getattr(persona, "id", None),
        )
```

(`get_run_persona` в этом модуле уже импортирован — используется в `generate_email_draft`.)

- [ ] **Шаг 7: Научить сидер NODA12 штамповать персону**

В `backend/scripts/seed_noda12_preset.py`:

1) `_seed_offers` получает обязательный `persona_id`:

```python
def _seed_offers(db, persona_id: int) -> None:
    """Upsert каталога OFFERS (идемпотентно по name), со скоупом на персону NODA12.

    Фаза 2, Task 2: persona_id проставляется ВСЕГДА, в том числе на строках, засеянных до
    появления колонки — иначе на общем инстансе матчер сможет предложить сессию NODA12
    получателю FG-кампании."""
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
        row.persona_id = persona_id
    db.flush()
    print(f"Seeded {len(OFFERS)} offers for persona_id={persona_id}.")
```

2) В `main()` ветка `--seed-offers` теперь сначала гарантирует персону:

```python
        if args.seed_offers:
            persona = db.query(Persona).filter(Persona.slug == NODA12_SLUG).first()
            if persona is None:
                persona = _seed_persona_noda12(db)
            _seed_offers(db, persona_id=persona.id)
```

(Блок `if args.seed_persona_noda12:` остаётся как есть — он идемпотентен.)

3) В `--dry-run`-ветке строку про офферы заменить на:

```python
            if args.seed_offers:
                print(f"offers: would upsert {len(OFFERS)} rows for persona '{NODA12_SLUG}' (idempotent by name)")
```

4) В докстринге модуля строку «Global (training_programs has no project_id/run_id column) — seeding
   is opt-in via --seed-offers.» заменить на:

```
Каталог скоупится по персоне (training_programs.persona_id, Фаза 2 Task 2): строки этого сидера
принадлежат персоне "noda12", глобальные (NULL) остаются видны всем. Сеяние — opt-in через
--seed-offers; повторный прогон проставляет persona_id и на строках, засеянных до появления колонки.
```

- [ ] **Шаг 8: Прогнать тесты задачи и смежный регресс**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_program_catalog_persona_scope.py tests/test_program_matcher.py tests/test_pipeline_program_match.py tests/test_seed_noda12_preset.py -q
```

Ожидание: новые PASS. `test_seed_noda12_preset.py::test_seed_offers_creates_expected_count` и
`::test_seed_offers_idempotent_by_name` УПАДУТ — они вызывают `_seed_offers(fresh_db)` без
persona_id.

- [ ] **Шаг 9: Обновить два существующих теста сидера под новую сигнатуру**

В `backend/tests/test_seed_noda12_preset.py` заменить оба вызова `seed._seed_offers(fresh_db)` на
пару «персона → офферы» (правка тестов НАШЕЙ фазы 1, а не AlexStaff-регресса — решение G не
затронуто):

```python
def test_seed_offers_creates_expected_count(fresh_db):
    persona = seed._seed_persona_noda12(fresh_db)
    seed._seed_offers(fresh_db, persona_id=persona.id)
    fresh_db.commit()
    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == len(seed.OFFERS)
    names = {r.name for r in rows}
    assert "Пивная игра (bullwhip-эффект)" in names
    assert "SIR-волна (эпидемия как система)" in names
    assert "Карантинная честность (переговорная, 3 игрока)" in names


def test_seed_offers_idempotent_by_name(fresh_db):
    persona = seed._seed_persona_noda12(fresh_db)
    seed._seed_offers(fresh_db, persona_id=persona.id)
    fresh_db.commit()
    seed._seed_offers(fresh_db, persona_id=persona.id)
    fresh_db.commit()
    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == len(seed.OFFERS)
```

- [ ] **Шаг 10: Прогнать те же файлы ещё раз — всё зелёное**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_program_catalog_persona_scope.py tests/test_program_matcher.py tests/test_pipeline_program_match.py tests/test_seed_noda12_preset.py -q
```

Ожидание: все PASS.

- [ ] **Шаг 11: Коммит**

```bash
git add backend/app/models/training_program.py backend/app/init_db.py backend/app/services/program_matcher.py backend/app/services/outreach_email_pipeline.py backend/scripts/seed_noda12_preset.py backend/tests/test_program_catalog_persona_scope.py backend/tests/test_seed_noda12_preset.py && git commit -m "feat(catalog): scope training programs by persona (NULL = visible to all)"
```

**Acceptance.** Пять новых тестов зелёные; `test_program_matcher.py` и
`test_pipeline_program_match.py` зелёные **без правок**; ни одна строка каталога не видна чужой
персоне (гейт фазы, п. 5).

---

## Task 3: Per-run выключатель матчера программ

**Goal.** Рамка‑2 («веер программ») генерируется без вмешательства матчера — он не подменяет
`solution` и не тратит LLM-вызов. При NULL матчер работает как сегодня.

**Файлы.**
- Modify: `backend/app/models/run_setup.py` (после `max_authored_words`)
- Modify: `backend/app/init_db.py` (новый `_ensure_*` + вызов)
- Modify: `backend/app/services/outreach_email_pipeline.py:566-575` (начало `_apply_program_match`)
- Test: `backend/tests/test_program_match_toggle.py` (новый)

- [ ] **Шаг 1: Написать падающий тест**

Создать `backend/tests/test_program_match_toggle.py`:

```python
"""Фаза 2, Task 3: per-run выключатель матчера программ (run_setups.program_match_enabled).

Нужен Рамке-2 FG: письмо-веер само перечисляет программы отрасли из промпта, и подстановка
матчером ОДНОЙ программы в слот solution ломает формат. NULL/True = матчер работает, как до фазы.
0 tokens: matcher застаблен и при выключенном гейте не должен вызываться вовсе."""

from __future__ import annotations

import app.services.outreach_email_pipeline as oep
import app.services.program_matcher as pm


class _RS:
    def __init__(self, enabled):
        self.program_match_enabled = enabled
        self.language = "Russian"


class _Run:
    persona_id = None

    def __init__(self, rs):
        self.run_setup = rs


def _stub_matcher(monkeypatch):
    calls = {"n": 0}

    def fake(db, **kwargs):
        calls["n"] += 1
        return {"program_id": 1, "name": "П", "asset_id": None, "format": "f",
                "bullets": ["b"], "solution_text": "Решение матчера", "rationale": "r",
                "fit_score": 90}

    monkeypatch.setattr(pm, "match_program", fake)
    return calls


def test_disabled_skips_the_matcher_entirely(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    assert oep._apply_program_match(fresh_db, _Run(_RS(False)), reasoning, {}) is None
    assert calls["n"] == 0, "выключенный матчер не должен стоить ни одного LLM-вызова"
    assert reasoning["solution"] == "generic"


def test_null_keeps_the_matcher_on(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    match = oep._apply_program_match(fresh_db, _Run(_RS(None)), reasoning, {})

    assert calls["n"] == 1
    assert match and reasoning["solution"] == "Решение матчера"


def test_true_keeps_the_matcher_on(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    oep._apply_program_match(fresh_db, _Run(_RS(True)), reasoning, {})

    assert calls["n"] == 1


def test_run_without_setup_keeps_the_matcher_on(fresh_db, monkeypatch):
    calls = _stub_matcher(monkeypatch)
    reasoning = {"problem": "боль", "solution": "generic", "key_point": "generic"}

    oep._apply_program_match(fresh_db, _Run(None), reasoning, {})

    assert calls["n"] == 1
```

- [ ] **Шаг 2: Запустить тест — убедиться, что падает**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_program_match_toggle.py -q
```

Ожидание: FAIL на `test_disabled_skips_the_matcher_entirely` — матчер вызывается, `calls["n"] == 1`.

- [ ] **Шаг 3: Добавить колонку в модель**

В `backend/app/models/run_setup.py` после `max_authored_words`:

```python
    # Фаза 2, Task 3: работает ли матчер программ на этом ране. NULL/True = да (поведение до фазы).
    # False нужен рамке-«веер»: письмо само перечисляет программы отрасли из промпта, а матчер
    # подменил бы слот solution ОДНОЙ программой и сломал формат. Это выключатель, не порог —
    # PROGRAM_MATCH_MIN_FIT остаётся глобальным env.
    program_match_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

Импорт `Boolean` дописать в строку `from sqlalchemy import ...` того же файла.

- [ ] **Шаг 4: Добавить идемпотентную миграцию**

В `backend/app/init_db.py`:

```python
def _ensure_run_setups_program_match_column() -> None:
    """Фаза 2, Task 3: per-run выключатель матчера программ. NULL = матчер включён, как до фазы."""
    insp = inspect(engine)
    if "run_setups" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_setups")}
    if "program_match_enabled" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE run_setups ADD COLUMN program_match_enabled BOOLEAN"))
```

Вызов в `ensure_schema()` — после `_ensure_run_setups_max_authored_words_column()`:

```python
    _ensure_run_setups_program_match_column()
```

- [ ] **Шаг 5: Поставить гейт в пайплайне**

В `backend/app/services/outreach_email_pipeline.py`, в `_apply_program_match` — сразу после
`rs = getattr(run, "run_setup", None)` (и ДО вызова `match_program`):

```python
        # Фаза 2, Task 3: пресет может выключить матчер целиком (рамка-«веер» перечисляет
        # программы сама). Проверяем ДО импорта и вызова — выключенный матчер не стоит ни одного
        # LLM-вызова. Только явный False; NULL = включён.
        if rs is not None and getattr(rs, "program_match_enabled", None) is False:
            return None
```

Внимание: строка `from app.services.program_matcher import match_program` находится внутри
`try:` — гейт ставится перед ней, но внутри того же `try`, чтобы область видимости `rs`
сохранилась. Порядок строк в блоке: `rs = ...` → гейт → импорт → `persona = get_run_persona(...)`
→ `match = match_program(...)`.

- [ ] **Шаг 6: Прогнать тесты задачи и смежные**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_program_match_toggle.py tests/test_pipeline_program_match.py tests/test_program_catalog_persona_scope.py -q
```

Ожидание: все PASS.

- [ ] **Шаг 7: Коммит**

```bash
git add backend/app/models/run_setup.py backend/app/init_db.py backend/app/services/outreach_email_pipeline.py backend/tests/test_program_match_toggle.py && git commit -m "feat(pipeline): per-run program-matcher switch (NULL = on)"
```

**Acceptance.** Четыре теста зелёные; `test_pipeline_program_match.py` зелёный без правок.

---

## Task 4: XLSX-экспорт черновиков рана

**Goal.** Менеджеры FG получают файл, из которого письма рассылаются вручную: одна строка на
черновик, тело письма читаемо. Попутно чинится импорт XLSX, сломанный выпиливанием `openpyxl`.

**Файлы.**
- Modify: `backend/requirements.txt` (вернуть `openpyxl` пином)
- Modify: `.gitignore` (+ `backend/exports/`)
- Create: `backend/scripts/export_run_drafts.py`
- Test: `backend/tests/test_export_run_drafts.py` (новый)

- [ ] **Шаг 1: Вернуть openpyxl и зафиксировать реальную версию**

```bash
cd backend && venv/Scripts/python.exe -m pip install openpyxl && venv/Scripts/python.exe -m pip show openpyxl | grep -i "^Version"
```

Полученную версию дописать в `backend/requirements.txt` под строку `pandas==3.0.3`
(подставить реальный номер вместо `X.Y.Z`):

```
# Возвращён в Фазе 2 (Task 4): нужен и XLSX-экспорту черновиков (scripts/export_run_drafts.py),
# и уже существующему импорту CRM-выгрузки — app/api/import_crm.py:31 вызывает pd.read_excel,
# которому openpyxl нужен движком. Гигиена d289d1b выпилила пакет по числу ПРЯМЫХ импортов,
# из-за чего импорт .xlsx падал ImportError в чистом venv.
openpyxl==X.Y.Z
```

- [ ] **Шаг 2: Проверить, что импорт XLSX больше не падает**

```bash
cd backend && venv/Scripts/python.exe -c "import pandas as pd, io, openpyxl; print(openpyxl.__version__); print(pd.read_excel(io.BytesIO(open('../test_leads.xlsx','rb').read())).shape)"
```

Ожидание: печатается версия и размер таблицы, без `ImportError`.

- [ ] **Шаг 3: Написать падающий тест**

Создать `backend/tests/test_export_run_drafts.py`:

```python
"""Фаза 2, Task 4: XLSX-экспорт черновиков рана (экспортный канал FG, решение B владельца 02.09).

Движок для этого канала не отправляет: менеджеры FG рассылают со своих ящиков, читая этот файл.
Отсюда состав колонок и пустая колонка «Менеджер» (правило разбивки базы — вопрос Г6 к FG).
0 tokens: ни LLM, ни сети."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import export_run_drafts as export  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.email_draft import EmailDraft  # noqa: E402
from app.repositories.project_repo import create_project  # noqa: E402
from app.repositories.run_repo import create_run  # noqa: E402

BODY = (
    "Здравствуйте, Мария!\n\n"
    "Первый абзац письма.\n\n"
    "Второй абзац письма."
)


def _run_with_drafts(fresh_db, count: int):
    proj = create_project(fresh_db, name="ExportTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    for i in range(count):
        contact = Contact(run_id=run.id, name=f"Контакт {i}", role="Директор по персоналу",
                          email=f"c{i}@example.com", company=f"Компания {i}", source_json={})
        fresh_db.add(contact)
        fresh_db.flush()
        fresh_db.add(EmailDraft(
            run_id=run.id, contact_id=contact.id, company=contact.company,
            to_email=contact.email, subject=f"Тема {i}", body=BODY,
        ))
    fresh_db.commit()
    return run


def test_collect_rows_returns_one_row_per_draft(fresh_db):
    run = _run_with_drafts(fresh_db, 3)
    rows = export.collect_rows(fresh_db, run.id)
    assert len(rows) == 3
    assert [r["company"] for r in rows] == ["Компания 0", "Компания 1", "Компания 2"]
    assert rows[0]["contact"] == "Контакт 0"
    assert rows[0]["email"] == "c0@example.com"
    assert rows[0]["role"] == "Директор по персоналу"
    assert rows[0]["subject"] == "Тема 0"
    assert rows[0]["body"] == BODY
    assert rows[0]["manager"] == ""  # правило разбивки ждёт ответа FG на Г6


def test_collect_rows_survives_a_missing_contact(fresh_db):
    """Черновик денормализует company/to_email — строка выгружается даже без строки контакта."""
    run = _run_with_drafts(fresh_db, 1)
    draft = fresh_db.query(EmailDraft).filter(EmailDraft.run_id == run.id).one()
    fresh_db.delete(fresh_db.get(Contact, draft.contact_id))
    fresh_db.commit()

    rows = export.collect_rows(fresh_db, run.id)
    assert len(rows) == 1
    assert rows[0]["company"] == "Компания 0"
    assert rows[0]["contact"] == ""
    assert rows[0]["role"] == ""


def test_write_xlsx_opens_and_has_header_and_all_rows(fresh_db, tmp_path):
    import openpyxl

    run = _run_with_drafts(fresh_db, 4)
    rows = export.collect_rows(fresh_db, run.id)
    out = tmp_path / "run.xlsx"

    export.write_xlsx(rows, out)

    wb = openpyxl.load_workbook(out)
    ws = wb.active
    assert [c.value for c in ws[1]] == export.HEADER
    assert ws.max_row == len(rows) + 1  # шапка + по строке на черновик
    assert ws.cell(row=2, column=export.HEADER.index("Компания") + 1).value == "Компания 0"
    body_cell = ws.cell(row=2, column=export.HEADER.index("Тело письма") + 1)
    assert body_cell.value == BODY
    assert body_cell.alignment.wrap_text is True


def test_empty_run_writes_header_only(fresh_db, tmp_path):
    import openpyxl

    proj = create_project(fresh_db, name="ExportEmpty", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    fresh_db.commit()
    out = tmp_path / "empty.xlsx"

    export.write_xlsx(export.collect_rows(fresh_db, run.id), out)

    ws = openpyxl.load_workbook(out).active
    assert ws.max_row == 1
```

- [ ] **Шаг 4: Запустить тест — убедиться, что падает**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_export_run_drafts.py -q
```

Ожидание: FAIL — `ModuleNotFoundError: No module named 'export_run_drafts'`.

- [ ] **Шаг 5: Написать скрипт экспорта**

Создать `backend/scripts/export_run_drafts.py`:

```python
"""Выгрузка черновиков рана в XLSX для ручной рассылки менеджерами (Фаза 2, Task 4).

Экспортный канал FG (решение B владельца 02.09.2026): движок ГЕНЕРИРУЕТ письма, а отправляют их
менеджеры FG вручную со своих ящиков по существующей базе клиента. Поэтому:

- черновики НЕ аппрувятся (approve в UI = автопостановка в очередь отправки) — выгружаются как
  есть, в том состоянии, в каком их оставило ревью;
- в теле письма нет подписи: она клеится при отправке из run_setups.sender_signature_html, а у
  FG-ранов это поле пустое (что заодно физически блокирует отправку —
  email_sender.validate_outbound_draft_sendable);
- колонка «Менеджер» выгружается пустой: правило разбивки базы между менеджерами — открытый
  вопрос Г6 к FG. Заполняется вручную в файле.

XLSX (не CSV): адресат — менеджеры, им нужен файл, который открывается двойным кликом, с
переносом строк в теле письма. openpyxl напрямую, без pandas: нужен контроль ширины колонок и
wrap_text.

Usage:
    cd backend && venv/Scripts/python.exe scripts/export_run_drafts.py --run-id 7
    cd backend && venv/Scripts/python.exe scripts/export_run_drafts.py --run-id 7 --out C:/tmp/fg.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.init_db import ensure_schema  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.email_draft import EmailDraft  # noqa: E402
from app.models.run import Run  # noqa: E402

HEADER: list[str] = [
    "ID черновика", "Компания", "Контакт", "Должность", "Email", "Тема", "Тело письма", "Менеджер",
]

# Ширины под HEADER; тело письма — широкая колонка с переносом.
_COLUMN_WIDTHS: tuple[int, ...] = (12, 28, 22, 24, 30, 44, 90, 18)
_BODY_COLUMN = HEADER.index("Тело письма") + 1


def collect_rows(db, run_id: int) -> list[dict]:
    """Черновики рана в порядке id. company/to_email берём из самого черновика (он их
    денормализует при создании — email_draft_repo.create_email_draft), должность и имя — из
    контакта, если строка контакта ещё жива."""
    drafts = (
        db.query(EmailDraft)
        .filter(EmailDraft.run_id == run_id)
        .order_by(EmailDraft.id.asc())
        .all()
    )
    rows: list[dict] = []
    for draft in drafts:
        contact = db.get(Contact, draft.contact_id) if draft.contact_id else None
        rows.append(
            {
                "draft_id": draft.id,
                "company": (draft.company or getattr(contact, "company", None) or "").strip(),
                "contact": (getattr(contact, "name", None) or "").strip(),
                "role": (getattr(contact, "role", None) or "").strip(),
                "email": (draft.to_email or getattr(contact, "email", None) or "").strip(),
                "subject": (draft.subject or "").strip(),
                "body": (draft.body or "").strip(),
                "manager": "",
            }
        )
    return rows


def write_xlsx(rows: list[dict], path: Path) -> Path:
    """Один лист: шапка + по строке на черновик. Возвращает путь записанного файла."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Черновики"

    ws.append(HEADER)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for row in rows:
        ws.append([
            row["draft_id"], row["company"], row["contact"], row["role"],
            row["email"], row["subject"], row["body"], row["manager"],
        ])

    for index, width in enumerate(_COLUMN_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=index).column_letter].width = width
    for excel_row in range(2, len(rows) + 2):
        ws.cell(row=excel_row, column=_BODY_COLUMN).alignment = Alignment(
            wrap_text=True, vertical="top",
        )

    ws.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Выгрузить черновики рана в XLSX для ручной рассылки.")
    ap.add_argument("--run-id", type=int, required=True, help="Ран, чьи черновики выгружаем.")
    ap.add_argument(
        "--out", type=str, default=None,
        help="Путь к файлу. По умолчанию backend/exports/run_<id>_drafts.xlsx.",
    )
    args = ap.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == args.run_id).first()
        if not run:
            print(f"Run id={args.run_id} not found.", file=sys.stderr)
            sys.exit(1)

        rows = collect_rows(db, run.id)
        out = Path(args.out) if args.out else (
            Path(__file__).resolve().parents[1] / "exports" / f"run_{run.id}_drafts.xlsx"
        )
        write_xlsx(rows, out)
        print(f"Exported {len(rows)} draft(s) of run_id={run.id} ({run.name!r}) -> {out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 6: Прогнать тест экспорта**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_export_run_drafts.py -q
```

Ожидание: 4 PASS.

- [ ] **Шаг 7: Не тащить выгрузки в git**

В корневой `.gitignore` в блок «Local DB / runtime» дописать:

```
# Выгрузки черновиков для менеджеров (Фаза 2, Task 4) — рабочие файлы, не артефакты репозитория
backend/exports/
```

- [ ] **Шаг 8: Коммит**

```bash
git add backend/requirements.txt backend/scripts/export_run_drafts.py backend/tests/test_export_run_drafts.py .gitignore && git commit -m "feat(export): XLSX export of run drafts for manual sending; restore openpyxl"
```

**Acceptance.** Четыре теста зелёные; `pd.read_excel` из шага 2 отрабатывает; файл открывается
в Excel, тело письма читаемо (перенос строк), число строк = числу черновиков рана.

---

## Task 5: `seed_fg_preset.py` — персона FG и матрица «отрасль × рамка»

**Goal.** Пресет FG воспроизводится одной командой на любом ране: персона `fg`, канон рамки,
отраслевой блок. Пока реального контента FG нет — сидер пишет помеченные плейсхолдеры и
отказывается это делать без явного согласия.

**Файлы.**
- Modify: `backend/app/services/persona_service.py` (после блока NODA12 — константы FG и
  `fg_persona_kwargs()`)
- Create: `backend/scripts/seed_fg_preset.py`
- Test: `backend/tests/test_seed_fg_preset.py` (новый)

- [ ] **Шаг 1: Написать падающий тест**

Создать `backend/tests/test_seed_fg_preset.py`:

```python
"""Фаза 2, Task 5: пресет FG — персона + матрица «отрасль × рамка».

Рамки (решение C владельца 02.09): Рамка-1 «ревю отрасли + у вас на предприятии → одно решение»
(матчер работает, лимит дефолтный); Рамка-2 «ревю отрасли → веер программ» (матчер выключен,
лимит повышен). Контента FG ещё нет — сидер обязан помечать плейсхолдеры и не писать их в ран
без явного --allow-placeholders (урок noda12: не сеять несуществующий контент). 0 tokens."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_fg_preset as seed  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.models.training_program import TrainingProgram  # noqa: E402
from app.services.persona_service import FG_SLUG  # noqa: E402


# --- Персона ------------------------------------------------------------------------------------

def test_seed_persona_fg_creates_row(fresh_db):
    persona = seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    assert persona.slug == FG_SLUG
    assert persona.no_signal_template_enabled is False  # у FG нет рекрутингового §2.3-шаблона
    assert persona.languages_json == ["Russian"]


def test_seed_persona_fg_idempotent(fresh_db):
    seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    assert fresh_db.query(Persona).filter(Persona.slug == FG_SLUG).count() == 1


# --- Матрица «отрасль × рамка» --------------------------------------------------------------------

def test_frames_differ_in_matcher_and_limit():
    _, scalar1 = seed.canon_fields("metallurgy", frame=1)
    _, scalar2 = seed.canon_fields("metallurgy", frame=2)

    assert scalar1["program_match_enabled"] is True
    assert scalar1["max_authored_words"] is None  # дефолт движка, решение D

    assert scalar2["program_match_enabled"] is False
    assert scalar2["max_authored_words"] == seed.FRAME2_MAX_WORDS


def test_frames_carry_different_draft_prompts():
    text1, _ = seed.canon_fields("metallurgy", frame=1)
    text2, _ = seed.canon_fields("metallurgy", frame=2)
    assert text1["draft_prompt"] != text2["draft_prompt"]
    assert "ОДНО решение" in text1["draft_prompt"]
    assert "веер программ" in text2["draft_prompt"].lower()


def test_both_frames_gate_the_minihook_on_a_strong_occasion():
    """Решение E: личный минихук — только при ярком недавнем поводе, и только из промпта пресета."""
    for frame in (1, 2):
        text, _ = seed.canon_fields("metallurgy", frame=frame)
        prompt = text["draft_prompt"].lower()
        assert "минихук" in prompt and "только при ярком недавнем поводе" in prompt


def test_industry_appears_in_the_prompt_setup():
    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert "metallurgy" in text["prompt_setup_text"]


def test_signature_is_empty_for_the_export_channel():
    """Решение B/O: письма шлют менеджеры со своих ящиков; пустая подпись ещё и блокирует отправку
    движком (email_sender.validate_outbound_draft_sendable)."""
    for frame in (1, 2):
        text, _ = seed.canon_fields("metallurgy", frame=frame)
        assert text["sender_signature_html"] == ""


def test_default_fit_exclusion_rules_are_kept():
    """У FG покупатель — предприятие отрасли, конкурент — другой провайдер обучения: дефолт верен."""
    from app.services.run_company_ai_fit_service import DEFAULT_FIT_EXCLUSION_RULES

    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert text["fit_exclusion_rules_text"] == DEFAULT_FIT_EXCLUSION_RULES


# --- Защита от плейсхолдеров -----------------------------------------------------------------------

def test_unknown_industry_is_flagged_as_placeholder():
    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert seed.PLACEHOLDER_MARKER in text["prompt_setup_text"]
    assert seed.has_placeholders(text) is True


def test_known_industry_has_no_placeholders(monkeypatch):
    monkeypatch.setitem(seed.INDUSTRY_CONTENT, "metallurgy", {
        "label": "Металлургия",
        "review": "Реальное ревю отрасли от FG.",
        "programs": [{"name": "Программа 1", "pitch": "Одно предложение о сути."}],
    })
    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert seed.PLACEHOLDER_MARKER not in text["prompt_setup_text"]
    assert seed.has_placeholders(text) is False


def test_apply_refuses_placeholders_without_the_flag(fresh_db):
    from app.repositories.project_repo import create_project
    from app.repositories.run_repo import create_run

    proj = create_project(fresh_db, name="FGGuard", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    fresh_db.commit()

    with pytest.raises(SystemExit):
        seed.apply_canon(fresh_db, run, "metallurgy", frame=1, allow_placeholders=False)

    from app.models.run_setup import RunSetup

    assert fresh_db.query(RunSetup).filter(RunSetup.run_id == run.id).first() is None


def test_apply_writes_when_placeholders_are_allowed(fresh_db):
    from app.models.run_setup import RunSetup
    from app.repositories.project_repo import create_project
    from app.repositories.run_repo import create_run

    proj = create_project(fresh_db, name="FGWrite", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    fresh_db.commit()

    seed.apply_canon(fresh_db, run, "metallurgy", frame=2, allow_placeholders=True)
    fresh_db.commit()

    setup = fresh_db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
    assert setup is not None
    assert setup.language == "Russian"
    assert setup.program_match_enabled is False
    assert setup.max_authored_words == seed.FRAME2_MAX_WORDS
    assert setup.sender_signature_html == ""


# --- Каталог программ FG ---------------------------------------------------------------------------

def test_seed_offers_scopes_programs_to_the_fg_persona(fresh_db, monkeypatch):
    monkeypatch.setitem(seed.INDUSTRY_CONTENT, "metallurgy", {
        "label": "Металлургия",
        "review": "Реальное ревю.",
        "programs": [{"name": "Программа 1", "pitch": "Суть."},
                     {"name": "Программа 2", "pitch": "Суть."}],
    })
    persona = seed._seed_persona_fg(fresh_db)
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    fresh_db.commit()

    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == 2
    assert all(r.persona_id == persona.id for r in rows)


def test_seed_offers_is_idempotent(fresh_db, monkeypatch):
    monkeypatch.setitem(seed.INDUSTRY_CONTENT, "metallurgy", {
        "label": "Металлургия", "review": "Ревю.",
        "programs": [{"name": "Программа 1", "pitch": "Суть."}],
    })
    persona = seed._seed_persona_fg(fresh_db)
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    fresh_db.commit()
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    fresh_db.commit()
    assert fresh_db.query(TrainingProgram).count() == 1
```

- [ ] **Шаг 2: Запустить тест — убедиться, что падает**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_seed_fg_preset.py -q
```

Ожидание: FAIL — `ModuleNotFoundError: No module named 'seed_fg_preset'`.

- [ ] **Шаг 3: Добавить персону FG в `persona_service.py`**

В конец `backend/app/services/persona_service.py` (после блока NODA12, перед
`_default_alexey_persona`), и `FG_SLUG = "fg"` — к списку слагов вверху файла:

```python
# --- FG-Consulting persona (Фаза 2, Task 5): экспортный канал — движок ГЕНЕРИРУЕТ письма, а
# менеджеры FG рассылают их вручную со своих ящиков (решение B владельца 02.09.2026). Отсюда две
# особенности против остальных персон: подпись пустая (её клеит менеджер в своём почтовом клиенте,
# а пустая подпись рана заодно блокирует отправку движком — email_sender.
# validate_outbound_draft_sendable) и primary_mailbox_email отсутствует (ящика у персоны нет).
# no_signal_template_enabled=False — у FG нет рекрутингового §2.3-шаблона, тот же механизм, что у
# noda12. RU-only, один гео-сегмент: кампания идёт по российской базе клиента. ---

FG_GEO_MAP_JSON: dict[str, Any] = {
    "default_segment": "default",
    "cyprus_no_city_segment": None,
    "cyprus_keywords": [],
    "city_segments": {},
    "ex_cis_keywords": [],
    "address_context_keywords": [],
    "negation_context_keywords": [],
    "modifiers": {},
}

# Маркер незаполненного контента FG. Виден и в теле письма, и в дифе сидера — черновик с ним
# нельзя перепутать с готовым к отправке (см. seed_fg_preset.PLACEHOLDER_MARKER).
FG_CONTENT_PENDING = "[FG-CONTENT PENDING]"

# Финальный абзац: CTA = 15-минутный звонок (Г4 подтверждён владельцем 02.09), но ДОСЛОВНЫЙ текст
# ждёт ответа FG на Г5 — поэтому здесь помеченный плейсхолдер, а не выдуманная формулировка.
# Абзац приклеивается к телу в коде и проверяется байт-гейтом (B-158), так что маркер физически
# виден в каждом черновике, пока текст не заменён.
FG_FINALES_JSON: dict[str, Any] = {
    "segments": {
        "default": {
            "label": "Россия (RU)",
            "prompt_ordinal": 1,
            "variants": {
                "ru": (
                    f"{FG_CONTENT_PENDING} Закрывающий абзац FG: приглашение на 15-минутный звонок "
                    "(вопрос Г5 — дословная формулировка за клиентом)."
                ),
            },
        },
    },
    "fallbacks": {},
}

FG_SLUG_DISPLAY_NAME = "FG Consulting"


def fg_persona_kwargs() -> dict[str, Any]:
    """Значения полей персоны "fg" — используются seed_fg_preset.py для upsert строки в БД.

    signature_html пустая намеренно (экспортный канал, решение B/O); primary_mailbox_email — None:
    у персоны нет своего ящика, письма уходят из почтовых клиентов менеджеров FG."""
    return {
        "slug": FG_SLUG,
        "display_name": FG_SLUG_DISPLAY_NAME,
        "self_intro": "FG-Consulting: отраслевые программы обучения и развития для предприятий.",
        "signature_html": "",
        "timezone": "Europe/Moscow",
        "languages_json": ["Russian"],
        "geo_map_json": FG_GEO_MAP_JSON,
        "finales_json": FG_FINALES_JSON,
        "proof_anchors_json": None,
        "primary_mailbox_email": None,
        "no_signal_template_enabled": False,
    }
```

- [ ] **Шаг 4: Написать сидер FG**

Создать `backend/scripts/seed_fg_preset.py`:

```python
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

КОНТЕНТА FG ЕЩЁ НЕТ. INDUSTRY_CONTENT пуст: отраслевые ревю и списки программ у клиента в
проработке. Неизвестный slug собирает пресет с плейсхолдерами, помеченными PLACEHOLDER_MARKER, и
такой прогон требует явного --allow-placeholders — защита от утечки болванок в письма реальным
людям (прецедент noda12: 6 честных сессий вместо 16 заявленных). Контент вливается позже
добавлением ключей в INDUSTRY_CONTENT, без правок механики.

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

# Отраслевой контент FG. ПУСТ до получения материалов клиента: ключ — slug отрасли, значение —
# {"label": <название по-русски>, "review": <короткое ревю ситуации>, "programs": [{"name", "pitch"}]}.
# Пополняется отдельным шагом по мере ответов FG (вопросы Б/Г5) — механика сидера при этом не меняется.
INDUSTRY_CONTENT: dict[str, dict] = {}

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
        row.target_pains = [f"отраслевая ситуация: {industry}"]
        row.audience = "руководители предприятий отрасли и их HR/T&D"
        row.format = "программа обучения FG-Consulting"
        row.bullets = [program["pitch"]]
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
```

- [ ] **Шаг 5: Прогнать тесты задачи**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_seed_fg_preset.py -q
```

Ожидание: 14 PASS.

- [ ] **Шаг 6: Проверить сидер вживую на dry-run**

```bash
cd backend && venv/Scripts/python.exe scripts/seed_fg_preset.py --run-id 1 --industry metallurgy --frame 2 --dry-run
```

Ожидание: печатается `placeholders=True`, диф полей, «Dry run; no changes.» Если рана id=1 в
локальной БД нет — вывод `Run id=1 not found.` и код 1, что тоже корректная проверка ветки.

- [ ] **Шаг 7: Коммит**

```bash
git add backend/app/services/persona_service.py backend/scripts/seed_fg_preset.py backend/tests/test_seed_fg_preset.py && git commit -m "feat(fg): FG persona + industry x frame preset seeder with placeholder guard"
```

**Acceptance.** 14 тестов зелёные; сидер отказывается писать плейсхолдеры без флага; персона FG
идемпотентна; каталог FG скоупится на её persona_id.

---

## Task 6: Сквозной смок обеих рамок на `fresh_db`

**Goal.** Доказать, что Tasks 1+2+3+5 сомкнулись: рамка‑1 генерит письмо с программой от матчера
в дефолтный лимит, рамка‑2 — письмо-веер без матчера под повышенный лимит; оба проходят
`hard_rules_gate` и получают оценку рубрики.

**Файлы.**
- Test: `backend/tests/test_fg_frames_seam.py` (новый)

- [ ] **Шаг 1: Написать смок-тест**

Создать `backend/tests/test_fg_frames_seam.py`:

```python
"""ПРИЁМКА Фазы 2 (гейт фазы, п. 3): обе рамки FG проходят пайплайн на чистой БД.

Смыкает четыре задачи фазы: настраиваемый лимит (Task 1), скоуп каталога по персоне (Task 2),
выключатель матчера (Task 3) и пресет FG (Task 5). Рамка-1 — письмо с ОДНИМ решением от матчера
в дефолтный лимит; рамка-2 — письмо-веер, матчер не вызывается, потолок FRAME2_MAX_WORDS.
0 tokens: generate_json, матчер и критик застаблены."""

from __future__ import annotations

import importlib
import pkgutil

import app.models as _models_pkg

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_fg_preset as seed  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.repositories.project_repo import create_project  # noqa: E402
from app.repositories.run_repo import create_run, get_run  # noqa: E402
from app.services.persona_service import FG_FINALES_JSON, fg_persona_kwargs  # noqa: E402

FG_RU_FINALE = FG_FINALES_JSON["segments"]["default"]["variants"]["ru"]

# Авторская часть рамки-1: ~60 слов, укладывается в канонные 180.
FRAME1_BODY = (
    "Здравствуйте, Мария!\n\n"
    "В отрасли сейчас заметно тянут сроки переделов: смены сдают партии неровно, "
    "и планирование едет.\n\n"
    "У вас на предприятии это обычно видно по простоям на стыке участков. Мы собираем "
    "разбор таких стыков с линейными руководителями за один день и даём им общий язык "
    "для планирования смен."
)

# Авторская часть рамки-2: ~240 слов — больше канонных 180, но меньше FRAME2_MAX_WORDS=280.
FRAME2_BODY = (
    "Здравствуйте, Мария!\n\n"
    "В отрасли сейчас заметно тянут сроки переделов, и планирование едет следом.\n\n"
    + " ".join(["слово"] * 225)
)


def _fg_run(fresh_db, frame: int):
    persona = seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    proj = create_project(fresh_db, name=f"FGSeam{frame}", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = persona.id
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    seed.apply_canon(fresh_db, run, "metallurgy", frame=frame, allow_placeholders=True)
    fresh_db.commit()
    run = get_run(fresh_db, run.id)
    contact = Contact(run_id=run.id, name="Мария", email="maria@fg-seam.example.com",
                      company="Комбинат", role="Директор по персоналу", source_json={})
    fresh_db.add(contact)
    fresh_db.commit()
    return run, contact, persona


def _stub_critic(monkeypatch):
    import app.services.email_validation_service as evs
    import app.services.llm_gateway as gw

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(
        gw, "complete_prompt_json_object",
        lambda prompt, task_kind=None, cache_prefix=None: {
            "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
            "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
        },
    )
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])


def test_frame1_uses_the_matcher_and_the_default_limit(fresh_db, monkeypatch):
    import app.services.outreach_email_pipeline as pipeline
    import app.services.program_matcher as pm

    run, contact, persona = _fg_run(fresh_db, frame=1)
    calls = {"matcher": 0}

    def fake_match(db, **kwargs):
        calls["matcher"] += 1
        calls["persona_id"] = kwargs.get("persona_id")
        return {"program_id": 1, "name": "П", "asset_id": None, "format": "f", "bullets": ["b"],
                "solution_text": "Разбор стыков участков за один день", "rationale": "r",
                "fit_score": 90}

    monkeypatch.setattr(pm, "match_program", fake_match)
    captured = {}

    def fake_generate_json(prompt, task_kind=None, cache_prefix=None):
        captured["prompt"] = (cache_prefix or "") + prompt
        return {"subject": "Планирование смен на Комбинате", "body": FRAME1_BODY}

    monkeypatch.setattr(pipeline, "generate_json", fake_generate_json)

    reasoning = {"hook": "", "angle": "", "problem": "простои на стыках", "solution": "generic",
                 "cta_type": "", "key_point": "generic"}
    match = pipeline._apply_program_match(fresh_db, run, reasoning, {})
    _subject, body = pipeline.generate_email_draft(
        fresh_db, run, contact, reasoning,
        prompt_setup_text=run.run_setup.prompt_setup_text, master_variant=None,
        style_mode="default", pers={"vacancy_signals": None}, finale_variant_index=0,
    )

    assert calls["matcher"] == 1
    assert calls["persona_id"] == persona.id  # каталог сужен до персоны FG (Task 2)
    assert match and reasoning["solution"] == "Разбор стыков участков за один день"
    assert "ОДНО решение" in captured["prompt"]  # draft_prompt рамки-1 доехал до генерации
    assert "AlexStaff" not in captured["prompt"]
    assert body.endswith(FG_RU_FINALE)


def test_frame1_letter_passes_the_gate_and_gets_a_rubric_score(fresh_db, monkeypatch):
    import app.services.email_validation_service as evs

    _stub_critic(monkeypatch)
    persona = Persona(**fg_persona_kwargs())
    body = f"{FRAME1_BODY}\n\n{FG_RU_FINALE}"

    result = evs.validate_outbound_email(
        "Планирование смен на Комбинате", body, {"vacancy_signals": None}, [],
        persona=persona, expected_finale_variants=[FG_RU_FINALE], company_name="Комбинат",
    )

    codes = [i["code"] for i in result["issues"]]
    assert "hard_rule_violation" not in codes, result["issues"]
    assert "no_vacancy_template_drift" not in codes, codes
    assert result["critic_taste_pass"] is True
    assert result["is_valid"] is True, result["issues"]


def test_frame2_skips_the_matcher(fresh_db, monkeypatch):
    import app.services.outreach_email_pipeline as pipeline
    import app.services.program_matcher as pm

    run, _contact, _ = _fg_run(fresh_db, frame=2)
    calls = {"matcher": 0}

    def fake_match(db, **kwargs):
        calls["matcher"] += 1
        return None

    monkeypatch.setattr(pm, "match_program", fake_match)
    reasoning = {"problem": "простои на стыках", "solution": "generic", "key_point": "generic"}

    assert pipeline._apply_program_match(fresh_db, run, reasoning, {}) is None
    assert calls["matcher"] == 0
    assert reasoning["solution"] == "generic"


def test_frame2_long_letter_passes_only_under_the_raised_limit(fresh_db, monkeypatch):
    """То же тело: под каноном движка — нарушение HARD RULE 4, под лимитом рамки-2 — чисто."""
    import app.services.email_validation_service as evs
    from app.services.run_context_service import get_max_authored_words

    _stub_critic(monkeypatch)
    run, _contact, _ = _fg_run(fresh_db, frame=2)
    persona = Persona(**fg_persona_kwargs())
    body = f"{FRAME2_BODY}\n\n{FG_RU_FINALE}"

    assert get_max_authored_words(run) == seed.FRAME2_MAX_WORDS

    strict = evs.validate_outbound_email(
        "Программы для Комбината", body, {"vacancy_signals": None}, [],
        persona=persona, expected_finale_variants=[FG_RU_FINALE], company_name="Комбинат",
    )
    assert any(i["code"] == "hard_rule_violation" for i in strict["issues"])

    relaxed = evs.validate_outbound_email(
        "Программы для Комбината", body, {"vacancy_signals": None}, [],
        persona=persona, expected_finale_variants=[FG_RU_FINALE], company_name="Комбинат",
        max_authored_words=get_max_authored_words(run),
    )
    assert not any(i["code"] == "hard_rule_violation" for i in relaxed["issues"]), relaxed["issues"]
    assert relaxed["is_valid"] is True, relaxed["issues"]


def test_fg_run_cannot_send_anything(fresh_db):
    """Гейт фазы, п. 5: пустая подпись FG-рана физически блокирует отправку."""
    from app.services.run_context_service import get_sender_signature_html

    run, _contact, _ = _fg_run(fresh_db, frame=1)
    assert (get_sender_signature_html(run) or "").strip() == ""


def test_fg_catalog_is_invisible_to_another_persona(fresh_db, monkeypatch):
    """Гейт фазы, п. 5: программа FG не попадает в каталог чужой персоны (а глобальная — попадает)."""
    import app.services.program_matcher as pm
    from app.models.training_program import TrainingProgram

    _run, _contact, _fg_persona = _fg_run(fresh_db, frame=1)
    other = Persona(slug="other-seam", display_name="Other")
    fresh_db.add(other)
    # Глобальная строка нужна, чтобы выборка чужой персоны была НЕпустой: на пустом каталоге
    # match_program возвращает None до LLM-вызова, и тест доказывал бы не то.
    fresh_db.add(TrainingProgram(name="Глобальная программа", target_pains=["боль"],
                                 bullets=["б"], persona_id=None))
    fresh_db.commit()

    captured = {}

    def fake_llm(prompt, task_kind=None):
        captured["prompt"] = prompt
        return {"program_id": None, "fit_score": 0, "solution_text": "", "rationale": ""}

    monkeypatch.setattr(pm, "complete_prompt_json_object", fake_llm)
    pm.match_program(fresh_db, problem="любая боль", persona_id=other.id)

    assert "Глобальная программа" in captured["prompt"]
    assert seed.PLACEHOLDER_MARKER not in captured["prompt"]
```

- [ ] **Шаг 2: Прогнать смок**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_fg_frames_seam.py -q
```

Ожидание: 6 PASS. Если `test_frame2_long_letter_passes_only_under_the_raised_limit` падает на
первом ассерте — подсчитать слова в `FRAME2_BODY` (`len(" ".join(...).split())`) и подогнать
длину: авторская часть должна быть строго между 180 и 280 словами.

- [ ] **Шаг 3: Коммит**

```bash
git add backend/tests/test_fg_frames_seam.py && git commit -m "test(fg): end-to-end smoke of both FG frames on a fresh DB"
```

**Acceptance.** Шесть тестов зелёные — это пункты 3 и 5 гейта фазы.

---

## Task 7: Упразднение ветки `track/fg`

**Goal.** Ветки-заглушки FG больше нет: работа идёт в основной ветке (решение A), а `TRACK_FG.md`
умирает вместе с ней — его содержание поглощено памятью и артефактом.

**Файлы.** Только git-состояние; файлов репозитория не меняется.

- [ ] **Шаг 1: Убедиться, что в worktree нет несохранённого**

```bash
git -C .worktrees/fg status --porcelain
```

Ожидание: пустой вывод. Если что-то есть — остановиться и показать владельцу, дальше не идти.

- [ ] **Шаг 2: Убедиться, что в ветке нет уникальных коммитов, кроме якоря**

```bash
git log --oneline fork-base..track/fg
```

Ожидание: ровно один коммит — `efe731f docs(fg): anchor the dormant FG child track`.
Любой другой коммит — стоп, показать владельцу.

- [ ] **Шаг 2а: Заархивировать якорный коммит тегом** (добавлено по решению владельца при
      исполнении: ветка локальная, без remote, поэтому после `branch -D` коммит жил бы только в
      reflog ~90 дней)

```bash
git tag archive/track-fg efe731f
```

- [ ] **Шаг 3: Снять worktree**

```bash
git worktree remove .worktrees/fg
```

- [ ] **Шаг 4: Удалить ветку**

```bash
git branch -D track/fg
```

- [ ] **Шаг 5: Проверить результат**

```bash
git worktree list && git branch --list "track/*"
```

Ожидание: в списке worktree только корневой; вывод `git branch --list` пуст — пункт 4 гейта фазы.

---

## Task 8: Самодостаточный запрет концовки при кастомном `draft_prompt`

**Добавлен по ходу фазы** (находка при исполнении Task 5, решение владельца — брать в эту фазу).
Порядок исполнения: после Task 6, до или после Task 7 — задачи независимы.

**Проблема.** `outreach_email_pipeline.py:423` — `task = rs.draft_prompt if rs and rs.draft_prompt
else (<дефолтный блок>)`, то есть свой промпт кампании ЗАМЕНЯЕТ дефолтный целиком, включая его
буллеты «Hard requirements» (там среди прочего «no farewell line, no invitation to meet, no
goodbye»). Но ниже (`:485-489`) код БЕЗУСЛОВНО дописывает: «Do NOT write a closing paragraph
yourself — **see the 'Hard requirements' bullet above**…». При кастомном промпте этого буллета
выше нет — ссылка указывает в никуда, а явный запрет на прощание и подпись из дефолта не приезжает.

**Почему это безопасно чинить.** `grep draft_prompt scripts/seed_alexstaff_preset.py` — ни одного
вхождения; в `seed_noda12_preset.py` — ноль. Обе существующие кампании идут по ветке `else`, где
текст остаётся дословным. FG — первая кампания со своим `draft_prompt`, поэтому правка не может
изменить ни одного письма AlexStaff или NODA12 (решение G соблюдено).

**Файлы.**
- Modify: `backend/app/services/outreach_email_pipeline.py:423` (запомнить факт кастомного промпта)
  и `:485-489` (развилка формулировки)
- Test: `backend/tests/test_custom_draft_prompt_closing_note.py` (новый)

- [ ] **Шаг 1: Написать падающий тест**

Создать `backend/tests/test_custom_draft_prompt_closing_note.py`:

```python
"""Фаза 2, Task 8: при кастомном run_setups.draft_prompt запрет писать концовку самодостаточен.

Свой промпт кампании заменяет дефолтный блок целиком — вместе с буллетами «Hard requirements»,
на которые ссылается дописываемая ниже фраза. Для FG (первая кампания со своим draft_prompt) эта
ссылка указывала бы в никуда, а вместе с ней пропадал бы и явный запрет на прощание/подпись.
Кампании без своего draft_prompt (AlexStaff, NODA12) обязаны получать прежний текст ДОСЛОВНО.
0 tokens: generate_json застаблен."""

from __future__ import annotations

import importlib
import pkgutil

import app.models as _models_pkg

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_fg_preset as fg_seed  # noqa: E402
import seed_noda12_preset as noda_seed  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.run_setup import RunSetup  # noqa: E402
from app.repositories.project_repo import create_project  # noqa: E402
from app.repositories.run_repo import create_run, get_run  # noqa: E402

VERBATIM_DEFAULT_NOTE = (
    "Do NOT write a closing paragraph yourself — see the 'Hard requirements' bullet above."
)
BODY = (
    # Не короче 120 символов: generate_email_draft отбраковывает короткие тела
    # (`if len(body) < 120: raise ValueError("Email body too short")`), и тест падал бы не по адресу.
    "Здравствуйте, Мария!\n\n"
    "Первый абзац письма про отрасль и её текущие вызовы для компании Комбинат.\n\n"
    "Второй абзац письма про решение, конкретный первый шаг и пользу для вашей команды."
)


def _capture_prompt(fresh_db, monkeypatch, run, contact):
    from app.services import outreach_email_pipeline as pipeline

    captured = {}

    def fake_generate_json(prompt, task_kind=None, cache_prefix=None):
        captured["prompt"] = (cache_prefix or "") + prompt
        return {"subject": "Тема для Комбината", "body": BODY}

    monkeypatch.setattr(pipeline, "generate_json", fake_generate_json)
    reasoning = {"hook": "", "angle": "", "problem": "", "solution": "", "cta_type": "", "key_point": ""}
    pipeline.generate_email_draft(
        fresh_db, run, contact, reasoning,
        prompt_setup_text=run.run_setup.prompt_setup_text, master_variant=None,
        style_mode="default", pers={"vacancy_signals": None}, finale_variant_index=0,
    )
    return captured["prompt"]


def _run_with(fresh_db, persona, setup_fields, name):
    proj = create_project(fresh_db, name=name, type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = persona.id
    setup = RunSetup(run_id=run.id)
    fresh_db.add(setup)
    for field, value in setup_fields.items():
        setattr(setup, field, value)
    fresh_db.commit()
    run = get_run(fresh_db, run.id)
    contact = Contact(run_id=run.id, name="Мария", email="m@closing-note.example.com",
                      company="Комбинат", source_json={})
    fresh_db.add(contact)
    fresh_db.commit()
    return run, contact


def test_campaign_without_own_draft_prompt_keeps_the_verbatim_note(fresh_db, monkeypatch):
    """Регресс AlexStaff/NODA12: ветка else обязана остаться дословной."""
    persona = noda_seed._seed_persona_noda12(fresh_db)
    fresh_db.commit()
    text_fields, scalar_fields = noda_seed._canon_fields_for_profile("consulting")
    run, contact = _run_with(fresh_db, persona, {**text_fields, **scalar_fields}, "ClosingNoteDefault")

    prompt = _capture_prompt(fresh_db, monkeypatch, run, contact)

    assert run.run_setup.draft_prompt is None  # предпосылка теста: свой промпт не задан
    assert VERBATIM_DEFAULT_NOTE in prompt


def test_campaign_with_own_draft_prompt_gets_a_self_contained_ban(fresh_db, monkeypatch):
    persona = fg_seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    text_fields, scalar_fields = fg_seed.canon_fields("metallurgy", frame=2)
    run, contact = _run_with(fresh_db, persona, {**text_fields, **scalar_fields}, "ClosingNoteCustom")

    prompt = _capture_prompt(fresh_db, monkeypatch, run, contact)

    assert run.run_setup.draft_prompt  # предпосылка теста: свой промпт задан
    assert "see the 'Hard requirements' bullet above" not in prompt
    assert "no farewell line" in prompt
    assert "no sign-off" in prompt


def test_both_branches_still_say_the_closing_is_appended(fresh_db, monkeypatch):
    """Общая часть смысла не должна разъехаться между ветками."""
    noda_persona = noda_seed._seed_persona_noda12(fresh_db)
    fg_persona = fg_seed._seed_persona_fg(fresh_db)
    fresh_db.commit()

    noda_text, noda_scalar = noda_seed._canon_fields_for_profile("consulting")
    run_a, contact_a = _run_with(fresh_db, noda_persona, {**noda_text, **noda_scalar}, "ClosingNoteA")
    fg_text, fg_scalar = fg_seed.canon_fields("metallurgy", frame=1)
    run_b, contact_b = _run_with(fresh_db, fg_persona, {**fg_text, **fg_scalar}, "ClosingNoteB")

    for run, contact in ((run_a, contact_a), (run_b, contact_b)):
        prompt = _capture_prompt(fresh_db, monkeypatch, run, contact)
        assert "is appended to your body automatically after you write it" in prompt
```

- [ ] **Шаг 2: Запустить тест — убедиться, что падает**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_custom_draft_prompt_closing_note.py -q
```

Ожидание: FAIL на `test_campaign_with_own_draft_prompt_gets_a_self_contained_ban` — сейчас в промпт
уходит фраза со ссылкой, а «no farewell line» отсутствует. Первый и третий тесты проходят.

- [ ] **Шаг 3: Развести формулировку по ветке**

В `backend/app/services/outreach_email_pipeline.py` — там, где собирается `task` (`:423`),
запомнить факт кастомного промпта:

```python
    custom_draft_prompt = bool(rs and rs.draft_prompt)
    task = rs.draft_prompt if rs and rs.draft_prompt else (
```

(остальная часть выражения не меняется), и заменить безусловный блок `:485-489` на развилку:

```python
    # B-158: запрет писать закрывающий абзац дописывается всегда, но формулировка зависит от того,
    # откуда приехал task. Дефолтный блок выше содержит буллеты «Hard requirements», на которые
    # можно сослаться; кампания со своим draft_prompt (Фаза 2, FG) заменяет их целиком — там
    # ссылка указывала бы в никуда, а вместе с буллетами пропадает и явный запрет на прощание.
    # Текст ветки else сохранён ДОСЛОВНО: кампании без своего draft_prompt (AlexStaff, NODA12 —
    # ни одна из них draft_prompt не задаёт) не меняются ни на байт.
    if custom_draft_prompt:
        task += (
            "\n\nDo NOT write a closing paragraph yourself: no farewell line, no invitation to "
            "meet, no goodbye, no sign-off. The closing paragraph (self-intro + meeting offer + "
            "one closing CTA question) is fixed by business rule and is appended to your body "
            "automatically after you write it."
        )
    else:
        task += (
            "\n\nDo NOT write a closing paragraph yourself — see the 'Hard requirements' bullet above. "
            "The closing paragraph (self-intro + meeting offer + one closing CTA question) is fixed by "
            "business rule and is appended to your body automatically after you write it."
        )
```

- [ ] **Шаг 4: Прогнать тесты задачи и регресс генерации**

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_custom_draft_prompt_closing_note.py tests/test_noda12_preset_seam.py tests/test_fg_frames_seam.py tests/test_finale_verbatim_append_b158.py tests/test_email_validation_b063.py -q
```

Ожидание: все PASS.

**Acceptance.** Три новых теста зелёные; `test_noda12_preset_seam.py` и
`test_finale_verbatim_append_b158.py` зелёные без правок — доказательство, что ветка `else`
осталась дословной.

---

## Гейт фазы

1. **`pytest -q` не хуже базовой линии.** База — 621 passed (проверено 02.09). Ожидание после
   фазы: 621 + 8 (Task 1) + 5 (Task 2) + 4 (Task 3) + 4 (Task 4) + 14 (Task 5) + 6 (Task 6)
   + 3 (Task 8) = **665 passed**.

```bash
cd backend && venv/Scripts/python.exe -m pytest -q
```

2. **Регресс AlexStaff зелёный без правок** (решение G):

```bash
cd backend && venv/Scripts/python.exe -m pytest tests/test_persona_finale_regression.py tests/test_hard_rules_gate_b273.py tests/test_email_validation_b063.py tests/test_email_validation_b077.py -q
```

Ни одна строка этих четырёх файлов в фазе не изменена — проверяется:

```bash
git diff --stat b214e80 -- backend/tests/test_persona_finale_regression.py backend/tests/test_hard_rules_gate_b273.py backend/tests/test_email_validation_b063.py backend/tests/test_email_validation_b077.py
```

Ожидание: пустой вывод.

3. **Сквозной смок обеих рамок на `fresh_db`** — `tests/test_fg_frames_seam.py`, 6 тестов зелёные
   (Task 6).

4. **Ветки FG нет:**

```bash
git worktree list && git branch --list "track/*"
```

Ожидание: `.worktrees/fg` отсутствует, список веток `track/*` пуст.

5. **Ни одного письма не отправлено; ни одна строка каталога не видна чужой персоне** —
   доказано тестами `test_fg_run_cannot_send_anything` и
   `test_fg_catalog_is_invisible_to_another_persona` (Task 6) плюс
   `test_persona_sees_its_own_and_global_but_not_alien` (Task 2). Дополнительно: за фазу не
   выполняется ни одной команды отправки, `--seed-offers`/`apply_canon` пишут только в локальную БД.

**Операционный шаг после приёмки** (не тест, выполняется владельцем или по его команде): прогнать
на живой БД NODA12-инстанса сидер каталога, чтобы уже засеянные строки получили `persona_id` —
без этого на общем инстансе матчер по-прежнему сможет предложить сессию NODA12 контакту FG:

```bash
cd backend && venv/Scripts/python.exe scripts/seed_noda12_preset.py --run-id <ID> --profile consulting --fields language --seed-offers
```

---

## Вне фазы

- **Task 9** (отдельный инстанс — ждёт сервера), **Task 10** (транспорт Gmail — исключён владельцем
  02.09), **Task 11** (волны).
- **Контент FG**: список отраслей, отраслевые ревю, программы, персона (Г1–Г2), дословный
  финальный CTA (Г5), правило разбивки базы по менеджерам (Г6). Вливается в `INDUSTRY_CONTENT` и
  `FG_FINALES_JSON` отдельным шагом по мере получения — механика этой фазы не меняется.
- **UI и API для новых полей**: `max_authored_words`, `program_match_enabled`, `persona_id`
  каталога не добавляются в `RunPromptSetupPatch` / `RunReviewSetupFieldsRead` и не появляются в
  диалогах фронта. Управление — через сидеры (осознанно: поля кампании, а не оперативные крутилки).
- **Кнопка экспорта в UI** и эндпоинт `GET /runs/{id}/drafts.xlsx` — экспорт остаётся скриптом.
- Верификатор SMTP.BZ; холодный канал FG (группа Д); таблица фидбека менеджеров; Alembic;
  редизайн фронта; EU/US — прежний бэклог.

---

## Риски и что за ними смотреть

1. **Peer-similarity в Рамке‑2** (находка разведки №5). Порог `PEER_SIMILARITY_THRESHOLD=0.88`,
   расчётное сходство писем одной отрасли ≈0.7 — запас есть, но небольшой. Митигация уже в
   `DRAFT_PROMPT_FRAME2` («перескажи ревю своими словами»). Смотреть на первой реальной волне:
   массовый код `duplicate_peer` в `validation_issues_json` — сигнал, что ревю надо разнообразить
   сильнее или поднять порог per-run (это была бы новая доработка, вне фазы).
2. **Плейсхолдеры в финале.** `FG_FINALES_JSON` содержит `[FG-CONTENT PENDING]`, и этот абзац
   приклеивается к КАЖДОМУ письму. Это сделано намеренно (маркер виден в экспорте), но означает:
   до ответа на Г5 экспортный файл нельзя отдавать менеджерам как готовый. Проверять глазами
   колонку «Тело письма» на маркер перед передачей.
3. **`openpyxl` возвращён после того, как был выпилен как мёртвый.** Если партнёр примет
   черри-пик Task 4, у него та же зависимость вернётся — это корректно (у него импорт CRM тоже
   сломан), но упомянуть при передаче.
4. **Пять `_ensure_*` подряд на одной таблице.** `run_setups` уже получает четыре ALTER'а при
   старте; добавляются два. Alembic по-прежнему вне скоупа (унаследованное решение), но точка
   роста зафиксирована.

---

## Self-Review notes

- **Покрытие handoff.** Карта кода handoff, п. 1 → Task 1; п. 2 → Task 2; п. 3 → Task 4;
  п. 4 → Task 5 (персона, профили-матрица, гейт матчера — вынесен в Task 3 как отдельная
  движковая доработка, поскольку это правка пайплайна, а не данные пресета; минихук — в
  `draft_prompt`; плейсхолдер-защита — в `apply_canon`); п. 5 → Task 7. Гейт фазы handoff
  воспроизведён пунктами 1–5 раздела «Гейт фазы».
- **Расхождение с рекомендацией handoff.** Handoff предлагал в экспорте колонки «компания,
  контакт, email, тема, тело, менеджер»; план добавляет «ID черновика» (сверка фидбека менеджеров
  с черновиком в БД — иначе структурированный фидбек не привязать) и «Должность» (менеджеру важно,
  к кому он пишет). Обе — дополнения, ни одна колонка из списка handoff не убрана.
- **Проверка «данные + фоллбэк».** Каждая из трёх доработок имеет тест на NULL-путь:
  `test_none_is_the_same_as_not_passing_it` (Task 1), `test_no_persona_id_keeps_the_whole_catalog`
  (Task 2), `test_null_keeps_the_matcher_on` (Task 3). Это и есть условие возврата партнёру.
- **Единственная правка существующих тестов** — два вызова `_seed_offers` в
  `test_seed_noda12_preset.py` (Task 2, шаг 9). Это тесты нашей же Фазы 1, а не AlexStaff-регресса;
  четыре файла из решения G не тронуты (проверяется командой `git diff --stat` в гейте).
- **Порядок задач.** 1 → 2 → 3 независимы между собой по коду, но Task 5 опирается на поля всех
  трёх, а Task 6 — на Task 5. Task 4 и Task 7 независимы и могут идти в любой момент.
  Рекомендуемый порядок исполнения: 1, 2, 3, 4, 5, 6, 7.
