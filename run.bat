@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Первый запуск: устанавливаю компоненты, это займёт пару минут...
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
  .venv\Scripts\python -m playwright install chromium
  .venv\Scripts\python make_shortcut.py
)
.venv\Scripts\python app.py
if errorlevel 1 pause
