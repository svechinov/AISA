import re
import time
import json
import requests
import dns.resolver
import smtplib
import socket
from duckduckgo_search import DDGS
from urllib.parse import urlparse

import logging
logger = logging.getLogger(__name__)

# LLM access goes through app.services.llm_gateway (provider per LLM_PROVIDER_PRIORITY — OpenAI for
# the partner). No direct Gemini/provider calls here, so the model/provider is a configuration
# choice (multi-model later) rather than hardcoded. SMTP email verification below is local (no LLM).

# ==========================================
# УЗЕЛ 1: Entity-Scout & Pattern-Analyzer
# ==========================================

def get_domain(url):
    """Извлекает чистый домен из URL"""
    if not url or url == 'Неизвестно':
        return None
    if not url.startswith('http'):
        url = 'http://' + url
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain

def search_ddg(query, max_res=5):
    """Выполняет поиск через DuckDuckGo и возвращает сниппеты"""
    try:
        results = DDGS().text(query, max_results=max_res, backend="html")
        text_corpus = ""
        if isinstance(results, list):
            for r in results:
                text_corpus += f"[{r.get('title', '')}] {r.get('body', '')}\n"
        return text_corpus
    except Exception as e:
        logger.warning(f"DDG search failed: {e}")
        return ""

def search_egrul_nalog(query):
    """Ищет ФИО директора через API ЕГРЮЛ"""
    try:
        session = requests.Session()
        payload = {'vyp3CaptchaToken': '', 'query': query}
        res = session.post('https://egrul.nalog.ru/', data=payload, timeout=5)
        res.raise_for_status()
        token = res.json().get('t')

        if not token: return None
        time.sleep(1)

        res2 = session.get(f'https://egrul.nalog.ru/search-result/{token}', timeout=5)
        res2.raise_for_status()
        rows = res2.json().get('rows', [])

        if rows:
            for row in rows:
                if 'g' in row and 'e' not in row: # Активная компания
                    ceo_info = row['g'] 
                    name = ceo_info.split(':')[-1].strip()
                    return name
    except Exception:
        pass
    return None

def call_llm_json(prompt):
    """Run a JSON-returning LLM call through the shared gateway and return it as a JSON string.

    Routes through app.services.llm_gateway (provider per LLM_PROVIDER_PRIORITY — OpenAI for the
    partner) instead of calling Gemini directly, so all LLM access lives in one place and the
    model/provider becomes a config choice later (multi-model). Callers json.loads() the result;
    returns None on failure (callers already handle None).
    """
    try:
        from app.services.llm_gateway import complete_prompt_json_object
        obj = complete_prompt_json_object(prompt)
        return json.dumps(obj, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"hardcore_osint LLM call failed: {e}")
        return None

def gather_raw_entities(company_name, domain, custom_prompt=None):
    """Собирает имена ЛПР и примеры email с домена"""
    logger.info("Entity scout: gathering raw data")
    
    # 1. Поиск CEO через ЕГРЮЛ
    ceo_name = search_egrul_nalog(company_name)
    
    # 2. Поиск других ЛПР через Dorks (Смещение на HH.ru, Хабр Карьера)
    roles_query = f'"{company_name}" (коммерческий директор OR директор по продажам OR HR директор OR директор по персоналу OR директор по обучению) (site:hh.ru OR site:career.habr.com OR ФИО)'
    roles_corpus = search_ddg(roles_query)
    
    # 3. Поиск любых email на домене (для вычисления маски)
    email_corpus = ""
    if domain:
         email_query = f'"@{domain}" email контакт'
         email_corpus = search_ddg(email_query)
         
    # 3.5 Поиск метаданных в документах (PDF/DOCX)
    docs_corpus = ""
    if domain:
         docs_query = f'"@{domain}" OR "{company_name}" (site:{domain} filetype:pdf OR filetype:docx)'
         docs_corpus = search_ddg(docs_query)

    # 4. Анализ через LLM
    prompt = custom_prompt if custom_prompt else f"""
    Анализ корпоративных данных для {company_name}.
    Домен компании: {domain}

    Данные из ЕГРЮЛ (CEO): {ceo_name if ceo_name else 'Не найдено'}
    
    Поисковая выдача по должностям (HH.ru, Хабр, etc):
    {roles_corpus}

    Поисковая выдача по email-адресам:
    {email_corpus}

    Выдача по документам (Metadata из PDF/DOCX):
    {docs_corpus}

    ЗАДАЧА:
    1. Извлеки все имена ЛПР и свяжи их с ролями (CEO, Коммерческий директор, HR-директор, Директор по обучению). Если роль из ЕГРЮЛ, укажи CEO. Также обращай внимание на авторов и контакты в блоке Metadata из PDF-документов.
    2. Оцени "Свежесть" контакта (Freshness). Если есть упоминания года (2024, 2025) - высокая свежесть (score 100). Если данные старые (2020-2022) - низкая свежесть (score 30). Игнорируй людей, которые уже не работают в компании. Отсортируй массив `leaders` от самых свежих и релевантных к менее важным.
    3. Найди любые email-адреса с доменом @{domain} в выдаче. Попробуй угадать "маску" (формат) корпоративной почты.

    Ответь СТРОГО в формате JSON:
    {{
        "leaders": [
            {{"role": "CEO", "name": "Иван Иванов", "freshness_score": 90}},
            {{"role": "HR Director", "name": "Анна Смирнова", "freshness_score": 50}}
        ],
        "email_mask_guess": "предполагаемая маска или null"
    }}
    """
    
    response = call_llm_json(prompt)
    if response:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
    return {"leaders": [], "email_mask_guess": None}

