@echo off
setlocal EnableExtensions

rem Dedicated forward caller for the separately registered 18th task.  The
rem aggregate registered 17-task set intentionally leaves this task unchanged;
rem child completion, frozen source, and forward-credit gates remain enforced.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

if defined BALDR_PYTHON set "PYTHON=%BALDR_PYTHON%"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"
if not defined ML_FORWARD_CONFIG_ROOT set "ML_FORWARD_CONFIG_ROOT=%REPO_ROOT%\output\v4_ml_forward_scheduler"
if not defined ML_FORWARD_DATABASE set "ML_FORWARD_DATABASE=D:\Min\Python\Project\FA_Data\sqlite\twstock.db"
if not defined ML_FORWARD_OUTPUT_ROOT set "ML_FORWARD_OUTPUT_ROOT=%REPO_ROOT%\output\v4_ml_daily_derived_shadow_real_v2"
if not defined ML_FORWARD_PAPER_STATE_DB set "ML_FORWARD_PAPER_STATE_DB=%REPO_ROOT%\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite"
if not defined BALDR_ML_RELEASE_ROOT set "BALDR_ML_RELEASE_ROOT=%REPO_ROOT%\output\v4_ml_derived_h5_20260907_real_v2"
if not defined BALDR_ML_RELEASE_MANIFEST_FILE_HASH set "BALDR_ML_RELEASE_MANIFEST_FILE_HASH=sha256:c306c1ea53ccef112204a8412a605b575e4d107b4503b2b5be5d6d5ee50910ea"
if not defined ML_FORWARD_ARCHIVE_ROOT set "ML_FORWARD_ARCHIVE_ROOT=%REPO_ROOT%\output\formal_daily_publications\pit_candidate_archive"
if not defined ML_FORWARD_CALENDAR_CACHE_ROOT set "ML_FORWARD_CALENDAR_CACHE_ROOT=%REPO_ROOT%\output\paper_execution_eod_replay\calendar_cache"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if /I "%~1"=="preflight" goto preflight

rem Keep the annual official calendar cache valid through the next real
rem Asia/Taipei 08:30 cutoff.  This is create-only and bounded; a failed or
rem expired refresh stops the forward producer before it can create a child.
"%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_official_calendar_cache_refresh_daily.py" --cache-root "%ML_FORWARD_CALENDAR_CACHE_ROOT%"
if errorlevel 1 goto calendar_refresh_failed

rem The Python wrapper waits for the real Asia/Taipei 08:30 clock, rejects
rem starts after 08:35, and requires exactly one operational/archive source.
if defined ML_FORWARD_CONFIG_PATH (
  "%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_ml_allocation_forward_daily.py" --config "%ML_FORWARD_CONFIG_PATH%" --config-root "%ML_FORWARD_CONFIG_ROOT%"
) else (
  rem Omitted --config invokes the daily create-only producer for
  rem configs\YYYY-MM-DD.json; no latest-file discovery is used.
  "%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_ml_allocation_forward_daily.py" --config-root "%ML_FORWARD_CONFIG_ROOT%"
)
exit /b %ERRORLEVEL%

:calendar_refresh_failed
echo Official calendar cache refresh blocked; forward producer was not started.
exit /b 2

:preflight
rem Read-only registration preflight: no network, wait, producer, child, or task mutation.
"%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_official_calendar_cache_refresh_daily.py" --preflight --cache-root "%ML_FORWARD_CALENDAR_CACHE_ROOT%"
if errorlevel 1 exit /b 2
"%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_ml_allocation_forward_daily.py" --preflight
set "PREFLIGHT_EXIT=%ERRORLEVEL%"
exit /b %PREFLIGHT_EXIT%
