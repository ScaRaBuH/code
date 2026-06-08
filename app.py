import streamlit as st
import sqlite3
import pandas as pd
from docling_parser import process_document
from analyzer import get_analysis_from_qwen, load_llm

st.set_page_config(page_title="Система анализа документов", layout="wide")

llm = load_llm()


# ── Вспомогательные функции ───────────────────────────────────────────────────

def get_db_connection():
    """Возвращает новое соединение с базой данных reports.db."""
    return sqlite3.connect("reports.db")


def init_db_checks() -> bool:
    """Проверяет, существует ли таблица reports в базе данных.
    Возвращает True, если таблица найдена, иначе False."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reports'")
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def delete_report(report_id: int):
    """Удаляет запись об отчёте из таблицы reports по его идентификатору.
    Все связанные чанки, таблицы и разделы удаляются каскадно (ON DELETE CASCADE)."""
    conn = get_db_connection()
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()


# ── Инициализация состояния сессии ────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []   # [{role, content}]

if "active_ids" not in st.session_state:
    st.session_state.active_ids = []


# ── Боковая панель ────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Загрузка документов")
    uploaded_file = st.file_uploader("PDF-документ", type="pdf")
    year = st.number_input("Год отчёта", value=2025, step=1)

    if uploaded_file and st.button("Обработать и сохранить", type="primary"):
        with st.spinner("Идёт обработка документа..."):
            temp_path = f"temp_{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            if process_document(temp_path, year, uploaded_file.name):
                st.success("✅ Документ добавлен в базу!")
                st.rerun()
            else:
                st.error("❌ Ошибка при обработке документа.")

    st.divider()
    st.header("🗂️ Выбор документов для анализа")

    active_ids: list[int] = []

    if init_db_checks():
        conn = get_db_connection()
        reports_df = pd.read_sql_query(
            "SELECT id, filename, report_year, upload_date FROM reports ORDER BY upload_date DESC",
            conn,
        )
        conn.close()

        if not reports_df.empty:
            report_options = {
                f"{row['filename']} ({row['report_year']})": row["id"]
                for _, row in reports_df.iterrows()
            }
            selected_labels = st.multiselect(
                "Отметьте документы:",
                list(report_options.keys()),
                default=[
                    label for label, rid in report_options.items()
                    if rid in st.session_state.active_ids
                ],
            )
            active_ids = [report_options[label] for label in selected_labels]
            st.session_state.active_ids = active_ids

            with st.expander("🗑️ Удалить документ из базы"):
                del_label = st.selectbox(
                    "Выберите документ для удаления:",
                    ["— выберите —"] + list(report_options.keys()),
                )
                if del_label != "— выберите —" and st.button("Удалить", type="secondary"):
                    delete_report(report_options[del_label])
                    st.success(f"Документ «{del_label}» удалён.")
                    st.rerun()
        else:
            st.info("В базе пока нет документов.")
    else:
        st.info("База данных пуста. Загрузите первый документ.")

    st.divider()
    with st.expander("💡 Типы запросов"):
        st.markdown("""
| Тип | Пример запроса |
|-----|---------------|
| 🔍 SEARCH | «Найди значение показателя X в таблице 3» |
| 🧮 CALCULATE | «Посчитай сумму по столбцу "Итого"» |
| ⚠️ ANOMALIES | «Проверь, нет ли расхождений в данных» |
| 📊 ANALYZE | «Проанализируй динамику показателей» |
| 🗂️ STRUCTURE | «Сколько таблиц в документе?» |
""")


# ── Главная область: чат ──────────────────────────────────────────────────────

st.title("📊 Система анализа документов")

if not active_ids:
    st.warning("👈 Выберите один или несколько документов в боковой панели.")
    st.stop()

conn = get_db_connection()
active_names = pd.read_sql_query(
    f"SELECT filename FROM reports WHERE id IN ({','.join('?' * len(active_ids))})",
    conn,
    params=active_ids,
)
conn.close()
names_str = ", ".join(active_names["filename"].tolist())
st.subheader(f"💬 Чат — {names_str}")

col1, col2 = st.columns([8, 1])
with col2:
    if st.button("🗑️ Очистить", help="Очистить историю чата"):
        st.session_state.messages = []
        st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_query = st.chat_input("Введите запрос к документам…")

if user_query:
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.chat_message("assistant"):
        with st.spinner("Модель анализирует документы…"):
            answer = get_analysis_from_qwen(llm, active_ids, user_query)
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})