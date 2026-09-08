@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I "%MODE%"=="weekly-register" goto weekly_register
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="register" if /I not "%MODE%"=="register-all" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

set "UPDATE_TASK=baldr-data-update-quick-daily"
set "OFFICIAL_EVENTS_TASK=baldr-official-market-events-daily"
set "FRESH_TASK=baldr-data-freshness-check-daily"
set "ML_RAW_PIT_REFRESH_TASK=baldr-ml-raw-pit-refresh-daily"
set "ML_DIRECT_CHAIN_MAINTAINER_TASK=baldr-ml-direct-chain-maintainer"
set "RECOMMENDATION_TASK=baldr-recommendation-snapshot-daily"
set "EVIDENCE_TASK=baldr-evidence-pipeline-dry-run-daily"
set "ML_PROMOTION_EVIDENCE_TASK=baldr-ml-promotion-evidence-daily"
set "ML_COPILOT_TASK=baldr-ml-allocation-copilot-daily"
set "ML_PROMOTION_AUTHORITY_TASK=baldr-ml-promotion-authority-daily"
set "DECISION_EVIDENCE_TASK=baldr-decision-evidence-capture-daily"
set "PAPER_PORTFOLIO_TASK=baldr-paper-portfolio-daily"
set "PAPER_EXECUTION_TASK=baldr-paper-execution-eod-replay-daily"
set "FORMAL_INPUT_TASK=baldr-formal-input-producer-daily"
set "UPDATE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_daily_data_update_quick.cmd"
set "OFFICIAL_EVENTS_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_official_market_event_backfill.cmd"
set "FRESH_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_daily_data_freshness_check.cmd"
set "ML_RAW_PIT_REFRESH_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_ml_raw_pit_refresh.cmd"
set "ML_DIRECT_CHAIN_MAINTAINER_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_ml_direct_chain_maintenance.cmd"
set "RECOMMENDATION_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_recommendation_snapshot.cmd"
set "EVIDENCE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"
set "ML_PROMOTION_EVIDENCE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_ml_promotion_evidence.cmd"
set "ML_COPILOT_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_ml_allocation_copilot.cmd"
set "ML_PROMOTION_AUTHORITY_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_ml_promotion_authority.cmd"
set "DECISION_EVIDENCE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_decision_evidence_capture.cmd"
set "PAPER_PORTFOLIO_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_paper_portfolio_daily.cmd"
set "PAPER_EXECUTION_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_paper_execution_daily_isolated.cmd"
set "FORMAL_INPUT_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_formal_input_producer_daily.cmd"
set "UPDATE_ACTION=cmd.exe /c ""%UPDATE_SCRIPT%"""
set "OFFICIAL_EVENTS_ACTION=cmd.exe /c ""%OFFICIAL_EVENTS_SCRIPT%"""
set "FRESH_ACTION=cmd.exe /c ""%FRESH_SCRIPT%"""
set "ML_RAW_PIT_REFRESH_ACTION=cmd.exe /c ""%ML_RAW_PIT_REFRESH_SCRIPT%"""
set "ML_DIRECT_CHAIN_MAINTAINER_ACTION=cmd.exe /c ""%ML_DIRECT_CHAIN_MAINTAINER_SCRIPT%"""
set "RECOMMENDATION_ACTION=cmd.exe /c ""%RECOMMENDATION_SCRIPT%"""
set "EVIDENCE_ACTION=cmd.exe /c ""%EVIDENCE_SCRIPT%"""
set "ML_PROMOTION_EVIDENCE_ACTION=cmd.exe /c ""%ML_PROMOTION_EVIDENCE_SCRIPT%"""
set "ML_COPILOT_ACTION=cmd.exe /c ""%ML_COPILOT_SCRIPT%"""
set "ML_PROMOTION_AUTHORITY_ACTION=cmd.exe /c ""%ML_PROMOTION_AUTHORITY_SCRIPT%"""
set "DECISION_EVIDENCE_ACTION=cmd.exe /c ""%DECISION_EVIDENCE_SCRIPT%"""
set "PAPER_PORTFOLIO_ACTION=cmd.exe /c ""%PAPER_PORTFOLIO_SCRIPT%"""
set "PAPER_EXECUTION_ACTION=cmd.exe /c ""%PAPER_EXECUTION_SCRIPT%"""
set "FORMAL_INPUT_ACTION=cmd.exe /c ""%FORMAL_INPUT_SCRIPT%"""
set "WEEKLY_TASK=baldr-v2-2-weekly-collection"
set "WEEKLY_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_v2_2_weekly_collection.cmd"
set "WEEKLY_ACTION=cmd.exe /c ""%WEEKLY_SCRIPT%"""
set "CHECK_WEEKLY=0"
if /I "%MODE%"=="dryrun" set "CHECK_WEEKLY=1"
if /I "%MODE%"=="register-all" set "CHECK_WEEKLY=1"