# ==========================================
# УЗЕЛ 2: Permutation Engine
# ==========================================

def generate_email_permutations(name, domain, mask_guess):
    """LLM генерирует варианты email-адресов на основе имени и домена"""
    prompt = f"""
    Сгенерируй массив возможных корпоративных email-адресов для человека.
    Имя: {name}
    Домен: {domain}
    Предполагаемая маска в компании: {mask_guess}

    Правила:
    1. Используй стандартные транслитерации (Ivan Ivanov -> i.ivanov, ivan.ivanov, ivanov, ivanov.i, ii, iivanov, ivanovi).
    2. Учитывай предполагаемую маску (если есть), поставь ее варианты первыми.
    3. Верни не более 10 самых вероятных вариантов.

    Ответь СТРОГО в формате JSON - простым массивом строк:
    [
        "i.ivanov@{domain}",
        "ivan.ivanov@{domain}"
    ]
    """
    response = call_llm_json(prompt)
    if response:
        try:
             return json.loads(response)
        except json.JSONDecodeError:
             pass
    return []

# ==========================================
# УЗЕЛ 3: SMTP-Verifier
# ==========================================

def get_mx_record(domain):
    try:
        records = dns.resolver.resolve(domain, 'MX')
        mx_record = records[0].exchange.to_text()
        return mx_record
    except Exception:
        return None

def verify_email_smtp(email, mx_record):
    """Жесткий пинг почтового сервера через SMTP (до команды RCPT TO)"""
    email = str(email or "").strip()
    if "@" not in email:
        # LLM permutation occasionally yields a bare username (no @domain) — treat as invalid
        # rather than crashing the whole discovery loop.
        return False
    domain = email.split('@', 1)[1]

    try:
        # Пингуем MX сервер
        server = smtplib.SMTP(timeout=3)
        server.connect(mx_record)
        server.helo(server.local_hostname)
        
        # Эмулируем отправителя (чтобы сервер не сбросил нас сразу)
        server.mail('ping@fg-consulting.ru')
        
        # Проверяем получателя
        code, message = server.rcpt(str(email))
        
        server.quit()
        
        # 250 - Пользователь существует
        if code == 250:
            return True
        return False
    except Exception as e:
         # Если таймаут или защита от спама, считаем невалидным, чтобы не портить репутацию отправки
         return False

def find_valid_email(name, domain, mask_guess):
    logger.info(f"Generating email hypotheses for {name}")
    permutations = generate_email_permutations(name, domain, mask_guess)
    
    if not permutations:
        return None
        
    logger.info(f"SMTP verification: {len(permutations)} candidate(s)")
    mx_record = get_mx_record(domain)
    
    if not mx_record:
        logger.warning(f"No MX record for {domain}")
        return None

    for email in permutations:
        is_valid = verify_email_smtp(email, mx_record)
        if is_valid:
            logger.info(f"Valid email found: {email}")
            return email
            
        # Пауза между пингами, чтобы не улететь в бан по IP
        time.sleep(1)
        
    logger.info("No valid email found")
    return None
