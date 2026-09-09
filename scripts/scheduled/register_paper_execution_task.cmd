@echo off
setlocal EnableExtensions

rem This script registers exactly one research-only Paper execution task. It
rem intentionally does not call the aggregate scheduler registration script.
set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="register" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "PAPER_EXECUTION_TASK=baldr-paper-execution-eod-replay-daily"
set "PAPER_EXECUTION_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_paper_execution_daily_isolated.cmd"
set "PAPER_EXECUTION_ACTION=cmd.exe /c ""%PAPER_EXECUTION_SCRIPT%"""
set "PAPER_EXECUTION_TIME=06:00"
if not defined BALDR_SCHTASKS_EXE set "BALDR_SCHTASKS_EXE=schtasks.exe"
if not defined BALDR_POWERSHELL_EXE set "BALDR_POWERSHELL_EXE=powershell.exe"

rem Task Scheduler uses host local time. 06:00 Pacific maps to 21:00 in
rem Taipei during PDT and 22:00 during PST. It runs after the 04:20 data
rem update and 05:00 freshness gate on the same Pacific natural day, while
rem remaining after the 15:00 delayed-EOD source gate in Taipei. Do not
rem change login, battery, wake, or retry policy here.
set "LOCAL_TIME_ZONE="
for /f "delims=" %%Z in ('tzutil /g 2^>nul') do set "LOCAL_TIME_ZONE=%%Z"
if /I not "%LOCAL_TIME_ZONE%"=="Pacific Standard Time" (
  echo Registration blocked: Windows timezone must be Pacific Standard Time; detected "%LOCAL_TIME_ZONE%".
  exit /b 2
)

echo Mode: %MODE%
echo Task: %PAPER_EXECUTION_TASK%
echo   Schedule: DAILY %PAPER_EXECUTION_TIME% Pacific local time
echo   Taipei mapping: 21:00 PDT / 22:00 PST (after update and freshness)
echo   Execution policy: existing principal/settings preserved; adapter bounded retry is repository-scoped
echo   Scope: research-only repo-isolated Paper ledger; D snapshot/market/recommendation are read-only
echo   Action: %PAPER_EXECUTION_ACTION%
echo   Wrapper: %PAPER_EXECUTION_SCRIPT%

if not exist "%PAPER_EXECUTION_SCRIPT%" (
  echo Wrapper missing: %PAPER_EXECUTION_SCRIPT%
  echo Wrapper preflight failed. No scheduled task was created.
  exit /b 2
)

if /I "%MODE%"=="dryrun" (
  echo Dryrun only. No scheduled task was created.
  exit /b 0
)

rem Existing tasks use schtasks /Change for trigger/action only. This preserves
rem principal, login, battery, wake, retry, and all other settings; /Create is
rem used only after a confirmed not-found query.
set "QUERY_OUTPUT=%TEMP%\baldr_paper_execution_query_%RANDOM%.txt"
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%PAPER_EXECUTION_TASK%" /FO LIST >"%QUERY_OUTPUT%" 2>&1
set "QUERY_EXIT=%ERRORLEVEL%"
if "%QUERY_EXIT%"=="0" goto existing_task
rem A nonzero query is not proof of absence. Permission, service, and other
rem query errors fail closed.
findstr /I /C:"cannot find" /C:"not found" "%QUERY_OUTPUT%" >nul
if errorlevel 1 (
  echo Scheduler query failed; refusing to create or change the task.
  type "%QUERY_OUTPUT%"
  del /q "%QUERY_OUTPUT%" >nul 2>&1
  exit /b 2
)
del /q "%QUERY_OUTPUT%" >nul 2>&1
goto create_task

:existing_task
del /q "%QUERY_OUTPUT%" >nul 2>&1
echo Existing task found; updating only trigger and action.
call "%BALDR_SCHTASKS_EXE%" /Change /TN "%PAPER_EXECUTION_TASK%" /ST %PAPER_EXECUTION_TIME% /TR "%PAPER_EXECUTION_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%
goto query_task

:create_task
echo Task not found; creating the single Paper execution task.
call "%BALDR_SCHTASKS_EXE%" /Create /TN "%PAPER_EXECUTION_TASK%" /SC DAILY /ST %PAPER_EXECUTION_TIME% /TR "%PAPER_EXECUTION_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%

rem Newly created tasks receive only the bounded execution policy; the existing
rem task path above never replaces its principal or host power settings.
call "%BALDR_POWERSHELL_EXE%" -NoProfile -Command "$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1); Set-ScheduledTask -TaskName '%PAPER_EXECUTION_TASK%' -Settings $settings"
if errorlevel 1 (
  echo Registration incomplete: scheduler execution policy could not be applied to the new task.
  exit /b 2
)

echo.
echo Registered task:
:query_task
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%PAPER_EXECUTION_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_paper_execution_task.cmd dryrun^|register
exit /b 2
