@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"
if "%SOURCE_DB_PATH%"=="" set "SOURCE_DB_PATH=%DATA_ROOT%\sqlite\twstock.db"
if "%SIDECAR_DB_PATH%"=="" set "SIDECAR_DB_PATH=%OUTPUT_ROOT%\scheduled\v2_2_weekly_collection\evidence_scheduler.db"

"%PYTHON%" "scripts\collect_v2_2_weekly_evidence.py" --source-db-path "%SOURCE_DB_PATH%" --sidecar-db-path "%SIDECAR_DB_PATH%" --output-root "%OUTPUT_ROOT%"
exit /b %ERRORLEVEL%
