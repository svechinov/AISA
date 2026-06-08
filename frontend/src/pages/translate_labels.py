import sys
content = open(r'C:\Users\user\AI-Biz-OS\frontend\src\pages\AiBizOsHumanUI.jsx', encoding='utf-8').read()
content = content.replace('label="OSINT Prompt"', 'label="Поисковый OSINT-запрос (Tavily)"')
content = content.replace('label="Deep OSINT (Lead/Contact extraction)"', 'label="Глубокий OSINT (Поиск ЛПР)"')
content = content.replace('label="Reasoning (Brainstorm hooks & angles)"', 'label="AI-логика (Хуки и углы)"')
content = content.replace('label="Drafting (Email generator)"', 'label="Генерация писем (Драфт)"')
content = content.replace('label="Company Search Prompt"', 'label="Запрос поиска компаний (Источники)"')
open(r'C:\Users\user\AI-Biz-OS\frontend\src\pages\AiBizOsHumanUI.jsx', 'w', encoding='utf-8').write(content)
