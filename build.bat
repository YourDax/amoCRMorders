@echo off
rem Сборка одного exe: dist\SdelkiAmoCRM.exe
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean SdelkiAmoCRM.spec
