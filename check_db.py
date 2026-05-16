import sqlite3

conn = sqlite3.connect("vpo_reports.db")
cursor = conn.cursor()

# Достаем последний сохраненный текст
cursor.execute("SELECT full_text FROM document_contents ORDER BY id DESC LIMIT 1")
row = cursor.fetchone()

if row:
    text = row[0]
    print(f"Общая длина сохраненного текста: {len(text)} символов.")
    
    # Ищем, упоминаются ли вообще студенты в сохраненном Markdown
    import re
    matches = [m.start() for m in re.finditer("численность", text, re.IGNORECASE)]
    print(f"Слово 'численность' найдено {len(matches)} раз.")
    
    # Выведем первые 2000 символов для проверки структуры
    print("\n--- НАЧАЛО ДОКУМЕНТА ---")
    print(text[:2000])
else:
    print("База данных пуста!")

conn.close()