import os
import sqlite3
import streamlit as st
import fitz  # PyMuPDF для физической нарезки

# Импорты актуального API Docling 2.x
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat

# Перенаправляем кэш моделей
os.environ["HF_HOME"] = os.path.join(os.getcwd(), "models_cache")

# ПРИНУДИТЕЛЬНЫЙ ХАК: Перехватываем управление ONNX на уровне Си-ядра
import onnxruntime as ort
if "DmlExecutionProvider" in ort.get_available_providers():
    # Заставляем ONNX отдавать абсолютный приоритет карте AMD
    os.environ["ORT_PROVIDER_PRIORITY"] = "DmlExecutionProvider"
    ort.set_default_logger_severity(3)  # Выключаем лишние логи в консоли

def process_document(file_path, year, original_filename):
    conn = sqlite3.connect("vpo_reports.db")
    cursor = conn.cursor()

    try:
        src_pdf = fitz.open(file_path)
        total_pages = len(src_pdf)
        print(f"Пайплайн: Всего в документе {total_pages} страниц.")

        cursor.execute(
            "INSERT INTO reports (filename, report_year, doc_type) VALUES (?, ?, ?)", 
            (original_filename, year, "VPO_Report")
        )
        report_id = cursor.lastrowid

        # Стандартные опции разметки
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.do_table_structure = True  # Оставляем честные таблицы!
        pipeline_options.accelerator_options.num_threads = 4

        # Инициализация конвертера по стандарту Docling 2.x
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        full_markdown_parts = []
        page_step = 5  # Нарезка для защиты от переполнения RAM
        
        progress_bar = st.progress(0, text="Инициализация парсинга...")

        for start_p in range(1, total_pages + 1, page_step):
            end_p = min(start_p + page_step - 1, total_pages)
            
            current_pct = int((start_p / total_pages) * 100)
            progress_bar.progress(current_pct, text=f"Парсинг страниц {start_p}-{end_p} из {total_pages}...")
            print(f"Обработка фрагмента: страницы {start_p}-{end_p}...")

            chunk_filename = f"temp_chunk_{start_p}_{end_p}.pdf"
            chunk_pdf_path = os.path.join(os.getcwd(), chunk_filename)
            
            try:
                chunk_pdf = fitz.open()
                chunk_pdf.insert_pdf(src_pdf, from_page=start_p - 1, to_page=end_p - 1)
                chunk_pdf.save(chunk_pdf_path)
                chunk_pdf.close()

                result = converter.convert(chunk_pdf_path)
                chunk_markdown = result.document.export_to_markdown()
                full_markdown_parts.append(chunk_markdown)

            except Exception as chunk_error:
                print(f"Сбой фрагмента {start_p}-{end_p}: {chunk_error}")
                full_markdown_parts.append(f"\n\n[Фрагмент страниц {start_p}-{end_p} пропущен]\n\n")
            finally:
                if os.path.exists(chunk_pdf_path):
                    try: os.remove(chunk_pdf_path)
                    except: pass

        src_pdf.close()
        progress_bar.empty()

        final_markdown = "\n\n".join(full_markdown_parts)
        cursor.execute(
            "INSERT INTO document_contents (report_id, full_text) VALUES (?, ?)", 
            (report_id, final_markdown)
        )
        conn.commit()
        print("Пайплайн: Успешно завершено!")
        return True

    except Exception as e:
        st.error(f"Критическая ошибка пайплайна: {e}")
        return False
    finally:
        conn.close()