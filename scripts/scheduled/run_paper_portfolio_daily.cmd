@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"

set "DECISION_AT_ARG="
if not "%PAPER_PORTFOLIO_DECISION_AT%"=="" set "DECISION_AT_ARG=--decision-at "%PAPER_PORTFOLIO_DECISION_AT%""

"%PYTHON%" "scripts\run_paper_portfolio_daily.py" --output-root "%OUTPUT_ROOT%" %DECISION_AT_ARG%
exit /b %ERRORLEVEL%
