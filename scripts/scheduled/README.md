# baldr Scheduled Operational Wrappers

These wrappers are intentionally conservative. They use CMD files and Windows built-in `schtasks.exe` because the previous PowerShell `.ps1` registration path was blocked by local execution policy. Do not use `Set-ExecutionPolicy` or bypass local policy. Only the dedicated Decision/Evidence capture task enters confirmed append-only capture；其餘正式 wrapper 依各自的唯讀、sidecar 或 Paper ledger 邊界執行。所有 Gate 都由機器重驗，不建立等待人工批准的排程 task。

## Tasks

| Task | State | Trigger | Behavior |
|---|---:|---|---|
| `baldr-data-update-quick-daily` | enabled after register | daily local time 04:20 | Runs the non-UI quick data update path for the recent weekday window. Writes market data CSV / SQLite updates plus status and logs under `OUTPUT_ROOT/scheduled/data_update_quick/`. If TPEX has failed dates, the task continues later steps and writes `passed_with_warnings`. |
| `baldr-official-market-events-daily` | enabled after register | daily local time 04:50 | 以官方來源建立 append-only market-event vintages；無公告／生效／修訂時間的事件 fail closed，不反推歷史可得時間。 |
| `baldr-data-freshness-check-daily` | enabled after register | daily local time 05:00 | Read-only SQLite / `DATA_ROOT` freshness check. Also verifies raw TWSE / TPEX daily price files for the latest SQLite daily date. Writes only status and logs under `OUTPUT_ROOT/scheduled/data_freshness/`. |
| `baldr-recommendation-snapshot-daily` | enabled after register | daily local time 05:10 | Runs the research-only recommendation snapshot path after freshness. Saves one recommendation result under `OUTPUT_ROOT/recommendation/runs/` and writes status/logs under `OUTPUT_ROOT/scheduled/recommendation_snapshot/`. It does not write the production evidence DB, does not confirm evidence, does not change portfolio state, and does not automate trading. |
| `baldr-evidence-pipeline-dry-run-daily` | enabled after register | daily local time 05:15 | Runs `scripts/run_evidence_pipeline.py` with `--dry-run` and forwards the resolved `DATA_ROOT` / `OUTPUT_ROOT` explicitly. Writes only report, status, and logs under `OUTPUT_ROOT/scheduled/evidence_pipeline_dry_run/`. Scheduled status inherits freshness and pipeline overall status: missing / stale / blocking data is `degraded`, while complete observed-or-estimated MoneyDJ provenance is `ready_with_advisories`. |
| `baldr-ml-promotion-evidence-daily` | enabled after register | daily local time 05:17 | 固定 discovery 並重驗 formal OOC v5、雙 replay、Shadow outcome、逐 horizon calibration／drift 與 hash custody。證據不完整時只寫 blocked status，不更新 compatible pointer；完整時也只發布 unsigned evidence。 |
| `baldr-ml-promotion-authority-daily` | enabled after register | daily local time 05:18 | 由獨立 DPAPI user-scope authority 重驗 compatible evidence、Gate registry 與決策有效窗。只有所有機器門檻通過才簽章；否則成功 fail closed，維持 alpha 0。 |
| `baldr-ml-allocation-copilot-daily` | enabled after register | daily local time 05:20 | 執行配置型 ML promotion 評估並寫入 append-only sidecar、promotion artifact 與 `latest_status.json`。缺少、無效或未授權證據時仍成功完成每日流程，但固定輸出 `formal_oos_allowed=false`、`selected_alpha_bp=0` 與四條未通過 lane；不改寫來源資料庫或投組狀態。 |
| `baldr-decision-evidence-capture-daily` | enabled after register | daily local time 05:25 | 依台北時間選擇下一個尚未到達的 08:30 日曆決策日，依序確認保存 durable Decision Desk snapshot 與 Evidence Event。既有 hash／unique key 使重跑轉為 duplicate；任一步失敗即回傳失敗並保留下一次重跑能力。它不推定交易日／成熟日、不改 Rule／Advice／Portfolio 狀態，也不連接券商執行。 |
| `baldr-paper-portfolio-daily` | enabled after register | daily local time 05:28 | 以正式市場 SQLite `mode=ro/query_only` 讀取嚴格早於決策日的最近行情，更新 append-only Paper Portfolio 估值帳本。只做 T-1 mark-to-market，不自動調倉、不修改 Advice，也不具券商執行能力。 |
| `baldr-v2-2-weekly-collection` | `weekly-register` 後啟用 | 每週日 18:00 | 執行 `run_v2_2_weekly_collection.cmd`，以 SQLite read-only 讀取來源並將 evidence append 至 sidecar。對外狀態為 `pending_human_review`；需要人工判讀，但不代表 Gate 通過、不寫 weekly history，且 `write_intent=false`。 |

