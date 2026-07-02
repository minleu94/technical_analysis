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

for /f %%I in ('"%PYTHON%" -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set "TODAY=%%I"

set "RUN_ROOT=%OUTPUT_ROOT%\scheduled\data_freshness"
set "STATUS_PATH=%RUN_ROOT%\latest_status.json"
set "LOG_PATH=%RUN_ROOT%\%TODAY%_data_freshness.log"

if not exist "%RUN_ROOT%" mkdir "%RUN_ROOT%"

"%PYTHON%" "scripts\scheduled\data_freshness_probe.py" --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --db-path "%DB_PATH%" --status-path "%STATUS_PATH%" --log-path "%LOG_PATH%" --stale-days "%STALE_DAYS%"
exit /b %ERRORLEVEL%
