# baldr Scheduled Operational Wrappers

These wrappers are intentionally conservative. They use CMD files and Windows built-in `schtasks.exe` because the previous PowerShell `.ps1` registration path was blocked by local execution policy. Do not use `Set-ExecutionPolicy` or bypass local policy. Only the dedicated Decision/Evidence capture task enters confirmed append-only capture；其餘正式 wrapper 依各自的唯讀、sidecar 或 Paper ledger 邊界執行。所有 Gate 都由機器重驗，不建立等待人工批准的排程 task。

## Tasks

| Task | State | Trigger | Behavior |
|---|---:|---|---|
| `baldr-data-update-quick-daily` | enabled after register | daily local time 04:20 | Runs the non-UI quick data update path for the recent weekday window. Writes market data CSV / SQLite updates plus status and logs under `OUTPUT_ROOT/scheduled/data_update_quick/`. If TPEX has failed dates, the task continues later steps and writes `passed_with_warnings`. |
| `baldr-official-market-events-daily` | enabled after register | daily local time 04:50 | 以官方來源建立 append-only market-event vintages；無公告／生效／修訂時間的事件 fail closed，不反推歷史可得時間。若 verified latest publication 的歷史起點被縮窄，task 會自動切換到 2014–當年度做 recovery；coverage 完整後才恢復兩年增量，避免 pointer 長期遺失歷史。 |
| `baldr-data-freshness-check-daily` | enabled after register | daily local time 05:00 | Read-only SQLite / `DATA_ROOT` freshness check. Also verifies raw TWSE / TPEX daily price files for the latest SQLite daily date. Writes only status and logs under `OUTPUT_ROOT/scheduled/data_freshness/`. |
| `baldr-ml-raw-pit-refresh-daily` | enabled after register | daily local time 05:05 | 先讀取 data-update quick 的 terminal freshness proof；daily／technical core date 就緒時，以 SQLite `mode=ro/query_only` 自動建立全市場 immutable raw PIT publication。既有同 cutoff 且較新的 publication 會跳過，不寫回來源 SQLite、不改變 formal gate；完成後由 Direct/OOC maintenance watcher 依 pointer/hash 自動接續。 |
| `baldr-recommendation-snapshot-daily` | enabled after register | daily local time 05:10 | Runs the research-only recommendation snapshot path after freshness. Saves one recommendation result under `OUTPUT_ROOT/recommendation/runs/` and writes status/logs under `OUTPUT_ROOT/scheduled/recommendation_snapshot/`. It does not write the production evidence DB, does not confirm evidence, does not change portfolio state, and does not automate trading. |
| `baldr-evidence-pipeline-dry-run-daily` | enabled after register | daily local time 05:15 | Runs `scripts/run_evidence_pipeline.py` with `--dry-run` and forwards the resolved `DATA_ROOT` / `OUTPUT_ROOT` explicitly. Writes only report, status, and logs under `OUTPUT_ROOT/scheduled/evidence_pipeline_dry_run/`. Scheduled status inherits freshness and pipeline overall status: missing / stale / blocking data is `degraded`, while complete observed-or-estimated MoneyDJ provenance is `ready_with_advisories`. |
| `baldr-ml-promotion-evidence-daily` | enabled after register | daily local time 05:17 | 固定 discovery 並重驗 formal OOC v5、雙 replay、Shadow outcome、逐 horizon calibration／drift 與 hash custody。證據不完整時只寫 blocked status，不更新 compatible pointer；若 OOC readiness 不足，blocker 會附上 `formal_ooc_dataset_full_market_not_ready:<readiness_check,...>` 的具體檢查名；若 direct store 落後最新 verified official market-event publication，會輸出 `formal_ooc_corporate_action_custody_stale:<field,...>`；完整時也只發布 unsigned evidence。 |
| `baldr-ml-promotion-authority-daily` | enabled after register | daily local time 05:18 | 由獨立 DPAPI user-scope authority 重驗 compatible evidence、Gate registry 與決策有效窗。只有所有機器門檻通過才簽章；否則成功 fail closed，維持 alpha 0。 |
| `baldr-ml-allocation-copilot-daily` | enabled after register | daily local time 05:20 | 執行配置型 ML promotion 評估並寫入 append-only sidecar、promotion artifact 與 `latest_status.json`。缺少、無效或未授權證據時仍成功完成每日流程，但固定輸出 `formal_oos_allowed=false`、`selected_alpha_bp=0` 與四條未通過 lane；不改寫來源資料庫或投組狀態。 |
| `baldr-decision-evidence-capture-daily` | enabled after register | daily local time 05:25 | 依台北時間選擇最近一個**已到達**的 08:30 日曆決策日，依序確認保存 durable Decision Desk snapshot 與 Evidence Event；不再把隔日 cutoff 當成已發生資料。既有 hash／unique key 使重跑轉為 duplicate；任一步失敗即回傳失敗並保留下一次重跑能力。它不推定交易日／成熟日、不改 Rule／Advice／Portfolio 狀態，也不連接券商執行。 |
| `baldr-paper-portfolio-daily` | enabled after register | daily local time 05:28 | 依台北時間選擇最近一個**已到達**的 08:30 決策日，以正式市場 SQLite `mode=ro/query_only` 讀取嚴格早於決策日的最近行情，更新 append-only Paper Portfolio 估值帳本。明確指定未到達的 `--decision-at` 會寫入 `skipped_future_decision` 並不開啟 state／market DB；只做 T-1 mark-to-market，不自動調倉、不修改 Advice，也不具券商執行能力。 |
| `baldr-ml-direct-chain-maintainer` | enabled after register | daily local time 05:30 | 自動解析並重驗最新全市場 immutable raw PIT pointer、official market-event custody 與目前 Direct identity，然後啟動／維持 `maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs`。使用既有 instance lock 防止重複訓練；無效輸入只寫 `blocked_invalid_bootstrap_input`，不寫來源 SQLite、不建立未受控 sidecar、不放寬 formal／alpha／broker gate。 |
| `baldr-v2-2-weekly-collection` | `weekly-register` 後啟用 | 每週日 18:00 | 執行 `run_v2_2_weekly_collection.cmd`，以 SQLite read-only 讀取來源並將 evidence append 至 sidecar。對外狀態為 `pending_human_review`；需要人工判讀，但不代表 Gate 通過、不寫 weekly history，且 `write_intent=false`。 |