## Register

Preview:

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun
```

Create or replace the daily tasks:

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd register
```

The register script creates:

```text
baldr-data-update-quick-daily
  DAILY 04:20
  cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_update_quick.cmd"

baldr-official-market-events-daily
  DAILY 04:50
  cmd.exe /c "<repo>\scripts\scheduled\run_official_market_event_backfill.cmd"

baldr-data-freshness-check-daily
  DAILY 05:00
  cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_freshness_check.cmd"

baldr-recommendation-snapshot-daily
  DAILY 05:10
  cmd.exe /c "<repo>\scripts\scheduled\run_recommendation_snapshot.cmd"

baldr-evidence-pipeline-dry-run-daily
  DAILY 05:15
  cmd.exe /c "<repo>\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"

baldr-ml-promotion-evidence-daily
  DAILY 05:17
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_promotion_evidence.cmd"

baldr-ml-promotion-authority-daily
  DAILY 05:18
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_promotion_authority.cmd"

baldr-ml-allocation-copilot-daily
  DAILY 05:20
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_allocation_copilot.cmd"

baldr-decision-evidence-capture-daily
  DAILY 05:25
  cmd.exe /c "<repo>\scripts\scheduled\run_decision_evidence_capture.cmd"

baldr-paper-portfolio-daily
  DAILY 05:28
  cmd.exe /c "<repo>\scripts\scheduled\run_paper_portfolio_daily.cmd"
```

舊 `baldr-evidence-working-copy-smoke-manual` 不再屬於排程清單；獨立 smoke script 只保留作工程診斷。unregister wrapper 仍會清除可能殘留的舊 task。

只建立或取代週日 sidecar collection task：

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd weekly-register
```

`weekly-register` 只建立 `baldr-v2-2-weekly-collection`，其排程為 `WEEKLY SUN 18:00` 並執行 `run_v2_2_weekly_collection.cmd`。它不建立、取代、啟用或以其他方式變更任何每日 task。

## Query

```cmd
scripts\scheduled\query_baldr_scheduled_tasks.cmd
schtasks /Query /TN baldr-official-market-events-daily /V /FO LIST
schtasks /Query /TN baldr-data-freshness-check-daily /V /FO LIST
schtasks /Query /TN baldr-recommendation-snapshot-daily /V /FO LIST
schtasks /Query /TN baldr-evidence-pipeline-dry-run-daily /V /FO LIST
schtasks /Query /TN baldr-ml-promotion-evidence-daily /V /FO LIST
schtasks /Query /TN baldr-ml-promotion-authority-daily /V /FO LIST
schtasks /Query /TN baldr-ml-allocation-copilot-daily /V /FO LIST
schtasks /Query /TN baldr-decision-evidence-capture-daily /V /FO LIST
schtasks /Query /TN baldr-paper-portfolio-daily /V /FO LIST
schtasks /Query /TN baldr-v2-2-weekly-collection /V /FO LIST
```

Missing tasks are reported as friendly `Task not found` messages by the query wrapper.

## Unregister

Preview:

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd dryrun
```

