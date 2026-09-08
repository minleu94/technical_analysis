@echo off
setlocal EnableExtensions

rem This script registers exactly one research-only Paper Portfolio task. It
rem intentionally does not call the aggregate scheduler registration script.
set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="register" goto usage

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "PAPER_PORTFOLIO_TASK=baldr-paper-portfolio-daily"
set "PAPER_PORTFOLIO_SCRIPT=%REPO_ROOT%\scripts\scheduled\run_paper_portfolio_daily.cmd"
set "PAPER_PORTFOLIO_ACTION=cmd.exe /c ""%PAPER_PORTFOLIO_SCRIPT%"""
set "PAPER_PORTFOLIO_TIME=16:30"
if not defined BALDR_SCHTASKS_EXE set "BALDR_SCHTASKS_EXE=schtasks.exe"

rem Task Scheduler uses host local time. 16:30 Pacific maps to 07:30 Taipei
rem during PDT and 08:30 during PST. The adapter waits on the real Taipei
rem 08:30 cutoff when PDT is in effect; it never treats 09:30 as preopen.
set "LOCAL_TIME_ZONE="
for /f "delims=" %%Z in ('tzutil /g 2^>nul') do set "LOCAL_TIME_ZONE=%%Z"
if /I not "%LOCAL_TIME_ZONE%"=="Pacific Standard Time" (
  echo Registration blocked: Windows timezone must be Pacific Standard Time; detected "%LOCAL_TIME_ZONE%".
  exit /b 2
)

echo Mode: %MODE%
echo Task: %PAPER_PORTFOLIO_TASK%
echo   Schedule: DAILY %PAPER_PORTFOLIO_TIME% Pacific local time
echo   Taipei mapping: 07:30 PDT / 08:30 PST; adapter waits for Taipei 08:30
echo   Execution policy: existing principal/settings preserved; adapter polls cutoff in up to 60-second slices
echo   Scope: research-only repo-isolated Paper state; D source and market are read-only
echo   Action: %PAPER_PORTFOLIO_ACTION%
echo   Wrapper: %PAPER_PORTFOLIO_SCRIPT%

if not exist "%PAPER_PORTFOLIO_SCRIPT%" (
  echo Wrapper missing: %PAPER_PORTFOLIO_SCRIPT%
  echo Wrapper preflight failed. No scheduled task was created.
  exit /b 2
)

if /I "%MODE%"=="dryrun" (
  echo Dryrun only. No scheduled task was created.
  exit /b 0
)

rem 既有 task 只用 schtasks /Change 更新 trigger/action，保留 principal、登入、
rem 電池與其他原設定；只有查不到 task 時才建立新 task。adapter 最多等待一小時
rem 的台北 cutoff，避免用 Set-ScheduledTask 整包替換既有 settings。
set "QUERY_OUTPUT=%TEMP%\baldr_paper_portfolio_query_%RANDOM%.txt"
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%PAPER_PORTFOLIO_TASK%" /FO LIST >"%QUERY_OUTPUT%" 2>&1
set "QUERY_EXIT=%ERRORLEVEL%"
if "%QUERY_EXIT%"=="0" goto existing_task
rem 非零不等於 task 不存在：只有明確的 not-found 訊息才允許 create；
rem 權限、服務或其他 query error 一律 fail closed，不覆寫既有 task。
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
call "%BALDR_SCHTASKS_EXE%" /Change /TN "%PAPER_PORTFOLIO_TASK%" /ST %PAPER_PORTFOLIO_TIME% /TR "%PAPER_PORTFOLIO_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%
goto query_task

:create_task
echo Task not found; creating the single Paper Portfolio task.
call "%BALDR_SCHTASKS_EXE%" /Create /TN "%PAPER_PORTFOLIO_TASK%" /SC DAILY /ST %PAPER_PORTFOLIO_TIME% /TR "%PAPER_PORTFOLIO_ACTION%"
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo Registered task:
:query_task
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%PAPER_PORTFOLIO_TASK%" /V /FO LIST
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\register_paper_portfolio_task.cmd dryrun^|register
exit /b 2
