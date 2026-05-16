import requests
import sqlite3
import re

def classify_user_intent(user_query):
    """
    Этап 1: Классификатор интента. Помогает понять, какой раздел ВПО-1 нужен пользователю.
    Возвращает имя категории.
    """
    prompt = f"""Ты — классификатор запросов к статистическому отчету вуза ВПО-1.
Проанализируй вопрос пользователя и определи, к какой категории данных он относится.

Категории на выбор:
1. TOTAL_STUDENTS — если вопрос про ОБЩУЮ численность студентов, весь контингент вуза, сколько ВСЕГО учится на текущий момент (все курсы вместе).
2. ADMISSION — если вопрос про ПРИЕМ, сколько ПРИНЯТО, зачислено, сколько первокурсников в этом году.
3. GRADUATES — если вопрос про ВЫПУСК, сколько выпустилось, окончило вуз, получили дипломы.
4. PERSONNEL — если вопрос про преподавателей, сотрудников, профессоров, персонал, кадры.
5. GENERAL — любые другие вопросы (про направления, общую информацию о вузе, адреса, лицензии, титульный лист).

ОТВЕТЬ ТОЛЬКО ИМЕНЕМ КАТЕГОРИИ И НИЧЕМ БОЛЬШЕ. Без лишних слов и знаков препинания.

ВОПРОС ПОЛЬЗОВАТЕЛЯ: {user_query}
КАТЕГОРИЯ:"""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen2.5:14b",  # Можно использовать модель полегче, если есть (например, qwen2.5:7b или 3b)
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0} # Жесткий детерминированный ответ
            },
            timeout=30
        )
        intent = response.json().get('response', 'GENERAL').strip().upper()
        # Чистим ответ от возможных галлюцинаций модели
        for valid_intent in ["TOTAL_STUDENTS", "ADMISSION", "GRADUATES", "PERSONNEL"]:
            if valid_intent in intent:
                return valid_intent
        return "GENERAL"
    except Exception as e:
        print(f"[LLM Classify Error]: {e}")
        return "GENERAL"


def get_analysis_from_qwen(report_id, user_query):
    """
    Этап 2: Извлекает текст из БД, классифицирует интент, вырезает точный раздел 
    и отправляет сфокусированный контекст в Ollama.
    """
    conn = sqlite3.connect("vpo_reports.db")
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT full_text FROM document_contents WHERE report_id = ?", (report_id,))
        row = cursor.fetchone()
        if not row:
            return "❌ Ошибка: Текст документа не найден в базе данных."
        document_text = row[0]
    except Exception as e:
        return f"❌ Ошибка БД: {e}"
    finally:
        conn.close()

    # Понимаем, что хочет пользователь, с помощью LLM-классификатора
    intent = classify_user_intent(user_query)
    print(f"[LOG] Определен интент пользователя: {intent}")

    # Размер окна контекста (~12 000 - 15 000 токенов)
    window_size = 55000 
    doc_text_lower = document_text.lower()
    match_index = -1

    # Ищем точку привязки в тексте в зависимости от распознанного намерения
    if intent == "TOTAL_STUDENTS":
        # Общий контингент студентов в ВПО-1 собирается в Разделе 2.1 (обычно графы после приема)
        # Также ищем маркеры "строка 01" или "всего", чтобы зацепиться за итоговые таблицы
        for kw in ["раздел 2.1", "распределение студентов по направлениям", "численность студентов"]:
            idx = doc_text_lower.find(kw)
            if idx != -1:
                match_index = idx
                break

    elif intent == "ADMISSION":
        # Прием студентов — это начало Раздела 2.1 ("Принято всего") или специализированные таблицы
        for kw in ["принято человек", "принято, единиц", "раздел 2.1", "прием"]:
            idx = doc_text_lower.find(kw)
            if idx != -1:
                match_index = idx
                break

    elif intent == "GRADUATES":
        # Выпускники находятся чуть дальше по Разделу 2.1 (имеют маркеры выпуска) или в Разделе 2.2
        for kw in ["выпуск всего", "выпущено", "раздел 2.2", "выпускников"]:
            idx = doc_text_lower.find(kw)
            if idx != -1:
                match_index = idx
                break

    elif intent == "PERSONNEL":
        # Профессорско-преподавательский состав — это Раздел 3
        for kw in ["раздел 3", "персонал организации", "численность работников", "профессорско"]:
            idx = doc_text_lower.find(kw)
            if idx != -1:
                match_index = idx
                break

    # Вырезаем контекст на основе найденного индекса
    if match_index != -1:
        # Отступаем на 2000 символов назад, чтобы гарантированно захватить шапку таблицы/раздела
        start_pos = max(0, match_index - 2000)
        context = document_text[start_pos:start_pos + window_size]
        print(f"[LOG] Вырезано умное окно вокруг раздела. Позиция: {start_pos}, размер: {window_size}")
    else:
        # План Б: Если зацепиться не удалось, используем обычный поиск совпадений по словам из самого запроса
        words = [w for w in user_query.lower().split() if len(w) > 4]
        for word in words:
            idx = doc_text_lower.find(word)
            if idx != -1:
                match_index = idx
                break
        
        if match_index != -1:
            start_pos = max(0, match_index - 3000)
            context = document_text[start_pos:start_pos + window_size]
            print(f"[LOG] Раздел не определен жестко, контекст вырезан по слову '{document_text[match_index:match_index+10]}'")
        else:
            context = document_text[:window_size]
            print("[LOG] Привязок не найдено. Передано начало документа.")

    # Строим итоговый системный промпт
    full_prompt = f"""Ты — ведущий аналитический помощник сотрудника университета. 
Перед тобой вырезанный фрагмент официального статистического отчета формы ВПО-1.
Используй его, чтобы дать точный и математически выверенный ответ на вопрос пользователя.

ВАЖНОЕ РАЗЛИЧИЕ В ТЕРМИНАХ ВПО-1:
- "Принято" / "Прием" — это только те, кто поступил в этом году (1 курс).
- "Численность студентов" / "Контингент" — это сколько ВСЕГО учится в вузе на данный момент на всех курсах. Не путай эти показатели!
- Итоговые строки по всему университету находятся в строках с пометкой "Всего" или кодом строки "01".

КОНТЕКСТ ДОКУМЕНТА:
{context}

ВОПРОС ПОЛЬЗОВАТЕЛЯ: 
{user_query}

ИНСТРУКЦИЯ ПО ОТВЕТУ:
1. Сначала найди строки "Всего" или "01" в таблицах (|...|), относящихся к сути вопроса.
2. Отвечай строго по существу, приводи точные цифры. Если таблица разбита по формам обучения (очная, заочная), укажи их, если это требуется.
3. Если во фрагменте нет точных данных для ответа на этот конкретный вопрос, прямо напиши: "В предоставленном фрагменте документа нет точных данных для ответа".
4. Ответ формулируй исключительно на русском языке."""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "qwen2.5:14b", 
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "num_ctx": 24576,      # Выделяем увеличенное контекстное окно в Ollama под наше большое окно
                    "temperature": 0.2     # Низкая температура снижает шанс галлюцинаций в цифрах
                }
            },
            timeout=150
        )
        return response.json().get('response', "Нейросеть прислала пустой ответ.")
    except Exception as e:
        return f"❌ Ошибка Ollama: {e}. Проверьте работу сервера Ollama."