Remove the scheduled tasks:

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd unregister
```

也可以在 Windows Task Scheduler 手動停用或刪除每日 task。若只要停止週日 sidecar collection，請在其中停用 `baldr-v2-2-weekly-collection`，或執行：

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd weekly-unregister
```

Rollback 時禁止自動 drop sidecar SQLite table；保留 `pending_human_review` 與 `collection_failed` record 供稽核與人工處理。

## Logs And Reports

Data freshness:

```text
<OUTPUT_ROOT>/scheduled/data_update_quick/latest_status.json
<OUTPUT_ROOT>/scheduled/data_update_quick/YYYYMMDD_data_update_quick.log
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log
```

`data_update_quick/latest_status.json` uses `passed_with_warnings` when TPEX failed dates remain, for example `TPEX 每日股價缺少日期：20260706`. `data_freshness/latest_status.json` uses `degraded` when SQLite is current but either `daily_price/YYYYMMDD.csv` or `daily_price_tpex/YYYYMMDD.csv` is missing for that latest daily date.

Recommendation snapshot:

```text
<OUTPUT_ROOT>/scheduled/recommendation_snapshot/latest_status.json
<OUTPUT_ROOT>/scheduled/recommendation_snapshot/YYYYMMDD_recommendation_snapshot.log
<OUTPUT_ROOT>/recommendation/runs/scheduled_rec_YYYYMMDD_HHMMSS.json
<OUTPUT_ROOT>/recommendation/runs/recommendation_runs.db
```

The recommendation snapshot status includes `result_id`, `recommendations_count`, `screening_matrix_rows`, `why_not_payload_rows`, `liquidity_gate_payload_rows`, `writes_recommendation_result`, `writes_evidence_db`, `auto_trading`, and `lifecycle_action`.

Evidence dry-run:

```text
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/latest_status.json
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/YYYYMMDD_evidence_pipeline_dry_run.log
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/reports/YYYYMMDD_evidence_pipeline_dry_run.md
```

ML allocation Production Co-pilot：

```text
<OUTPUT_ROOT>/scheduled/ml_promotion_evidence/latest_status.json
<OUTPUT_ROOT>/release_v4/ml_allocation_promotion_evidence/latest_pointer.json
<OUTPUT_ROOT>/release_v4/ml_promotion_authority/latest_status.json
<OUTPUT_ROOT>/release_v4/ml_promotion_authority/latest_authorization_pointer.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/latest_status.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/raw_pit_publications/runs/<publication_id>/
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/orchestration/YYYYMMDD/<run_hash>/*_post_freeze_shadow_input.json.gz
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/orchestration/YYYYMMDD/<run_hash>/*_allocation_proposal.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/artifacts/YYYYMMDD_<hash>_promotion.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/sidecar/YYYYMMDD_<hash>_shadow.json
```

排程入口是 `scripts/run_daily_ml_allocation_orchestration.py`。它先用官方交易日曆求 strict T-1，再從正式 SQLite 以 `mode=ro/query_only` 發布固定 11 檔、730 日 causal lookback 的 immutable `all_field_enriched` raw snapshot；只在 post-freeze input 與 ML allocation inference 都成功後才呼叫 promotion evaluator。`<run_hash>` 綁定決策時間、raw publication、凍結 training manifest、模型 artifact 與 policy；相同輸入冪等重跑，不同 custody 版本不覆蓋舊輸出。凍結 release 預設為 `DATA_ROOT/output/release_v4/ml_allocation_bounded_v4_operational`，可用 `BALDR_ML_RELEASE_ROOT` 覆寫。