echo Mode: %MODE%
echo Task: %PAPER_EXECUTION_TASK%
echo   Schedule: DAILY 00:05
echo   Action: %PAPER_EXECUTION_ACTION%
echo Task: %UPDATE_TASK%
echo   Schedule: DAILY 04:20
echo   Action: %UPDATE_ACTION%
echo Task: %OFFICIAL_EVENTS_TASK%
echo   Schedule: DAILY 04:50
echo   Action: %OFFICIAL_EVENTS_ACTION%
echo Task: %FRESH_TASK%
echo   Schedule: DAILY 05:00
echo   Action: %FRESH_ACTION%
echo Task: %ML_RAW_PIT_REFRESH_TASK%
echo   Schedule: DAILY 05:05
echo   Action: %ML_RAW_PIT_REFRESH_ACTION%
echo Task: %ML_DIRECT_CHAIN_MAINTAINER_TASK%
echo   Schedule: DAILY 05:30
echo   Action: %ML_DIRECT_CHAIN_MAINTAINER_ACTION%
echo Task: %RECOMMENDATION_TASK%
echo   Schedule: DAILY 05:10
echo   Action: %RECOMMENDATION_ACTION%
echo Task: %EVIDENCE_TASK%
echo   Schedule: DAILY 05:15
echo   Action: %EVIDENCE_ACTION%
echo Task: %ML_PROMOTION_EVIDENCE_TASK%
echo   Schedule: DAILY 05:17
echo   Action: %ML_PROMOTION_EVIDENCE_ACTION%
echo Task: %ML_PROMOTION_AUTHORITY_TASK%
echo   Schedule: DAILY 05:18
echo   Action: %ML_PROMOTION_AUTHORITY_ACTION%
echo Task: %ML_COPILOT_TASK%
echo   Schedule: DAILY 05:20
echo   Action: %ML_COPILOT_ACTION%
echo Task: %DECISION_EVIDENCE_TASK%
echo   Schedule: DAILY 05:25
echo   Action: %DECISION_EVIDENCE_ACTION%
echo Task: %PAPER_PORTFOLIO_TASK%
echo   Schedule: DAILY 16:30 Pacific local time
echo   Taipei mapping: 07:30 PDT / 08:30 PST; adapter waits for Taipei 08:30
echo   Action: %PAPER_PORTFOLIO_ACTION%
echo Task: %FORMAL_INPUT_TASK%
echo   Schedule: DAILY 21:25
echo   Action: %FORMAL_INPUT_ACTION%
if /I "%MODE%"=="dryrun" (
  echo Task: %WEEKLY_TASK%
  echo   Schedule: WEEKLY SUN 18:00
  echo   Action: %WEEKLY_ACTION%
)
if /I "%MODE%"=="register-all" (
  echo Task: %WEEKLY_TASK%
  echo   Schedule: WEEKLY SUN 18:00
  echo   Action: %WEEKLY_ACTION%
)

rem 所有正式註冊都必須在 Pacific 主機執行；Paper adapter 會再以
rem Asia/Taipei 真實 08:30 cutoff guard 阻止早到來源讀取。
if /I "%MODE%"=="register" call :check_timezone
if errorlevel 1 exit /b 2
if /I "%MODE%"=="register-all" call :check_timezone
if errorlevel 1 exit /b 2

set "WRAPPER_MISSING=0"
call :check_wrapper "%UPDATE_SCRIPT%"
call :check_wrapper "%OFFICIAL_EVENTS_SCRIPT%"
call :check_wrapper "%FRESH_SCRIPT%"
call :check_wrapper "%ML_RAW_PIT_REFRESH_SCRIPT%"
call :check_wrapper "%ML_DIRECT_CHAIN_MAINTAINER_SCRIPT%"
call :check_wrapper "%RECOMMENDATION_SCRIPT%"
call :check_wrapper "%EVIDENCE_SCRIPT%"
call :check_wrapper "%ML_PROMOTION_EVIDENCE_SCRIPT%"
call :check_wrapper "%ML_PROMOTION_AUTHORITY_SCRIPT%"
call :check_wrapper "%ML_COPILOT_SCRIPT%"
call :check_wrapper "%DECISION_EVIDENCE_SCRIPT%"
call :check_wrapper "%PAPER_PORTFOLIO_SCRIPT%"
call :check_wrapper "%PAPER_EXECUTION_SCRIPT%"
call :check_wrapper "%FORMAL_INPUT_SCRIPT%"
if "%CHECK_WEEKLY%"=="1" call :check_wrapper "%WEEKLY_SCRIPT%"
if "%WRAPPER_MISSING%"=="1" (
  echo Wrapper preflight failed. No scheduled task was created.
  exit /b 2
)

if /I "%MODE%"=="dryrun" (
  echo Dryrun only. No scheduled task was created.
  exit /b 0
)

