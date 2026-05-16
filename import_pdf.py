import pdfplumber
import sqlite3
import re

def clean_numeric(value):
    if not value or value.strip() == "-": return 0.0
    cleaned = re.sub(r'[^\d,.-]', '', value.replace(',', '.'))
    try: return float(cleaned)
    except ValueError: return 0.0

def process_pdf(pdf_path, year=2025):
    conn = sqlite3.connect("vpo_reports.db")
    cursor = conn.cursor()

    # Регистрируем отчет
    cursor.execute("INSERT INTO reports (filename, report_year) VALUES (?, ?)", (pdf_path, year))
    report_id = cursor.lastrowid

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            section_title = "Unknown Section"
            for line in text.split('\n'):
                if "Раздел" in line:
                    section_title = line.strip()
                    break
            
            # Создаем раздел
            cursor.execute("INSERT INTO sections (report_id, section_title) VALUES (?, ?)", (report_id, section_title))
            section_id = cursor.lastrowid

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3: continue
                    
                    row_name = (row[0] or "").replace('\n', ' ')
                    row_code = (row[1] or "").strip()
                    
                    if not row_code.isdigit(): continue

                    for col_idx, cell in enumerate(row[2:], start=3):
                        val = clean_numeric(cell)
                        if val > 0:
                            cursor.execute("""
                                INSERT INTO report_entries (section_id, row_code, row_name, column_index, value_numeric)
                                VALUES (?, ?, ?, ?, ?)
                            """, (section_id, row_code, row_name, col_idx, val))

    conn.commit()
    conn.close()
    print(f"Файл {pdf_path} успешно импортирован.")

if __name__ == "__main__":
    # Замените на имя вашего файла
    process_pdf("ВПО-1 2025 28-10-2025.pdf")