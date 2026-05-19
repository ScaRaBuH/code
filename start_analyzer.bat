@echo off
echo Запуск системы...
//call .\venv\Scripts\activate
python init_db.py
streamlit run app.py
pause
