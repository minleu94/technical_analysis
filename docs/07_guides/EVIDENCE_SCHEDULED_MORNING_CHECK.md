# Evidence Scheduled Morning Check

> 適用範圍：`scripts/scheduled/` 的 CMD safe scheduled wrappers。這份指南只用於檢查 read-only freshness 與 evidence dry-run 結果，不代表任何事件類型有效。

## 1. 檢查 Windows Task Scheduler

本機 PowerShell `.ps1` 註冊路徑曾被 execution policy 擋住；目前採用 CMD wrapper + Windows 內建 `schtasks.exe`。不要使用 `Set-ExecutionPolicy`，不要修改 PowerShell execution policy。

查詢：

```cmd
scripts\scheduled\query_baldr_scheduled_tasks.cmd
schtasks /Query /TN baldr-data-freshness-check-daily /V /FO LIST
schtasks /Query /TN baldr-evidence-pipeline-dry-run-daily /V /FO LIST
```

預期：

- `baldr-data-freshness-check-daily`：每天本機時間 05:00，執行 `scripts\scheduled\run_daily_data_freshness_check.cmd`。
- `baldr-evidence-pipeline-dry-run-daily`：每天本機時間 05:15，執行 `scripts\scheduled\run_evidence_pipeline_dry_run.cmd`。
- `baldr-evidence-working-copy-smoke-manual`：manual-only；目前不建立每日自動 task。
- Codex app `baldr scheduled evidence morning report`：每天約 05:30，只讀查詢上述 task、status、report 與必要 log，產生繁體中文摘要；它不是 Windows Task Scheduler task，也不重新執行 pipeline。

若前兩個 task 沒有出現，先執行：

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun
```

確認輸出合理後，才執行：

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd register
```

若 `schtasks.exe` 因權限不足或系統政策失敗，不要繞過安全限制；在 QA 記錄 `registration_blocked`，再用 Task Scheduler UI 手動建立同等兩個 daily task。

## 2. 明天早上檢查 data freshness

預設位置：

```text
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log
```

檢查項目：

- `status` 應為 `passed`，或是可解讀的 `degraded`。
- `read_only` 必須為 `true`。
- `daily_prices_latest_date` 與 `technical_indicators_latest_date` 應符合人工預期。
- 若出現 `sqlite_db_missing`、`data_root_missing` 或 `sqlite_read_failed`，當天 evidence dry-run 只能視為 degraded / failed。

## 3. 明天早上檢查 evidence dry-run

預設位置：

```text
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/latest_status.json
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/YYYYMMDD_evidence_pipeline_dry_run.log
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/reports/YYYYMMDD_evidence_pipeline_dry_run.md
```

檢查項目：

- `dry_run` 必須為 `true`。
- `writes_evidence_db` 必須為 `false`。
- `freshness_status` 若不是 `passed`，`status` 應標為 `degraded` 或 `failed`。
- 閱讀 report，確認 blocking gaps、warnings 與 source diagnostics。

## 4. 人工判讀

每天早上只做三件事：

1. 確認 freshness status。
2. 確認 evidence dry-run report。
3. 將結果填入 `docs/06_qa/POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`。

這些檢查不能證明 alpha、不能證明任何事件類型有效，也不能取代人工 Evidence Review UI smoke。

## 5. 停用或刪除

Dry-run 預覽：

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd dryrun
```

移除 task：

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd unregister
```

也可以在 Windows Task Scheduler UI 中手動 Disable 或 Delete 前兩個 daily task。

## 6. 安全邊界

目前會自動跑：

- read-only data freshness check。
- evidence pipeline dry-run。

目前不會自動跑：

- production evidence confirm。
- production evidence DB 寫入。
- production data update。
- UI 啟動或 UI state 讀取。
- portfolio / scoring / recommendation weights 修改。
- promote / demote / retire。
- 自動交易。
- Codex app 摘要 automation 不會建立或修改 Windows Task Scheduler task，也不會重新執行 freshness / evidence pipeline。

Production confirm 仍未啟用，未來仍需人工核准、working-copy smoke、多日 dry-run record 與 rollback / recovery 檢查。
