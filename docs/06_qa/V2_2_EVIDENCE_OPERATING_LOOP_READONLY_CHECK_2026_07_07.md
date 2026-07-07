# V2.2 Evidence Operating Loop Read-only Check

> 檢查時間：2026-07-06 local / 2026-07-07 UTC
> 範圍：Pre-V2 readiness、Evidence Review、weekly history、multi-day dry-run、manual review note 與 action item rhythm。
> 結論：仍未累積到 V2.2 / Phase 0 gate。weekly history 維持 `0/3`，multi-day dry-run record 維持 `1/3`，production scheduler 維持 disabled。

## Read-only Boundary

本次只讀取既有正式 DB、既有 scheduled dry-run output、既有 QA 文件與 repo 內程式碼。

- 未啟用 Windows Task Scheduler。
- 未執行 replay。
- 未寫入 evidence DB、working-copy DB 或 formal DB。
- 未用 fixture、manual edit、replay 或單次 smoke 補 gate。
- 未產生買賣建議，未修改 lifecycle state。

## Inputs Checked

- `app_module/pre_v2_readiness_service.py`
- `scripts/inspect_pre_v2_readiness.py`
- `docs/06_qa/POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`
- `docs/06_qa/POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md`
- `D:/Min/Python/Project/FA_Data/sqlite/twstock.db`（SQLite `mode=ro` / `PRAGMA query_only=ON`）
- `D:/Min/Python/Project/FA_Data/output/scheduled/evidence_pipeline_dry_run/*`

## Current Readiness

`scripts/inspect_pre_v2_readiness.py` 對正式 DB 與正式 multi-day record 的讀取結果：

| Item | Status | Observed | Required | 判讀 |
|---|---|---:|---:|---|
| weekly history | `waiting_for_time` | 0 | 3 | `evidence_operations_weekly_reviews` 表存在，但正式 DB count = 0。 |
| multi-day dry-run | `waiting_for_time` | 1 | 3 | record 表格只計入 `2026-07-02`。 |
| source gaps | `action_required` | N/A | N/A | 正式 DB 缺 active DDD snapshot；最新正式 recommendation payload 仍缺 why-not / liquidity / screening matrix payload。 |
| read-only Agent report sample | `ready` | 5 | N/A | 可讀 Research Run metadata；`strategy_lifecycle_evidence_table_missing` 仍只是 diagnostic。 |

正式 DB 唯讀查詢結果：

| Table | Count | Latest |
|---|---:|---|
| `evidence_operations_weekly_reviews` | 0 | `NULL` |
| `decision_desk_snapshots` | 0 | `NULL` |
| `evidence_events` | 0 | `NULL` |
| `decision_quality_reviews` | 0 | `NULL` |
| `decision_quality_items` | 0 | `NULL` |
| `decision_quality_action_items` | 0 | `NULL` |
| `signal_decay_observations` | 0 | `NULL` |

## Scheduled Dry-run Reports

`OUTPUT_ROOT/scheduled/evidence_pipeline_dry_run` 內已有 2026-07-02 至 2026-07-06 的 read-only dry-run reports。這些檔案證明 daily dry-run wrapper 曾產生 raw evidence，但不自動計入 multi-day gate，因為 gate 還要求 working-copy confirm smoke、Evidence Review dashboard review、manual notes 與人工可比較紀錄。

| Report date | Dry-run | Confirm | Events seen | Events inserted | Warnings | Scheduler after | Blocking gaps |
|---|---|---|---:|---:|---:|---|---|
| 2026-07-02 | true | false | 7 | 0 | 23 | `not_ready` | watchlist / portfolio / risk prompt / why-not / liquidity gaps |
| 2026-07-03 | true | false | 7 | 0 | 29 | `not_ready` | watchlist / portfolio / risk prompt / why-not / liquidity gaps |
| 2026-07-04 | true | false | 7 | 0 | 29 | `not_ready` | watchlist / portfolio / risk prompt / why-not / liquidity gaps |
| 2026-07-05 | true | false | 7 | 0 | 29 | `not_ready` | watchlist / portfolio / risk prompt / why-not / liquidity gaps |
| 2026-07-06 | true | false | 432 | 0 | 862 | `ready_for_manual_confirm` | none |

