# Evidence Scheduled Morning Check

> 適用範圍：`scripts/scheduled/` 的 CMD safe scheduled wrappers。這份指南只用於檢查 read-only freshness 與 evidence dry-run 結果，不代表任何事件類型有效。

## 1. 檢查 Windows Task Scheduler

本機 PowerShell `.ps1` 註冊路徑曾被 execution policy 擋住；目前採用 CMD wrapper + Windows 內建 `schtasks.exe`。不要使用 `Set-ExecutionPolicy`，不要修改 PowerShell execution policy。

查詢：

```cmd
scripts\scheduled\query_baldr_scheduled_tasks.cmd
schtasks /Query /TN baldr-data-update-quick-daily /V /FO LIST
schtasks /Query /TN baldr-data-freshness-check-daily /V /FO LIST
schtasks /Query /TN baldr-recommendation-snapshot-daily /V /FO LIST
schtasks /Query /TN baldr-evidence-pipeline-dry-run-daily /V /FO LIST
```

預期：

- `baldr-data-update-quick-daily`：每天本機時間 04:20，執行 `scripts\scheduled\run_daily_data_update_quick.cmd`。這會走非 UI 快速更新路徑，補最近工作日窗口的 TWSE / TPEX 每日股價、大盤、產業、券商分點、SQLite 同步與必要的技術指標增量；若 TPEX 缺日，status 會是 `passed_with_warnings` 並列出缺少日期。
- `baldr-data-freshness-check-daily`：每天本機時間 05:00，執行 `scripts\scheduled\run_daily_data_freshness_check.cmd`；若 SQLite 最新但 TWSE / TPEX 最新日原始 CSV 缺失，status 會是 `degraded`。
- `baldr-recommendation-snapshot-daily`：每天本機時間 05:10，保存 research-only recommendation result，供 05:15 dry-run 讀取；它會寫推薦結果，但不寫 production evidence DB、不下單、不套用 lifecycle action。
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
<OUTPUT_ROOT>/scheduled/data_update_quick/latest_status.json
<OUTPUT_ROOT>/scheduled/data_update_quick/YYYYMMDD_data_update_quick.log
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log
```

檢查項目：

- `baldr-data-update-quick-daily` 應先於 freshness 成功或清楚列出 failed step。
- `data_update_quick/latest_status.json` 若為 `passed_with_warnings`，先看 warnings 是否只來自 TPEX 暫時缺資料；若核心步驟失敗，當天 freshness / evidence 只能視為 degraded 或 failed。
- `status` 應為 `passed`、`ready_with_advisories`，或是可解讀的 `degraded`；`ready_with_advisories` 表示流程可用但有已揭露的估算來源品質提示。
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
- `pipeline_overall_status` 若為 `degraded`，scheduled `status` 也必須為 `degraded`；Task Scheduler `LastTaskResult=0` 只代表 wrapper 正常完成，不代表 report 無 warnings。
- `pipeline_warnings_count` 是跨 pipeline steps 的 warning occurrences；需搭配 `pipeline_warning_unique_count` 與 `pipeline_warning_top_counts` 判讀，不可把 `pipeline_diagnostic_codes=[]` 誤解成完全沒有 warnings。
- `pipeline_overall_status=ready_with_advisories` 時，確認 `pipeline_advisories_count`、`pipeline_advisory_top_counts` 與 report 的 `Source Quality Coverage`。MoneyDJ 個股若只在金額榜而未在張數榜，估算股數仍須保留 `estimated`，但完整 observed / estimated 覆蓋不是資料缺失。
- fixed-threshold recommendation snapshot 未保存比較母體時，`score_percentile_bp` 為不適用；不可從已選推薦股反推百分位。
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

- 非 UI 快速資料更新。
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
