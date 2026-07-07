# Workbench Left Navigation IA Closeout（2026-07-07）

> 範圍：Qt 主 UI 左側主導覽、Workbench internal tabs、DecisionDesk 內嵌、empty state、session-only queue feedback、schedule/report regression QA。

## Completed

- 主 UI 已由上方主 tab 改為左側主導覽。
- 預設主工作區為 `決策工作台`。
- 主工作區順序：`決策工作台`、`市場探索`、`推薦分析`、`策略回測`、`觀察清單`、`持倉管理`、`數據更新`、`Runtime`。
- `每日決策` 不再是頂層主工作區，已嵌入 `決策工作台 > 決策來源`。
- `市場觀察` 重新定位為 `市場探索`；原市場子 tab 保留。
- Workbench 內部子頁：`總覽`、`決策來源`、`Evidence`、`持倉追蹤`、`操作節奏`。
- 今日待判讀 queue 為空時顯示 empty state；queue row drill-down 後只在本次 UI session 顯示已查看計數。

## Safety Boundary

- 未修改 scheduled wrappers。
- 未修改 scheduled output schema。
- 未修改 morning report。
- 未修改 Pre-V2 readiness contract。
- 未修改 simulated phase progress contract。
- 未啟用 scheduler。
- 未寫 DB。
- 未執行 replay。
- 未補 lifecycle gate。
- 未產生買賣建議。

## Still Waiting For Formal Data

- Phase 0 weekly history 仍為 `0/3`，必須靠真實 weekly review history 累積。
- Multi-day dry-run 仍為 `1/3`，必須靠真實時間下的 scheduled/manual dry-run record 累積。
- Replay summary 只能協助揭露 source gap、payload gap、benchmark / industry coverage 與 UI 設計問題；不能替代上述 gate。

## QA Evidence

| Check | Command | Result |
|---|---|---|
| Focused UI / Workbench / schedule-report tests | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_left_navigation.py tests\test_ui_qt_workbench_view.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_workbench_read_only_boundary.py tests\test_scheduled_evidence_status_service.py tests\test_scheduled_evidence_pipeline_dry_run_wrapper.py tests\test_ui_qt_update_view_workbench.py -q -o addopts=` | Passed: 65 passed in 2.50s |
| Update Tab QA | `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py` | Passed: 24 passed, 0 failed, 4 skipped |
| py_compile | `.\.venv\Scripts\python.exe -m py_compile ui_qt\widgets\left_navigation.py ui_qt\main.py ui_qt\views\workbench_view.py tests\test_ui_qt_left_navigation.py tests\test_ui_qt_workbench_view.py tests\test_ui_qt_decision_desk_main_integration.py` | Passed |
| mypy | `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | Passed: Success, no issues found in 296 source files |

`scripts\qa_validate_update_tab.py` generated `output/qa/update_tab/VALIDATION_REPORT.md`; this is tool output and remains uncommitted.

