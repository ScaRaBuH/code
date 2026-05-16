import sqlite3

def init_advanced_db():
    conn = sqlite3.connect("vpo_reports.db")
    cursor = conn.cursor()

    # Сбрасываем старое
    cursor.executescript("""
        DROP TABLE IF EXISTS report_entries;
        DROP TABLE IF EXISTS tables_metadata;
        DROP TABLE IF EXISTS sections;
        DROP TABLE IF EXISTS reports;
    """)

    # 1. Сведения об отчете
    cursor.execute("""
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            institution_name TEXT,
            report_year INTEGER,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Разделы (Раздел 1, Раздел 2...)
    cursor.execute("""
        CREATE TABLE sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            section_number TEXT,
            section_title TEXT,
            FOREIGN KEY (report_id) REFERENCES reports (id)
        )
    """)

    # 3. Метаданные таблиц (в одном разделе может быть много таблиц)
    cursor.execute("""
        CREATE TABLE tables_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER,
            table_name TEXT,
            page_number INTEGER,
            FOREIGN KEY (section_id) REFERENCES sections (id)
        )
    """)

    # 4. Сами данные (каждая ячейка)
    cursor.execute("""
        CREATE TABLE report_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_id INTEGER,
            row_name TEXT,     -- Наименование показателя
            row_code TEXT,     -- Код строки (самый важный ключ!)
            column_number INTEGER, -- Номер графы
            value_numeric REAL,
            value_text TEXT,   -- На случай, если в таблице текст
            FOREIGN KEY (table_id) REFERENCES tables_metadata (id)
        )
    """)

    conn.commit()
    conn.close()
    print("Идеальная структура БД создана.")

if __name__ == "__main__":
    init_advanced_db()