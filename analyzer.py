import re
import sqlite3
import os
import streamlit as st
from llama_cpp import Llama
from table_retriever import TableRetriever
from reranker import get_reranker
from retriever import FaissRetriever, extract_section_fragment


@st.cache_resource
def load_llm() -> Llama:
    """Загружает языковую модель Qwen из файла .gguf и кэширует её на весь сеанс.
    Путь к модели определяется относительно расположения текущего файла."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "models", "Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf")
    return Llama(
        model_path=path,
        n_gpu_layers=28,
        n_ctx=32768,
        n_threads=6,
        n_batch=512,
        flash_attn=True,
        verbose=False,
    )


@st.cache_resource
def load_table_retriever():
    """Создаёт и кэширует экземпляр TableRetriever для поиска по таблицам."""
    return TableRetriever()


@st.cache_resource
def load_retriever():
    """Создаёт и кэширует экземпляр FaissRetriever для семантического поиска по чанкам."""
    return FaissRetriever()


_VALID_INTENTS = ("SEARCH", "CALCULATE", "ANOMALIES", "ANALYZE", "STRUCTURE", "GENERAL")

_META_RE = re.compile(r"###\s+МЕТАДАННЫЕ:.*?###\n+", re.DOTALL)
_PAGE_IN_META_RE = re.compile(r"Стр\.\s*(\d+)")
_SECTION_QUERY_RE = re.compile(r"(\d+(?:\.\d+)+)")

_INTENT_PROMPT = """
SEARCH - поиск факта
CALCULATE - вычисления
ANOMALIES - поиск ошибок
ANALYZE - анализ
STRUCTURE - структура документа
GENERAL - остальное

Запрос: {query}
Ответ:
"""

_SYSTEM_PROMPT = """Ты аналитик университета. Отвечай ТОЛЬКО на основе предоставленного контекста.

Строгие правила:
- Используй исключительно информацию из раздела «Контекст» ниже.
- Если ответ на вопрос не содержится в контексте — прямо сообщи об этом.
- Не добавляй факты, данные или рассуждения из общих знаний.
- Не придумывай цифры, названия и даты.
- Когда готов дать финальный ответ, напиши маркер ###ОТВЕТ### и после него — сам ответ.

Тип запроса: {intent}

Контекст:
{context}

Вопрос:
{query}

###ОТВЕТ###"""


def rerank_results(query, results, top_k=100):
    """Переранжирует список результатов поиска с помощью CrossEncoder-реранкера.
    Добавляет поле rerank_score к каждому результату, сортирует по убыванию
    и возвращает не более top_k лучших."""
    if not results:
        return []

    reranker = get_reranker()
    pairs = [(query, r["chunk_text"][:2000]) for r in results]
    scores = reranker.predict(pairs)

    for r, score in zip(results, scores):
        r["rerank_score"] = float(score)

    results.sort(key=lambda x: x["rerank_score"], reverse=True)
    return results[:top_k]


def is_table_query(query):
    """Определяет, связан ли запрос с табличными данными.
    Проверяет наличие ключевых слов, характерных для вопросов о численности,
    долях, категориях обучающихся и финансовых показателях."""
    keywords = [
        "сколько", "численность", "количество", "обучающихся",
        "магистрат", "магистр", "бакалавр", "аспирант",
        "стипенд", "доля", "процент", "всего",
    ]
    return any(k in query.lower() for k in keywords)


def get_intent(llm, user_query):
    """Определяет тип запроса пользователя (intent).
    Сначала проверяет запрос по регулярным выражениям для быстрого распознавания
    STRUCTURE и SEARCH, затем при необходимости обращается к языковой модели.
    Возвращает одну из констант: SEARCH, CALCULATE, ANOMALIES, ANALYZE, STRUCTURE, GENERAL."""
    q = user_query.lower()

    if re.search(r"(оглавлен|структур)", q):
        return "STRUCTURE"

    if re.search(
        r"(что содержится в разделе|что находится в разделе"
        r"|что указано в разделе|содержимое раздела)", q
    ):
        return "SEARCH"

    prompt = _INTENT_PROMPT.format(query=user_query)
    try:
        out = llm(prompt, max_tokens=8, temperature=0)
        raw = out["choices"][0]["text"].strip().upper()
        for v in _VALID_INTENTS:
            if v in raw:
                return v
    except Exception:
        pass

    return "GENERAL"


