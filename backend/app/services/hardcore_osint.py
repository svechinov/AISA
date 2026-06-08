import os
import sys
import re
import time
import json
import sqlite3
import requests
import dns.resolver
import smtplib
import socket
from duckduckgo_search import DDGS
from urllib.parse import urlparse

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
DB_PATH = r"C:\Users\user\Documents\Обсидиан\ИИ-автоматизация\LeadGen\leads.db"
API_KEY = os.environ.get("GEMINI_API_KEY")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"

if not API_KEY:
    print("❌ ОШИБКА: Переменная окружения GEMINI_API_KEY не установлена.")

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
        print(f"    [!] Ошибка поиска DDG: {e}")
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

def call_gemini(prompt):
    """Отправляет запрос в LLM"""
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }
    try:
        response = requests.post(f"{API_URL}?key={API_KEY}", headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return result['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"    [!] Ошибка Gemini API: {e}")
        return None

def gather_raw_entities(company_name, domain, custom_prompt=None):
    """Собирает имена ЛПР и примеры email с домена"""
    print(f"  🔍 Шаг 1: Сбор сырых данных (Entity-Scout & Pattern-Analyzer)...")
    
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
    
    response = call_gemini(prompt)
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
    response = call_gemini(prompt)
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
    domain = email.split('@')[1]
    
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
    print(f"  🧠 Шаг 2: Генерация гипотез для {name}...")
    permutations = generate_email_permutations(name, domain, mask_guess)
    
    if not permutations:
        return None
        
    print(f"  ⚙️ Шаг 3: SMTP-верификация ({len(permutations)} вариантов)...")
    mx_record = get_mx_record(domain)
    
    if not mx_record:
        print(f"    [!] MX запись для {domain} не найдена.")
        return None

    for email in permutations:
        is_valid = verify_email_smtp(email, mx_record)
        if is_valid:
            print(f"    ✅ ВАЛИДНЫЙ EMAIL НАЙДЕН: {email}")
            return email
            
        # Пауза между пингами, чтобы не улететь в бан по IP
        time.sleep(1)
        
    print(f"    ❌ Валидный email не найден.")
    return None

# ==========================================
# ОРКЕСТРАТОР АГЕНТА
# ==========================================

def process_empty_contacts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Ищем компании, у которых нет контактного лица (ФИО) ИЛИ нет email-а
    c.execute("SELECT id, company_name, website, contact_name, email FROM fg_leads WHERE (contact_name = '' OR contact_name IS NULL OR email = '' OR email IS NULL) LIMIT 5")
    leads = c.fetchall()
    
    if not leads:
         print("✅ В базе нет лидов без контактов.")
         conn.close()
         return

    print(f"🚀 Запуск OSINT-Агента: найдено {len(leads)} лидов для обогащения контактов.\n")

    for lead in leads:
        lead_id = lead['id']
        company = lead['company_name']
        website = lead['website']
        existing_name = lead['contact_name']
        
        print(f"=== OSINT: {company} ===")
        domain = get_domain(website)
        
        if not domain:
            print("  ⚠️ Нет домена. OSINT невозможен.")
            continue
            
        # Шаг 1: Разведка (Entity Scout)
        raw_data = gather_raw_entities(company, domain)
        leaders = raw_data.get('leaders', [])
        mask = raw_data.get('email_mask_guess')
        
        # Если в базе не было имени, но мы его нашли - берем приоритетного ЛПР
        target_name = existing_name
        target_role = ""
        
        if not target_name and leaders:
             # Ищем приоритет: CEO -> Комдир -> HRD
             for role in ['CEO', 'Коммерческий директор', 'Директор по продажам', 'HR Director', 'Директор по персоналу']:
                 found = next((l for l in leaders if role.lower() in l['role'].lower()), None)
                 if found:
                     target_name = found['name']
                     target_role = found['role']
                     print(f"  🎯 Выбран приоритетный ЛПР: {target_name} ({target_role})")
                     break
             # Если специфичных нет, берем первого попавшегося
             if not target_name:
                 target_name = leaders[0]['name']
                 target_role = leaders[0]['role']
                 print(f"  🎯 Выбран ЛПР: {target_name} ({target_role})")
                 
        if not target_name:
            print("  ❌ Не удалось найти ФИО ЛПР. Пропускаем.")
            continue
            
        # Шаг 2 & 3: Генерация гипотез и SMTP-верификация
        valid_email = find_valid_email(target_name, domain, mask)
        
        # Шаг 4: Сохранение результатов
        if target_name or valid_email:
             update_fields = []
             params = []
             
             if not existing_name and target_name:
                  update_fields.extend(["contact_name = ?", "contact_role = ?"])
                  params.extend([target_name, target_role])
                  
             if valid_email:
                  update_fields.append("email = ?")
                  params.append(valid_email)
                  
             if update_fields:
                 update_query = "UPDATE fg_leads SET " + ", ".join(update_fields) + " WHERE id = ?"
                 params.append(lead_id)
                 
                 c.execute(update_query, tuple(params))
                 conn.commit()
                 print("  💾 Данные обогащены в БД!")
             
        time.sleep(2)

    conn.close()

if __name__ == "__main__":
    process_empty_contacts()