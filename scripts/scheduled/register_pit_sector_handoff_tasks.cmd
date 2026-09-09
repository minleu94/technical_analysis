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
set "PAPER_EVENT_CAPTURE_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_paper_event_source_capture_daily.cmd"
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
echo   Paper event source: same action, after PIT sidecar readback

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

rem 既有 task 只用 schtasks /Change 更新 trigger/action，保留 principal、登入、
rem 電池、wake、retry 與其他 settings；只有明確查到 task 不存在時才建立。
set "CAPTURE_QUERY=%TEMP%\baldr_pit_capture_query_%RANDOM%.txt"
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%CAPTURE_TASK%" /FO LIST >"%CAPTURE_QUERY%" 2>&1
set "CAPTURE_QUERY_EXIT=%ERRORLEVEL%"
if "%CAPTURE_QUERY_EXIT%"=="0" goto capture_existing
findstr /I /C:"cannot find" /C:"not found" "%CAPTURE_QUERY%" >nul
if errorlevel 1 (
  echo Scheduler query failed; refusing to create or change %CAPTURE_TASK%.
  type "%CAPTURE_QUERY%"
  del /q "%CAPTURE_QUERY%" >nul 2>&1
  exit /b 2
)
if not exist "%PAPER_EVENT_CAPTURE_SCRIPT%" (
  echo Wrapper missing: %PAPER_EVENT_CAPTURE_SCRIPT%
  echo Paper event capture preflight failed. No scheduled task was created.
  exit /b 2
)
del /q "%CAPTURE_QUERY%" >nul 2>&1
call "%BALDR_SCHTASKS_EXE%" /Create /TN "%CAPTURE_TASK%" /SC DAILY /ST %CAPTURE_TIME% /TR "%CAPTURE_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%
set "CAPTURE_CREATED=1"
goto sidecar_query

:capture_existing
del /q "%CAPTURE_QUERY%" >nul 2>&1
echo Existing task found; updating only trigger and action: %CAPTURE_TASK%.
call "%BALDR_SCHTASKS_EXE%" /Change /TN "%CAPTURE_TASK%" /ST %CAPTURE_TIME% /TR "%CAPTURE_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%

:sidecar_query
set "SIDECAR_QUERY=%TEMP%\baldr_pit_sidecar_query_%RANDOM%.txt"
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%SIDECAR_TASK%" /FO LIST >"%SIDECAR_QUERY%" 2>&1
set "SIDECAR_QUERY_EXIT=%ERRORLEVEL%"
if "%SIDECAR_QUERY_EXIT%"=="0" goto sidecar_existing
findstr /I /C:"cannot find" /C:"not found" "%SIDECAR_QUERY%" >nul
if errorlevel 1 (
  echo Scheduler query failed; refusing to create or change %SIDECAR_TASK%.
  type "%SIDECAR_QUERY%"
  del /q "%SIDECAR_QUERY%" >nul 2>&1
  exit /b 2
)
del /q "%SIDECAR_QUERY%" >nul 2>&1
call "%BALDR_SCHTASKS_EXE%" /Create /TN "%SIDECAR_TASK%" /SC DAILY /ST %SIDECAR_TIME% /TR "%SIDECAR_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%
set "SIDECAR_CREATED=1"
goto apply_new_settings

:sidecar_existing
del /q "%SIDECAR_QUERY%" >nul 2>&1
echo Existing task found; updating only trigger and action: %SIDECAR_TASK%.
call "%BALDR_SCHTASKS_EXE%" /Change /TN "%SIDECAR_TASK%" /ST %SIDECAR_TIME% /TR "%SIDECAR_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%

:apply_new_settings
rem 僅新建 task 套用一小時／IgnoreNew；既有 task 完全不以 Set-ScheduledTask
rem 整包替換，避免覆蓋 archi 的登入、電池、wake 或其他安全設定。
if not "%CAPTURE_CREATED%"=="1" if not "%SIDECAR_CREATED%"=="1" goto query_tasks
call "%BALDR_POWERSHELL_EXE%" -NoProfile -Command "$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1); if ('%CAPTURE_CREATED%' -eq '1') { Set-ScheduledTask -TaskName '%CAPTURE_TASK%' -Settings $settings }; if ('%SIDECAR_CREATED%' -eq '1') { Set-ScheduledTask -TaskName '%SIDECAR_TASK%' -Settings $settings }"
if errorlevel 1 (
  echo Registration incomplete: scheduler execution policy could not be applied to a new PIT task.
  exit /b 2
)

:query_tasks
echo.
echo Registered PIT handoff tasks:
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%CAPTURE_TASK%" /V /FO LIST
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%SIDECAR_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_pit_sector_handoff_tasks.cmd dryrun^|register
exit /b 2
