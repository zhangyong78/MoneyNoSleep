@echo off
setlocal

cd /d "%~dp0"

chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem =========================
rem Edit these settings
rem =========================
set SYNC_ALL=0
set STOCK_CODES=600000.SH,000001.SZ
set STOCK_FILE=
set DB_PATH=data/duckdb/mns.duckdb
set PARQUET_ROOT=data/parquet
set STATE_PATH=data/logs/baostock_bulk_sync_state.json
set RESET_STATE=1
set FETCH_TIMEFRAMES=5m,1d
set DERIVE_SOURCE_TIMEFRAME=5m
set DERIVE_TIMEFRAMES=15m,30m,1h
set ADJUSTFLAG=2
set MAX_RETRIES=2
set ALLOW_QUALITY_ISSUES=0

rem Optional BaoStock credentials. Leave blank for anonymous login.
set MNS_BAOSTOCK_USER_ID=
set MNS_BAOSTOCK_PASSWORD=

set START_DATE=2020-01-02T09:30:00
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd') + 'T15:00:00'"') do set END_DATE=%%i

echo.
echo BaoStock bulk sync starting...
echo Workspace      : %CD%
echo DB             : %DB_PATH%
echo State file     : %STATE_PATH%
echo Date range     : %START_DATE% ^> %END_DATE%
echo Fetch          : %FETCH_TIMEFRAMES%
echo Derive source  : %DERIVE_SOURCE_TIMEFRAME%
echo Derive targets : %DERIVE_TIMEFRAMES%
if "%SYNC_ALL%"=="1" (
  echo Stock scope    : ALL
) else (
  echo Stock scope    : %STOCK_CODES%
)
echo.

set CMD=python tools/baostock_bulk_sync.py --db "%DB_PATH%" --parquet-root "%PARQUET_ROOT%" --start "%START_DATE%" --end "%END_DATE%" --fetch-timeframes "%FETCH_TIMEFRAMES%" --derive-source-timeframe "%DERIVE_SOURCE_TIMEFRAME%" --derive-timeframes "%DERIVE_TIMEFRAMES%" --adjustflag "%ADJUSTFLAG%" --max-retries %MAX_RETRIES% --state-path "%STATE_PATH%"

if "%SYNC_ALL%"=="1" (
  set CMD=%CMD% --sync-all
) else (
  if not "%STOCK_CODES%"=="" set CMD=%CMD% --stock-codes "%STOCK_CODES%"
)

if not "%STOCK_FILE%"=="" set CMD=%CMD% --stock-file "%STOCK_FILE%"
if "%ALLOW_QUALITY_ISSUES%"=="1" set CMD=%CMD% --allow-quality-issues
if "%RESET_STATE%"=="1" set CMD=%CMD% --reset-state

echo Running command:
echo %CMD%
echo.

call %CMD%
set EXIT_CODE=%ERRORLEVEL%

echo.
if "%EXIT_CODE%"=="0" (
  echo BaoStock bulk sync finished successfully.
) else (
  echo BaoStock bulk sync failed. Exit code: %EXIT_CODE%
)

echo.
pause
exit /b %EXIT_CODE%
