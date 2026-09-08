@echo off
setlocal EnableExtensions

rem This script registers exactly one task. It intentionally does not call the
rem aggregate baldr scheduler registration script.
set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="register" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "FORMAL_INPUT_TASK=baldr-formal-input-producer-daily"
set "FORMAL_INPUT_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_formal_input_producer_daily.cmd"
set "FORMAL_INPUT_ACTION=cmd.exe /c ""%FORMAL_INPUT_SCRIPT%"""
set "FORMAL_INPUT_TIME=21:25"
if not defined BALDR_SCHTASKS_EXE set "BALDR_SCHTASKS_EXE=schtasks.exe"
if not defined BALDR_POWERSHELL_EXE set "BALDR_POWERSHELL_EXE=powershell.exe"

rem Windows Task Scheduler stores a daily trigger in host local time. The
rem Pacific 21:25 anchor is safe across PDT/PST for the Taipei Rule window.
set "LOCAL_TIME_ZONE="
for /f "delims=" %%Z in ('tzutil /g 2^>nul') do set "LOCAL_TIME_ZONE=%%Z"
if /I not "%LOCAL_TIME_ZONE%"=="Pacific Standard Time" (
  echo Registration blocked: Windows timezone must be Pacific Standard Time; detected "%LOCAL_TIME_ZONE%".
  exit /b 2
)

echo Mode: %MODE%
echo Task: %FORMAL_INPUT_TASK%
echo   Schedule: DAILY %FORMAL_INPUT_TIME% Pacific local time
echo   Taipei mapping: 12:25 PDT / 13:25 PST
echo   Execution policy: 1 hour limit; duplicate instances IgnoreNew
echo   Action: %FORMAL_INPUT_ACTION%
echo   Wrapper: %FORMAL_INPUT_SCRIPT%

if not exist "%FORMAL_INPUT_SCRIPT%" (
  echo Wrapper missing: %FORMAL_INPUT_SCRIPT%
  echo Wrapper preflight failed. No scheduled task was created.
  exit /b 2
)

if /I "%MODE%"=="dryrun" (
  echo Dryrun only. No scheduled task was created.
  exit /b 0
)

call "%BALDR_SCHTASKS_EXE%" /Create /TN "%FORMAL_INPUT_TASK%" /SC DAILY /ST %FORMAL_INPUT_TIME% /TR "%FORMAL_INPUT_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

rem Apply a bounded execution limit and prevent overlapping instances. The
rem command mode is used so Restricted execution policy is not bypassed.
call "%BALDR_POWERSHELL_EXE%" -NoProfile -Command "$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1); Set-ScheduledTask -TaskName '%FORMAL_INPUT_TASK%' -Settings $settings"
if errorlevel 1 (
  echo Registration incomplete: scheduler execution policy could not be applied.
  exit /b 2
)

echo.
echo Registered task:
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%FORMAL_INPUT_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_formal_input_producer_task.cmd dryrun^|register
exit /b 2
