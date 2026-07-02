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

"%PYTHON%" "scripts\scheduled\run_scheduled_evidence_pipeline_dry_run.py" --dry-run --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --db-path "%DB_PATH%" --sources "%SOURCES%"
exit /b %ERRORLEVEL%
