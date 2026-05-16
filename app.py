import streamlit as st
import sqlite3
import pandas as pd
import os
from docling_parser import process_document
from analyzer import get_analysis_from_qwen

st.set_page_config(page_title="Универсальный Аналитик", layout="wide")

def get_db_connection():
    return sqlite3.connect("vpo_reports.db")

def delete_report(report_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()

st.title("🤖 Универсальная система анализа документов")

# --- Сайдбар ---
with st.sidebar:
    st.header("📂 Загрузка")
    uploaded_file = st.file_uploader("Выберите PDF", type="pdf")
    year = st.number_input("Год документа", value=2025)
    
    if uploaded_file and st.button("Обработать"):
        with st.spinner("Docling анализирует структуру..."):
            temp_path = "temp_upload.pdf"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            if process_document(temp_path, year, uploaded_file.name):
                st.success("Документ успешно добавлен!")
                os.remove(temp_path)
                st.rerun()
            else:
                st.error("Ошибка при обработке документа.")

    st.divider()
    
    # Список документов
    conn = get_db_connection()
    reports_df = pd.read_sql_query("SELECT id, filename FROM reports", conn)
    conn.close()

    active_report_id = None
    if not reports_df.empty:
        report_dict = dict(zip(reports_df['filename'], reports_df['id']))
        selected_name = st.selectbox("Активный документ:", list(report_dict.keys()))
        active_report_id = report_dict[selected_name]
        
        if st.button("🗑️ Удалить документ"):
            delete_report(active_report_id)
            st.rerun()
    else:
        st.info("База пуста.")

# --- Основной экран ---
if active_report_id:
    st.subheader(f"📄 Работа с: {selected_name}")
    user_query = st.text_input("Задайте вопрос по документу:", placeholder="Например: Какая общая численность студентов?")
    
    if st.button("🚀 Спросить ИИ", type="primary"):
        if user_query:
            with st.spinner("Qwen анализирует текст..."):
                answer = get_analysis_from_qwen(active_report_id, user_query)
                st.markdown("### Ответ нейросети:")
                st.info(answer)
        else:
            st.warning("Введите вопрос.")
else:
    st.write("Загрузите или выберите документ в боковой панели для начала работы.")