@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"
if "%MAX_STOCKS%"=="" set "MAX_STOCKS=200"
if "%TOP_N%"=="" set "TOP_N=50"

"%PYTHON%" "scripts\scheduled\run_scheduled_recommendation_snapshot.py" --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --max-stocks "%MAX_STOCKS%" --top-n "%TOP_N%"
exit /b %ERRORLEVEL%
