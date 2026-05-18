import streamlit as st
import sqlite3
import pandas as pd
import os
from docling_parser import process_document
from analyzer import get_analysis_from_qwen

st.set_page_config(page_title="Система анализа", layout="wide")

def get_db_connection():
    return sqlite3.connect("reports.db")

st.title("📊 Система анализа документов")

with st.sidebar:
    st.header("📂 Управление данными")
    uploaded_file = st.file_uploader("Загрузить новый документ (PDF)", type="pdf")
    year = st.number_input("Год", value=2025)
    
    if uploaded_file and st.button("Обработать и сохранить"):
        with st.spinner("Идёт обработка документа..."):
            temp_path = "temp.pdf"
            with open(temp_path, "wb") as f: f.write(uploaded_file.getbuffer())
            if process_document(temp_path, year, uploaded_file.name):
                st.success("Готово!")
                st.rerun()

    st.divider()
    conn = get_db_connection()
    reports_df = pd.read_sql_query("SELECT id, filename, report_year FROM reports", conn)
    conn.close()

    if not reports_df.empty:
        # Мультивыбор активных документов
        report_options = {f"{row['filename']} ({row['report_year']})": row['id'] for _, row in reports_df.iterrows()}
        selected_labels = st.multiselect("Выберите активные документы:", list(report_options.keys()))
        active_ids = [report_options[label] for label in selected_labels]
    else:
        st.info("База данных пуста.")
        active_ids = []

# Основной экран
if active_ids:
    st.subheader(f"💬 Чат по {len(active_ids)} док.")
    user_query = st.text_input("Ваш вопрос:")
    
    if st.button("Выполнить запрос", type="primary"):
        with st.spinner("Модель обробатывает запрос..."):
            answer = get_analysis_from_qwen(active_ids, user_query)
            st.markdown(answer)