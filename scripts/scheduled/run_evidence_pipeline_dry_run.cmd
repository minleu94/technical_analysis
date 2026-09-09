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
if "%PAPER_EVIDENCE_OPERATION_ROOT%"=="" set "PAPER_EVIDENCE_OPERATION_ROOT=%REPO_ROOT%\output\paper_execution_eod_replay"
if "%PAPER_EVIDENCE_LEDGER_DB%"=="" set "PAPER_EVIDENCE_LEDGER_DB=%PAPER_EVIDENCE_OPERATION_ROOT%\paper_trade_ledger.sqlite"
if "%PAPER_EVIDENCE_HEALTH_STATUS_PATH%"=="" set "PAPER_EVIDENCE_HEALTH_STATUS_PATH=%PAPER_EVIDENCE_OPERATION_ROOT%\scheduled\paper_portfolio_isolated\latest_status.json"
if "%PAPER_EVIDENCE_HEALTH_BASELINE%"=="" set "PAPER_EVIDENCE_HEALTH_BASELINE=%OUTPUT_ROOT%\position_health\latest.json"
if "%PAPER_EVIDENCE_STATUS_PATH%"=="" set "PAPER_EVIDENCE_STATUS_PATH=%PAPER_EVIDENCE_OPERATION_ROOT%\scheduled\paper_portfolio_daily\latest_status.json"
if "%PAPER_HEALTH_SOURCE_OUTPUT%"=="" set "PAPER_HEALTH_SOURCE_OUTPUT=%OUTPUT_ROOT%\position_health_sources"
if "%PAPER_HEALTH_FORWARD_BINDING%"=="" set "PAPER_HEALTH_FORWARD_BINDING=%REPO_ROOT%\output\forward_position_thesis\bindings"
if "%PAPER_HEALTH_POLICY_SOURCE%"=="" set "PAPER_HEALTH_POLICY_SOURCE=%REPO_ROOT%\output\formal_daily_publications\rule_source\scheduler\rule_source_latest_status.json"

"%PYTHON%" "scripts\scheduled\run_scheduled_evidence_pipeline_dry_run.py" --dry-run --refresh-paper-health --bind-forward-thesis --produce-position-health-sources --evaluate-position-health-transition --run-exit-effectiveness --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --db-path "%DB_PATH%" --sources "%SOURCES%" --paper-evidence-operation-root "%PAPER_EVIDENCE_OPERATION_ROOT%" --paper-evidence-ledger-db "%PAPER_EVIDENCE_LEDGER_DB%" --paper-evidence-health-status-path "%PAPER_EVIDENCE_HEALTH_STATUS_PATH%" --paper-evidence-health-baseline "%PAPER_EVIDENCE_HEALTH_BASELINE%" --paper-evidence-status-path "%PAPER_EVIDENCE_STATUS_PATH%" --paper-health-source-output "%PAPER_HEALTH_SOURCE_OUTPUT%" --paper-health-forward-binding "%PAPER_HEALTH_FORWARD_BINDING%" --paper-health-policy-source "%PAPER_HEALTH_POLICY_SOURCE%"
exit /b %ERRORLEVEL%
