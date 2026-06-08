import sqlite3
import re

import faiss
import numpy as np

from embedding_manager import get_embedder, bytes_to_vector


def extract_section_fragment(text: str, section_number: str) -> str:
    """Вырезает из текста чанка фрагмент, относящийся к указанному разделу.
    Ищет вхождение section_number, затем обрезает текст до начала следующего раздела.
    Если раздел не найден, возвращает первые 5000 символов. Максимум — 12 000 символов."""
    pattern = re.compile(
        rf"{re.escape(section_number)}[\s\.]", re.IGNORECASE
    )
    match = pattern.search(text)
    if not match:
        return text[:5000]

    fragment = text[match.start():]

    next_section = re.search(r"\n(?:#+\s*)?\d+(?:\.\d+)*", fragment[50:])
    if next_section:
        fragment = fragment[: next_section.start()]

    return fragment[:12000]


class FaissRetriever:
    """Семантический ретривер на основе FAISS IndexFlatIP (косинусное сходство).
    При инициализации загружает все чанки с эмбеддингами из БД и строит индекс в памяти."""

    def __init__(self):
        """Инициализирует индекс FAISS и загружает чанки из базы данных."""
        self.index = None
        self.chunk_map = []
        self.load_from_db()

    def load_from_db(self):
        """Загружает все чанки с эмбеддингами из таблицы document_chunks
        и строит FAISS-индекс для поиска по косинусному сходству."""
        conn = sqlite3.connect("reports.db")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT report_id, chunk_order, chunk_text, embedding
            FROM document_chunks
            WHERE embedding IS NOT NULL
            ORDER BY report_id, chunk_order
        """)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return

        vectors = []
        for report_id, chunk_order, chunk_text, embedding in rows:
            vectors.append(bytes_to_vector(embedding))
            self.chunk_map.append({
                "report_id": report_id,
                "chunk_order": chunk_order,
                "chunk_text": chunk_text,
            })

        vectors = np.array(vectors, dtype=np.float32)
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

        print(f"FAISS loaded: {len(vectors)} chunks")

    def search_by_section(self, section, report_ids=None):
        """Ищет чанки, содержащие точное вхождение номера раздела.
        Использует регулярное выражение с negative lookbehind/lookahead, чтобы не захватывать
        номера вида «12.1» или «2.10». Фильтрует по report_ids, если список передан.
        Возвращает список результатов со score=1.0."""
        pattern = re.compile(rf"(?<!\d){re.escape(section)}(?!\d)")
        results = []

        for chunk in self.chunk_map:
            if report_ids and chunk["report_id"] not in report_ids:
                continue
            if pattern.search(chunk["chunk_text"]):
                results.append({
                    "score": 1.0,
                    "report_id": chunk["report_id"],
                    "chunk_order": chunk["chunk_order"],
                    "chunk_text": chunk["chunk_text"],
                })

        return results

    def search(self, query, report_ids=None, top_k=10):
        """Выполняет семантический поиск по запросу query с помощью FAISS.
        Кодирует запрос в эмбеддинг, ищет top_k ближайших чанков в индексе,
        затем фильтрует результаты по report_ids (если переданы).
        Возвращает список словарей с полями score, report_id, chunk_order, chunk_text."""
        if self.index is None:
            return []

        embedder = get_embedder()
        query_vector = embedder.encode(query, normalize_embeddings=True)
        query_vector = np.array([query_vector], dtype=np.float32)

        scores, ids = self.index.search(query_vector, top_k)

        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx == -1:
                continue
            chunk = self.chunk_map[idx]
            if report_ids and chunk["report_id"] not in report_ids:
                continue
            results.append({
                "score": float(score),
                "report_id": chunk["report_id"],
                "chunk_order": chunk["chunk_order"],
                "chunk_text": chunk["chunk_text"],
            })

        return results