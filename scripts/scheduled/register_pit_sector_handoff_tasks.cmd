@echo off
setlocal EnableExtensions

rem 這個腳本只註冊 PIT 盤前 capture 與盤後 sidecar 兩項 task；不會
rem 重註冊其他 BALDR task，也不會啟動任何交易或資料庫更新。
set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="register" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "CAPTURE_TASK=baldr-pit-sector-membership-preopen-capture-daily"
set "SIDECAR_TASK=baldr-formal-pit-sidecar-postcutoff-daily"
set "CAPTURE_TIME=16:00"
set "SIDECAR_TIME=18:00"
set "CAPTURE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_pit_sector_membership_preopen_capture.cmd"
set "SIDECAR_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_formal_pit_sidecar_postcutoff.cmd"
set "CAPTURE_ACTION=cmd.exe /c ""%CAPTURE_SCRIPT%"""
set "SIDECAR_ACTION=cmd.exe /c ""%SIDECAR_SCRIPT%"""
if not defined BALDR_SCHTASKS_EXE set "BALDR_SCHTASKS_EXE=schtasks.exe"
if not defined BALDR_POWERSHELL_EXE set "BALDR_POWERSHELL_EXE=powershell.exe"

set "LOCAL_TIME_ZONE="
for /f "delims=" %%Z in ('tzutil /g 2^>nul') do set "LOCAL_TIME_ZONE=%%Z"
if /I not "%LOCAL_TIME_ZONE%"=="Pacific Standard Time" (
  echo Registration blocked: Windows timezone must be Pacific Standard Time; detected "%LOCAL_TIME_ZONE%".
  exit /b 2
)

echo Mode: %MODE%
echo Task: %CAPTURE_TASK%
echo   Schedule: DAILY %CAPTURE_TIME% Pacific local time
echo   Taipei mapping: 07:00 PDT / 08:00 PST; both before 08:30
echo   Action: %CAPTURE_ACTION%
echo Task: %SIDECAR_TASK%
echo   Schedule: DAILY %SIDECAR_TIME% Pacific local time
echo   Taipei mapping: 09:00 PDT / 10:00 PST; both after 08:30
echo   Action: %SIDECAR_ACTION%

if not exist "%CAPTURE_SCRIPT%" (
  echo Wrapper missing: %CAPTURE_SCRIPT%
  echo Wrapper preflight failed. No scheduled task was created.
  exit /b 2
)
if not exist "%SIDECAR_SCRIPT%" (
  echo Wrapper missing: %SIDECAR_SCRIPT%
  echo Wrapper preflight failed. No scheduled task was created.
  exit /b 2
)
if /I "%MODE%"=="dryrun" (
  echo Dryrun only. No scheduled task was created.
  exit /b 0
)

call "%BALDR_SCHTASKS_EXE%" /Create /TN "%CAPTURE_TASK%" /SC DAILY /ST %CAPTURE_TIME% /TR "%CAPTURE_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%
call "%BALDR_SCHTASKS_EXE%" /Create /TN "%SIDECAR_TASK%" /SC DAILY /ST %SIDECAR_TIME% /TR "%SIDECAR_ACTION%" /F
if errorlevel 1 exit /b %ERRORLEVEL%

rem 每一輪最多一小時，同一 task 不重入；不修改現有其他 task。
call "%BALDR_POWERSHELL_EXE%" -NoProfile -Command "$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1); Set-ScheduledTask -TaskName '%CAPTURE_TASK%' -Settings $settings; Set-ScheduledTask -TaskName '%SIDECAR_TASK%' -Settings $settings"
if errorlevel 1 (
  echo Registration incomplete: scheduler execution policy could not be applied.
  exit /b 2
)

echo.
echo Registered PIT handoff tasks:
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%CAPTURE_TASK%" /V /FO LIST
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%SIDECAR_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_pit_sector_handoff_tasks.cmd dryrun^|register
exit /b 2
