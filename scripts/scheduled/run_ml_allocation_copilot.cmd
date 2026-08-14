@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"
if "%ML_ALLOCATION_PAPER_STATE_DB%"=="" set "ML_ALLOCATION_PAPER_STATE_DB=%OUTPUT_ROOT%\paper_portfolio\paper_portfolio.sqlite"

set "DECISION_AT_ARG="
if not "%ML_ALLOCATION_DECISION_AT%"=="" set "DECISION_AT_ARG=--decision-at "%ML_ALLOCATION_DECISION_AT%""
set "AUTO_CATCH_UP_ARG=--auto-catch-up"

"%PYTHON%" "scripts\run_daily_ml_allocation_orchestration.py" --output-root "%OUTPUT_ROOT%" --paper-state-db "%ML_ALLOCATION_PAPER_STATE_DB%" %AUTO_CATCH_UP_ARG% %DECISION_AT_ARG%
exit /b %ERRORLEVEL%
