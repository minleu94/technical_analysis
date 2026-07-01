# Post-V1 Forward Performance Dashboard QA 2026-07-05

## Scope

本 QA 覆蓋 Forward Performance Dashboard read-only UI v1：dashboard DTO/service、Qt table model、Research Lab `Forward Evidence` view、只讀資料邊界、禁用交易語氣檢查與文件同步。

## Files Changed

新增：

- `app_module/forward_performance_dashboard_dtos.py`
- `app_module/forward_performance_dashboard_service.py`
- `ui_qt/models/forward_performance_table_model.py`
- `ui_qt/views/forward_performance_view.py`
- `tests/test_forward_performance_dashboard_service.py`
- `tests/test_ui_qt_forward_performance_view.py`
- `tests/test_forward_performance_dashboard_no_trading_language.py`
- `docs/superpowers/specs/2026-07-05-post-v1-forward-performance-dashboard-design.md`
- `docs/superpowers/plans/2026-07-05-post-v1-forward-performance-dashboard.md`
- `docs/06_qa/POST_V1_FORWARD_PERFORMANCE_DASHBOARD_QA_2026_07_05.md`

修改：

- `ui_qt/views/backtest/result_panel.py`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_vision_specification.md`
- `docs/07_guides/APPLICATION_MANUAL.md`

未觸碰：

- `decision_module/scoring_engine.py`
- 推薦權重
- portfolio position mutation path
- scheduler / background task creation

## UI Placement

Dashboard 掛在 Research Lab / 策略回測結果分頁，新增 `Forward Evidence` tab。沒有新增頂層 workspace。

## Read-only Guarantee

- View 只呼叫 `ForwardPerformanceDashboardService`。
- Service 只呼叫 `ForwardPerformanceReadModel.summarize()`。
- View 不 import SQLite repository、不直接讀 DB。
- Service factory 使用 SQLite read-only mode；缺 DB / schema 時呈現 empty / degraded diagnostic。
- 不寫 evidence event、不寫 outcome、不改 portfolio。

## Forbidden Language Check

新增測試掃描 dashboard surface，確認不含禁用英文交易語氣，也不 import scoring / portfolio mutation / evidence write path。

## Filter Coverage

支援：

- start / end date
- event type / family
- source type
- symbol
- regime
- sector
- profile id
- strategy version id
- window days
- group by
- minimum sample size

## Read Model Coverage

Dashboard service 只使用 `ForwardPerformanceReadModel` 已提供的 group summary：

- sample / pending / missing
- forward return / benchmark excess / industry excess
- rates
- MAE / MFE
- quality counts
- warning counts
- summary status

## Test Commands

已執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_forward_performance_dashboard_service.py tests/test_ui_qt_forward_performance_view.py tests/test_forward_performance_dashboard_no_trading_language.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_forward_performance_read_model.py tests/test_summarize_forward_performance_cli.py tests/test_evidence_pipeline_smoke.py -q -o addopts=
.\.venv\Scripts\python.exe scripts/check_financial_float_boundaries.py
$files = Get-ChildItem app_module,ui_qt,ui_qt\views,ui_qt\models,scripts -Filter *.py | Select-Object -ExpandProperty FullName; .\.venv\Scripts\python.exe -m py_compile @files
.\.venv\Scripts\python.exe -m py_compile app_module\forward_performance_dashboard_dtos.py app_module\forward_performance_dashboard_service.py ui_qt\models\forward_performance_table_model.py ui_qt\views\forward_performance_view.py ui_qt\views\backtest\result_panel.py
git diff --check
```

## Test Results

- Dashboard focused tests：11 passed。
- Forward performance read model / summary CLI / smoke regression：15 passed。
- Financial float boundary scan：passed，exit 0。
- py_compile：passed。PowerShell wildcard 不會以 bash 方式展開，因此使用等價檔案清單展開命令；另補跑 changed Python files 精準編譯，包含 `ui_qt/views/backtest/result_panel.py`。
- `git diff --check`：passed，exit 0；僅有 Windows CRLF conversion warning，無 whitespace error。

## Known Limitations

- Dashboard 只檢查已保存 evidence；沒有事件或 outcome 時只能顯示空狀態。
- close-to-close forward return 不是實盤可執行績效。
- Why Not / Liquidity events 仍只在 persisted payload present 時可累積，舊 Recommendation 不回補。
- Benchmark / industry 缺失會降級顯示，不能補成中性。
- 尚未做 Live vs Research Gap linkage。
- 尚未做 Signal Decay Monitor。

## Scheduler Readiness

`ready_for_design`。

本輪沒有建立 Windows Task Scheduler、cron 或任何 background scheduler。

## Not Done

- 未建立正式 scheduler。
- 未建立 lifecycle action。
- 未宣稱 alpha。
- 未宣稱任何 event type 有效。
- 未修改 ScoringEngine。
- 未修改推薦權重。
- 未修改 portfolio position。

## Next Increment

1. Scheduler dry-run design。
2. Live vs Research Gap event linkage。
3. Signal Decay Monitor。
4. Decision Quality Review。
