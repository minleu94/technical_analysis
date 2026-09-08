@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"

rem 這個獨立排程在延遲 EOD replay 門檻後執行；queue 會自動挑選下一官方 session 到期的 frozen recommendation。
if not defined PAPER_EXECUTION_OUTPUT_ROOT set "PAPER_EXECUTION_OUTPUT_ROOT=%TEMP%\baldr_paper_execution_%RANDOM%"
if not defined PAPER_EXECUTION_STATE_DB set "PAPER_EXECUTION_STATE_DB=%OUTPUT_ROOT%\paper_portfolio\paper_portfolio.sqlite"
if not defined PAPER_EXECUTION_MARKET_DB set "PAPER_EXECUTION_MARKET_DB=%DATA_ROOT%\sqlite\twstock.db"
if not defined PAPER_EXECUTION_LEDGER_DB set "PAPER_EXECUTION_LEDGER_DB=%OUTPUT_ROOT%\paper_portfolio\paper_trade_ledger.sqlite"
if not defined PAPER_EXECUTION_RECOMMENDATION_ROOT set "PAPER_EXECUTION_RECOMMENDATION_ROOT=%OUTPUT_ROOT%\recommendation\runs"
if not defined PAPER_EXECUTION_RECEIPT_ROOT set "PAPER_EXECUTION_RECEIPT_ROOT=%OUTPUT_ROOT%\scheduled\paper_execution_eod_replay\receipts"
set "PAPER_EXECUTION_CLOCK_ARG="
if defined PAPER_EXECUTION_CLOCK_MANIFEST set "PAPER_EXECUTION_CLOCK_ARG=--clock-manifest ^"%PAPER_EXECUTION_CLOCK_MANIFEST%^""
set "PAPER_EXECUTION_APPEND_ARG=--confirm-append-paper-ledger"
rem PAPER_EXECUTION_APPEND=0 或 candidate-only 時保留 candidate-only，不追加 ledger。
if /I "%PAPER_EXECUTION_APPEND%"=="0" set "PAPER_EXECUTION_APPEND_ARG="
if /I "%PAPER_EXECUTION_APPEND%"=="candidate-only" set "PAPER_EXECUTION_APPEND_ARG="

if defined PAPER_EXECUTION_RECOMMENDATION_JSON (
  "%PYTHON%" "scripts\run_paper_execution_daily.py" --recommendation-json "%PAPER_EXECUTION_RECOMMENDATION_JSON%" --state-db "%PAPER_EXECUTION_STATE_DB%" --market-db "%PAPER_EXECUTION_MARKET_DB%" --output-root "%PAPER_EXECUTION_OUTPUT_ROOT%" --ledger-db "%PAPER_EXECUTION_LEDGER_DB%" --receipt-root "%PAPER_EXECUTION_RECEIPT_ROOT%" %PAPER_EXECUTION_APPEND_ARG% %PAPER_EXECUTION_CLOCK_ARG%
) else (
  "%PYTHON%" "scripts\run_paper_execution_daily.py" --recommendation-root "%PAPER_EXECUTION_RECOMMENDATION_ROOT%" --state-db "%PAPER_EXECUTION_STATE_DB%" --market-db "%PAPER_EXECUTION_MARKET_DB%" --output-root "%PAPER_EXECUTION_OUTPUT_ROOT%" --ledger-db "%PAPER_EXECUTION_LEDGER_DB%" --receipt-root "%PAPER_EXECUTION_RECEIPT_ROOT%" %PAPER_EXECUTION_APPEND_ARG% %PAPER_EXECUTION_CLOCK_ARG%
)
exit /b %ERRORLEVEL%
