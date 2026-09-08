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
set "PAPER_EXECUTION_TIME=00:05"
if not defined BALDR_SCHTASKS_EXE set "BALDR_SCHTASKS_EXE=schtasks.exe"
if not defined BALDR_POWERSHELL_EXE set "BALDR_POWERSHELL_EXE=powershell.exe"

rem Task Scheduler uses host local time. 00:05 Pacific maps to 15:05 in
rem Taipei during PDT and 16:05 during PST, both after the 15:00 delayed-EOD
rem source gate. Do not change login or battery policy here.
set "LOCAL_TIME_ZONE="
for /f "delims=" %%Z in ('tzutil /g 2^>nul') do set "LOCAL_TIME_ZONE=%%Z"
if /I not "%LOCAL_TIME_ZONE%"=="Pacific Standard Time" (
  echo Registration blocked: Windows timezone must be Pacific Standard Time; detected "%LOCAL_TIME_ZONE%".
  exit /b 2
)

echo Mode: %MODE%
echo Task: %PAPER_EXECUTION_TASK%
echo   Schedule: DAILY %PAPER_EXECUTION_TIME% Pacific local time
echo   Taipei mapping: 15:05 PDT / 16:05 PST (after delayed EOD gate)
echo   Execution policy: 1 hour limit; duplicate instances IgnoreNew
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

call "%BALDR_SCHTASKS_EXE%" /Create /TN "%PAPER_EXECUTION_TASK%" /SC DAILY /ST %PAPER_EXECUTION_TIME% /TR "%PAPER_EXECUTION_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

rem Keep the host's existing interactive/login and battery restrictions. Only
rem bound execution time and duplicate-instance behavior are set here.
call "%BALDR_POWERSHELL_EXE%" -NoProfile -Command "$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1); Set-ScheduledTask -TaskName '%PAPER_EXECUTION_TASK%' -Settings $settings"
if errorlevel 1 (
  echo Registration incomplete: scheduler execution policy could not be applied.
  exit /b 2
)

echo.
echo Registered task:
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%PAPER_EXECUTION_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_paper_execution_task.cmd dryrun^|register
exit /b 2
