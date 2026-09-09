@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I "%MODE%"=="weekly-unregister" goto weekly_unregister
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="unregister" goto usage

set TASKS=baldr-paper-execution-eod-replay-daily baldr-data-update-quick-daily baldr-official-market-events-daily baldr-data-freshness-check-daily baldr-ml-raw-pit-refresh-daily baldr-ml-direct-chain-maintainer baldr-recommendation-snapshot-daily baldr-evidence-pipeline-dry-run-daily baldr-ml-promotion-evidence-daily baldr-ml-promotion-authority-daily baldr-ml-allocation-copilot-daily baldr-decision-evidence-capture-daily baldr-paper-portfolio-daily baldr-pit-sector-membership-preopen-capture-daily baldr-formal-pit-sidecar-postcutoff-daily baldr-formal-input-producer-daily baldr-evidence-working-copy-smoke-manual

rem The forward task is deliberately outside this destructive aggregate list.
rem It is managed by its exact XML plan and can only be removed by the
rem dedicated rollback command after a task-name query.
set "FORWARD_TASK=baldr-ml-allocation-forward-daily"

echo Mode: %MODE%
for %%T in (%TASKS%) do (
  schtasks.exe /Query /TN "%%T" >nul 2>nul
  if errorlevel 1 (
    echo Task not found: %%T
  ) else (
    echo Task found: %%T
    if /I "%MODE%"=="unregister" (
      schtasks.exe /Delete /TN "%%T" /F
      if errorlevel 1 exit /b 1
    )
  )
)

echo.
echo ===== %FORWARD_TASK% =====
schtasks.exe /Query /TN "%FORWARD_TASK%" >nul 2>nul
if errorlevel 1 (
  echo Task not found: %FORWARD_TASK%
) else (
  echo Task found: %FORWARD_TASK%
  echo Forward task is excluded from aggregate removal; use its dedicated XML rollback.
)

if /I "%MODE%"=="dryrun" echo Dryrun only. No scheduled task was removed.
exit /b 0

:weekly_unregister
set "WEEKLY_TASK=baldr-v2-2-weekly-collection"

schtasks.exe /Query /TN "%WEEKLY_TASK%" >nul 2>nul
if errorlevel 1 (
  echo Task not found: %WEEKLY_TASK%
  exit /b 0
)

echo Task found: %WEEKLY_TASK%
schtasks.exe /Delete /TN "%WEEKLY_TASK%" /F
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\scheduled\unregister_baldr_scheduled_tasks.cmd dryrun^|unregister^|weekly-unregister
exit /b 2
