import pandas as pd
import os

def create_test_excel():
    data = [
        {
            "Компания": "Сбер",
            "Web": "https://www.sberbank.ru",
            "Имя": "Герман",
            "Фамилия": "Греф",
            "Рабочий email": "test_gref@sberbank.ru",
            "Должность (контакт)": "CEO"
        },
        {
            "Компания": "Яндекс",
            "Web": "https://yandex.ru",
            "Имя": "Артем",
            "Фамилия": "Савиновский",
            "Рабочий email": "test_artem@yandex-team.ru",
            "Должность (контакт)": "Генеральный директор"
        },
        {
            "Компания": "FG Consulting",
            "Web": "https://www.fgconsulting.ru/",
            "Имя": "Тест",
            "Фамилия": "FG",
            "Рабочий email": "test@fgconsulting.ru",
            "Должность (контакт)": "HR Director"
        }
    ]
    
    df = pd.DataFrame(data)
    file_path = r"C:\Users\user\AI-Biz-OS\test_leads.xlsx"
    df.to_excel(file_path, index=False)
    print(f"Test file created at {file_path}")

if __name__ == "__main__":
    create_test_excel()
