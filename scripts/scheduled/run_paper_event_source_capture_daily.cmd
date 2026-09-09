@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

if defined BALDR_PYTHON set "PYTHON=%BALDR_PYTHON%"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 只消費已凍結 recommendation，於台北 09:00..13:30 以官方 MIS
rem raw bytes 建立 repository durable event capture；不寫 Paper ledger。
"%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_paper_event_source_capture_daily.py"
exit /b %ERRORLEVEL%