## Direct chain automatic bootstrap

`baldr-ml-direct-chain-maintainer` 的入口是
`scripts/scheduled/run_ml_direct_chain_maintenance.cmd`。wrapper 會從
`OUTPUT_ROOT/release_v4/ml_pit_year_shards/latest_manifest.json` 解析最新
pointer，重驗 publication／dataset canonical hash、`all_universe=true`、raw
dataset safety、`decision_at` 與 official market-event custody，再把已驗證的
immutable manifest 傳給既有 Direct → OOC maintainer。它不建立 raw data、不改寫
來源 SQLite、不建立歷史 sector membership，也不把 `companies.csv` 當成 PIT sidecar。

狀態寫入：

```text
<OUTPUT_ROOT>/scheduled/ml_direct_chain_maintenance/latest_status.json
```

wrapper 在長時間監督期間會定期重驗 training output instance lock，並更新
`heartbeat_at`、`maintenance_lock_state` 與 `maintenance_owner_process_id`；因此
`running` 狀態中的 owner 是 child maintainer 取得 lock 後的實際命令列 custody，
不是只在 bootstrap 時讀到的暫時值。wrapper 結束後也會重新讀取一次 lock 狀態。

`status=running` 代表已通過 bootstrap 並正在監督既有 chain；`completed` 代表
wrapper 子程序正常返回（包括 instance lock 已由現有 owner 持有的安全重複觸發）。
若是後者，status 會明列 `execution_disposition=existing_owner_lock`、
`maintenance_lock_state=verified` 與經命令列驗證的 `maintenance_owner_process_id`；命令列
還必須與同一個 `training_output_dir` 完整相符，避免把其他 lineage 的 maintainer 誤認為現有
owner，或把安全跳過誤讀成 Direct/OOC 已完成。若 live owner 命令列暫時無法讀取，wrapper
會改列 `execution_disposition=owner_lock_unverifiable` 與
`maintenance_lock_state=owner_lock_unverifiable`，保留 lock 並等待下次驗證；
`blocked_invalid_bootstrap_input` 代表輸入驗證失敗，舊 publication／run 會保留，
不會用猜測資料啟動訓練。status 永遠明列 `database_mode=ro`、`query_only=true`、
`writes_source_database=false`、`formal_oos_allowed=false`、`production_alpha_bp=0`
與 `broker_order_allowed=false`。完成排程註冊後不需要人工重新執行 Direct、OOC 或
promotion；每日觸發會自動重試，既有 lock 與 hash-bound checkpoint 負責冪等續接。

