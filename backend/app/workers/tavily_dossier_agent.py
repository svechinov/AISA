import os
import sys
import time
from tavily import TavilyClient
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models.contact import Contact

def get_tavily_client():
    API_KEY = os.environ.get("TAVILY_API_KEY")
    if not API_KEY:
        return None
    return TavilyClient(api_key=API_KEY)

def generate_search_query(company_name, website):
    site_context = f" Изучи их официальный сайт {website}." if website and website != 'Неизвестен' else ""
    return f"Найди глубокую бизнес-информацию о компании '{company_name}'.{site_context} Меня интересует: последние новости и планы на 2026 год, стратегия развития, проблемы масштабирования или реструктуризации, фокус на обучение руководителей и развитие лидерства. Также найди ФИО топ-менеджеров (генеральный, коммерческий, HR директор)."

def run_deep_research(company_name: str, website: str) -> str:
    print(f"  🔍 Запуск Tavily Deep Research для: {company_name}...")
    tavily_client = get_tavily_client()
    if not tavily_client:
        print("  ❌ Ошибка Tavily API: ключ не задан")
        return None
    query = generate_search_query(company_name, website)
    try:
        response = tavily_client.search(
            query=query,
            search_depth="advanced", 
            include_answer=True,
            max_results=7
        )
        dossier = "### ИИ-Аналитика (Tavily)\n"
        if response.get("answer"):
            dossier += f"{response['answer']}\n\n"
        dossier += "### Найденные факты и источники:\n"
        for idx, result in enumerate(response.get("results", [])):
            dossier += f"**{idx+1}. {result.get('title', 'Без заголовка')}**\n"
            dossier += f"   *URL:* {result.get('url')}\n"
            dossier += f"   *Отрывок:* {result.get('content')}\n\n"
        return dossier
    except Exception as e:
        print(f"  ❌ Ошибка Tavily API: {e}")
        return None

def process_leads():
    print("🚀 Инициализация Tavily Research Agent...")
    tavily_client = get_tavily_client()
    if not tavily_client:
        print("❌ TAVILY_API_KEY не установлен, пропускаем OSINT.")
        return
    db: Session = SessionLocal()
    try:
        leads = db.query(Contact).filter(Contact.ai_pipeline_status == 'needs_osint').limit(3).all()
        if not leads:
            print("✅ Нет лидов для глубокого исследования.")
            return

        print(f"Найдено {len(leads)} компаний для глубокого исследования.")
        for lead in leads:
            company_name = lead.company or 'Неизвестно'
            website = lead.website or 'Неизвестен'
            
            # Set to running
            lead.ai_pipeline_status = 'osint_running'
            db.commit()

            print(f"\n=== Досье: {company_name} ===")
            dossier = run_deep_research(company_name, website)
            
            if dossier:
                lead.deep_dossier = dossier
                lead.ai_pipeline_status = 'needs_profiling'
                print("  💾 Досье сохранено в базу данных.")
            else:
                lead.ai_pipeline_status = 'needs_osint' # revert
                print("  ⚠️ Не удалось получить досье.")
            db.commit()
            time.sleep(2)
        print("\n✅ Сбор досье завершен!")
    finally:
        db.close()

if __name__ == "__main__":
    process_leads()