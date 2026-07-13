@echo off
setlocal

cd /d "%~dp0"

echo Starting Moneynosleep Qt Backtest...
echo Working dir: %CD%
echo.

set "PY_CMD="

python --version >nul 2>&1
if not errorlevel 1 set "PY_CMD=python"

if not defined PY_CMD (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)

if not defined PY_CMD (
    echo Python was not found in PATH.
    echo Please install Python 3.11+ or add it to PATH.
    echo.
    pause
    exit /b 1
)

%PY_CMD% -m mns start-qt
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