## OOC refresh continuation

Direct v4 完成後，若新的 PIT sector sidecar 被放入 direct output lineage，
`continue_ml_direct_ooc_after_store.py` 會先以正式 assembler 驗證 canonical manifest、
accepted/license/source hash、可得時間與 training cutoff；全部通過才建立新的 immutable
Direct run，否則沿用現有 publication 並維持 formal gate 關閉。可用
`BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 指向受控來源；未設定時只掃描明確的
`pit_sector_membership`／`sector_membership`／`sidecars` 目錄與固定檔名，不會把
`companies.csv` 或研究輸出當成 PIT 歷史資料。若要讓這個等待跨越 worker／supervisor
中斷，維護程序可加 `--watch-formal-inputs`；它只在偵測到一個合規且唯一的 sidecar
時自動續跑，沒有來源時不會重複訓練。

維護器的 `--watch-formal-inputs` 不只等待 sector sidecar：它會以 pointer、canonical hash、
raw dataset safety、dataset decision_at 與現行 Direct identity 驗證新版或同一 cutoff 的新版
all-field raw PIT publication；也會驗證最新 official market-event publication。合格輸入會在同一
次 immutable Direct → OOC chain 綁定，並保留既有已驗證的 sector sidecar；只重發 wrapper、但
canonical events hash 未變時不會觸發不必要的重訓。這些探測不會自動建立或採用未受控的 causal
non-cash ledger／Rule Champion artifact，formal gate、alpha=0、broker disabled 仍維持。

正式 ledger／Rule Champion 可由受控 Windows 使用者環境變數
`BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH`／`BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH`
交給同一 watcher。維護器先執行唯讀 ledger chain、cutoff 與 Rule history HMAC 驗證；只有
sector、ledger、history 三項都可合法 hash-bind 時，formal-only refresh 才會啟動。分批出現
或驗證失敗的來源只會等待，不會觸發部分重訓、改寫舊 run 或提升 alpha。

長駐 watcher 每輪也會重新讀取 Windows 使用者／系統環境登錄值，讓 watcher 啟動後才完成的 owner deposit 能交接到同一個 process；只會將受控
path、HMAC key 與 store id 放入目前 process memory，絕不寫入檔案、命令列、status 或 log。若 watcher 自己採用的登錄值被移除，會清掉
該 process 內的值並回到 fail-closed 驗證；log 最多記錄被刷新的是變數名稱，不記錄任何 value。這不會繞過 ledger chain、Rule HMAC、PIT
sector 或 formal promotion gate。

獨立執行 `scripts/inspect_ml_formal_input_readiness.py` 時也會使用同一套 controlled Windows registry handoff：它只把 owner deposit 接到當前 read-only process memory，不寫回 registry、artifact 或 source DB。

Direct numeric store runs also publish `runs/<run_id>/heartbeat.json` with the
current stage, PID, completed years, and UTC `updated_at`.  While the OOC
continuation helper is waiting, it mirrors the latest valid heartbeat into
`continuation_status.json` when available and when its PID matches the
direct process being supervised.  This is progress observability only;
`checkpoint.json`, the finalized year manifests, and the hash-bound
`latest_manifest.json` remain the completion authority.  A stale or missing
heartbeat must never be interpreted as a completed store.

New direct builds also publish real annual boundaries: each source shard first
reports `raw_spool_source_shard_<year>_rows_<n>_processed` while validating (at
least every 100,000 rows or after 30 seconds without a progress event) and
then `raw_spool_source_shard_<year>_complete`, followed by
`year_raw_spool_complete` and `year_labels_complete`. During the potentially
long annual assembly, the builder reports
`assembly_decision_<date>_rows_<n>_processed` from the sample-row loop at the
same bounded row/time cadence, so a single large decision date cannot silence
the heartbeat. The label-spool stage also reports
`label_spool_starting_<symbols>_symbols_<dates>_dates`, bounded
`label_spool_symbol_<n>_of_<total>_decision_<n>_of_<total>_processed` events
while a single symbol is expensive, and `label_spool_symbols_<n>_of_<total>_processed`
at symbol boundaries, followed by `label_spool_complete`. The annual stages then
continue with `year_assembly_complete`, `year_artifacts_complete`, and
`year_directory_finalized`. These are
observability stages only; continuation still requires the checkpoint,
finalized year manifest, and hash-bound latest pointer before it can start OOC
training.

The initial raw discovery pass uses the same bounded heartbeat contract. It
reports `discovery_source_shard_<year>_rows_<n>_processed` and
`discovery_source_shard_<year>_complete` while verifying compressed hashes,
row hashes, feature definitions, and source content custody, so a long resume
scan remains observable without treating progress as completion.

After a successful discovery, the direct run stores a hash-bound
`discovery_cache.json`. A later checkpoint resume rechecks the raw manifest
identity and every compressed shard hash before reusing the cached feature
registry, calendar, folds, and source digest; any mismatch falls back to the
full fail-closed discovery scan.

Promotion evidence custody compares the official market-event canonical file
hash to the direct store. A republished wrapper with the same
`canonical_events_hash` is accepted as a no-op publication change, so an
unchanged immutable direct store is not rebuilt solely for corrected duplicate
metadata. Any canonical timeline hash change still produces
`formal_ooc_corporate_action_custody_stale` and remains fail-closed.

On Windows a venv launcher may have a separate Python worker PID.  The OOC
continuation accepts a direct heartbeat only when its PID is the supervised
launcher or a live descendant of that launcher; an unrelated or stale PID is
ignored.  This preserves process custody while still exposing the real annual
stage.

The annual raw spool now commits at each source-shard boundary to keep the
ephemeral SQLite transaction bounded; no annual artifact is published until
the complete work directory, hashes, and checkpoint pass validation.

The OOC trainer also keeps final-meta training bounded: it streams matured OOF
rows fold-by-fold and batch-by-batch, uses only a deterministic bounded sample
for medians, and makes separate bounded passes for normalization, Gram fitting,
and logistic IRLS. It does not materialize one full-width `train.meta.f32`, so
the 4GB memory guard remains meaningful on Windows.

OOC classifier calibration now has an expanding outer-fold cross-fitted
diagnostic: each target fold uses only earlier OOF blocks whose labels are
mature before the next fold starts. The report is integer-bp and explicitly
`oof_diagnostic_only=true` / `production_eligible=false`; it does not rewrite
the raw base vector consumed by the meta allocator. A later training manifest
may therefore replace `classifier_calibration_not_cross_fitted` with
`classifier_calibration_not_attached_to_ooc_model`; that remains a fail-closed
shadow boundary until a calibration artifact is attached to OOC inference.

`scripts\continue_ml_direct_ooc_after_store.py` 啟動時會先將 `continuation_status.json` 寫成 `waiting_for_direct_store`，避免沿用上一輪的 terminal `blocked` 診斷；direct store 完成後才會驗證 custody 並啟動 OOC。所有新版 waiting、custody、training heartbeat、complete 與 blocked status 都明列 `formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。若舊版 helper 完成時缺少這三個欄位，已結束 OOC helper 的 release coordinator 會自動補寫 fail-closed 欄位；明確的 true／非零值則直接阻擋，不以缺欄位或不安全值放行。Direct numeric v4 會把官方 halt/resume timeline 以 decision-time `effective_at`／`available_at` 寫入 replay source；舊 direct run 不會被原地改寫，續接流程會以新的 immutable custody 重新發布。接著 `scripts\continue_ml_release_after_ooc.py` 必須先觀察到 PID 與命令列均相符的 OOC helper，再等待其結束；之後才確認 training `latest_manifest.json`、continuation status 與兩者 manifest hash 完整一致，並依序執行 promotion evidence、promotion authority 與 daily ML copilot。任何缺件、hash 不一致或非零 exit code 都只寫 `blocked`，它不取代 Windows Task Scheduler，也不修改正式 market SQLite。

