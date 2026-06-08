import os
import sys
import time
from dotenv import load_dotenv
load_dotenv()

from app.db import SessionLocal
from app.models.contact import Contact
from app.models.contact_personalization import ContactPersonalization
from app.models.run import Run
from app.models.run_setup import RunSetup
from app.models.run_outreach_context import RunOutreachContext
from app.models.run_master_email_variant import RunMasterEmailVariant
from app.models.email_draft import EmailDraft
from app.models.system_setting import SystemSetting
from app.models.template_variable import TemplateVariable

# Import background tasks
from app.workers.tavily_dossier_agent import process_leads as run_tavily_dossier
from app.workers.fg_profiler_agent import process_fg_leads as run_gemini_profiler

BATCH_SIZE = 15     # Сколько лидов берем за один цикл
PAUSE_BETWEEN_BATCHES = 60 # Пауза в секундах между пачками

def get_remaining_leads():
    """Считает, сколько осталось лидов со статусом needs_osint или needs_profiling"""
    db = SessionLocal()
    try:
        count = db.query(Contact).filter(Contact.ai_pipeline_status.in_(['needs_osint', 'needs_profiling'])).count()
        return count
    finally:
        db.close()

def main():
    print("🌙 Запуск ночного Оркестратора Ai-Biz-OS + FG LeadGen 🌙")
    
    while True:
        remaining = get_remaining_leads()
        print(f"\n📊 В очереди осталось лидов: {remaining}")
        
        if remaining == 0:
            print("🎉 База полностью обработана. Спокойной ночи!")
            break
            
        print("\n--- ЭТАП 1: Разведка (Tavily) ---")
        for _ in range(5):
            run_tavily_dossier()
        
        print("\n--- ЭТАП 2: Генерация писем (Gemini Pro) ---")
        run_gemini_profiler()
        
        print(f"\n⏳ Цикл завершен. Отдыхаем {PAUSE_BETWEEN_BATCHES} секунд для сброса счетчиков RPM/TPM...")
        time.sleep(PAUSE_BETWEEN_BATCHES)

if __name__ == "__main__":
    main()