def _strip_metadata(text):
    """Удаляет блок метаданных формата ### МЕТАДАННЫЕ: ... ### из текста чанка."""
    return _META_RE.sub("", text)


def _page_from_metadata(text):
    """Извлекает номер первой страницы из блока метаданных чанка.
    Возвращает целое число или 0, если метаданные не найдены."""
    m = _PAGE_IN_META_RE.search(text[:300])
    return int(m.group(1)) if m else 0


def extract_headers_from_chunks(chunks):
    """Извлекает все заголовки Markdown (h1–h6) из списка чанков документа.
    Возвращает список словарей с полями level, title и page."""
    headers = []
    md_header = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    for chunk in chunks:
        text = _strip_metadata(chunk[1])
        page = _page_from_metadata(chunk[1]) or chunk[0]

        for m in md_header.finditer(text):
            headers.append({
                "level": len(m.group(1)),
                "title": m.group(2).strip(),
                "page": page,
            })

    return headers


def build_structure_context(report_name, chunks):
    """Строит текстовое представление структуры документа в виде дерева заголовков.
    Используется для ответа на запросы типа STRUCTURE (оглавление, структура)."""
    headers = extract_headers_from_chunks(chunks)
    lines = [f"=== СТРУКТУРА {report_name} ==="]

    for h in headers:
        indent = "  " * (h["level"] - 1)
        lines.append(f'{indent}{h["title"]} (стр. {h["page"]})')

    return "\n".join(lines)


def faiss_results_to_context(report_name, results):
    """Формирует единую строку контекста из списка найденных чанков.
    Ограничивает суммарный объём контекста 60 000 символами, чтобы не превысить
    контекстное окно модели."""
    MAX_CONTEXT_CHARS = 60_000
    parts = []
    total_size = 0

    for r in results:
        block = (
            f"\n=== {report_name}\n"
            f"Чанк {r['chunk_order']}\n"
            f"===\n\n"
            f"{r['chunk_text']}\n"
        )
        if total_size + len(block) > MAX_CONTEXT_CHARS:
            break
        parts.append(block)
        total_size += len(block)

    return "\n".join(parts)


def _deduplicate(results, key_fn):
    """Удаляет дублирующиеся результаты из списка по ключу, вычисляемому функцией key_fn.
    Сохраняет порядок и оставляет только первое вхождение каждого уникального ключа."""
    seen = set()
    unique = []
    for r in results:
        sig = key_fn(r)
        if sig not in seen:
            seen.add(sig)
            unique.append(r)
    return unique


