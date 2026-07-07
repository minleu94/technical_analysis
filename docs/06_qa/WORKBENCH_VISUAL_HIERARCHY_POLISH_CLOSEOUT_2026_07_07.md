# Workbench Visual Hierarchy Polish Closeout（2026-07-07）

> 範圍：左側主導覽自製線條 SVG icon、icon-only 收合、Workbench 四格指揮台摘要列、總覽 gutter 對齊與文件同步。

## Completed

- 左側主導覽不再以 `WB` / `MX` 等兩字母縮寫作為主要 icon。
- `LeftNavigationWidget` 內建自製 SVG icon registry，使用一致 20x20 線條風格與 Midnight Analyst token。
- Expanded 狀態顯示 icon + label + badge；collapsed 狀態只顯示 icon，完整 label 仍保留在 tooltip。
- Workbench `總覽` 頂部改為四個指揮台摘要 block：`今日待判讀`、`人工待處理`、`等待真實時間`、`Warnings`。
- `等待真實時間` block 明確顯示 weekly history 與 multi-day dry-run 比例。
- Workbench overview page 新增一致 top / left gutter，避免標題與摘要貼齊 tab pane 邊界。

## Safety Boundary

- 未修改 scheduler、scheduled wrapper、scheduled output schema 或 morning report。
- 未寫 DB、未執行 replay、未改 lifecycle、未產生買賣建議。
- 未修改 scoring、portfolio、backtest、recommendation 或 evidence capture 的 domain 計算。
- SVG icon 與 summary blocks 都是 presentation 層；不改 `WorkbenchDashboardDTO` source semantics。

## Still Waiting For Formal Data

- Phase 0 weekly history 仍是 `0/3`，必須靠真實 weekly review history 累積。
- Phase 0 multi-day dry-run 仍是 `1/3`，必須靠真實交易日的 scheduled / manual dry-run record、working-copy confirm smoke、Evidence Review / Workbench review 與 manual note 累積。
- 真實 manual review note rhythm 與 action item rhythm 仍需正式操作紀錄，不能由 UI 預留位置、replay、fixture 或文件手動修改補齊。
- Phase 5 scheduler approval 仍 blocked；必須等 Phase 0 gate、backup / rollback / recovery、source gap acceptance 與 explicit manual approval。

## QA Evidence

| Check | Command | Result |
|---|---|---|
| Left navigation focused tests | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_left_navigation.py -q -o addopts=` | Passed: 3 passed |
| MainWindow integration | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=` | Passed: 10 passed |
| Workbench focused tests | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_workbench_view.py -q -o addopts=` | Passed: 9 passed |
| Required combined UI / UpdateView gate | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_runtime_view.py tests\test_ui_qt_left_navigation.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_ui_qt_workbench_view.py tests\test_ui_qt_weak_market_views.py tests\test_ui_qt_update_view_workbench.py -q -o addopts=` | Passed: 68 passed in 2.65s |
| Update Tab QA | `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py` | Passed: 24 passed, 0 failed, 4 skipped |
| py_compile changed Python files | `.\.venv\Scripts\python.exe -m py_compile ui_qt\widgets\left_navigation.py ui_qt\main.py ui_qt\views\workbench_view.py tests\test_ui_qt_left_navigation.py tests\test_ui_qt_workbench_view.py` | Passed |
| mypy required UI gate | `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | Passed: Success, no issues found in 296 source files |

## Notes

本 closeout 只表示 Workbench visual hierarchy polish 完成，不表示 V2.2 真實 Evidence Operating Loop 完成，也不改變 official Phase 0 / Phase 5 gate。
