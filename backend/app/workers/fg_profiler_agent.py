import os
import sys
import time
import litellm
from litellm import completion
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.system_setting import SystemSetting

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
except ImportError:
    print("❌ Не найдена библиотека tenacity. Установите её: pip install tenacity")

# Используем мощную модель Pro (Gemini 3.1 Pro Preview) для глубокого анализа болей
API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
if API_KEY:
    litellm.api_key = API_KEY
else:
    print("❌ ОШИБКА: Ключи API не найдены, но продолжаем работу (LiteLLM может использовать fallback).")

REQUEST_DELAY = 1        # Минимальная пауза, так как мы на Tier 1

SYSTEM_PROMPT = """Ты — Senior SDR (Sales Development Representative) и бизнес-стратег в консалтинговой компании "FG Consulting". 
Твоя задача — изучить данные о компании-потенциальном клиенте и подготовить материалы для начала переговоров.

О нас (FG Consulting):
Мы специализируемся на внедрении системных изменений в корпоративное управление и обучение (продажи и лидерство). 
НАШ ФОКУС СЕЙЧАС: Продажа быстрых, точечных решений (Quick Wins), которые дают клиенту мгновенную пользу, "расшивают" узкие места и открывают двери для долгосрочных контрактов.

Твоя задача:
1. Изучить текст с официального сайта компании клиента и собранное досье.
2. Выделить 1-2 самые острые боли, релевантные нашему офферу. Обязательно рассмотри контекст УПРАВЛЕНЧЕСКОГО голода (нехватка сильных руководителей, проблемы при слияниях/диверсификации) и ПРОДАЖ.
3. Составить корпоративный словарь компании (как они называют свои продукты/услуги).
4. Разработать мощный ПРОДУКТОВЫЙ ХУК (предложение, от которого нельзя отказаться). Хук должен быть не обещанием "светлого будущего", а предложением решить конкретную проблему "здесь и сейчас", опираясь на инфоповод из досье или активность ЛПР (например, выступление или статью).
5. Предложить ОДИН конкретный, быстрый шаг (Quick Win). Используй свой интеллект для кастомизации решения. Это могут быть (но не ограничиваясь ими): тренинг, фасилитационная сессия, воркшоп, ассессмент (оценка), экспресс-аудит или любое другое компактное консалтинговое решение, идеально подходящее под их боль.
6. Написать драфт B2B холодного письма от лица FG Consulting.
   - Открыть письмо конкретным фактом из их новостей или публичной активности ЛПР (чтобы доказать глубокую подготовку).
   - Ударить в боль: "Обычно на этом этапе компании теряют деньги/сотрудников из-за...".
   - Предложить наш кастомизированный Quick Win (быстрый шаг).
   - Призыв к действию (CTA) — короткий 15-минутный созвон.
   - ЗАПРЕЩЕНО использовать IT-жаргон (например, TaaS, аутстаффинг). Используй слова "внешний партнер", "развитие управленческих компетенций".

Формат ответа — ТОЛЬКО Markdown разметка (без приветствий ИИ). Структура:
### 1. Возможные боли
### 2. Корпоративный словарь
### 3. Продуктовый Хук (Quick Win)
### 4. B2B Письмо
"""

class APIQuotaError(Exception):
    pass

@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=5, max=120),
    retry=retry_if_exception_type((APIQuotaError, litellm.exceptions.RateLimitError))
)
def call_llm(prompt, model, system_prompt=SYSTEM_PROMPT):
    try:
        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )
        return response.choices[0].message.content
    except litellm.exceptions.RateLimitError as e:
        print(f"\\n⏳ [TPM Limit] Превышена квота запросов (429). Скрипт засыпает перед повторной попыткой... {e}")
        raise APIQuotaError("Rate limit exceeded")
    except Exception as e:
        print(f"\\n❌ Ошибка LiteLLM: {e}")
        raise

def process_fg_leads():
    db: Session = SessionLocal()
    try:
        leads = db.query(Contact).filter(Contact.ai_pipeline_status == 'needs_profiling').limit(15).all()
        if not leads:
            print("✅ Нет новых лиды для обработки в fg_leads (или им еще не собрали досье).")
            return

        print(f"🚀 Начинаем профилирование {len(leads)} лидов (Pipeline: FG Consulting)...\n")

        # Fetch AI model from settings
        ai_model_setting = db.query(SystemSetting).filter_by(key="ai_model").first()
        selected_model = ai_model_setting.value if ai_model_setting and ai_model_setting.value else "gemini/gemini-3.1-pro-preview"
        print(f"Using AI Model: {selected_model}")

        from app.models.run import Run
        from app.models.run_setup import RunSetup

        for lead in leads:
            company_name = lead.company or 'Неизвестно'
            site_url = lead.website or 'Неизвестен'
            dossier_text = lead.deep_dossier or ''
            
            print(f"=== Обработка: {company_name} ===")

            run_setup = db.query(RunSetup).filter(RunSetup.run_id == lead.run_id).first()
            custom_system_prompt = SYSTEM_PROMPT
            if run_setup and run_setup.prompt_setup_text:
                custom_system_prompt = run_setup.prompt_setup_text
            
            prompt = f"""
            Компания: {company_name}
            Сайт: {site_url}
            Собранное досье на компанию (новости, факты, ЛПР):
            {dossier_text}
            """
            
            try:
                print(f"  🧠 Генерация аналитики ({selected_model})...")
                analysis_result = call_llm(prompt, model=selected_model, system_prompt=custom_system_prompt)
                
                # Split result to get letter out if possible, but for now store it all in body
                # In Ai-Biz-OS we create an EmailDraft
                draft = EmailDraft(
                    run_id=lead.run_id,
                    contact_id=lead.id,
                    to_email=lead.email or 'unknown@example.com',
                    subject=f"Предложение от FG Consulting для {company_name}",
                    body=analysis_result,
                    status="draft",
                    review_status="pending",
                    pipeline_source="fg_profiler"
                )
                db.add(draft)
                lead.ai_pipeline_status = 'profiled'
                db.commit()
                print(f"  💾 Черновик сохранен в БД.")
            except Exception as e:
                print(f"  ❌ Ошибка при генерации для {company_name}: {e}")
                
            print(f"  ⏳ Пауза {REQUEST_DELAY} сек. перед следующим лидом...")
            time.sleep(REQUEST_DELAY)

        print("\n✅ Партия успешно обработана!")
    finally:
        db.close()

if __name__ == "__main__":
    process_fg_leads()