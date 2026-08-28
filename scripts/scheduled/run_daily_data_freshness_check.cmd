@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"
if "%DB_PATH%"=="" set "DB_PATH=%DATA_ROOT%\sqlite\twstock.db"
if "%STALE_DAYS%"=="" set "STALE_DAYS=7"

rem Optional ACL-safe artifact overrides. Defaults remain the canonical output root.
rem If only the status path is overridden, keep the log beside it so a protected
rem OUTPUT_ROOT cannot block the otherwise read-only probe.
if not "%BALDR_FRESHNESS_STATUS_PATH%"=="" if "%BALDR_FRESHNESS_LOG_PATH%"=="" set "BALDR_FRESHNESS_LOG_PATH=%BALDR_FRESHNESS_STATUS_PATH%.log"
if "%BALDR_FRESHNESS_STATUS_PATH%"=="" (
  if "%BALDR_FRESHNESS_LOG_PATH%"=="" (
    "%PYTHON%" "scripts\scheduled\data_freshness_probe.py" --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --db-path "%DB_PATH%" --stale-days "%STALE_DAYS%"
  ) else (
    "%PYTHON%" "scripts\scheduled\data_freshness_probe.py" --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --db-path "%DB_PATH%" --log-path "%BALDR_FRESHNESS_LOG_PATH%" --stale-days "%STALE_DAYS%"
  )
) else (
  "%PYTHON%" "scripts\scheduled\data_freshness_probe.py" --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --db-path "%DB_PATH%" --status-path "%BALDR_FRESHNESS_STATUS_PATH%" --log-path "%BALDR_FRESHNESS_LOG_PATH%" --stale-days "%STALE_DAYS%"
)
exit /b %ERRORLEVEL%
