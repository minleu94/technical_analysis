@echo off
setlocal EnableExtensions

rem 這個 wrapper 交給單一 Python retry runner 先執行固定 D 槽來源的唯讀
rem dependency gate，再呼叫 repository-scoped Paper adapter；不把任何
rem PAPER_EXECUTION_* 或 DATA_ROOT 環境變數傳成 writer 路徑。
set "SCRIPT_DIR=%~dp0"
rem Avoid a FOR modifier here: Task Scheduler and nested cmd.exe both parse
rem that syntax, and a second parser can corrupt %%~fI before the adapter runs.
cd /d "%SCRIPT_DIR%..\.." || exit /b 1
set "REPO_ROOT=%CD%"

set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
set "RETRY_RUNNER=%REPO_ROOT%\scripts\scheduled\paper_execution_retry_runner.py"
if not exist "%RETRY_RUNNER%" (
  echo Paper execution retry runner missing: %RETRY_RUNNER%
  exit /b 2
)

rem 06:00 Pacific 位於 quick update 04:20 與 freshness 05:00 之後；若上游
rem 尚未完成或官方行情尚未發布，最多在同一 task 執行窗內重試三次，避免隔日
rem 以新 recommendation 取代當日待成交決策。每次 adapter retry 仍由既有
rem queue resolver 以 execution_date 與 source hash 冪等選擇同一凍結來源。
rem retry runner 使用 Python sleep，適用於 Task Scheduler 的非互動 stdin，並
rem 只將明確暫時性 source blocker 交給下一次嘗試；terminal blocker 立即退出。
"%PYTHON%" "%RETRY_RUNNER%" --max-attempts 3 --retry-delay-seconds 900
exit /b %ERRORLEVEL%
