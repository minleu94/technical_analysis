@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || exit /b 1

if defined BALDR_PYTHON set "PYTHON=%BALDR_PYTHON%"
if not defined PYTHON if exist "%REPO_ROOT%\.venv\Scripts\python.exe" set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"
if not defined FORMAL_DAILY_PUBLICATION_ROOT set "FORMAL_DAILY_PUBLICATION_ROOT=%REPO_ROOT%\output\formal_daily_publications"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 此 task 必須在台北 08:30 前執行；Python 入口會以真實 clock
rem 與每個 response completion timestamp fail closed，不能用日期覆寫。
rem 同一盤前 task 先準備當日 Rule machine source bundle；若 Rule source
rem 缺日曆／parent／market 視窗，仍讓 PIT capture 自己留下可觀測結果，
rem 但最後 exit code 保留失敗，避免排程把部分成功誤報成整體成功。
call "%REPO_ROOT%\scripts\scheduled\run_formal_rule_source_preopen.cmd"
set "RULE_SOURCE_EXIT=%ERRORLEVEL%"
if not "%RULE_SOURCE_EXIT%"=="0" echo Rule source preopen blocked; inspect rule_source\scheduler\rule_source_latest_status.json
"%PYTHON%" "%REPO_ROOT%\scripts\scheduled\run_pit_sector_membership_preopen_capture.py"
set "PIT_EXIT=%ERRORLEVEL%"
if not "%PIT_EXIT%"=="0" exit /b %PIT_EXIT%
exit /b %RULE_SOURCE_EXIT%
