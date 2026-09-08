@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
rem 不使用 FOR 路徑修飾，避免 Task Scheduler／巢狀 cmd.exe 的第二次解析
rem 把 %%~fI 誤當成無效的 batch 參數替換。
cd /d "%SCRIPT_DIR%..\.." || exit /b 1
set "REPO_ROOT=%CD%"

if defined BALDR_PYTHON set "PYTHON=%BALDR_PYTHON%"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"
if not defined DATA_ROOT set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if not defined FORMAL_DAILY_MARKET_DB set "FORMAL_DAILY_MARKET_DB=%DATA_ROOT%\sqlite\twstock.db"
if not defined FORMAL_DAILY_RULE_BASELINE_ROOT set "FORMAL_DAILY_RULE_BASELINE_ROOT=%DATA_ROOT%\output\formal_prospective"
if not defined FORMAL_DAILY_CALENDAR_CACHE_ROOT set "FORMAL_DAILY_CALENDAR_CACHE_ROOT=%REPO_ROOT%\output\paper_execution_eod_replay\calendar_cache"
if not defined FORMAL_DAILY_RULE_SOURCE_ROOT set "FORMAL_DAILY_RULE_SOURCE_ROOT=%REPO_ROOT%\output\formal_daily_publications\rule_source"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 只取 machine producer 內的實際系統 clock；不接受時間覆寫、日期或 fixture
rem 參數。market DB／baseline 都是唯讀輸入，bundle 與 status 只寫 repo。
"%PYTHON%" -m data_module.formal_rule_source_producer
exit /b %ERRORLEVEL%
