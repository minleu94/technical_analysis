@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

if defined BALDR_PYTHON set "PYTHON=%BALDR_PYTHON%"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"
rem 來源根目錄只供 isolated adapter 以唯讀方式讀取；它不接受呼叫端
rem 以 OUTPUT_ROOT 或 state_db 將 writer 導回 D 槽。
set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
set "REPO_PAPER_OPERATION_ROOT=%REPO_ROOT%\output\paper_execution_eod_replay"
set "REPO_PAPER_STATE_DB=%REPO_PAPER_OPERATION_ROOT%\paper_portfolio\paper_portfolio.sqlite"
set "PAPER_EXECUTION_LEDGER_DB=%REPO_PAPER_OPERATION_ROOT%\paper_trade_ledger.sqlite"

rem 先建立／確認本日台北 08:30 preopen snapshot。adapter 首次執行只將
rem D snapshot 以 read-only consistent backup seed 到 repository；EOD replay
rem 與 Formal 後續只讀這份 repository state，不覆寫 D snapshot。
:valuation
"%PYTHON%" "scripts\scheduled\run_paper_portfolio_daily_isolated.py"
if errorlevel 1 exit /b %ERRORLEVEL%

rem 可選的 bounded T+1 next-session-open Paper execution candidate handoff；
rem 這裡只作 candidate，正式 append 由 15:00 後的獨立 EOD task 受控執行。
set "PAPER_EXECUTION_EXIT=0"
if not defined PAPER_EXECUTION_RECOMMENDATION_JSON exit /b 0
set "PAPER_EXECUTION_OUTPUT_ROOT=%TEMP%\baldr_paper_execution_%RANDOM%"
set "PAPER_EXECUTION_STATE_DB=%REPO_PAPER_STATE_DB%"
set "PAPER_EXECUTION_MARKET_DB=%DATA_ROOT%\sqlite\twstock.db"
set "PAPER_EXECUTION_CLOCK_ARG="
if defined PAPER_EXECUTION_CLOCK_MANIFEST set "PAPER_EXECUTION_CLOCK_ARG=--clock-manifest "%PAPER_EXECUTION_CLOCK_MANIFEST%""

"%PYTHON%" "scripts\run_paper_execution_daily.py" --recommendation-json "%PAPER_EXECUTION_RECOMMENDATION_JSON%" --state-db "%PAPER_EXECUTION_STATE_DB%" --market-db "%PAPER_EXECUTION_MARKET_DB%" --output-root "%PAPER_EXECUTION_OUTPUT_ROOT%" --ledger-db "%PAPER_EXECUTION_LEDGER_DB%" %PAPER_EXECUTION_CLOCK_ARG%
if errorlevel 1 set "PAPER_EXECUTION_EXIT=2"

if not "%PAPER_EXECUTION_EXIT%"=="0" exit /b %PAPER_EXECUTION_EXIT%
exit /b 0