任何 release、官方日曆、strict T-1、raw publication、post-freeze input 或 inference 缺件都會留下 `passed_rule_only`、`alpha=0`、`formal_oos_allowed=false`、`broker_order_allowed=false`，且不呼叫 promotion evaluator，因此不會新增假的 shadow sidecar。`latest_status.json` 明列 `post_freeze_input_status`、`inference_status`、`promotion_status`，以及 raw manifest、input、兩份 audit、proposal、replay 與 promotion 的 domain/file hashes。完成 inference 後產生的 sidecar 只代表一筆 observation；每日編排器固定輸出 `shadow_day_credit_allowed=false`，是否能列入 20 個真實交易日由後續 evidence collector 依完整性另行判定，不在此處自行加總。

Promotion evidence 與 authorization 不接受人工作業環境變數注入。05:17 builder 只能從固定、hash-bound custody pointer 發布 unsigned evidence；05:18 Authority 只能以 DPAPI 保護的本機 user-scope key 簽署同一決策窗；05:20 Co-pilot 只讀固定 `latest_authorization_pointer.json`，且再次要求授權的 model／dataset 與實際 inference release 完全相同。任何錯配都回退 Rule-only。

四條 alpha lane 固定為 `0 / 2000 / 3500 / 5000 bp`。Evidence 不存在、格式無效、門檻未通過或 authorization hash 不相符時，runner 一律 fail closed 為 `alpha=0`。同一決策日與同一輸入會得到相同 hash 與相同檔名；若同日證據版本不同，舊 sidecar 與 artifact 仍會保留。

Decision Desk / Evidence confirmed capture：

```text
<OUTPUT_ROOT>/scheduled/decision_evidence_capture/latest_status.json
```

`latest_status.json` 記錄台北 `decision_at`、`snapshot.saved`／`snapshot.duplicate`、`evidence.events_inserted`／`evidence.duplicates`／`evidence.failures`，以及整體 `passed`／`failed`。預設時間選擇規則只比較台北當下與 08:30；它明確輸出 `trading_calendar_validated=false`、`maturity_date_inferred=false`，不把週末、休市或未成熟資料偽裝成正式交易日證據。snapshot 成功、event capture 失敗時，下次執行會重用 snapshot hash 並再次嘗試 event unique-key capture。

Paper Portfolio 每日估值：

```text
<OUTPUT_ROOT>/paper_portfolio/paper_portfolio.sqlite
<OUTPUT_ROOT>/scheduled/paper_portfolio_daily/latest_status.json
```

runner 會以既有 baseline 初始化一次，之後只 append 新 snapshot。市場 DB 永遠唯讀，SQL 與 domain runner 都拒絕 `price_date >= decision_date` 或 `available_date >= decision_date`；同一決策日重跑只回報 duplicate。此排程不把 current weight 猜成 0、不產生交易、不套用配置提案。

Working-copy smoke diagnostic script（不構成人工 Gate，也不註冊為 task）：

```cmd
scripts\scheduled\run_evidence_working_copy_smoke.cmd <source-db-path> <working-copy-db-path> [YYYY-MM-DD] [repeat]
```

If the DB paths are missing, the wrapper prints usage and exits. Repeat defaults to 2.

每週 sidecar collection：

```text
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/evidence_scheduler.db
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/logs/v2_2_weekly_collection_YYYYMMDD_HHMMSS.log
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/v2_2_weekly_collection_YYYYMMDD.json
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/v2_2_weekly_collection_YYYYMMDD.md
```

sidecar record 刻意與 source DB 分離。Schema v3 只允許 `pending_human_review` 與 `collection_failed`；首次開啟舊 sidecar 時，repository 會在單一 SQLite transaction 內保留所有 `collection_id`、payload、hash、error 與建立時間，並把舊版 `observed_automatic`（尚未取得人工核准）原子映射回 `pending_human_review`。Migration 可重跑且不開啟或修改 source DB。收集成功只代表待人工審核，收集失敗則保存 `collection_failed` 與 diagnostics。

## Evidence Boundary

The daily automation runs only:

