# V2.2 Simulated Phase Progress QA - 2026-07-07

> 檢查時間：2026-07-06 local / 2026-07-07 UTC
> 範圍：Historical Evidence Replay reference-fix summary、scheduled dry-run latest status、Pre-V2 readiness、Phase 0 official gate 分離判讀。
> 結論：historical replay 可支援 `simulated_phase_progress` 從 Phase 0 演練到 simulated Phase 5；official Phase 0 / Phase 5 gate 未改變。

## Read-only Boundary

本次只讀取既有 replay summary、既有 scheduled dry-run status、正式 DB 與 repo 內 QA record。

- 未啟用 scheduler。
- 未執行 replay。
- 未寫入 evidence DB、working-copy DB 或 formal DB。
- 未用 replay、fixture、manual edit 或 raw scheduled report 補 official gate。
- 未產生買賣、倉位、策略有效性或 lifecycle action 結論。

## CLI Smoke

執行的新 read-only CLI：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_simulated_phase_progress.py `
  --db-path D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --research-db-path D:\Min\Python\Project\FA_Data\sqlite\research_runs.db `
  --replay-summary-path D:\Min\Python\Project\FA_Data\output\evidence_pipeline\historical_replay_reference_fix_20260706\historical_replay_2026-01-06_2026-07-06_reference_fix.json `
  --scheduled-output-root D:\Min\Python\Project\FA_Data\output\scheduled\evidence_pipeline_dry_run `
  --decision-date 2026-07-06 `
  --multi-day-record-path docs\06_qa\POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md `
  --json-output
```

關鍵輸出：

| Field | Value |
|---|---|
| `simulated_overall_status` | `simulated_ready` |
| `official_phase_5_status` | `blocked` |
| `production_scheduler_allowed` | `false` |
| `replay_run_id` | `hre_eb11c53d4986` |
| replay days | `118` |
| events seen | `118056` |
| outcomes created | `472224` |
| official weekly history | `0/3` |
| official multi-day dry-run record | `1/3` |
| simulated Phase 5 | `simulated_ready` |
| official Phase 5 item status | `official_gate_not_satisfied` |

## Replay 標註

這次 reference-fix replay 被標註為：

| 標註 | 值 | 意義 |
|---|---|---|
| `replay_mode` | `historical_replay` | 歷史重放，不是真實排程。 |
| `source_label` | `simulated_scheduler` | 模擬 scheduler，不是 production scheduler。 |
| `replay_run_id` | `hre_eb11c53d4986` | 本次 replay summary 的唯一識別。 |
| first `replay_decision_date` | `2026-01-06` | 第一個模擬決策日。 |
| last `replay_decision_date` | `2026-07-06` | 最後一個模擬決策日。 |
| first `replay_data_as_of_date` | `2026-01-06` | 第一個 replay day 可見資料上限。 |
| last `replay_data_as_of_date` | `2026-07-06` | 最後一個 replay day 可見資料上限。 |
| `data_as_of_dates` | `2026-07-06` | outcome summary 可見資料上限。 |
| `official_gate_credit` | `false` | 不計入 official weekly / multi-day / Phase 5 gate。 |
| `requires_real_world_validation` | `true` | 仍需真實時間資料補強。 |

Scheduled dry-run latest status 被標註為：

| 標註 | 值 | 意義 |
|---|---|---|
| `dry_run` | `true` | 只跑 dry-run。 |
| `confirm` | `false` | 未做 formal DB confirm。 |
| `writes_evidence_db` | `false` | 不寫 evidence DB。 |
| `scheduled_task_observed` | `true` | 只代表看見 scheduled task output。 |
| `manual_record_credit` | `false` | 尚未經完整人工 review，不計入 multi-day record。 |

## Phase 0-5 判讀

| Phase | Simulated 判讀 | Official 判讀 | 說明 |
|---|---|---|---|
| Phase 0 | `simulated_ready` | `official_gate_not_satisfied` | replay / scheduled output 可觀察，但 weekly history `0/3`、multi-day record `1/3`。 |
| Phase 1 | `simulated_ready` | `official_gate_not_satisfied` | replay summary 可提供 Workbench evidence disclosure / degraded-state 設計輸入。 |
| Phase 2 | `simulated_ready` | `official_gate_not_satisfied` | scheduled dry-run status 可演練 operating loop，但 action item / manual note 未正式保存。 |
| Phase 3 | `simulated_ready` | `official_gate_not_satisfied` | replay gaps 可轉成 candidate source backlog，尚未進正式 source policy。 |
| Phase 4 | `simulated_ready` | `official_gate_not_satisfied` | outcome summary 可產生 execution realism candidate，不改 Portfolio / scoring。 |
| Phase 5 | `simulated_ready` | `official_gate_not_satisfied` | 可產生 approval package rehearsal；official scheduler gate 仍 blocked。 |

## 真實資料補強 Checklist

### 補 Phase 0 Weekly History

1. 每週用 working-copy DB 產生 weekly evidence operations review。
2. 人工確認 review 內容、source trace、blocking gaps 與 action item dry-run。
3. 只有取得 explicit approval 後，才在 working-copy DB 使用 `--save-history`。
4. 累積至少 3 筆不同週期的 weekly history。
5. 再用 `scripts/inspect_pre_v2_readiness.py` 確認 `weekly_history >= 3`。

### 補 Multi-day Dry-run

1. 每個真實交易日先 read-only 檢查 freshness 與 scheduled dry-run latest status。
2. 確認 latest status 只代表 raw output，不直接補 record。
3. 對同日 working-copy DB 執行 confirm smoke repeat=2。
4. 人工打開 Evidence Review / Workbench 檢查 dashboard 與 degraded warnings。
5. 人工填入 `POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`。
6. 累積至少 3 個可比較交易日；目前仍是 `1/3`。

### 補 Phase 3 / 4

1. 將 replay diagnostics / source gaps 轉成 candidate source backlog。
2. 每個候選 source 定義 `source_id`、`available_date`、`quality`、`missing_policy`。
3. 先跑 diagnostics / dry-run，不接入 `ScoringEngine`。
4. execution realism candidate 先留在 research-only sandbox，避免改動持倉或回測核心語意。

### 補 Phase 5

1. official Phase 0 weekly / multi-day gates 先達標。
2. working-copy confirm smoke 證明 idempotent。
3. source gaps 無 blocking，或 signed accepted residual 已記錄。
4. backup / rollback / recovery checklist 完成。
5. explicit manual approval 到位後，才可另案設計 write-mode enablement。

## Decision

`simulated_phase_progress` 工具可用於 historical replay 到 Phase 5 的工程演練與審核包預演；它不改變 lifecycle、不啟用 scheduler、不補 official gate。下一步真實累積仍應優先完成 weekly history `3/3` 與 multi-day dry-run `3/3`。
