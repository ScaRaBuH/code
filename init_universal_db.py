import sqlite3

def setup_db():
    conn = sqlite3.connect("vpo_reports.db")
    cursor = conn.cursor()

    # Удаляем старые таблицы, чтобы избежать конфликтов имен
    cursor.executescript("""
        DROP TABLE IF EXISTS document_contents;
        DROP TABLE IF EXISTS reports;
        DROP TABLE IF EXISTS report_entries;
        DROP TABLE IF EXISTS sections;
    """)

    # Таблица для метаданных документов
    cursor.execute("""
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            doc_type TEXT,
            report_year INTEGER,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица для хранения текста в формате Markdown
    cursor.execute("""
        CREATE TABLE document_contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            full_text TEXT,
            FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Универсальная база данных успешно инициализирована!")

if __name__ == "__main__":
    setup_db()