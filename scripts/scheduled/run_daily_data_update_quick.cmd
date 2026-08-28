@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if "%DATA_ROOT%"=="" set "DATA_ROOT=D:\Min\Python\Project\FA_Data"
if "%OUTPUT_ROOT%"=="" set "OUTPUT_ROOT=%DATA_ROOT%\output"
if "%WINDOW_WEEKDAYS%"=="" set "WINDOW_WEEKDAYS=10"
set "TECHNICAL_POOL_ARGS="
if /I "%BALDR_ENABLE_TECHNICAL_PROCESS_POOL%"=="1" set "TECHNICAL_POOL_ARGS=--enable-technical-process-pool"
if not "%BALDR_TECHNICAL_PROCESS_POOL_WORKERS%"=="" set "TECHNICAL_POOL_ARGS=%TECHNICAL_POOL_ARGS% --technical-process-pool-workers %BALDR_TECHNICAL_PROCESS_POOL_WORKERS%"
if not "%BALDR_TECHNICAL_PROCESS_POOL_MAX_IN_FLIGHT%"=="" set "TECHNICAL_POOL_ARGS=%TECHNICAL_POOL_ARGS% --technical-process-pool-max-in-flight %BALDR_TECHNICAL_PROCESS_POOL_MAX_IN_FLIGHT%"
if not "%BALDR_TECHNICAL_PROCESS_POOL_MAX_RETRIES%"=="" set "TECHNICAL_POOL_ARGS=%TECHNICAL_POOL_ARGS% --technical-process-pool-max-retries %BALDR_TECHNICAL_PROCESS_POOL_MAX_RETRIES%"

"%PYTHON%" "scripts\scheduled\run_daily_data_update_quick.py" --data-root "%DATA_ROOT%" --output-root "%OUTPUT_ROOT%" --window-weekdays "%WINDOW_WEEKDAYS%" %TECHNICAL_POOL_ARGS%
exit /b %ERRORLEVEL%
