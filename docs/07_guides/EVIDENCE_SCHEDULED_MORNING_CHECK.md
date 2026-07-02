# Evidence Scheduled Morning Check

> 適用範圍：`scripts/scheduled/` 的 safe scheduled wrappers。這份指南只用於檢查 read-only freshness 與 evidence dry-run 結果，不代表任何事件類型有效。

## 1. 檢查 Windows Task Scheduler

開啟 Task Scheduler，確認：

- `baldr-data-freshness-check-daily`：Enabled，預設每日 07:30。
- `baldr-evidence-pipeline-dry-run-daily`：Enabled，預設每日 07:45。
- `baldr-evidence-working-copy-smoke-manual`：Disabled；只可人工執行，且必須指定 working-copy DB。

若前兩個 task 沒有出現，先執行：

```powershell
.\scripts\scheduled\register_baldr_scheduled_tasks.ps1 -Mode DryRun
```

確認輸出合理後，才考慮：

```powershell
.\scripts\scheduled\register_baldr_scheduled_tasks.ps1 -Mode Register
```

若被權限或 execution policy 擋住，不要調整安全政策，改用 Task Scheduler UI 手動建立並在 QA 記錄 `registration_blocked`。

手動建立欄位：

| Task | Trigger | Program | Arguments |
|---|---|---|---|
| `baldr-data-freshness-check-daily` | Daily 07:30 | `powershell.exe` | `-NoProfile -File "<repo>\scripts\scheduled\run_daily_data_freshness_check.ps1"` |
| `baldr-evidence-pipeline-dry-run-daily` | Daily 07:45 | `powershell.exe` | `-NoProfile -File "<repo>\scripts\scheduled\run_evidence_pipeline_dry_run.ps1"` |
| `baldr-evidence-working-copy-smoke-manual` | Disabled / manual | `powershell.exe` | `-NoProfile -File "<repo>\scripts\scheduled\run_evidence_working_copy_smoke.ps1" -SourceDbPath "<source-db>" -WorkingCopyDbPath "<working-copy-db>"` |

`Start in` 設為 repo 根目錄。Working-copy smoke 應維持 Disabled，只有人工指定 working-copy DB 時才執行。

## 2. 檢查 data freshness status

預設位置：

```text
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/logs/
```

檢查項目：

- `status` 應為 `passed` 或可解讀的 `degraded`。
- `read_only` 必須為 `true`。
- `daily_prices_latest_date` 與 `technical_indicators_latest_date` 應符合人工預期。
- 若出現 `sqlite_db_missing`、`data_root_missing` 或 `sqlite_read_failed`，當天 evidence dry-run 只能視為 degraded / failed。

## 3. 檢查 evidence dry-run status

預設位置：

```text
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/latest_status.json
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/reports/
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/logs/
```

檢查項目：

- `dry_run` 必須為 `true`。
- `writes_evidence_db` 必須為 `false`。
- `freshness_status` 若不是 `passed`，`status` 應標為 `degraded` 或 `failed`。
- 閱讀 `report_path` 指向的 Markdown report，確認 blocking gaps、warnings 與 source diagnostics。

## 4. 人工判讀

每天早上只做三件事：

1. 確認 freshness status。
2. 確認 evidence dry-run report。
3. 將結果填入 `docs/06_qa/POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`。

這些檢查不能證明 alpha、不能證明任何事件類型有效，也不能取代人工 Evidence Review UI smoke。

## 5. 停用

Dry-run 預覽：

```powershell
.\scripts\scheduled\unregister_baldr_scheduled_tasks.ps1 -Mode DryRun
```

移除 task：

```powershell
.\scripts\scheduled\unregister_baldr_scheduled_tasks.ps1 -Mode Unregister
```

也可以在 Task Scheduler UI 中手動 Disable 前兩個 daily task。Working-copy smoke 預設應維持 Disabled。