schtasks.exe /Create /TN "%UPDATE_TASK%" /SC DAILY /ST 04:20 /TR "%UPDATE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%OFFICIAL_EVENTS_TASK%" /SC DAILY /ST 04:50 /TR "%OFFICIAL_EVENTS_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%FRESH_TASK%" /SC DAILY /ST 05:00 /TR "%FRESH_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%ML_RAW_PIT_REFRESH_TASK%" /SC DAILY /ST 05:05 /TR "%ML_RAW_PIT_REFRESH_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%ML_DIRECT_CHAIN_MAINTAINER_TASK%" /SC DAILY /ST 05:30 /TR "%ML_DIRECT_CHAIN_MAINTAINER_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%RECOMMENDATION_TASK%" /SC DAILY /ST 05:10 /TR "%RECOMMENDATION_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%EVIDENCE_TASK%" /SC DAILY /ST 05:15 /TR "%EVIDENCE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%ML_PROMOTION_EVIDENCE_TASK%" /SC DAILY /ST 05:17 /TR "%ML_PROMOTION_EVIDENCE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%ML_PROMOTION_AUTHORITY_TASK%" /SC DAILY /ST 05:18 /TR "%ML_PROMOTION_AUTHORITY_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%ML_COPILOT_TASK%" /SC DAILY /ST 05:20 /TR "%ML_COPILOT_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%DECISION_EVIDENCE_TASK%" /SC DAILY /ST 05:25 /TR "%DECISION_EVIDENCE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

rem Paper Portfolio 既有 task 只允許 dedicated wrapper 用 /Change 保留其餘
rem principal/settings；不存在時才由它建立，不在 aggregate 路徑用 /F 覆蓋。
call "%SCRIPT_DIR%register_paper_portfolio_task.cmd" register
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%PAPER_EXECUTION_TASK%" /SC DAILY /ST 00:05 /TR "%PAPER_EXECUTION_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%FORMAL_INPUT_TASK%" /SC DAILY /ST 21:25 /TR "%FORMAL_INPUT_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

if /I "%MODE%"=="register-all" (
  schtasks.exe /Create /TN "%WEEKLY_TASK%" /SC WEEKLY /D SUN /ST 18:00 /TR "%WEEKLY_ACTION%" /F
  if errorlevel 1 exit /b %ERRORLEVEL%
)

echo.
echo Registered tasks:
schtasks.exe /Query /TN "%UPDATE_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%OFFICIAL_EVENTS_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%FRESH_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%ML_RAW_PIT_REFRESH_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%ML_DIRECT_CHAIN_MAINTAINER_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%RECOMMENDATION_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%EVIDENCE_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%ML_PROMOTION_EVIDENCE_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%ML_PROMOTION_AUTHORITY_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%ML_COPILOT_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%DECISION_EVIDENCE_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%PAPER_PORTFOLIO_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%PAPER_EXECUTION_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%FORMAL_INPUT_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
if /I "%MODE%"=="register-all" (
  schtasks.exe /Query /TN "%WEEKLY_TASK%" /V /FO LIST
  if errorlevel 1 exit /b %ERRORLEVEL%
)
exit /b 0

:weekly_register
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

if /I "%MODE%"=="register" call :check_timezone
if errorlevel 1 exit /b 2
if /I "%MODE%"=="register-all" call :check_timezone
if errorlevel 1 exit /b 2

set "WEEKLY_TASK=baldr-v2-2-weekly-collection"
set "WEEKLY_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_v2_2_weekly_collection.cmd"
set "WEEKLY_ACTION=cmd.exe /c ""%WEEKLY_SCRIPT%"""

echo Mode: weekly-register
echo Task: %WEEKLY_TASK%
echo   Schedule: WEEKLY SUN 18:00
echo   Action: %WEEKLY_ACTION%

if not exist "%WEEKLY_SCRIPT%" (
  echo Wrapper missing: %WEEKLY_SCRIPT%
  echo Wrapper preflight failed. No scheduled task was created.
  exit /b 2
)

schtasks.exe /Create /TN "%WEEKLY_TASK%" /SC WEEKLY /D SUN /ST 18:00 /TR "%WEEKLY_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo Registered task:
schtasks.exe /Query /TN "%WEEKLY_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun^|register^|register-all^|weekly-register
exit /b 2

:check_timezone
set "LOCAL_TIME_ZONE="
for /f "delims=" %%Z in ('tzutil /g 2^>nul') do set "LOCAL_TIME_ZONE=%%Z"
if /I not "%LOCAL_TIME_ZONE%"=="Pacific Standard Time" (
  echo Registration blocked: Windows timezone must be Pacific Standard Time; detected "%LOCAL_TIME_ZONE%".
  exit /b 2
)
exit /b 0

:check_wrapper
if not exist "%~1" (
  echo Wrapper missing: %~1
  set "WRAPPER_MISSING=1"
)
exit /b 0
