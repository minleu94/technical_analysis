@echo off
setlocal EnableExtensions

set TASKS=baldr-paper-execution-eod-replay-daily baldr-data-update-quick-daily baldr-official-market-events-daily baldr-data-freshness-check-daily baldr-ml-raw-pit-refresh-daily baldr-ml-direct-chain-maintainer baldr-recommendation-snapshot-daily baldr-evidence-pipeline-dry-run-daily baldr-ml-promotion-evidence-daily baldr-ml-promotion-authority-daily baldr-ml-allocation-copilot-daily baldr-decision-evidence-capture-daily baldr-paper-portfolio-daily baldr-formal-input-producer-daily
set WEEKLY_TASK=baldr-v2-2-weekly-collection
if not defined BALDR_SCHTASKS_EXE set "BALDR_SCHTASKS_EXE=schtasks.exe"
set /a MISSING_TASK_COUNT=0 >nul
set /a EXPECTED_TASK_COUNT=15 >nul

for %%T in (%TASKS%) do (
  echo.
  echo ===== %%T =====
  call "%BALDR_SCHTASKS_EXE%" /Query /TN "%%T" /V /FO LIST 2>nul
  if errorlevel 1 (
    echo Task not found: %%T
    set /a MISSING_TASK_COUNT+=1 >nul
  )
)

echo.
echo ===== %WEEKLY_TASK% =====
call "%BALDR_SCHTASKS_EXE%" /Query /TN "%WEEKLY_TASK%" /V /FO LIST 2>nul
if errorlevel 1 (
  echo Task not found: %WEEKLY_TASK%
  set /a MISSING_TASK_COUNT+=1 >nul
)

if not "%MISSING_TASK_COUNT%"=="0" (
  echo.
  echo Scheduler query summary: %MISSING_TASK_COUNT% of %EXPECTED_TASK_COUNT% task^(s^) missing or unavailable.
  exit /b 1
)

echo.
echo Scheduler query summary: all %EXPECTED_TASK_COUNT% task^(s^) are available.
exit /b 0
