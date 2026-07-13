@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo Starting Moneynosleep UI...
"%PYTHON_EXE%" -m mns start-ui
if errorlevel 1 (
  echo.
  echo Failed to start Moneynosleep UI.
  pause
  exit /b 1
)

echo.
echo Moneynosleep UI start command finished.
echo Check the printed URL above, usually http://127.0.0.1:8501
pause
