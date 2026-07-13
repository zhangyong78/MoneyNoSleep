@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=py -3"
)

if not defined PYTHON_EXE (
    echo Python 3.11+ was not found.
    echo Please install Python or add it to PATH.
    echo.
    pause
    exit /b 1
)

echo Starting local data sync and lookup...
echo Working dir: %CD%
echo.

%PYTHON_EXE% -m mns start-qt-local-data
if errorlevel 1 (
    echo.
    echo Launch failed.
    echo Try this first:
    echo pip install -e .[qt]
    echo.
    pause
    exit /b 1
)

endlocal
