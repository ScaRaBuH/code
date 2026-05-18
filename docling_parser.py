import os
import sqlite3
import fitz  # PyMuPDF
from docling.document_converter import DocumentConverter

def process_document(file_path, year, original_filename):
    conn = sqlite3.connect("reports.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            report_year INTEGER,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            chunk_order INTEGER,
            chunk_text TEXT,
            FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE
        )
    """)

    try:
        # Добавление отчета в БД
        cursor.execute(
            "INSERT INTO reports (filename, report_year) VALUES (?, ?)",
            (original_filename, year)
        )
        report_id = cursor.lastrowid

        # Разбиение и обработка
        src_pdf = fitz.open(file_path)
        total_pages = len(src_pdf)
        converter = DocumentConverter()
        
        chunk_size = 10 # Количество страниц в одном разбиении
        for start_p in range(1, total_pages + 1, chunk_size):
            end_p = min(start_p + chunk_size - 1, total_pages)
            
            chunk_pdf_path = f"temp_{start_p}_{end_p}.pdf"
            chunk_pdf = fitz.open()
            chunk_pdf.insert_pdf(src_pdf, from_page=start_p-1, to_page=end_p-1)
            chunk_pdf.save(chunk_pdf_path)
            chunk_pdf.close()

            # Конвертация куска
            result = converter.convert(chunk_pdf_path)
            markdown_text = result.document.export_to_markdown()
            
            # Сохраняем кусок в БД
            cursor.execute(
                "INSERT INTO document_chunks (report_id, chunk_order, chunk_text) VALUES (?, ?, ?)",
                (report_id, start_p, markdown_text)
            )
            conn.commit()
            
            os.remove(chunk_pdf_path)

        src_pdf.close()
        return True
    except Exception as e:
        print(f"Ошибка парсинга: {e}")
        return False
    finally:
        conn.close()