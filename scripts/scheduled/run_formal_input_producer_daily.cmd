@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

if defined BALDR_PYTHON set "PYTHON=%BALDR_PYTHON%"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"
if not defined DATA_ROOT set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if not defined OUTPUT_ROOT set "OUTPUT_ROOT=%DATA_ROOT%\output"
rem Formal 與盤前 writer 共用這份 repository Paper snapshot；D 槽只保留
rem market/source read-only input，candidate output 仍分離寫入 publication root。
set "FORMAL_DAILY_PAPER_SNAPSHOT_DB=%REPO_ROOT%\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite"
if not defined FORMAL_DAILY_MARKET_DB set "FORMAL_DAILY_MARKET_DB=%DATA_ROOT%\sqlite\twstock.db"
if not defined FORMAL_DAILY_PUBLICATION_ROOT set "FORMAL_DAILY_PUBLICATION_ROOT=%REPO_ROOT%\output\formal_daily_publications"
if not defined FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT set "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT=%FORMAL_DAILY_PUBLICATION_ROOT%\pit_candidate_archive"
rem 當日 Rule source 由盤前 machine revalidation producer 建在 repository
rem publication root；D 槽的既有 clock 僅作唯讀 parent policy，不能遮蔽
rem 當日 source-window hash。Python wrapper 會選取最新且完整、可重驗的
rem bundle；每輪不需手動編輯三個來源路徑。
if not defined FORMAL_DAILY_RULE_SOURCE_ROOT set "FORMAL_DAILY_RULE_SOURCE_ROOT=%FORMAL_DAILY_PUBLICATION_ROOT%\rule_source"
rem Formal ledger 來源由隔離的 Paper EOD 工作產生。排程交接不得繼承舊版
rem D writer 路徑；仍可由明確的 FORMAL_DAILY_PAPER_TRADE_LEDGER_DB
rem 選取已驗證來源。
if not defined FORMAL_DAILY_PAPER_TRADE_LEDGER_DB set "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB=%REPO_ROOT%\output\paper_execution_eod_replay\paper_trade_ledger.sqlite"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 來源路徑只在 Windows 使用者環境設定一次；缺件由 Python 入口寫入
rem durable latest_status.json 並以非零狀態結束，不會靜默略過。
"%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_formal_input_producer_daily.py"
exit /b %ERRORLEVEL%
