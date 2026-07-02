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
if "%SOURCES%"=="" set "SOURCES=all"

for /f %%I in ('"%PYTHON%" -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set "TODAY=%%I"
for /f %%I in ('"%PYTHON%" -c "from datetime import date; print(date.today().strftime('%%Y-%%m-%%d'))"') do set "DECISION_DATE=%%I"

set "RUN_ROOT=%OUTPUT_ROOT%\scheduled\evidence_pipeline_dry_run"
set "REPORT_ROOT=%RUN_ROOT%\reports"
set "STATUS_PATH=%RUN_ROOT%\latest_status.json"
set "LOG_PATH=%RUN_ROOT%\%TODAY%_evidence_pipeline_dry_run.log"
set "REPORT_PATH=%REPORT_ROOT%\%TODAY%_evidence_pipeline_dry_run.md"
set "FRESHNESS_STATUS_PATH=%OUTPUT_ROOT%\scheduled\data_freshness\latest_status.json"

if not exist "%RUN_ROOT%" mkdir "%RUN_ROOT%"
if not exist "%REPORT_ROOT%" mkdir "%REPORT_ROOT%"

"%PYTHON%" "scripts\run_evidence_pipeline.py" --decision-date "%DECISION_DATE%" --dry-run --db-path "%DB_PATH%" --sources "%SOURCES%" --report-output "%REPORT_PATH%" --json-output > "%LOG_PATH%" 2>&1
set "PIPELINE_EXIT=%ERRORLEVEL%"

"%PYTHON%" "scripts\scheduled\write_scheduled_status.py" --mode evidence-dry-run --task "baldr-evidence-pipeline-dry-run-daily" --status-path "%STATUS_PATH%" --log-path "%LOG_PATH%" --report-path "%REPORT_PATH%" --decision-date "%DECISION_DATE%" --db-path "%DB_PATH%" --freshness-status-path "%FRESHNESS_STATUS_PATH%" --exit-code "%PIPELINE_EXIT%"
exit /b %PIPELINE_EXIT%
