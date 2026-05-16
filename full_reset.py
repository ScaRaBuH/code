import sqlite3

def setup_fresh_db():
    conn = sqlite3.connect("vpo_reports.db")
    cursor = conn.cursor()

    # Удаляем всё старое
    cursor.execute("DROP TABLE IF EXISTS report_entries")
    cursor.execute("DROP TABLE IF EXISTS sections")
    cursor.execute("DROP TABLE IF EXISTS reports")

    # 1. Таблица отчетов
    cursor.execute("""
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            report_year INTEGER,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Таблица разделов (Здесь будет тот самый s.id)
    cursor.execute("""
        CREATE TABLE sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            section_title TEXT,
            FOREIGN KEY (report_id) REFERENCES reports (id)
        )
    """)

    # 3. Таблица данных
    cursor.execute("""
        CREATE TABLE report_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER,
            row_code TEXT,
            row_name TEXT,
            column_index INTEGER,
            value_numeric REAL,
            FOREIGN KEY (section_id) REFERENCES sections (id)
        )
    """)

    conn.commit()
    conn.close()
    print("База данных успешно пересоздана. Теперь она готова к работе!")

if __name__ == "__main__":
    setup_fresh_db()