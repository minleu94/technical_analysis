@echo off
setlocal EnableExtensions

rem 這個 wrapper 只呼叫 repository-scoped Paper adapter；不把任何
rem PAPER_EXECUTION_* 或 DATA_ROOT 環境變數傳成 writer 路徑。
set "SCRIPT_DIR=%~dp0"
rem Avoid a FOR modifier here: Task Scheduler and nested cmd.exe both parse
rem that syntax, and a second parser can corrupt %%~fI before the adapter runs.
cd /d "%SCRIPT_DIR%..\.." || exit /b 1
set "REPO_ROOT=%CD%"

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
set "ISOLATED_ADAPTER=%REPO_ROOT%\scripts\scheduled\run_paper_execution_daily_isolated.py"
if not exist "%ISOLATED_ADAPTER%" (
  echo Isolated Paper adapter missing: %ISOLATED_ADAPTER%
  exit /b 2
)

rem Adapter 固定 D 的既有 snapshot／market／recommendation 為只讀來源，
rem 並只把 research-only append 寫到 repo output\paper_execution_eod_replay。
"%PYTHON%" "%ISOLATED_ADAPTER%"
exit /b %ERRORLEVEL%
