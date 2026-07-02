@echo off
setlocal EnableExtensions

set "MODE=%~1"
if "%MODE%"=="" set "MODE=dryrun"
if /I not "%MODE%"=="dryrun" if /I not "%MODE%"=="unregister" goto usage

set TASKS=baldr-data-freshness-check-daily baldr-evidence-pipeline-dry-run-daily baldr-evidence-working-copy-smoke-manual

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

if /I "%MODE%"=="dryrun" echo Dryrun only. No scheduled task was removed.
exit /b 0

:usage
echo Usage: scripts\scheduled\unregister_baldr_scheduled_tasks.cmd dryrun^|unregister
exit /b 2