def _collect_context_for_report(report_id, user_query, intent, cursor):
    """Собирает текстовый контекст для одного документа по его report_id.
    В зависимости от intent выбирает стратегию поиска:
    - STRUCTURE: строит дерево заголовков из всех чанков;
    - запрос с номером раздела: точечный поиск по section_number;
    - остальное: семантический поиск с опциональным поиском по таблицам и реранкингом.
    Возвращает строку контекста, готовую к подстановке в промпт."""
    cursor.execute(
        "SELECT chunk_order, chunk_text, COALESCE(has_tables, 0) "
        "FROM document_chunks "
        "WHERE report_id = ? "
        "ORDER BY chunk_order",
        (report_id,),
    )
    chunks = cursor.fetchall()

    row = cursor.execute(
        "SELECT filename FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    report_name = row[0] if row else str(report_id)

    if intent == "STRUCTURE":
        return build_structure_context(report_name, chunks)

    retriever = load_retriever()

    # ── Поиск по номеру раздела ───────────────────────────────────────────────
    section_match = re.search(r"(\d+(?:\.\d+)*)", user_query)
    if section_match:
        section = section_match.group(1)
        print("\nSECTION INFO:\n")

        raw_results = retriever.search_by_section(section, report_ids=[report_id])
        filtered = []
        for r in raw_results:
            fragment = extract_section_fragment(r["chunk_text"], section)
            print(f"\nSECTION FRAGMENT:\n{fragment[:3000]}\n")
            filtered.append({
                "score": r["score"],
                "report_id": r["report_id"],
                "chunk_order": r["chunk_order"],
                "chunk_text": fragment,
            })

        results = _deduplicate(filtered, key_fn=lambda r: r["chunk_text"][:1000])

    # ── Семантический поиск ───────────────────────────────────────────────────
    else:
        table_results = []
        if is_table_query(user_query):
            table_retriever = load_table_retriever()
            # Запрос с запасом
            table_results = table_retriever.search(
                user_query, report_ids=[report_id], top_k=100
            )
            print("\nTABLE SEARCH\n")
            for r in table_results:
                print(f"  table chunk={r['chunk_order']} score={r['score']:.4f}")

        # Аналогично — берём с запасом, чтобы после фильтрации осталось достаточно
        text_results = retriever.search(
            user_query, report_ids=[report_id], top_k=100
        )

        results = [
            {
                "score": r["score"],
                "report_id": r["report_id"],
                "chunk_order": r["chunk_order"],
                "chunk_text": r["table_text"],
            }
            for r in table_results
        ]
        results.extend(text_results)

        # Убеждаемся, что все результаты принадлежат нужному отчёту
        results = [r for r in results if r["report_id"] == report_id]

        results = _deduplicate(
            results,
            key_fn=lambda r: str(r["chunk_order"]) + r["chunk_text"][:500],
        )
        results = rerank_results(user_query, results, top_k=100)

        print("\nRERANK RESULTS")
        for r in results:
            print(f"  chunk={r['chunk_order']} rerank={r['rerank_score']:.4f}")
        print()

    print("=" * 50)
    print("QUERY:", user_query)
    print("REPORT:", report_name)
    for r in results:
        print(
            f"  chunk={r['chunk_order']}"
            f"  score={r.get('score', 0):.4f}"
            f"  rerank={r.get('rerank_score', 0):.4f}"
        )
    print("=" * 50)

    return faiss_results_to_context(report_name, results)


def get_analysis_from_qwen(llm, report_ids, user_query):
    """Главная точка входа для анализа запроса пользователя.
    Определяет intent, собирает контекст по каждому из выбранных документов,
    формирует промпт и получает ответ от языковой модели.
    Из сырого вывода удаляет блоки размышлений (<think> и текст до маркера ###ОТВЕТ###).
    Возвращает финальный текст ответа."""
    intent = get_intent(llm, user_query)

    conn = sqlite3.connect("reports.db")
    cursor = conn.cursor()
    contexts = []

    for report_id in report_ids:
        try:
            ctx = _collect_context_for_report(report_id, user_query, intent, cursor)
            if ctx:
                contexts.append(ctx)
        except Exception as exc:
            print(f"Ошибка при обработке report_id={report_id}: {exc}")

    conn.close()

    full_context = "\n\n".join(contexts)

    print("SELECTED REPORT IDS:", report_ids)
    print("CONTEXT LENGTH:", len(full_context))

    if not full_context.strip():
        return "По выбранным документам релевантная информация не найдена."

    prompt = _SYSTEM_PROMPT.format(
        intent=intent,
        context=full_context,
        query=user_query,
    )

    print()
    print("=" * 80)
    print("FINAL CONTEXT")
    print("=" * 80)
    print(full_context[:5000])
    print("=" * 80)
    print()

    out = llm(prompt, max_tokens=2048, temperature=0.1, repeat_penalty=1.1)
    raw_answer = out["choices"][0]["text"]
    print(f"\nRAW MODEL OUTPUT:\n{raw_answer}\n")

    # Убираем блоки <think>...</think>
    raw_answer = re.sub(r"<think>.*?</think>", "", raw_answer, flags=re.DOTALL)

    # Если модель повторила маркер внутри ответа — берём текст после последнего вхождения
    marker = "###ОТВЕТ###"
    if marker in raw_answer:
        raw_answer = raw_answer.split(marker)[-1]

    return raw_answer.strip()