若 direct process 已正常完成但 supervisor 因 Windows custody／launcher race 中斷，可使用 `--resume-after-direct-store` 重新驗證 immutable direct manifest 後續接 OOC；此模式不宣稱 direct PID 仍存活，且同樣要求完整 checkpoint、年度 manifest、fold index 與 hash custody。

release follow-up 的三個命令現在以受監督子程序執行；每個命令會在 `post_ooc_followup_status.json` 發布 `followup_command_running`／`followup_command_complete`、子程序 PID、命令序號、開始時間與 return code。這只增加長命令的可觀測性，不改變 fail-closed promotion gate 或任何正式資料寫入邊界。

ML promotion evidence 與 promotion authority 的 status／pointer atomic publication 也使用 120 次、每次 0.5 秒的 Windows transient-lock bounded retry；重試耗盡仍會 fail-closed，不會以半成品覆寫既有狀態。

OOC handoff 在啟動訓練前會先發布 `store_custody_validation_starting`，再重新計算 direct top-level manifest canonical hash，並驗證 complete checkpoint、每個年度的 8 個 artifact hash／byte custody，以及所有 fold index artifact；任一年度、fold 或 checkpoint 不一致即停止在 `blocked`，不會開始訓練。

若現行 legacy direct run 已經在執行，`scripts\continue_ml_direct_v3_refresh_chain.py` 可由受控背景程序接手：它先以 PID／完整命令列等待既有 direct、OOC、release 三層全部結束，再啟動新的 immutable v4 direct build，並在 direct process 尚未退出前綁定新的 OOC helper 與 release helper，避免 process-custody race。狀態保存於 `v3_refresh_chain_status.json`，建置與下游輸出保存於 direct/training `logs\*v3_refresh.log`；任何失敗仍 fail-closed，不會刪除舊 run、改寫正式 SQLite 或開啟 alpha。

