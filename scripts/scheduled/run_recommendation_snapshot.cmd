@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"
if "%MAX_STOCKS%"=="" set "MAX_STOCKS=200"
if "%TOP_N%"=="" set "TOP_N=50"
if "%FORWARD_CANDIDATE_OUTPUT_ROOT%"=="" set "FORWARD_CANDIDATE_OUTPUT_ROOT=%REPO_ROOT%\output\forward_position_thesis"
if "%FORWARD_THESIS_POLICY_PATH%"=="" set "FORWARD_THESIS_POLICY_PATH=%REPO_ROOT%\output\forward_position_thesis\policies\paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1.json"

set "FORWARD_ARGS=--forward-candidate-output-root "%FORWARD_CANDIDATE_OUTPUT_ROOT%""
if not "%FORWARD_THESIS_POLICY_PATH%"=="" set "FORWARD_ARGS=%FORWARD_ARGS% --forward-thesis-policy-path "%FORWARD_THESIS_POLICY_PATH%""
if not "%FORWARD_CALENDAR_CACHE_PATH%"=="" set "FORWARD_ARGS=%FORWARD_ARGS% --forward-calendar-cache-path "%FORWARD_CALENDAR_CACHE_PATH%""

"%PYTHON%" "scripts\scheduled\run_scheduled_recommendation_snapshot.py" --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --max-stocks "%MAX_STOCKS%" --top-n "%TOP_N%" %FORWARD_ARGS%
exit /b %ERRORLEVEL%
