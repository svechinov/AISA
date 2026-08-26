#!/usr/bin/env python3
"""B-372: сравнительный прогон трёх веток — `standard`, `cheap` и `kimi` (Ollama Cloud) — на трёх
OSINT-задачах, которые сейчас не размечены в `llm_gateway.TASK_TIER` и поэтому всегда падают в
`standard`:

  - досье компании     — tavily_osint.get_company_dossier
  - vacancy-радар       — vacancy_radar._extract_signal
  - LPR-OSINT           — deep_lpr_osint.perform_deep_lpr_osint

На проде LLM_PROVIDER_PRIORITY=claude,openai,perplexity,grok и ключа GEMINI нет — тир `cheap`
фактически = claude-haiku-4-5, `standard` = claude-sonnet-5. Ветка `kimi` зовёт
llm_gateway._kimi_complete напрямую (не через _complete_with_fallback) — так измеряется сама
модель, а не логика фолбэка.

Три фазы, чтобы поиск (Tavily/Yandex) не оплачивался дважды при повторных прогонах сравнения:

  --collect [N]   Взять N компаний (default 25) из боевой БД (contacts: заполненные company +
                   website, отбор детерминированный — сортировка по id). Только SELECT. Для
                   каждой компании собрать три корпуса ТЕМИ ЖЕ функциями/запросами, что и прод
                   (tavily_osint / vacancy_radar / deep_lpr_osint), сложить в
                   /app/data/b372_corpora.json. Поиск выполняется ровно один раз.

  --compare [--yes] [--arms standard,cheap,kimi]
                   Читает b372_corpora.json, НИКАКОГО поиска не делает. Для каждой записи
                   собирает промпт точно так же, как прод (те же task/schema-константы), и гоняет
                   его по каждой из --arms веток (default все три: standard, cheap, kimi). Без
                   --yes печатает только смету (число вызовов и оценку $, кроме kimi — см. ниже) и
                   не тратит ни цента. Результаты дописываются в /app/data/b372_results.json:
                   существующий файл читается и мержится по ключу (kind, company) — ветки,
                   посчитанные в прошлых прогонах, не теряются, даже если сейчас указан только
                   --arms kimi (например, чтобы досчитать недостающую ветку, не переплачивая за
                   уже оплаченные standard/cheap).

  --report        Считает метрики по b372_results.json и печатает сравнение по трём веткам:
                   валидность, схема, заземление (галлюцинированные ссылки), наполненность,
                   согласие веток по is_hiring (попарно: standard↔cheap, standard↔kimi),
                   стоимость/скорость, плюс блок расхождений для ручной вычитки. Стоимость kimi
                   не считается по прайсу Anthropic — Ollama Cloud продаёт Kimi фикс-подпиской, не
                   по токенам (см. AlexStaff/Content/kimi-content-handoff-2026-07-27.md); для этой
                   ветки печатается отдельная строка-примечание вместо $ оценки.

TASK_TIER НЕ трогаем — разметку тира по результатам этого прогона Алексей делает сам.
Только SELECT — скрипт никогда не пишет в боевую БД.

RUNNING ON THE SERVER — backend/Dockerfile копирует в образ только app/, backend/scripts/ туда не
попадает, поэтому запускать как одноразовый скрипт против прод-БД (см. CLAUDE.md "Грабли"):

    scp backend/scripts/b372_tier_compare.py bizos:~/ai-biz-os/infra/data/
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/b372_tier_compare.py --collect 25'
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/b372_tier_compare.py --compare'          # смета, dry-run
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/b372_tier_compare.py --compare --yes'    # реальный прогон, все 3 ветки
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/b372_tier_compare.py --compare --yes --arms kimi'  # догнать только kimi
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/b372_tier_compare.py --report'

Загружает /app/data/.env в os.environ ДО импортов app.* (DATABASE_URL и LLM-ключи должны быть в
os.environ до Settings(); Tavily/веб-поиск читают os.environ, а не settings). Локально (dev) —
не-op, если /app/data/.env не существует; тогда используется обычный backend/.env через
env_bootstrap внутри app.config.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# --- Load /app/data/.env into the process environment BEFORE importing app.config/app.db ---
_DATA_ENV = Path("/app/data/.env")
if _DATA_ENV.is_file():
    for _line in _DATA_ENV.read_text(encoding="utf-8").splitlines():
        s = _line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        _key, _, _val = s.partition("=")
        _key = _key.strip()
        _val = _val.strip()
        if len(_val) >= 2 and _val[0] == _val[-1] and _val[0] in "\"'":
            _val = _val[1:-1]
        if _key:
            os.environ[_key] = _val

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import app.models  # noqa: E402 — package with __path__, for the pkgutil walk below

# Import every model module so SQLAlchemy's mapper configuration sees all relationships —
# skipping one here risks "expression 'X' failed to locate a name" the first time a relationship
# is touched.
for _mod in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_mod.name}")

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.services.deep_lpr_osint import LPR_OSINT_SCHEMA, _person_search_corpus  # noqa: E402
from app.services.llm_gateway import (  # noqa: E402
    _coerce_json_dict_from_text,
    _complete_with_fallback,
    _kimi_complete,
)
from app.services.prompt_builder import build_prompt  # noqa: E402
from app.services.vacancy_radar import (  # noqa: E402
    EXTRACTION_SCHEMA,
    _corpus_from_ats_patterns,
    _corpus_from_careers_page,
    _corpus_from_general_search,
    _corpus_from_linkedin_jobs,
    careers_page_declares_no_openings,
)

CORPORA_PATH = Path("/app/data/b372_corpora.json")
RESULTS_PATH = Path("/app/data/b372_results.json")

DEFAULT_N = 25

# Same 5 keys as deep_lpr_osint.LPR_OSINT_SCHEMA, reused rather than duplicated.
LPR_FIELDS = tuple(LPR_OSINT_SCHEMA.keys())

# B-372: third comparison arm alongside standard/cheap — Kimi via Ollama Cloud (see backend
# app.services.llm_gateway._kimi_complete). All three arms in default run order.
ARMS_ALL = ("standard", "cheap", "kimi")

# claude-sonnet-5 / claude-haiku-4-5 pricing, $ per 1M tokens (in/out). Kimi has no "in"/"out"
# here on purpose: Ollama Cloud sells it as a flat-rate subscription, not per-token billing (see
# AlexStaff/Content/kimi-content-handoff-2026-07-27.md) — there is no verified $/1M-token rate to
# plug in, so _print_cost_estimate and cmd_report skip the Anthropic-style $ math for this arm and
# print a separate disclaimer line instead.
PRICES = {
    "standard": {"in": 3.0, "out": 15.0, "model": "claude-sonnet-5"},
    "cheap": {"in": 1.0, "out": 5.0, "model": "claude-haiku-4-5"},
    "kimi": {"model": "kimi-k2.7-code"},
}
# Rough JSON-object output size assumption for the pre-flight estimate only; --report uses the
# actual response size instead.
_ASSUMED_OUTPUT_TOKENS = 400


# =============================================================================================
# --collect: read boевую БД (SELECT only), build the three corpora with the same functions/
# queries prod uses, search exactly once.
# =============================================================================================


def _select_companies(db, n: int) -> list[Contact]:
    """Deterministic, read-only selection: first N distinct companies (by ascending contact id)
    that have both a company name and a website set. Only SELECT — never writes."""
    q = (
        db.query(Contact)
        .filter(Contact.company.isnot(None), Contact.company != "")
        .filter(Contact.website.isnot(None), Contact.website != "")
        .order_by(Contact.id.asc())
    )
    seen: set[str] = set()
    out: list[Contact] = []
    for c in q.yield_per(200):
        key = c.company.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= n:
            break
    return out


def _collect_dossier_corpus(company_name: str, website: str) -> dict | None:
    """Same query + result assembly as tavily_osint.get_company_dossier (English, no custom run
    prompt — kept reproducible across runs, not tied to any single run's RunSetup). Returns None
    when search yields nothing, same as prod (no dossier fabricated from an empty corpus)."""
    from app.services.search_service import search_web

    site_ctx = f" (website: {website})" if website and website.strip() else ""
    query = (
        f"Find deep business intelligence on {company_name}{site_ctx}. "
        "Focus on: 1. Recent news, launches, funding, strategy. 2. Growth and team signals "
        "(expansion, restructuring, hiring plans, key departures). "
        "3. Key decision makers (CEO, founders, HR/People lead). "
    )
    hits = search_web(query, max_results=6, max_passages=5)
    if not hits:
        return None
    context = ""
    urls: list[str] = []
    for h in hits:
        context += f"Source ({h.get('url')}): [{h.get('title', '')}] {h.get('snippet', '')}\n"
        urls.append(h.get("url"))
    return {"query": query, "hits": hits, "context": context, "urls": urls}


def _collect_vacancy_corpus(company_name: str, website: str) -> dict | None:
    """Same cascade as vacancy_radar.collect_vacancy_signals, stopped right after corpus assembly
    (the LLM extraction call happens later, in --compare, once per tier). Reuses the same private
    stage functions so the corpus is byte-identical to what prod would gather."""
    careers_parts, careers_urls = _corpus_from_careers_page(website)
    if careers_parts and any(careers_page_declares_no_openings(p) for p in careers_parts):
        # B-265: own careers page says "no openings" — cascade stops, no LLM call in prod either.
        return {"stage": "declared_no_openings", "corpus_parts": [], "source_urls": careers_urls}

    for stage_name, stage_fn in (
        ("careers_page", lambda: (careers_parts, careers_urls)),
        ("ats", lambda: _corpus_from_ats_patterns(company_name, website)),
        ("linkedin", lambda: _corpus_from_linkedin_jobs(company_name)),
        ("general", lambda: _corpus_from_general_search(company_name, website)),
    ):
        corpus_parts, source_urls = stage_fn()
        if corpus_parts:
            return {"stage": stage_name, "corpus_parts": corpus_parts, "source_urls": source_urls}
    return None


def _collect_lpr_corpus(contact: Contact) -> dict | None:
    """Same tiered person search as deep_lpr_osint._person_search_corpus, for the one
    representative contact selected for this company. English only (matches the default run
    language, keeps the prompt comparable across companies from different runs)."""
    raw = _person_search_corpus(contact.name, contact.company, contact.role, "English")
    if not raw.strip():
        return None
    urls = re.findall(r"\((https?://[^)]+)\)", raw)
    return {"contact_name": contact.name, "contact_role": contact.role, "raw_dossier": raw, "urls": urls}


def cmd_collect(n: int) -> None:
    db = SessionLocal()
    try:
        contacts = _select_companies(db, n)
        print(f"Отобрано компаний: {len(contacts)} (запрошено {n}, отбор по id asc, только SELECT).")
        companies_out = []
        for c in contacts:
            print(f"  собираю: {c.company!r} ({c.website})")
            dossier = _collect_dossier_corpus(c.company, c.website)
            vacancy = _collect_vacancy_corpus(c.company, c.website)
            lpr = _collect_lpr_corpus(c)
            companies_out.append(
                {
                    "contact_id": c.id,
                    "company": c.company,
                    "website": c.website,
                    "dossier": dossier,
                    "vacancy": vacancy,
                    "lpr": lpr,
                }
            )
        out = {
            "collected_at": datetime.utcnow().isoformat() + "Z",
            "n_requested": n,
            "companies": companies_out,
        }
        CORPORA_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        n_dossier = sum(1 for c in companies_out if c["dossier"])
        n_vacancy = sum(1 for c in companies_out if c["vacancy"] and c["vacancy"]["corpus_parts"])
        n_lpr = sum(1 for c in companies_out if c["lpr"])
        print(
            f"\nWrote {CORPORA_PATH} — {len(companies_out)} компаний: "
            f"dossier={n_dossier} vacancy={n_vacancy} lpr={n_lpr} "
            "(компании без корпуса по задаче — пропускаются в --compare, как и в проде)."
        )
    finally:
        db.close()


# =============================================================================================
# --compare: read b372_corpora.json (no search), build the exact prod prompt for each task, run
# both tiers, write b372_results.json.
# =============================================================================================


def _dossier_prompt(company_name: str, website: str, context: str) -> str:
    """Exact copy of the prompt tavily_osint.get_company_dossier builds in the default (English,
    no custom run prompt) branch — kept in sync by hand since get_company_dossier bundles prompt
    building with the LLM call, and here the two tiers must be called separately."""
    language = "English"
    return f"""
You are an expert OSINT analyst. Analyze the following OSINT data about {company_name} ({website}).
Extract key facts, business triggers, and hypotheses for a B2B sales pitch.
LANGUAGE: write ALL text values (facts, hypotheses, triggers) in {language.upper()} (keep the JSON keys in English).
CRITICAL: You must provide strict evidence for each fact.
Return ONLY a valid JSON object with this exact structure:
{{
  "hypotheses": ["hypothesis 1", "hypothesis 2"],
  "triggers": ["trigger 1", "trigger 2"],
  "evidence": [
    {{"fact": "statement of fact", "source_url": "url", "confidence_score": 95}}
  ]
}}

OSINT Data:
{context}
"""


def _vacancy_prompt(company_name: str, corpus_parts: list[str]) -> str:
    """Exact copy of the task text + build_prompt call from vacancy_radar._extract_signal."""
    task = (
        f"You are screening whether the company '{company_name}' is CURRENTLY hiring, from raw "
        "evidence gathered from its careers page, an ATS job board, LinkedIn, or web search.\n"
        "- is_hiring=true ONLY when the evidence shows present-tense open roles (careers page "
        "with listings, live job posts, 'we are hiring' announcements). Old news about past "
        "hiring or generic 'join us' boilerplate without roles is NOT enough.\n"
        "- open_roles: list the concrete roles you can actually see in the evidence, with the "
        "source URL for each. Include location and country when the evidence shows where the "
        "role is based (e.g. a city name, 'remote', or a country). Never invent roles or "
        "locations.\n"
        "- summary: one short line naming the roles and where they were seen. Empty string when "
        "is_hiring is false.\n"
    )
    return build_prompt(
        task=task,
        data={"company": company_name, "search_results": "\n".join(corpus_parts)},
        rules=[],
        output_schema=EXTRACTION_SCHEMA,
    )


def _lpr_prompt(name: str, company: str, role: str, raw_dossier: str) -> str:
    """Exact copy of the default task text + build_prompt call from
    deep_lpr_osint.perform_deep_lpr_osint (custom_task=None, English branch)."""
    language = "English"
    task = (
        "You are an expert OSINT profiler. Analyze the raw search results about this person "
        "and build a structured personal dossier.\n"
        "Focus: professional background, recent public statements/posts, talks, "
        "key interests and focus areas, and the person's own city/country if it is visible "
        "(recipient_location) — distinct from the company's headquarters.\n"
        f"WRITE ALL field values IN {language.upper()}. If specific information is missing, leave "
        "the field empty or write 'Not found'. Never invent facts that are not in the search "
        "results.\n\n"
    )
    task += f"\nRaw search results:\n{raw_dossier}"
    data = {"person": name, "company": company, "role": role}
    return build_prompt(task=task, data=data, rules=[], output_schema=LPR_OSINT_SCHEMA)


def _build_tasks(corpora: dict) -> list[dict]:
    """corpora (as written by --collect) -> flat list of {"kind", "company", "prompt",
    "corpus_urls"}, one per task instance that actually has a corpus (companies with no evidence
    for a given task are skipped, matching what prod would have done too)."""
    tasks: list[dict] = []
    for c in corpora["companies"]:
        company = c["company"]
        if c.get("dossier"):
            prompt = _dossier_prompt(company, c["website"], c["dossier"]["context"])
            tasks.append({"kind": "dossier", "company": company, "prompt": prompt, "corpus_urls": c["dossier"]["urls"]})
        vacancy = c.get("vacancy")
        if vacancy and vacancy["corpus_parts"]:
            prompt = _vacancy_prompt(company, vacancy["corpus_parts"])
            tasks.append({"kind": "vacancy", "company": company, "prompt": prompt, "corpus_urls": vacancy["source_urls"]})
        lpr = c.get("lpr")
        if lpr:
            prompt = _lpr_prompt(lpr["contact_name"], company, lpr["contact_role"], lpr["raw_dossier"])
            tasks.append({"kind": "lpr", "company": company, "prompt": prompt, "corpus_urls": lpr["urls"]})
    return tasks


def _print_cost_estimate(tasks: list[dict], arms: list[str]) -> None:
    total_chars = sum(len(t["prompt"]) for t in tasks)
    est_in_tokens = total_chars / 3
    n_tasks = len(tasks)
    print(f"Задач (промптов): {n_tasks}. Вызовов LLM всего: {n_tasks * len(arms)} (ветки: {', '.join(arms)}).")
    print(f"Суммарный размер промптов: {total_chars} символов (~{est_in_tokens:,.0f} input-токенов на ветку).")
    grand_total = 0.0
    for arm in arms:
        cfg = PRICES[arm]
        if "in" not in cfg:
            print(
                f"  {arm:8s} ({cfg['model']}): $ не считаем — Ollama Cloud продаёт Kimi "
                "фикс-подпиской, не по токенам (не прайс Anthropic); в итог ниже не входит."
            )
            continue
        in_cost = est_in_tokens / 1e6 * cfg["in"]
        out_cost = n_tasks * _ASSUMED_OUTPUT_TOKENS / 1e6 * cfg["out"]
        cost = in_cost + out_cost
        grand_total += cost
        print(
            f"  {arm:8s} ({cfg['model']}): ~${cost:.2f} "
            f"(input ~${in_cost:.2f} + output ~${out_cost:.2f}, output оценён грубо, "
            f"{_ASSUMED_OUTPUT_TOKENS} токенов/ответ)"
        )
    print(f"  Итого (ветки с известным прайсом): ~${grand_total:.2f}\n")


def _run_arm(arm: str, prompt: str) -> dict:
    """Run one comparison arm on `prompt`, return the parsed JSON object (raises on failure).

    standard/cheap go through the normal fallback path (_complete_with_fallback), same as prod.
    kimi calls llm_gateway._kimi_complete directly — bypassing fallback — so the comparison
    measures the Kimi model itself, parsed through the same _coerce_json_dict_from_text as every
    other arm."""
    if arm in ("standard", "cheap"):
        return _complete_with_fallback(prompt, arm)
    if arm == "kimi":
        key = (settings.OLLAMA_ANTHROPIC_TOKEN or "").strip()
        if not key:
            raise ValueError("OLLAMA_ANTHROPIC_TOKEN not set")
        text = _kimi_complete(prompt, key, settings.KIMI_MODEL)
        return _coerce_json_dict_from_text(text)
    raise ValueError(f"unknown arm: {arm!r}")


def _load_existing_results() -> dict[tuple[str, str], dict]:
    """(kind, company) -> entry, as previously written to RESULTS_PATH. Empty dict if no file yet."""
    if not RESULTS_PATH.is_file():
        return {}
    existing = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {(e["kind"], e["company"]): e for e in existing}


def cmd_compare(yes: bool, arms: list[str]) -> None:
    if not CORPORA_PATH.is_file():
        print(f"Нет {CORPORA_PATH} — сначала запусти --collect.", file=sys.stderr)
        raise SystemExit(1)
    corpora = json.loads(CORPORA_PATH.read_text(encoding="utf-8"))
    tasks = _build_tasks(corpora)
    if not tasks:
        print("Пустой корпус — нечего сравнивать.", file=sys.stderr)
        raise SystemExit(1)

    _print_cost_estimate(tasks, arms)

    if not yes:
        print("Dry-run: смета выше, реальных вызовов LLM не было. Повтори с --yes для настоящего прогона.")
        return

    # Merge into whatever is already on disk — arms computed in earlier runs (e.g. standard/cheap,
    # already paid for) must survive a later run that only tops up --arms kimi.
    existing = _load_existing_results()
    merged: dict[tuple[str, str], dict] = dict(existing)
    order: list[tuple[str, str]] = list(existing.keys())
    for t in tasks:
        key = (t["kind"], t["company"])
        if key not in existing:
            order.append(key)

    for i, t in enumerate(tasks, 1):
        key = (t["kind"], t["company"])
        entry: dict = merged.get(key) or {"kind": t["kind"], "company": t["company"]}
        entry["prompt_chars"] = len(t["prompt"])
        entry["corpus_urls"] = t["corpus_urls"]
        for arm in arms:
            t0 = time.monotonic()
            try:
                resp = _run_arm(arm, t["prompt"])
                entry[arm] = {"ok": True, "response": resp, "elapsed_s": time.monotonic() - t0}
            except Exception as e:
                entry[arm] = {"ok": False, "error": str(e), "elapsed_s": time.monotonic() - t0}
        merged[key] = entry
        status = " ".join(f"{arm}={'ok' if entry[arm]['ok'] else 'FAIL'}" for arm in arms)
        print(f"[{i}/{len(tasks)}] {t['kind']} {t['company']}: {status}")

    out = [merged[k] for k in order]
    RESULTS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\nWrote {RESULTS_PATH} — {len(out)} задач всего (в этом прогоне посчитано {len(tasks)} "
        f"x {len(arms)} веток = {len(tasks) * len(arms)} вызовов; ранее посчитанные ветки сохранены)."
    )


# =============================================================================================
# --report: read b372_results.json, compute metrics. Pure functions below are unit-tested offline
# in tests/test_b372_tier_compare.py on synthetic data.
# =============================================================================================


def _dossier_schema_ok(resp) -> bool:
    if not isinstance(resp, dict):
        return False
    if not isinstance(resp.get("hypotheses"), list) or not isinstance(resp.get("triggers"), list):
        return False
    evidence = resp.get("evidence")
    if not isinstance(evidence, list):
        return False
    for e in evidence:
        if not isinstance(e, dict):
            return False
        if not isinstance(e.get("fact"), str) or not isinstance(e.get("source_url"), str):
            return False
        if not isinstance(e.get("confidence_score"), (int, float)) or isinstance(e.get("confidence_score"), bool):
            return False
    return True


def _vacancy_schema_ok(resp) -> bool:
    if not isinstance(resp, dict):
        return False
    if not isinstance(resp.get("is_hiring"), bool):
        return False
    roles = resp.get("open_roles")
    if not isinstance(roles, list):
        return False
    for r in roles:
        if not isinstance(r, dict):
            return False
        if not isinstance(r.get("role"), str) or not isinstance(r.get("evidence_url"), str):
            return False
    return True


def _lpr_schema_ok(resp) -> bool:
    if not isinstance(resp, dict):
        return False
    return all(f in resp for f in LPR_FIELDS)


_SCHEMA_CHECK = {"dossier": _dossier_schema_ok, "vacancy": _vacancy_schema_ok, "lpr": _lpr_schema_ok}


def _grounding_ratio(urls_found: list[str], corpus_urls: list[str]) -> tuple[int, int]:
    """(#urls that really are in the corpus, #urls total) for one response. A url not found in
    the corpus is a hallucination."""
    corpus_set = {u for u in corpus_urls if u}
    total = len(urls_found)
    matched = sum(1 for u in urls_found if u in corpus_set)
    return matched, total


def _dossier_urls(resp) -> list[str]:
    evidence = resp.get("evidence") if isinstance(resp, dict) else None
    if not isinstance(evidence, list):
        return []
    return [e.get("source_url") for e in evidence if isinstance(e, dict) and e.get("source_url")]


def _vacancy_urls(resp) -> list[str]:
    roles = resp.get("open_roles") if isinstance(resp, dict) else None
    if not isinstance(roles, list):
        return []
    return [r.get("evidence_url") for r in roles if isinstance(r, dict) and r.get("evidence_url")]


def _tier_agreement(standard_resp, cheap_resp) -> bool | None:
    """True/False if both responses carry an is_hiring verdict, None when either doesn't (not
    comparable)."""
    if not isinstance(standard_resp, dict) or not isinstance(cheap_resp, dict):
        return None
    if "is_hiring" not in standard_resp or "is_hiring" not in cheap_resp:
        return None
    return bool(standard_resp["is_hiring"]) == bool(cheap_resp["is_hiring"])


def _pct(n: float, d: float) -> str:
    return f"{(100.0 * n / d):.0f}%" if d else "n/a"


def cmd_report() -> None:
    if not RESULTS_PATH.is_file():
        print(f"Нет {RESULTS_PATH} — сначала запусти --compare --yes.", file=sys.stderr)
        raise SystemExit(1)
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    by_kind: dict[str, list[dict]] = {"dossier": [], "vacancy": [], "lpr": []}
    for r in results:
        by_kind[r["kind"]].append(r)

    # Some rows may predate B-372 (only standard/cheap computed) — every block below skips an arm
    # for a row where that arm's key is simply absent, rather than assuming full coverage.
    print("=== B-372: standard (claude-sonnet-5) vs cheap (claude-haiku-4-5) vs kimi (Ollama Cloud) ===\n")
    print(f"Задач: dossier={len(by_kind['dossier'])} vacancy={len(by_kind['vacancy'])} lpr={len(by_kind['lpr'])}\n")

    print("--- 1-2. Валидность и схема ---")
    for arm in ARMS_ALL:
        print(f"  Ветка: {arm}")
        for kind, rows in by_kind.items():
            rows_with_arm = [r for r in rows if arm in r]
            n = len(rows_with_arm)
            if not n:
                continue
            valid = [r for r in rows_with_arm if r[arm]["ok"]]
            n_valid = len(valid)
            n_schema = sum(1 for r in valid if _SCHEMA_CHECK[kind](r[arm]["response"]))
            print(
                f"    {kind}: валидность {n_valid}/{n} ({_pct(n_valid, n)}), "
                f"схема {n_schema}/{n_valid} ({_pct(n_schema, n_valid)})"
            )
    print()

    print("--- 3. Заземление (доля source_url/evidence_url реально из корпуса) ---")
    for arm in ARMS_ALL:
        for kind, url_fn in (("dossier", _dossier_urls), ("vacancy", _vacancy_urls)):
            matched = total = 0
            for r in by_kind[kind]:
                if arm not in r or not r[arm]["ok"]:
                    continue
                urls = url_fn(r[arm]["response"])
                m, t = _grounding_ratio(urls, r["corpus_urls"])
                matched += m
                total += t
            print(f"  {arm}/{kind}: {matched}/{total} ({_pct(matched, total)})")
    print()

    print("--- 4. Наполненность ---")
    for arm in ARMS_ALL:
        dossier_valid = [r[arm]["response"] for r in by_kind["dossier"] if arm in r and r[arm]["ok"] and _dossier_schema_ok(r[arm]["response"])]
        avg_ev = sum(len(v.get("evidence", [])) for v in dossier_valid) / len(dossier_valid) if dossier_valid else 0.0
        avg_hyp = sum(len(v.get("hypotheses", [])) for v in dossier_valid) / len(dossier_valid) if dossier_valid else 0.0
        print(f"  {arm}/dossier: evidence avg={avg_ev:.1f} hypotheses avg={avg_hyp:.1f} (n={len(dossier_valid)})")

        lpr_valid = [r[arm]["response"] for r in by_kind["lpr"] if arm in r and r[arm]["ok"] and _lpr_schema_ok(r[arm]["response"])]
        if lpr_valid:
            slots = len(lpr_valid) * len(LPR_FIELDS)
            nonempty = sum(1 for v in lpr_valid for f in LPR_FIELDS if str(v.get(f, "")).strip()) / slots
            not_found = sum(1 for v in lpr_valid for f in LPR_FIELDS if str(v.get(f, "")).strip().lower() == "not found") / slots
        else:
            nonempty = not_found = 0.0
        print(f"  {arm}/lpr: непустые поля {_pct(nonempty, 1)}, 'Not found' {_pct(not_found, 1)} (n={len(lpr_valid)})")
    print()

    print("--- 5. Согласие веток (is_hiring, vacancy), попарно со standard ---")
    for other in ("cheap", "kimi"):
        agree = compared = 0
        mismatches: list[str] = []
        for r in by_kind["vacancy"]:
            if not ("standard" in r and other in r and r["standard"]["ok"] and r[other]["ok"]):
                continue
            a = _tier_agreement(r["standard"]["response"], r[other]["response"])
            if a is None:
                continue
            compared += 1
            if a:
                agree += 1
            else:
                mismatches.append(r["company"])
        print(f"  standard vs {other}: совпало {agree}/{compared} ({_pct(agree, compared)})")
        if mismatches:
            print("    Расхождения (разобрать руками):")
            for name in mismatches:
                print(f"      - {name}")
    print()

    print("--- 6. Стоимость и скорость (по факту прогона) ---")
    for arm in ARMS_ALL:
        cfg = PRICES[arm]
        total_time = 0.0
        n = 0
        total_cost = 0.0
        for rows in by_kind.values():
            for r in rows:
                if arm not in r:
                    continue
                e = r[arm]
                n += 1
                total_time += e.get("elapsed_s", 0.0)
                if "in" in cfg:
                    in_tok = r["prompt_chars"] / 3
                    out_chars = len(json.dumps(e["response"], ensure_ascii=False)) if e["ok"] else 0
                    out_tok = out_chars / 3
                    total_cost += in_tok / 1e6 * cfg["in"] + out_tok / 1e6 * cfg["out"]
        avg_time = total_time / n if n else 0.0
        if "in" in cfg:
            print(f"  {arm} ({cfg['model']}): ${total_cost:.4f} всего, среднее время {avg_time:.1f}с (n={n})")
        else:
            print(
                f"  {arm} ({cfg['model']}): $ не считаем — фикс-подписка Ollama Cloud, не прайс "
                f"Anthropic (оценка по факту прогона недоступна); среднее время {avg_time:.1f}с (n={n})"
            )
    print()

    print("--- Расхождения для ручной вычитки (первые 5 задач) ---")
    for r in results[:5]:
        print(f"\n=== {r['kind']} / {r['company']} ===")
        for arm in ARMS_ALL:
            if arm not in r:
                continue
            e = r[arm]
            print(f"-- {arm} --\n{json.dumps(e.get('response', e.get('error')), ensure_ascii=False, indent=2)}")


# =============================================================================================


def _parse_arms(raw: str) -> list[str]:
    arms = [a.strip().lower() for a in raw.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ARMS_ALL]
    if unknown:
        raise SystemExit(f"--arms: неизвестные ветки {unknown!r}, допустимые: {ARMS_ALL}")
    if not arms:
        raise SystemExit("--arms: пустой список веток")
    return arms


def main() -> int:
    ap = argparse.ArgumentParser(description="B-372: сравнение веток standard/cheap/kimi на трёх OSINT-задачах.")
    ap.add_argument(
        "--collect", type=int, nargs="?", const=DEFAULT_N, metavar="N",
        help=f"Собрать N компаний из боевой БД (default {DEFAULT_N}). Только SELECT.",
    )
    ap.add_argument("--compare", action="store_true", help="Прогнать выбранные ветки по собранным корпусам.")
    ap.add_argument("--report", action="store_true", help="Посчитать метрики по результатам прогона.")
    ap.add_argument("--yes", action="store_true", help="Реально тратить деньги на --compare (без флага — только смета).")
    ap.add_argument(
        "--arms", default=",".join(ARMS_ALL), metavar="standard,cheap,kimi",
        help=f"Какие ветки гонять в --compare (default все: {','.join(ARMS_ALL)}). "
        "Например --arms kimi — досчитать только недостающую ветку.",
    )
    args = ap.parse_args()

    if args.collect is not None:
        cmd_collect(args.collect)
    elif args.compare:
        cmd_compare(args.yes, _parse_arms(args.arms))
    elif args.report:
        cmd_report()
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
