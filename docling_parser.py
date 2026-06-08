import os
import re
import sqlite3

import fitz  # PyMuPDF
from docling.document_converter import DocumentConverter
from embedding_manager import create_embedding


# ── Утилиты ───────────────────────────────────────────────────────────────────

def _clean_markdown(text: str) -> str:
    """Очищает Markdown-текст от артефактов, которые оставляет Docling:
    удаляет тройные и более пустые строки, убирает пробелы в конце каждой строки."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


# Разделительная строка Markdown-таблицы: | --- | :---: | ----: |
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:]+\|", re.MULTILINE)


def _has_markdown_table(text: str) -> bool:
    """Проверяет, содержит ли текст хотя бы одну Markdown-таблицу
    по наличию строки-разделителя вида | --- | :---: |."""
    return bool(_TABLE_SEP_RE.search(text))


def _fitz_fallback(pdf_path: str) -> str:
    """Резервный метод извлечения текста из PDF через PyMuPDF (fitz).
    Используется, если Docling завершился с ошибкой. Возвращает plain-текст
    всех страниц или сообщение об ошибке."""
    try:
        doc = fitz.open(pdf_path)
        pages_text = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(t for t in pages_text if t.strip())
    except Exception:
        return "[Контент страниц недоступен: ошибка резервного извлечения]"


def extract_tables(markdown_text):
    """Извлекает все Markdown-таблицы из текста чанка.
    Таблица распознаётся как последовательность строк, начинающихся с «|».
    Таблицы длиннее MAX_TABLE_SIZE символов разбиваются на части."""
    MAX_TABLE_SIZE = 5000
    raw_tables = []
    current_table = []

    for line in markdown_text.splitlines():
        if line.strip().startswith("|"):
            current_table.append(line)
        else:
            if len(current_table) >= 3:
                raw_tables.append("\n".join(current_table))
            current_table = []

    if len(current_table) >= 3:
        raw_tables.append("\n".join(current_table))

    tables = []
    for table in raw_tables:
        if len(table) > MAX_TABLE_SIZE:
            for i in range(0, len(table), MAX_TABLE_SIZE):
                tables.append(table[i : i + MAX_TABLE_SIZE])
        else:
            tables.append(table)

    return tables


def extract_sections(md_text: str):
    """Извлекает нумерованные разделы из Markdown-текста документа.
    Распознаёт как заголовки вида «## 1.2 Название», так и строки вида «1.2 Название».
    Отфильтровывает мусор из таблиц (строки с «код», «мбит», «кбит»,
    короткие заголовки, строки с диапазонами через дефис).
    Возвращает список кортежей (номер_раздела, заголовок) без дублей."""
    sections = []
    seen = set()

    for line in md_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Заголовок markdown
        m = re.match(r"^#+\s*(\d+(?:\.\d+){1,3})\s+(.+)$", line)
        if not m:
            # Обычный заголовок раздела
            m = re.match(r"^(\d+(?:\.[1-9]\d*){1,3})\s+(.+)$", line)
        if not m:
            continue

        sec_num = m.group(1).strip()
        sec_title = m.group(2).strip()
        title_l = sec_title.lower()

        # Фильтрация мусора
        if any(kw in title_l for kw in ("код", "мбит", "кбит")):
            continue
        if len(sec_title) < 15:
            continue
        if re.match(r"^\d+(\.\d+)?\s*[-–]", sec_title):
            continue

        key = (sec_num, sec_title)
        if key in seen:
            continue

        seen.add(key)
        sections.append((sec_num, sec_title))

    return sections


# ── Схема БД ──────────────────────────────────────────────────────────────────

def _ensure_schema(cursor: sqlite3.Cursor) -> None:
    """Создаёт все необходимые таблицы в базе данных, если они ещё не существуют:
    reports, document_chunks, document_tables, sections.
    Также добавляет колонку embedding в document_chunks при её отсутствии (миграция)."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT,
            report_year INTEGER,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id   INTEGER,
            chunk_order INTEGER,
            chunk_text  TEXT,
            has_tables  INTEGER DEFAULT 0,
            embedding   BLOB,
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_tables (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id   INTEGER,
            chunk_order INTEGER,
            table_text  TEXT,
            embedding   BLOB,
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sections (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id       INTEGER,
            section_number  TEXT,
            section_title   TEXT,
            chunk_order     INTEGER,
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE document_chunks ADD COLUMN embedding BLOB")
    except sqlite3.OperationalError:
        pass


# ── Основная функция ──────────────────────────────────────────────────────────

def process_document(file_path: str, year: int, original_filename: str) -> bool:
    """Обрабатывает PDF-документ и сохраняет его содержимое в базу данных.
    Разбивает документ на чанки по 3 страницы с перекрытием в 1 страницу,
    конвертирует каждый чанк в Markdown через Docling (с fallback на fitz),
    извлекает таблицы и разделы, создаёт эмбеддинги и записывает всё в БД.
    При любой критической ошибке откатывает запись об отчёте из таблицы reports.
    Временные PDF-файлы чанков удаляются в блоке finally.
    Возвращает True при успехе, False при ошибке."""
    conn = sqlite3.connect("reports.db")
    cursor = conn.cursor()
    _ensure_schema(cursor)
    conn.commit()

    report_id: int | None = None
    temp_files: list[str] = []

    try:
        src_pdf = fitz.open(file_path)
        total_pages = len(src_pdf)
        if total_pages == 0:
            raise ValueError("PDF пуст — ни одной страницы не обнаружено.")

        converter = DocumentConverter()

        chunk_size = 3   # страниц в чанке
        overlap    = 1   # страница перекрытия
        step       = chunk_size - overlap  # = 2

        temp_chunks: list[tuple[int, str, int, bytes]] = []
        temp_sections = []
        pid = os.getpid()

        for start_p in range(1, total_pages + 1, step):
            end_p = min(start_p + chunk_size - 1, total_pages)

            chunk_path = f"tmp_docling_{pid}_{start_p}_{end_p}.pdf"
            temp_files.append(chunk_path)

            chunk_pdf = fitz.open()
            chunk_pdf.insert_pdf(src_pdf, from_page=start_p - 1, to_page=end_p - 1)
            chunk_pdf.save(chunk_path)
            chunk_pdf.close()

            try:
                result = converter.convert(chunk_path)
                md_text = _clean_markdown(result.document.export_to_markdown())
            except Exception as exc:
                print(f"⚠️  Docling: стр. {start_p}–{end_p} — {exc}. Используем fitz-fallback.")
                md_text = _fitz_fallback(chunk_path)

            if not md_text.strip():
                continue

            has_tbl = int(_has_markdown_table(md_text))

            # Метаданные — однострочный формат.
            # Этот формат разбирается _META_RE в analyzer.py;
            # изменение структуры требует синхронного обновления regex там.
            metadata = (
                f"### МЕТАДАННЫЕ: Стр. {start_p}-{end_p} из {total_pages} | "
                f"Файл: {original_filename} | "
                f"{'ЕСТЬ ТАБЛИЦА' if has_tbl else 'Текст'} ###\n\n"
            )

            full_text = metadata + md_text
            embedding = create_embedding(full_text)
            sections = extract_sections(full_text)

            temp_chunks.append((start_p, full_text, has_tbl, embedding))

            for sec_num, sec_title in sections:
                temp_sections.append((sec_num, sec_title, start_p))

        src_pdf.close()

        if not temp_chunks:
            print(f"⚠️  '{original_filename}': ни одного чанка не удалось извлечь.")
            return False

        cursor.execute(
            "INSERT INTO reports (filename, report_year) VALUES (?, ?)",
            (original_filename, year),
        )
        report_id = cursor.lastrowid

        cursor.executemany(
            "INSERT INTO document_chunks "
            "(report_id, chunk_order, chunk_text, has_tables, embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            [(report_id, order, text, has_tbl, emb) for order, text, has_tbl, emb in temp_chunks],
        )

        # Сохранение таблиц
        for order, text, has_tbl, emb in temp_chunks:
            tables = extract_tables(text)
            print(f"chunk={order} tables={len(tables)}")

            for table_text in tables:
                table_embedding = create_embedding(table_text)
                cursor.execute(
                    "INSERT INTO document_tables "
                    "(report_id, chunk_order, table_text, embedding) "
                    "VALUES (?, ?, ?, ?)",
                    (report_id, order, table_text, table_embedding),
                )

        cursor.executemany(
            "INSERT INTO sections "
            "(report_id, section_number, section_title, chunk_order) "
            "VALUES (?, ?, ?, ?)",
            [
                (report_id, sec_num, sec_title, chunk_order)
                for sec_num, sec_title, chunk_order in temp_sections
            ],
        )
        conn.commit()

        chunks_with_tables = sum(chunk[2] for chunk in temp_chunks)
        print(
            f"✅ '{original_filename}': {len(temp_chunks)} чанков "
            f"(стр. 1–{total_pages}), с таблицами: {chunks_with_tables}"
        )
        return True

    except Exception as exc:
        print(f"❌ Критическая ошибка при обработке '{original_filename}': {exc}")
        if report_id is not None:
            cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            conn.commit()
        return False

    finally:
        for path in temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        conn.close()