若 supervisor 本身在 legacy chain 停止後被中斷，重啟時使用 `--resume-after-legacy-chain`；此模式會先掃描完整命令列，若仍有任何相符的 direct／OOC／release process 就拒絕啟動，確認無 active target 後才從既有 checkpoint 接續。正常模式會在等待前一次性驗證三個 legacy PID，避免後續 helper 已先退出而造成錯誤的 custody failure。

若需要讓這條長時間 refresh chain 在 worker 或 supervisor 因 Windows sleep／process
中斷後自行恢復，可由受控背景程序執行
`scripts\maintain_ml_direct_v3_refresh_chain.py`。它會先以完整命令列掃描
Direct／OOC／release target；只要任一 target 存活就只等待，不會平行啟動。全部
target 停止且 primary status 尚未 `complete` 時，才會呼叫既有
`--resume-after-legacy-chain`，由相同 run identity 的 checkpoint、年度 manifest
與 raw hash 決定可否續跑。它另以 training output 目錄的 instance lock 防止兩個
維護器競爭；任何 retry 都維持 `formal_oos_allowed=false`、alpha 0、broker false，
不刪除舊 run、不改寫正式 SQLite 或手動發布 pointer。

補充：`continue_ml_direct_v3_refresh_chain.py` 若以自訂 `--status-path` 啟動，會自動把 direct／OOC／release 的 operational log 寫到 heartbeat 同層的 `logs` 目錄；因此即使正式資料目錄的 log 權限受限，也能繼續執行而不改寫正式資料。未指定自訂 status path 時仍使用既有 direct/training `logs` 位置。

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

baldr-ml-raw-pit-refresh-daily
  DAILY 05:05
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_raw_pit_refresh.cmd"

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
schtasks /Query /TN baldr-ml-raw-pit-refresh-daily /V /FO LIST
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

官方市場事件：

```text
<OUTPUT_ROOT>/scheduled/official_market_events/latest_status.json
<OUTPUT_ROOT>/release_v4/official_market_events/latest_manifest.json
<OUTPUT_ROOT>/release_v4/official_market_events/runs/<publication_id>/
<OUTPUT_ROOT>/release_v4/official_market_events/quarantine/<failure_id>/
```

TPEx 官方端點暫時不可用時，wrapper 會保留最後一個完整 formal publication，將本次失敗的 raw custody 移入 quarantine，並在 `latest_status.json` 記錄 `failure_class`、`formal_publication_preserved` 與可重試狀態；不會寫入 active SQLite，也不需要人工確認。若 latest pointer 仍可驗證但只涵蓋近兩年，下一次成功執行會自動 recovery 到 2014 起點；只有通過完整年度覆蓋與 hash 驗證的 publication 才能繼續供 PIT／ML evidence 使用。

Data freshness:

The quick update publishes `status=running` with a run/process identity before its long-running steps begin, then records `started_at` and `completed_at` on the terminal status. Downstream freshness and ML evidence checks treat a running or stale update as not-ready, so a partially completed update cannot be consumed.

