# Post-V1 V1.4 Evidence Review History QA（2026-07-03）

## 變更範圍

V1.4 將 V1.3 weekly evidence operations package 補上可封存與可查閱的歷史層：

- `EvidenceOperationsHistoryRepository` 以 append-only / hash-idempotent 方式保存 weekly review payload snapshot。
- `scripts/build_evidence_operations_weekly_review.py` 新增 `--save-history` 與 `--list-history`。
- Research Lab `Evidence Review` 新增「覆盤歷史」唯讀子頁。

## 安全邊界

- `production_scheduler_allowed` 維持 `false`。
- `--save-history` 必須指定 explicit `--db-path`；疑似正式 DB 仍需額外 `--allow-production-like-db`。
- 覆盤歷史只保存人工週報快照，不建立 scheduler、不寫 action item、不改 Strategy Lifecycle state、不改 portfolio、不產生買賣建議。

## 已執行驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_operations_history_repository.py tests/test_evidence_operations_cli.py -q -o addopts=
```

結果：`5 passed`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_operations_history_dashboard_service.py tests/test_ui_qt_evidence_review_dashboards.py -q -o addopts=
```

結果：`8 passed`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_operations_history_repository.py tests/test_evidence_operations_history_dashboard_service.py tests/test_evidence_operations_cli.py tests/test_ui_qt_evidence_review_dashboards.py -q -o addopts=
```

結果：`13 passed`

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module/evidence_operations_history_dtos.py app_module/evidence_operations_history_repository.py scripts/build_evidence_operations_weekly_review.py
.\.venv\Scripts\python.exe -m py_compile app_module/evidence_operations_history_dashboard_dtos.py app_module/evidence_operations_history_dashboard_service.py ui_qt/models/evidence_operations_history_table_model.py ui_qt/views/evidence_operations_history_view.py ui_qt/views/evidence_review_view.py ui_qt/views/backtest/result_panel.py
```

結果：通過。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
```

結果：`38 passed`

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

結果：通過；摘要 `通過: 24`、`失敗: 0`、`跳過: 4`。此命令產生的 `output/qa/update_tab/VALIDATION_REPORT.md` 屬工具輸出，不納入本次提交。

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

結果：`Success: no issues found in 269 source files`

## 尚未宣稱

- 未宣稱任何 signal、profile、strategy 或 alert 具投資有效性。
- 未啟用 production scheduler。
- 未完成多週真實覆盤樣本累積；V1.4 只提供保存與查閱機制。
