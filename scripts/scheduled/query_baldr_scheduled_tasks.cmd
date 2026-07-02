@echo off
setlocal EnableExtensions

set TASKS=baldr-data-freshness-check-daily baldr-evidence-pipeline-dry-run-daily baldr-evidence-working-copy-smoke-manual

for %%T in (%TASKS%) do (
  echo.
  echo ===== %%T =====
  schtasks.exe /Query /TN "%%T" /V /FO LIST 2>nul
  if errorlevel 1 (
    echo Task not found: %%T
  )
)

exit /b 0
