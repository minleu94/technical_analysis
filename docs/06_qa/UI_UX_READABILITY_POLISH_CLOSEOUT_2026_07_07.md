# UI / UX Readability Polish Closeout（2026-07-07）

> 範圍：Runtime Observatory 空間壓縮、左側主導覽 icon / 收合、Workbench 總覽可讀性、弱勢市場跌幅色彩語意、Manual / UI 設計文件同步。

## Completed

- Runtime Observatory 頂部 scope note 改為緊湊說明列，下方任務狀態、治理健康與事件流上移，避免大片空白。
- 左側主導覽加入短代碼 icon，並支援 expanded / icon-only collapsed 模式；collapsed 狀態保留 tooltip 與目前選取狀態。
- Workbench 總覽新增 DTO 摘要列，先顯示今日待判讀、人工待處理、Evidence waiting、Warnings 與 Phase 0 gate。
- Workbench 的 `Evidence`、`持倉追蹤`、`操作節奏` 子頁明確標示為摘要與下鑽入口 / 預留深挖區，避免被誤認為完整功能已完成。
- 市場探索弱勢個股與弱勢產業的 `跌幅%` 以正數顯示跌幅大小，並用紅色代表下跌語意；正負號不再和欄名重複表意。

## Safety Boundary

- 未修改 scheduler、scheduled wrapper、scheduled output schema 或 morning report。
- 未寫 DB、未執行 replay、未改 lifecycle、未產生買賣建議。
- 未修改 scoring、portfolio、backtest、recommendation 或 evidence capture 的 domain 計算。
- `PandasTableModel.red_positive_columns` 只提供 UI 色彩語意 override；一般正數欄位仍維持正綠負紅。

## Still Waiting For Formal Data

- Phase 0 weekly history 仍是 `0/3`，必須靠真實 weekly review history 累積。
- Phase 0 multi-day dry-run 仍是 `1/3`，必須靠真實交易日的 scheduled / manual dry-run record、working-copy confirm smoke、Evidence Review / Workbench review 與 manual note 累積。
- 真實 manual review note rhythm 與 action item rhythm 仍需正式操作紀錄，不能由 UI 預留位置、replay、fixture 或文件手動修改補齊。
- Phase 5 scheduler approval 仍 blocked；必須等 Phase 0 gate、backup / rollback / recovery、source gap acceptance 與 explicit manual approval。

## QA Evidence

| Check | Command | Result |
|---|---|---|
| Runtime focused UI test | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_runtime_view.py -q -o addopts=` | Passed: 5 passed |
| Left navigation / MainWindow integration | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_left_navigation.py tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=` | Passed: 13 passed |
| Workbench readability | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_workbench_view.py -q -o addopts=` | Passed: 9 passed |
| Weak market color semantics | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_weak_market_views.py -q -o addopts=` | Passed: 3 passed |
| Combined focused UI / UpdateView gate | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_runtime_view.py tests\test_ui_qt_left_navigation.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_ui_qt_workbench_view.py tests\test_ui_qt_weak_market_views.py tests\test_ui_qt_update_view_workbench.py -q -o addopts=` | Passed: 68 passed in 2.57s |
| Update Tab QA | `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py` | Passed: 24 passed, 0 failed, 4 skipped |
| py_compile changed Python files | `.\.venv\Scripts\python.exe -m py_compile ui_qt\views\runtime_view.py ui_qt\widgets\left_navigation.py ui_qt\main.py ui_qt\views\workbench_view.py ui_qt\models\pandas_table_model.py ui_qt\views\weak_stocks_view.py ui_qt\views\weak_industries_view.py tests\test_ui_qt_runtime_view.py tests\test_ui_qt_left_navigation.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_ui_qt_workbench_view.py tests\test_ui_qt_weak_market_views.py` | Passed |
| mypy required UI gate | `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | Passed: Success, no issues found in 296 source files |

## Notes

本 closeout 只表示 UI/UX readability slice 完成，不表示 V2.2 真實 Evidence Operating Loop 完成，也不改變 official Phase 0 / Phase 5 gate。
