# Post-V1 Evidence Review Dashboards QA（2026-07-11）

## Scope

本輪新增 Research Lab `Evidence Review` read-only UI pack，包含 Decision Quality Review、Signal Decay、Live vs Research Gap 三個 dashboard，並保留既有 Forward Evidence 子頁。

## Files Changed

新增：

- `app_module/decision_quality_dashboard_dtos.py`
- `app_module/decision_quality_dashboard_service.py`
- `app_module/signal_decay_dashboard_dtos.py`
- `app_module/signal_decay_dashboard_service.py`
- `app_module/live_research_gap_dashboard_dtos.py`
- `app_module/live_research_gap_dashboard_service.py`
- `ui_qt/views/evidence_review_view.py`
- `ui_qt/views/decision_quality_view.py`
- `ui_qt/views/signal_decay_view.py`
- `ui_qt/views/live_research_gap_view.py`
- `ui_qt/models/decision_quality_table_model.py`
- `ui_qt/models/signal_decay_table_model.py`
- `ui_qt/models/live_research_gap_table_model.py`
- `ui_qt/widgets/evidence_boundary_banner.py`
- Round 11 focused tests。

修改：

- `app_module/decision_quality_service.py`
- `ui_qt/views/backtest/result_panel.py`
- core docs / roadmap / manual / architecture docs。

## UI Placement

新增 Research Lab 結果區 `Evidence Review` 分頁，子頁為：

1. Forward Evidence
2. Live vs Research Gap
3. Signal Decay
4. Decision Quality

## Dashboard Coverage

Decision Quality Dashboard 顯示 process score、review item 狀態、reason codes、review question、quality 與 warnings。

Signal Decay Dashboard 顯示 scope、短窗 / 長窗樣本、decay score、status、lifecycle candidate、confidence、quality 與 warnings。

Live vs Research Gap Dashboard 顯示 source trace、evidence link、portfolio mode、gap metrics、attribution categories、match confidence、quality 與 warnings。

## Read-only Guarantee

- UI 只呼叫 dashboard service。
- Dashboard service 只呼叫 read/list API。
- 新 UI 不直接 import repository、SQLite、scoring、portfolio mutation 或 scheduler。
- Dashboard service 不呼叫 write / capture / lifecycle action。
- 不建立 Windows Task Scheduler、cron 或 background job。

## Forbidden Language Check

新增 `tests/test_evidence_review_dashboards_no_trading_language.py`，檢查新 dashboard production files 不含 forbidden trading language，不直接讀 DB，不 import mutation modules，也不呼叫 write methods。

## Test Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_quality_dashboard_service.py tests\test_signal_decay_dashboard_service.py tests\test_live_research_gap_dashboard_service.py tests\test_ui_qt_evidence_review_dashboards.py tests\test_evidence_review_dashboards_no_trading_language.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_decision_quality_service.py tests\test_signal_decay_service.py tests\test_live_research_gap_service.py tests\test_forward_performance_dashboard_service.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

UI 修改依 repo 規範另跑：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

PowerShell wildcard py_compile 使用展開檔案清單：

```powershell
$files = @()
$files += Get-ChildItem app_module -Filter *.py | ForEach-Object FullName
$files += Get-ChildItem ui_qt -Filter *.py | ForEach-Object FullName
$files += Get-ChildItem ui_qt\views -Filter *.py | ForEach-Object FullName
$files += Get-ChildItem ui_qt\models -Filter *.py | ForEach-Object FullName
$files += Get-ChildItem ui_qt\widgets -Filter *.py | ForEach-Object FullName
$files += Get-ChildItem scripts -Filter *.py | ForEach-Object FullName
& .\.venv\Scripts\python.exe -m py_compile @files
```

## Test Results

初始 TDD red：Round 11 focused tests 因新 dashboard modules 尚未存在而 collection failed。

實作後最終結果：

- Round 11 focused tests：13 passed。
- Decision Quality / Signal Decay / Live Gap / Forward Performance dashboard service 回歸：16 passed。
- Financial float boundary check：passed。
- PowerShell-expanded py_compile：passed。
- Update workbench UI pytest：38 passed。
- Update tab QA：24 passed / 0 failed / 4 skipped。
- mypy：Success，no issues found in 256 source files。
- `git diff --check`：passed；僅有 Git CRLF normalization warnings，無 whitespace error。

## Known Limitations

- Dashboard 只呈現已保存 evidence / observation / review，沒有資料時不回補、不重算。
- Signal Decay lifecycle candidate 只供人工審核，不會自動套用。
- Live vs Research Gap 在缺真實交易與人工 override 記錄時仍只能視為 research / simulated gap。
- Decision Quality score 只代表流程 evidence，不代表投資能力，也不是責備判斷。
- Forward close-to-close return 不是實盤可執行績效。

## Not Done

- 未建立正式 scheduler。
- 未宣稱 alpha。
- 未建立自動 lifecycle action。
- 未修改 ScoringEngine、推薦權重、portfolio position 或 Research Run Registry。
- 未補完整實帳歸因。

## Next Increment

1. Production scheduler approval implementation only after explicit human approval。
2. Multi-day dry-run evidence pipeline record。
3. Evidence report export / PDF backlog。
4. Optional dashboard polish。
