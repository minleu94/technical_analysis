@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

powershell.exe -NoProfile -File "%REPO_ROOT%\scripts\scheduled\run_v2_2_weekly_collection.ps1" -RepoRoot "%REPO_ROOT%"
exit /b %ERRORLEVEL%
