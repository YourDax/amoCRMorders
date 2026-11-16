@echo off
rem Сборка: dist\SdelkiAmoCRM\ (программа) и dist\SdelkiAmoCRM-Setup.exe (установщик, если есть Inno Setup 6)
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean SdelkiAmoCRM.spec || exit /b 1
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  for /f "tokens=2 delims==" %%v in ('findstr /b "VERSION" paths.py') do set VER=%%~v
  %ISCC% /DAppVersion=%VER: =% installer.iss
) else (
  echo Inno Setup 6 не найден - установщик не собран, программа лежит в dist\SdelkiAmoCRM
)
