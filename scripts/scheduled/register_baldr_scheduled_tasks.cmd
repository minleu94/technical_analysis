@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="register" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

set "FRESH_TASK=baldr-data-freshness-check-daily"
set "EVIDENCE_TASK=baldr-evidence-pipeline-dry-run-daily"
set "SMOKE_TASK=baldr-evidence-working-copy-smoke-manual"
set "FRESH_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_daily_data_freshness_check.cmd"
set "EVIDENCE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"
set "FRESH_ACTION=cmd.exe /c ""%FRESH_SCRIPT%"""
set "EVIDENCE_ACTION=cmd.exe /c ""%EVIDENCE_SCRIPT%"""

echo Mode: %MODE%
echo Task: %FRESH_TASK%
echo   Schedule: DAILY 05:00
echo   Action: %FRESH_ACTION%
echo Task: %EVIDENCE_TASK%
echo   Schedule: DAILY 05:15
echo   Action: %EVIDENCE_ACTION%
echo Task: %SMOKE_TASK%
echo   Manual-only: no daily task will be created by this script.

if /I "%MODE%"=="dryrun" (
  echo Dryrun only. No scheduled task was created.
  exit /b 0
)

schtasks.exe /Create /TN "%FRESH_TASK%" /SC DAILY /ST 05:00 /TR "%FRESH_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

schtasks.exe /Create /TN "%EVIDENCE_TASK%" /SC DAILY /ST 05:15 /TR "%EVIDENCE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo Registered tasks:
schtasks.exe /Query /TN "%FRESH_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
schtasks.exe /Query /TN "%EVIDENCE_TASK%" /V /FO LIST
if errorlevel 1 exit /b %ERRORLEVEL%
exit /b 0

:usage
echo Usage: scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun^|register
exit /b 2