The same runner appends bounded `data-update-status-history.v1` records to `history.jsonl` (or the explicit `--history-path`) for the running and terminal attempts. The history is append-only and idempotent by record hash; it does not backfill an existing `latest_status.json` and does not change any downstream readiness or write permission.

```text
<OUTPUT_ROOT>/scheduled/data_update_quick/latest_status.json
<OUTPUT_ROOT>/scheduled/data_update_quick/history.jsonl
<OUTPUT_ROOT>/scheduled/data_update_quick/YYYYMMDD_data_update_quick.log
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log
```

Automatic raw PIT refresh:

```text
<OUTPUT_ROOT>/scheduled/ml_raw_pit_refresh/latest_status.json
<OUTPUT_ROOT>/scheduled/ml_raw_pit_refresh/refresh.log
<OUTPUT_ROOT>/release_v4/ml_pit_year_shards/latest_manifest.json
<OUTPUT_ROOT>/release_v4/ml_pit_year_shards/runs/<publication_id>/
```

`latest_status.json` records the upstream data-update status, core dates, decision cutoff,
source database read-only contract, builder return code, and published manifest hashes.
`blocked_upstream_not_ready` means the runner waits for a later data-update proof;
`skipped_current` means the current pointer already covers the cutoff; `completed` means
the immutable raw publication passed pointer, canonical hash, all-universe scope, dataset
safety, and decision-time validation. The runner never deletes an earlier publication.

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

`latest_status.json` 記錄台北 `decision_at`、`snapshot.saved`／`snapshot.duplicate`、`evidence.events_inserted`／`evidence.duplicates`／`evidence.failures`，以及整體 `passed`／`failed`。排程預設選擇最近一個已到達的台北 08:30 cutoff；明確指定未到達的日期則由 capture CLI 以 `decision_date cannot be future-dated` fail closed。它明確輸出 `trading_calendar_validated=false`、`maturity_date_inferred=false`，不把週末、休市或未成熟資料偽裝成正式交易日證據。snapshot 成功、event capture 失敗時，下次執行會重用 snapshot hash 並再次嘗試 event unique-key capture。

Paper Portfolio 每日估值：

```text
<OUTPUT_ROOT>/paper_portfolio/paper_portfolio.sqlite
<OUTPUT_ROOT>/scheduled/paper_portfolio_daily/latest_status.json
```

runner 會以既有 baseline 初始化一次，之後只 append 新 snapshot。排程預設選擇最近一個已到達的台北 08:30 cutoff；明確指定仍未到達的 `--decision-at` 會寫入 `skipped_future_decision`，且不開啟 state／market DB。市場 DB 永遠唯讀，SQL 與 domain runner 都拒絕 `price_date >= decision_date` 或 `available_date >= decision_date`；同一決策日重跑只回報 duplicate。此排程不把 current weight 猜成 0、不產生交易、不套用配置提案。

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

### ML allocation automatic catch-up

run_ml_allocation_copilot.cmd 會固定傳入 --auto-catch-up。只有在沒有
明確指定 ML_ALLOCATION_DECISION_AT、排程選到下一個台北曆日，且完整
orchestration 實際證明該候選日的 strict T-1 尚未就緒時，runner 才會
向後重試最多 31 個曆日，選擇最近的已過交易日。判定依據是既有
hash-bound raw publication 與 post-freeze T-1 proof，不新增另一套資料
解讀，也不寫入來源 SQLite、不使用未來資料；資料庫或官方日曆狀態未知時，
不猜測，保留 fail-closed。明確指定日期時不會自動改日期。

latest_status.json 會保存 decision_selection_mode、
requested_decision_at、decision_selection_reason 與每個候選的
decision_selection_attempts，因此自動補跑不需要人工猜測，也不會把
回溯日期偽裝成原本的決策日。

週日 sidecar task 只執行 collection CLI；不呼叫 `--save-history` 或 `--confirm-action-items`，也不寫 source DB。成功週期由 Pre-V2/V4 readiness 自動計數與重驗；不足證據只限制 formal evidence credit，不阻擋 Rule／Advice／Paper operational production。

### ML promotion evidence automatic catch-up