- non-UI quick market data updates for the recent weekday window;
- read-only data freshness checks;
- research-only recommendation snapshot generation and recommendation result save;
- evidence pipeline dry-run reports.
- unsigned, fail-closed ML promotion evidence construction.
- independent DPAPI-protected machine authorization.
- fail-closed ML allocation promotion evaluation and append-only sidecar records.
- dedicated confirmed Decision Desk snapshot and Evidence Event append-only capture.
- strict T-1 append-only Paper Portfolio valuation.

週日 sidecar task 只執行 collection CLI；不呼叫 `--save-history` 或 `--confirm-action-items`，也不寫 source DB。成功週期由 Pre-V2/V4 readiness 自動計數與重驗；不足證據只限制 formal evidence credit，不阻擋 Rule／Advice／Paper operational production。

Only the dedicated Decision/Evidence capture task writes the durable snapshot and production evidence event tables through the existing idempotent repositories. The Paper Portfolio task writes only its isolated append-only paper ledger. The data freshness, recommendation, evidence dry-run, ML co-pilot and weekly collection tasks do not write the production evidence DB. No scheduled task runs the UI, reads UI state, changes the live portfolio, changes `ScoringEngine`, changes recommendation weights, promotes / demotes / retires strategies, connects to a broker, or automates trading.

ML allocation co-pilot task 只消費前兩個獨立 task 產生、且與本次 inference release 相同的 evidence／authorization custody。Evidence builder 不簽章，Authority 不訓練模型，Co-pilot 不自行製造 OOS、PIT、calibration、drift 或 shadow days 證據；非零 alpha 必須通過三層重驗。

The recommendation snapshot is intentionally saved before the evidence dry-run so the dry-run can observe the latest recommendation payloads, including screening matrix / why-not / liquidity gate payloads when available.

Generated evidence reports 是機器 Gate 的可稽核輸入；它們本身不證明 alpha，也不得直接轉成交易指令。

During dry-run, the runner may build a transient Daily Decision Desk snapshot for the same run. Reports mark this as `source_coverage_basis=dry_run_transient_decision_desk_snapshot`; this reconciles diagnostics only and does not persist the snapshot.

The evidence dry-run `latest_status.json` also includes selected pipeline summary fields from the same run, including `pipeline_overall_status`, warning counts, advisory counts, source-quality coverage rows, diagnostics, and source-coverage readiness. `pipeline_warnings_count` is only actual warning occurrences. `pipeline_natural_maturity_warning_counts` separates `insufficient_future_data` from `pipeline_actionable_warning_counts`; `natural_maturity_only=true` means the remaining degradation is expected to resolve only as forward observations mature and is not a manual repair blocker. `manual_action_required=true` is reserved for a failed or stale freshness input, missing pipeline summary, pipeline error / blocking gap, or non-natural warning. The wrapper always records `dry_run=true`, `confirm=false`, `writes_evidence_db=false`, and `production_scheduler_allowed=false`. `pipeline_advisories_count` separately records complete but estimated MoneyDJ provenance; it does not mean source data is missing. Fixed-threshold recommendation snapshots may leave `score_percentile_bp` empty because no comparable ranked universe is persisted; that is not a warning. These fields are copied from the dry-run stdout only; the wrapper does not rerun the pipeline. Decision Desk SQLite section providers use `mode=ro` / `query_only` for scheduled reads.

## Codex Morning Summary

The Codex app automation `baldr scheduled evidence morning report` runs separately at about local time 05:30. It only reads Windows Task Scheduler status, `latest_status.json`, the latest data update status, the latest recommendation snapshot status, the latest evidence dry-run report, and relevant log warning / error sections, then writes a Traditional Chinese summary to the user.

It must not rerun data update, rerun data freshness, rerun the evidence pipeline, enter confirm write mode, create or modify Windows Task Scheduler tasks, write the production evidence DB, change portfolio / scoring / recommendation weights, apply lifecycle actions, push, or produce trading advice.
