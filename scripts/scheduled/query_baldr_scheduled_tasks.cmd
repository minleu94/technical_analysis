@echo off
setlocal EnableExtensions

set TASKS=baldr-data-update-quick-daily baldr-data-freshness-check-daily baldr-recommendation-snapshot-daily baldr-evidence-pipeline-dry-run-daily baldr-evidence-working-copy-smoke-manual
set WEEKLY_TASK=baldr-v2-2-weekly-collection

for %%T in (%TASKS%) do (
  echo.
  echo ===== %%T =====
  schtasks.exe /Query /TN "%%T" /V /FO LIST 2>nul
  if errorlevel 1 (
    echo Task not found: %%T
  )
)

echo.
echo ===== %WEEKLY_TASK% =====
schtasks.exe /Query /TN "%WEEKLY_TASK%" /V /FO LIST 2>nul
if errorlevel 1 (
  echo Task not found: %WEEKLY_TASK%
)

exit /b 0