05:17 `run_ml_promotion_evidence.cmd` 會以唯讀方式解讀
`scheduled/data_update_quick/latest_status.json` 的 `check_overview_after`，只接受
`daily_data` 與 `technical_indicators` 都已到達的最晚日期。若原始下一個官方決策日的
strict T-1 超過該日期，就依官方日曆向後掃描最多 31 個曆日，改選最近一個已具備
T-1 證據的決策日；若 strict T-1 已完整，則維持預備的下一個決策日。此選擇不使用
未來資料、不寫正式 SQLite，也不更新 compatible pointer。

Evidence runner 在選日前先驗證 upstream `data_update_quick` status 為 `passed` / `passed_with_warnings`，且 `daily_data` / `technical_indicators` latest date 不得超過當前台北日。status 遺失、failed、格式破損或未來日期時，直接寫 blocked，不猜測未來決策日。

Evidence status schema v3 會保存 `requested_decision_at`、`decision_selection_mode`、
`decision_selection_reason`、`decision_selection_attempts` 與
`latest_core_feature_date`、`upstream_data_update_proof_state` 與
`upstream_data_update_proof_reason`。選日調整不是 Gate 通過；formal OOC、PIT、replay、shadow
或 authority 任一缺件仍會回傳 blocked、alpha 0。

Only the dedicated Decision/Evidence capture task writes the durable snapshot and production evidence event tables through the existing idempotent repositories. The Paper Portfolio task writes only its isolated append-only paper ledger. The data freshness, recommendation, evidence dry-run, ML co-pilot and weekly collection tasks do not write the production evidence DB. No scheduled task runs the UI, reads UI state, changes the live portfolio, changes `ScoringEngine`, changes recommendation weights, promotes / demotes / retires strategies, connects to a broker, or automates trading.

ML allocation co-pilot task 只消費前兩個獨立 task 產生、且與本次 inference release 相同的 evidence／authorization custody。Evidence builder 不簽章，Authority 不訓練模型，Co-pilot 不自行製造 OOS、PIT、calibration、drift 或 shadow days 證據；非零 alpha 必須通過三層重驗。

The recommendation snapshot is intentionally saved before the evidence dry-run so the dry-run can observe the latest recommendation payloads, including screening matrix / why-not / liquidity gate payloads when available.

Generated evidence reports 是機器 Gate 的可稽核輸入；它們本身不證明 alpha，也不得直接轉成交易指令。

During dry-run, the runner may build a transient Daily Decision Desk snapshot for the same run. Reports mark this as `source_coverage_basis=dry_run_transient_decision_desk_snapshot`; this reconciles diagnostics only and does not persist the snapshot.

The evidence dry-run `latest_status.json` also includes selected pipeline summary fields from the same run, including `pipeline_overall_status`, warning counts, advisory counts, source-quality coverage rows, diagnostics, and source-coverage readiness. `pipeline_warnings_count` is only actual warning occurrences. `pipeline_natural_maturity_warning_counts` separates `insufficient_future_data` from `pipeline_actionable_warning_counts`; `natural_maturity_only=true` means the remaining degradation is expected to resolve only as forward observations mature and is not a manual repair blocker. `manual_action_required=true` is reserved for a failed or stale freshness input, missing pipeline summary, pipeline error / blocking gap, or non-natural warning. The wrapper always records `dry_run=true`, `confirm=false`, `writes_evidence_db=false`, and `production_scheduler_allowed=false`. `pipeline_advisories_count` separately records complete but estimated MoneyDJ provenance; it does not mean source data is missing. Fixed-threshold recommendation snapshots may leave `score_percentile_bp` empty because no comparable ranked universe is persisted; that is not a warning. These fields are copied from the dry-run stdout only; the wrapper does not rerun the pipeline. Decision Desk SQLite section providers use `mode=ro` / `query_only` for scheduled reads.

## Codex Morning Summary

The Codex app automation `baldr scheduled evidence morning report` runs separately at about local time 05:30. It only reads Windows Task Scheduler status, `latest_status.json`, the latest data update status, the latest recommendation snapshot status, the latest evidence dry-run report, and relevant log warning / error sections, then writes a Traditional Chinese summary to the user.

It must not rerun data update, rerun data freshness, rerun the evidence pipeline, enter confirm write mode, create or modify Windows Task Scheduler tasks, write the production evidence DB, change portfolio / scoring / recommendation weights, apply lifecycle actions, push, or produce trading advice.
