# Post-V1 Evidence Scheduled Dry-run QA（2026-07-12）

## Scope

本 QA 覆蓋 safe scheduled wrappers：

- `scripts/scheduled/run_daily_data_freshness_check.ps1`
- `scripts/scheduled/run_evidence_pipeline_dry_run.ps1`
- `scripts/scheduled/run_evidence_working_copy_smoke.ps1`
- `scripts/scheduled/register_baldr_scheduled_tasks.ps1`
- `scripts/scheduled/unregister_baldr_scheduled_tasks.ps1`
- `scripts/scheduled/README.md`

本輪只允許 read-only data freshness check、evidence pipeline dry-run，以及 manual / disabled working-copy smoke。

## Safety Boundary

- 不啟用正式 evidence 寫入排程。
- 不建立自動寫 production evidence DB 的 task。
- 不更新 production data。
- 不跑 UI。
- 不讀 UI state。
- 不改 portfolio、ScoringEngine、推薦權重或 lifecycle state。
- 不宣稱 alpha 或任一事件類型有效。

## Scheduled Tasks

| Task | Default | Trigger | Writes |
|---|---|---|---|
| `baldr-data-freshness-check-daily` | Enabled | Daily 07:30 | 只寫 status/log，不寫 DB |
| `baldr-evidence-pipeline-dry-run-daily` | Enabled | Daily 07:45 | 只寫 report/status/log，不寫 evidence DB |
| `baldr-evidence-working-copy-smoke-manual` | Disabled | Manual only | 只可寫 working-copy DB |

## Wrapper Behavior

### Data Freshness

`run_daily_data_freshness_check.ps1` 使用 SQLite read-only URI 檢查 `daily_prices` 與 `technical_indicators` 最新日期，並檢查 `DATA_ROOT` / DB path 是否存在。輸出：

- `<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json`
- `<OUTPUT_ROOT>/scheduled/data_freshness/logs/`

### Evidence Dry-run

`run_evidence_pipeline_dry_run.ps1` 讀取 data freshness `latest_status.json`。若 freshness 不是 `passed`，pipeline status 會標成 `degraded` 或 `failed`。它呼叫 `scripts/run_evidence_pipeline.py --dry-run`，不使用 write mode。輸出：

- `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/latest_status.json`
- `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/reports/`
- `<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/logs/`

### Working-copy Smoke

`run_evidence_working_copy_smoke.ps1` 必須人工指定 `-SourceDbPath` 與 `-WorkingCopyDbPath`，且 working-copy path 不得等於 source DB 或 default `DATA_ROOT/sqlite/twstock.db`。Repeat 最低為 2。

## Test Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_scripts_exist.py tests/test_scheduled_readme_no_production_confirm.py tests/test_scheduled_scripts_no_trading_language.py -q -o addopts=
.\scripts\scheduled\register_baldr_scheduled_tasks.ps1 -Mode DryRun
.\scripts\scheduled\unregister_baldr_scheduled_tasks.ps1 -Mode DryRun
```

## Test Results

- `tests/test_scheduled_scripts_exist.py tests/test_scheduled_readme_no_production_confirm.py tests/test_scheduled_scripts_no_trading_language.py`：passed。
- `tests/test_forward_performance_dashboard_service.py tests/test_ui_qt_evidence_review_dashboards.py tests/test_evidence_review_dashboards_no_trading_language.py`：passed。
- `tests/test_ui_qt_update_view_workbench.py`：passed。
- `scripts/qa_validate_update_tab.py`：passed，24 passed / 0 failed / 4 skipped。
- `scripts/check_financial_float_boundaries.py`：passed。
- `git diff --check`：passed；只顯示 CRLF warning。
- PowerShell AST parse：passed，5 個 `.ps1` 無 parse error。
- `register_baldr_scheduled_tasks.ps1 -Mode DryRun`：blocked by local execution policy before script body ran。
- `unregister_baldr_scheduled_tasks.ps1 -Mode DryRun`：blocked by local execution policy before script body ran。

## Registration Result

`registration_blocked`：本機 PowerShell execution policy 禁止執行 repo `.ps1`，DryRun 階段即被擋住，錯誤類型為 `PSSecurityException / UnauthorizedAccess`。依安全要求，本輪未使用 bypass、未修改 execution policy、未執行 Register，因此 Windows Task Scheduler 尚未建立 task。

手動註冊可依 `scripts/scheduled/README.md` 或 `docs/07_guides/EVIDENCE_SCHEDULED_MORNING_CHECK.md` 的 Task Scheduler UI 欄位設定。

## Morning Check

每日檢查步驟見：

- `docs/07_guides/EVIDENCE_SCHEDULED_MORNING_CHECK.md`

## Known Limitations

- Data freshness task 只檢查，不更新資料。
- Evidence daily task 只 dry-run，不累積 production evidence events / outcomes。
- Working-copy smoke 預設 disabled / manual-only。
- 多日觀察仍需人工填入 dry-run record。

## Not Done

- 未建立 production write-mode evidence schedule。
- 未建立 production data update schedule。
- 未建立 dashboard 自動判讀或通知。
- 未建立任何自動策略生命週期動作。

## Next Increment

1. 連續 3-5 個交易日觀察 scheduled dry-run report。
2. 完成人工 Evidence Review UI smoke closeout。
3. 若 stable，再設計 production scheduler approval review，不直接啟用。
