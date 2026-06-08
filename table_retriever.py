import sqlite3

import faiss
import numpy as np

from embedding_manager import get_embedder, bytes_to_vector


class TableRetriever:
    """Семантический ретривер для поиска по извлечённым Markdown-таблицам.
    Работает аналогично FaissRetriever, но использует отдельную таблицу document_tables,
    в которой хранятся только табличные фрагменты с собственными эмбеддингами."""

    def __init__(self):
        """Инициализирует индекс FAISS и загружает таблицы из базы данных."""
        self.index = None
        self.tables = []
        self.load()

    def load(self):
        """Загружает все записи из таблицы document_tables (только с эмбеддингами)
        и строит FAISS-индекс IndexFlatIP для поиска по косинусному сходству."""
        conn = sqlite3.connect("reports.db")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT report_id, chunk_order, table_text, embedding
            FROM document_tables
            WHERE embedding IS NOT NULL
        """)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return

        vectors = []
        for report_id, chunk_order, table_text, embedding in rows:
            vectors.append(bytes_to_vector(embedding))
            self.tables.append({
                "report_id": report_id,
                "chunk_order": chunk_order,
                "table_text": table_text,
            })

        vectors = np.array(vectors, dtype=np.float32)
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

    def search(self, query, report_ids=None, top_k=10):
        """Выполняет семантический поиск по таблицам документов.
        Кодирует запрос в эмбеддинг, ищет top_k ближайших таблиц в индексе,
        затем фильтрует результаты по report_ids (если переданы).
        Возвращает список словарей с полями score, report_id, chunk_order, table_text."""
        if self.index is None:
            return []

        embedder = get_embedder()
        q = embedder.encode(query, normalize_embeddings=True)
        scores, ids = self.index.search(np.array([q], dtype=np.float32), top_k)

        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx == -1:
                continue
            table = self.tables[idx]
            if report_ids and table["report_id"] not in report_ids:
                continue
            results.append({"score": float(score), **table})

        return results