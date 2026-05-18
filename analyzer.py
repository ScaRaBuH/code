import requests
import sqlite3

def classify_intent(query):
    """Определяет тип задачи пользователя"""
    prompt = f"""Классифицируй запрос пользователя к документам.
Запрос: {query}
Выбери ОДНУ категорию:
- SEARCH (поиск факта/цифры)
- CALCULATE (математическое действие, расчет суммы, сравнение чисел)
- ANOMALIES (поиск ошибок, несоответствий, странных данных)
- ANALYZE (общие выводы, тенденции)
- GENERAL (другие варианты)
Ответь только одним словом."""
    
    try:
        res = requests.post("http://localhost:11434/api/generate", 
                            json={"model": "qwen2.5:14b", "prompt": prompt, "stream": False})
        return res.json().get('response', 'GENERAL').strip().upper()
    except:
        return "GENERAL"

def get_analysis_from_qwen(report_ids, user_query):
    intent = classify_intent(user_query)
    
    # Собираем релевантные разбиения из всех выбранных документов
    conn = sqlite3.connect("reports.db")
    cursor = conn.cursor()
    
    all_context = ""
    for r_id in report_ids:
        # Простой поиск по ключевым словам в кусках 
        keywords = [w for w in user_query.split() if len(w) > 4]
        if keywords:
            search_clause = " OR ".join([f"chunk_text LIKE '%{k}%'" for k in keywords])
            cursor.execute(f"SELECT chunk_text FROM document_chunks WHERE report_id = ? AND ({search_clause}) LIMIT 3", (r_id,))
        else:
            cursor.execute("SELECT chunk_text FROM document_chunks WHERE report_id = ? LIMIT 2", (r_id,))
        
        chunks = cursor.fetchall()
        report_name = cursor.execute("SELECT filename FROM reports WHERE id=?", (r_id,)).fetchone()[0]
        all_context += f"\n--- ДАННЫЕ ИЗ ФАЙЛА {report_name} ---\n" + "\n".join([c[0] for c in chunks])
    
    conn.close()

    # Выбор специализированного промпта
    templates = {
        "SEARCH": "Твоя цель — найти точное значение. Выдай цифру и название таблицы.",
        "CALCULATE": "Твоя цель — произвести расчет. Покажи ход решения: какие числа ты взял и как сложил/сравнил.",
        "ANOMALIES": "Внимательно проверь данные на логические ошибки (например, сумма подпунктов не равна итогу).",
        "ANALYZE": "Сделай краткий аналитический вывод на основе данных.",
        "GENERAL": "Просто ответь на вопрос, опираясь на текст."
    }

    full_prompt = f"""Ты — эксперт-аналитик по отчетам.
ИНСТРУКЦИЯ: {templates.get(intent, templates['GENERAL'])}
Используй данные ниже для ответа.

КОНТЕКСТ:
{all_context}

ВОПРОС: {user_query}
ОТВЕТ (на русском языке):"""

    try:
        response = requests.post("http://localhost:11434/api/generate", 
            json={
                "model": "qwen2.5:14b", 
                "prompt": full_prompt, 
                "stream": False,
                "options": {"num_ctx": 32000, "temperature": 0.2}
            })
        return f"**[Тип запроса: {intent}]**\n\n{response.json().get('response')}"
    except Exception as e:
        return f"Ошибка: {e}"