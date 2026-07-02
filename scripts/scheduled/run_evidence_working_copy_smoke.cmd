@echo off
setlocal EnableExtensions

if "%~1"=="" goto usage
if "%~2"=="" goto usage

set "SOURCE_DB_PATH=%~1"
set "WORKING_COPY_DB_PATH=%~2"

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"

if "%~3"=="" (
  for /f %%I in ('"%PYTHON%" -c "from datetime import date; print(date.today().strftime('%%Y-%%m-%%d'))"') do set "DECISION_DATE=%%I"
) else (
  set "DECISION_DATE=%~3"
)
if "%~4"=="" (
  set "REPEAT=2"
) else (
  set "REPEAT=%~4"
)

for /f %%I in ('"%PYTHON%" -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set "TODAY=%%I"

set "RUN_ROOT=%OUTPUT_ROOT%\scheduled\evidence_working_copy_smoke"
set "REPORT_ROOT=%RUN_ROOT%\reports"
set "STATUS_PATH=%RUN_ROOT%\latest_status.json"
set "LOG_PATH=%RUN_ROOT%\%TODAY%_evidence_working_copy_smoke.log"
set "REPORT_PATH=%REPORT_ROOT%\%TODAY%_evidence_working_copy_smoke.md"

if not exist "%RUN_ROOT%" mkdir "%RUN_ROOT%"
if not exist "%REPORT_ROOT%" mkdir "%REPORT_ROOT%"

"%PYTHON%" "scripts\smoke_evidence_pipeline_working_copy.py" --source-db-path "%SOURCE_DB_PATH%" --working-copy-db-path "%WORKING_COPY_DB_PATH%" --decision-date "%DECISION_DATE%" --repeat "%REPEAT%" --report-output "%REPORT_PATH%" --json-output > "%LOG_PATH%" 2>&1
set "SMOKE_EXIT=%ERRORLEVEL%"

"%PYTHON%" "scripts\scheduled\write_scheduled_status.py" --mode working-copy-smoke --task "baldr-evidence-working-copy-smoke-manual" --status-path "%STATUS_PATH%" --log-path "%LOG_PATH%" --report-path "%REPORT_PATH%" --decision-date "%DECISION_DATE%" --source-db-path "%SOURCE_DB_PATH%" --working-copy-db-path "%WORKING_COPY_DB_PATH%" --repeat "%REPEAT%" --exit-code "%SMOKE_EXIT%"
exit /b %SMOKE_EXIT%

:usage
echo Usage: scripts\scheduled\run_evidence_working_copy_smoke.cmd ^<source-db-path^> ^<working-copy-db-path^> [YYYY-MM-DD] [repeat]
echo This wrapper is manual-only. It must not be attached to a daily schedule.
exit /b 2
