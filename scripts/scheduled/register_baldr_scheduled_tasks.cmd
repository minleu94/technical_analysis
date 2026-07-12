@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I "%MODE%"=="weekly-register" goto weekly_register
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="register" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

set "UPDATE_TASK=baldr-data-update-quick-daily"
set "FRESH_TASK=baldr-data-freshness-check-daily"
set "RECOMMENDATION_TASK=baldr-recommendation-snapshot-daily"
set "EVIDENCE_TASK=baldr-evidence-pipeline-dry-run-daily"
set "SMOKE_TASK=baldr-evidence-working-copy-smoke-manual"
set "UPDATE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_daily_data_update_quick.cmd"
set "FRESH_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_daily_data_freshness_check.cmd"
set "RECOMMENDATION_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_recommendation_snapshot.cmd"
set "EVIDENCE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"
set "UPDATE_ACTION=cmd.exe /c ""%UPDATE_SCRIPT%"""
set "FRESH_ACTION=cmd.exe /c ""%FRESH_SCRIPT%"""
set "RECOMMENDATION_ACTION=cmd.exe /c ""%RECOMMENDATION_SCRIPT%"""
set "EVIDENCE_ACTION=cmd.exe /c ""%EVIDENCE_SCRIPT%"""
set "WEEKLY_TASK=baldr-v2-2-weekly-collection"
set "WEEKLY_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_v2_2_weekly_collection.cmd"
set "WEEKLY_ACTION=cmd.exe /c ""%WEEKLY_SCRIPT%"""

echo Mode: %MODE%
echo Task: %UPDATE_TASK%
echo   Schedule: DAILY 04:20
echo   Action: %UPDATE_ACTION%
echo Task: %FRESH_TASK%
echo   Schedule: DAILY 05:00
echo   Action: %FRESH_ACTION%
echo Task: %RECOMMENDATION_TASK%
echo   Schedule: DAILY 05:10
echo   Action: %RECOMMENDATION_ACTION%
echo Task: %EVIDENCE_TASK%
echo   Schedule: DAILY 05:15
echo   Action: %EVIDENCE_ACTION%
echo Task: %SMOKE_TASK%
echo   Manual-only: no daily task will be created by this script.

if /I "%MODE%"=="dryrun" (
  echo Task: %WEEKLY_TASK%
  echo   Schedule: WEEKLY SUN 18:00
  echo   Action: %WEEKLY_ACTION%
  echo Dryrun only. No scheduled task was created.
  exit /b 0
)

schtasks.exe /Create /TN "%UPDATE_TASK%" /SC DAILY /ST 04:20 /TR "%UPDATE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%FRESH_TASK%" /SC DAILY /ST 05:00 /TR "%FRESH_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%RECOMMENDATION_TASK%" /SC DAILY /ST 05:10 /TR "%RECOMMENDATION_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%EVIDENCE_TASK%" /SC DAILY /ST 05:15 /TR "%EVIDENCE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo Registered tasks:
schtasks.exe /Query /TN "%UPDATE_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%FRESH_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%RECOMMENDATION_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%EVIDENCE_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
exit /b 0

:weekly_register
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

set "WEEKLY_TASK=baldr-v2-2-weekly-collection"
set "WEEKLY_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_v2_2_weekly_collection.cmd"
set "WEEKLY_ACTION=cmd.exe /c ""%WEEKLY_SCRIPT%"""

echo Mode: weekly-register
echo Task: %WEEKLY_TASK%
echo   Schedule: WEEKLY SUN 18:00
echo   Action: %WEEKLY_ACTION%

schtasks.exe /Create /TN "%WEEKLY_TASK%" /SC WEEKLY /D SUN /ST 18:00 /TR "%WEEKLY_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo Registered task:
schtasks.exe /Query /TN "%WEEKLY_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun^|register^|weekly-register
exit /b 2