2026-07-06 是下一次人工 review 的最佳候選輸入，但目前只能視為「待人工判讀的 raw dry-run evidence」，不是已完成的 multi-day record row。

## Evidence Review Status

- `POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md` 仍是人工 checklist scaffold；Manual Result Table 未填入新的 Actual / Pass / Fail。
- `PRE_V2_NON_SCHEDULE_READINESS_CLOSEOUT_2026_07_06.md` 已記錄一次 prior UI smoke closeout，但這不是新的 2026-07-06 scheduled dry-run dashboard review。
- 因此本次未新增 Evidence Review manual closeout，也未把 2026-07-06 raw report 登錄為 multi-day gate。

## Manual Review Note And Action Item Rhythm

- Workbench Action Items 與 Operating Loop 是 read-only DTO / UI rhythm，不建立 repository、不標記完成、不寫 manual note。
- 正式 DB 的 `decision_quality_reviews`、`decision_quality_items`、`decision_quality_action_items` 都是 0 筆。
- 目前沒有可判讀的真實 action item rhythm；下一步只能先做 dry-run planning 與人工 review note，不得自動套用 lifecycle action。

## Next Read-only Checklist

### Daily Dry-run Review

1. 只讀檢查 freshness：
   ```powershell
   Get-Content -Raw -Encoding UTF8 D:\Min\Python\Project\FA_Data\output\scheduled\data_freshness\latest_status.json
   ```
2. 只讀檢查 latest scheduled dry-run status：
   ```powershell
   Get-Content -Raw -Encoding UTF8 D:\Min\Python\Project\FA_Data\output\scheduled\evidence_pipeline_dry_run\latest_status.json
   ```
3. 只讀檢查 latest dry-run report，確認 `dry_run=True`、`confirm=False`、`events_inserted=0`、`writes_evidence_db=false`。
4. 跑 Pre-V2 inspector 到 stdout，不指定 `--report-output`：
   ```powershell
   .\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --decision-date <YYYY-MM-DD> --multi-day-record-path docs\06_qa\POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md --json-output
   ```
5. 若 latest scheduled dry-run 是 `ready_for_manual_confirm`，只把它列為人工 review 候選；不要直接補 `POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`。
6. 只有在同一觀察日完成 freshness、source coverage、manual dry-run、working-copy confirm smoke、Evidence Review dashboard review 與人工 notes 後，才可新增一列 multi-day record；不得回填過去 raw scheduled report。

### Weekly Review

1. 只讀產生 weekly review JSON，不使用 `--save-history`、不使用 `--confirm-action-items`：
   ```powershell
   .\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --db-path D:\Min\Python\Project\FA_Data\sqlite\twstock.db --plan-action-items --json-output
   ```
2. 確認 payload 內 `write_performed=false`、`production_scheduler_allowed=false`、manual lifecycle candidates 的 `apply_action=false`。
3. 若要讓 weekly history 計入 gate，必須另行取得 explicit approval，改用 working-copy DB 執行 `--save-history`；不得對 formal DB 直接保存 history。
4. Action item planning 保持 dry-run；只有人工核准且使用 explicit working-copy DB 時才可 confirm。

### Manual Review Note

1. Manual note 必須描述當日看到的 source trace、degraded reason、blocking gaps、dashboard review 結論與下一步。
2. Note 不得包含買賣建議、倉位建議或 lifecycle action。
3. Note 不得把 historical replay、raw scheduled report 或單次 smoke 說成 Phase 0 gate 已完成。

## Decision

V2.2 Evidence Operating Loop 仍未完成。下一次應優先人工判讀 2026-07-06 dry-run report，因為它已到 `ready_for_manual_confirm` 且 blocking gaps 為 none；但它仍需要完整 manual review / working-copy smoke / note 才能成為可比較操作紀錄。
