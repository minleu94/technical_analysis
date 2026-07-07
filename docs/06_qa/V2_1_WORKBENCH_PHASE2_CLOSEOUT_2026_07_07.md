# V2.1 Workbench Phase 2 Read-only Operating Loop Closeout

> 日期：2026-07-07
> 狀態：Phase 2 UI / read-only operating loop closeout completed
> 範圍：Qt Workbench read-only shell、background evidence feed、read-only Action Items、Operating Loop、closeout / gate review。
> 非範圍：Phase 0 真實時間 gate 補完、V2.2 真實 evidence operating loop、production scheduler approval、交易建議或 lifecycle action。

## 1. 交付範圍

- `WorkbenchDashboardDTO` 已承接 `background_evidence_feed`、`action_items` 與 `operating_loop_steps`，仍是 UI / composer 可使用的唯一 payload 邊界。
- `WorkbenchActionItem` 已加入 `severity`、`queue_group`、`source_label`、`sort_rank`、`source_trace`、`degraded_reason`、`drilldown_target` 與 `write_intent=false`，形成可掃描的人工處理佇列。
- `WorkbenchOperatingLoopStep` 新增 `daily_start`、`manual_queue`、`weekly_review_history`、`multi_day_dry_run`、`manual_review_note` 與 `scheduler_gate`，把「今天要看什麼、哪些要人工處理、哪些只是等待時間累積」串成只讀操作節奏。
- Qt Workbench view / table models 已顯示 Evidence Feed、Action Items 與 Operating Loop，並保留空狀態 / degraded 狀態文案。
- Drill-down target contract 與舊頁導向一致：`daily_decision` 對應 Daily Decision，`evidence_review` / `evidence_mode` 對應 Evidence Review，`portfolio_review` 對應 Portfolio。

## 2. Read-only Boundary

- UI / model / composer 只使用 `WorkbenchSourceService` 與 `WorkbenchDashboardDTO` payload。
- 不直接讀 SQLite、不讀 replay DB、不執行 replay、不建立 repository、不寫 DB。
- 不重算 scoring、recommendation、portfolio、backtest、lifecycle 或 source gap。
- 不建立 scheduler、不啟用 production scheduler、不修改 lifecycle 狀態。
- 不標記 Action Item / Operating Loop step 完成，也不 append manual review note。
- 不產生買賣建議、不下單、不把 degraded / waiting 狀態改寫成 gate passed。

## 3. Gate Review

| Gate | 判定 | 說明 |
|---|---|---|
| Phase 2 UI / read-only operating loop | Closeout | Workbench 已能以 DTO payload 顯示背景證據、人工佇列與每日操作節奏。 |
| Phase 0 weekly history | Not complete | 仍為 `0/3`，必須用真實時間累積，不能用 fixture、manual edit 或 replay 補齊。 |
| Phase 0 multi-day dry-run | Not complete | 仍為 `1/3`，必須用真實時間累積。 |
| V2.2 real evidence operating loop | Not complete | 需要真實 weekly review、multi-day dry-run、manual review note 與 action item rhythm 可重複後才能升級判定。 |
| Production scheduler approval | Not complete | `production_scheduler_allowed=false`，Phase 5 gate 仍需明確人工核准。 |

## 4. Verification

| 驗證 | 命令 | 結果 |
|---|---|---|
| Workbench focused tests | `.\.venv\Scripts\python.exe -m pytest tests\test_workbench_read_only_composer.py tests\test_workbench_source_service.py tests\test_ui_qt_workbench_view.py tests\test_ui_qt_decision_desk_main_integration.py tests\test_v2_workbench_prototype_cli.py tests\test_workbench_replay_summary.py tests\test_workbench_read_only_boundary.py -q -o addopts=` | Passed: 48 passed in 14.19s |
| Update View Workbench tests | `.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=` | Passed: 38 passed in 2.05s |
| Update Tab QA | `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py` | Passed: 24 passed, 0 failed, 4 skipped; report saved under ignored `output/qa/update_tab/VALIDATION_REPORT.md` |
| py_compile | `.\.venv\Scripts\python.exe -m py_compile app_module\workbench_dtos.py app_module\workbench_read_only_composer.py ui_qt\models\workbench_table_models.py ui_qt\views\workbench_view.py tests\test_workbench_read_only_composer.py tests\test_ui_qt_workbench_view.py tests\test_workbench_read_only_boundary.py` | Passed |
| mypy | `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | Passed: Success, no issues found in 292 source files |
| Diff hygiene | `git diff --check` | Passed; only Windows line-ending warnings were emitted |

## 5. Not Done

- Phase 0 weekly history `0/3` 不能由本次 UI closeout 補完。
- Multi-day dry-run `1/3` 不能由 replay、fixture 或 manual table edit 補完。
- V2.2 Evidence Operating Loop 尚未宣告完成；它需要真實時間紀錄讓 weekly / multi-day / manual review / action item rhythm 可重複。
- Production scheduler approval 仍在 Phase 5 gate 外，不因 Workbench UI 成熟而自動開啟。
