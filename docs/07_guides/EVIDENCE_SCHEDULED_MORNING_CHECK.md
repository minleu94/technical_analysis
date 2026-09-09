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
- 若 `paper_health_refresh_status` 不是 `passed` 或 `reused`，wrapper 會把 health baseline 指向不存在的 sentinel、將 scheduled `status` 設為 `failed` 並以非零退出；即使 child exit code 為 0，也不得沿用舊的 `position_health/latest.json`。
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

## 7. Paper Portfolio 與 Evidence 的來源接線

05:15 scheduled dry-run 會把明確指定的隔離 Paper operation root 與
position-health baseline 傳給 `scripts/run_evidence_pipeline.py`。Portfolio alert
來源是 `output/paper_execution_eod_replay/paper_portfolio/paper_portfolio.sqlite`
中請求日前最近的 Paper snapshot，health 來源是
`<OUTPUT_ROOT>/position_health/latest.json`（由同一個 05:15 daily refresh 建立；兩者
都以唯讀模式讀取）。
這條路徑不再把手動 `PortfolioService` JSONL 當作 Paper evidence；每個事件的
metadata 會保留 snapshot id、選取資料列 canonical hash、SQLite data version、
health baseline hash／日期與研究 only 邊界。

健康基線只在日期不晚於 Paper snapshot 且 boundary flags 完整時使用。缺檔、
未來日期、資料列 coverage 不完整、檔案在讀取中被替換或 boundary violation
會回傳 `unknown`／`MISSING`，不建立假的 attribution 或 prompt。健康基線過期或
缺少 thesis 等人工作業欄位會保留實際 `WATCH` attribution 與 degraded warning；
它可以讓事件可追溯，但不會將 scheduler readiness 改成 ready。

`portfolio_alert_snapshot_available`／`risk_prompt_snapshot_available` 表示已有
可讀 section；`*_capture_ready` 仍要求 observed／estimated 且無 warnings。因此
有內容但 degraded 時，source coverage 會標示 quality not ready，不會錯誤寫成
`*_snapshot_section_missing`，也不會把 `ready=false` 隱藏。`risk_prompt` 是由
同一份 Paper alert 與其他當日 Decision Desk sections 推導，仍沿用原有
`risk_prompt_source_quality:*` warnings。

05:15 scheduled wrapper 會先執行 daily position-health refresh，成功時使用
`<OUTPUT_ROOT>/position_health/latest.json`；日期檔為
`baseline_YYYYMMDD.json`，同日相同 bytes reuse，變更則建立 hash suffix 並保留舊檔。
若 refresh blocked，wrapper 會傳入不存在的 sentinel path，讓 evidence 明確顯示
`unknown`／`MISSING`，不能沿用 stale baseline。只有 previous
`source_snapshot_id` 與 current Paper snapshot 相同，或同一 Paper preopen status
receipt 綁定兩端 snapshot、ledger 路徑與 transaction row digest 且期間沒有該代號
事件時，才保留連續持有的人工作業欄位；無法證明 entry lineage 時，舊 thesis／state
與 reasons 只留在當前列的歷史欄位，當前持倉回到 WATCH／unknown。
