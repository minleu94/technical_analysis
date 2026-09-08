@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

if defined BALDR_PYTHON set "PYTHON=%BALDR_PYTHON%"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"
if not defined FORMAL_DAILY_PUBLICATION_ROOT set "FORMAL_DAILY_PUBLICATION_ROOT=%REPO_ROOT%\output\formal_daily_publications"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 盤後只重新建立 handoff 並讀取 08:30 前 archive；Python 入口不接受
rem decision date/clock override，也不重新抓取同一自然日的 HTTP source。
"%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_formal_pit_sidecar_postcutoff.py"
exit /b %ERRORLEVEL%
