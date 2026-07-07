# V2.2 Simulated Phase Progress Design

## Purpose

建立一條與正式 Phase gate 隔離的 `simulated_phase_progress` 軌道，使用 Historical Evidence Replay 與 read-only scheduled dry-run reports，將 Phase 0 到 Phase 5 的設計、診斷、候選缺口與 approval package rehearsal 先跑完。

這條軌道的核心價值是加速工程準備與人工覆盤，不是補正式 gate。

## Non-goals

- 不把 historical replay 計入 Phase 0 weekly history。
- 不把 scheduled dry-run raw reports 自動計入 multi-day dry-run record。
- 不啟用 production scheduler。
- 不寫 formal evidence DB。
- 不建立或套用 lifecycle action。
- 不產生買賣建議、倉位建議或策略有效性結論。
- 不把 simulated Phase 5 完成標示為 official Phase 5 approval。

## Authority Boundary

正式 gate 仍以 `PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、`VERSION_ROADMAP_V2_1_TO_V4_0.md` 與 `APPLICATION_MANUAL.md` 為準。

`simulated_phase_progress` 只能輸出下列語意：

- `simulated_ready`
- `simulated_degraded`
- `simulated_blocked`
- `official_gate_not_satisfied`
- `manual_validation_required`

以下字串只可出現在本禁止清單、測試 fixture 或負向斷言；runtime output 與使用者可見報告禁止輸出：

- `official_ready`
- `phase_complete`
- `scheduler_approved`
- `production_ready`
- 任何暗示投資有效或可交易的文字。

## Replay Tagging

所有 replay-derived evidence 必須保留或新增以下標註：

| Field | Required | Meaning |
|---|---|---|
| `replay_mode=historical_replay` | yes | 來源是歷史重放，不是真實排程。 |
| `source_label=simulated_scheduler` | yes | 模擬 scheduler，不是 production scheduler。 |
| `replay_run_id` | yes | 本次 replay 唯一識別。 |
| `replay_decision_date` | yes | 模擬當天的決策日。 |
| `replay_data_as_of_date` | yes | replay 當下允許可見的資料截止日。 |
| `data_as_of_date` | yes for outcomes | Forward outcome 計算可見資料上限。 |
| `phase_simulation_scope` | yes | 對應 Phase 0 / 1 / 2 / 3 / 4 / 5 的模擬用途。 |
| `official_gate_credit=false` | yes | 明確宣告不得計入正式 gate。 |
| `requires_real_world_validation=true` | yes | 後續需要真實資料補強。 |

若來源是 scheduled dry-run raw report，則需標註：

| Field | Required | Meaning |
|---|---|---|
| `dry_run=true` | yes | 只跑 dry-run。 |
| `confirm=false` | yes | 未寫 evidence DB。 |
| `writes_evidence_db=false` | yes | 不寫 formal DB。 |
| `scheduled_task_observed=true` | yes | 只代表 task output 被看到。 |
| `manual_record_credit=false` | yes | 未經人工 review 前不得計入 multi-day record。 |

## Simulated Phase Model

### Phase 0: Simulated Observability

目的：用 replay 與 scheduled dry-run 檢查 evidence pipeline 是否能被觀察、診斷與回放。

可算 simulated progress：

- replay days count。
- events seen / outcomes created。
- benchmark coverage。
- source gaps / payload gaps。
- scheduled dry-run report presence。

不可算 official progress：

- weekly history count。
- multi-day dry-run count。
- manual review completed。

輸出：

- `simulated_phase_0_status`
- `official_weekly_history_observed`
- `official_multi_day_record_observed`
- `official_gate_not_satisfied_reason`

### Phase 1: Workbench Design Input

目的：把 replay quality boundary 轉成 Workbench 第一屏、Evidence mode、warnings 與 degraded state 的設計輸入。

可用 replay 支援：

- market benchmark coverage。
- industry benchmark missing rate。
- screening matrix source gap。
- pending future-data。
- old payload limitations。

輸出：

- Workbench data quality disclosures。
- replay-derived evidence feed diagnostics。
- drill-down guidance。

### Phase 2: Operating Loop Rehearsal

目的：用 replay / dry-run payload 演練 daily first-look、manual queue、weekly review、multi-day dry-run 與 scheduler gate 的 UI / CLI rhythm。

可算 simulated progress：

- action items can be generated read-only。
- operating loop steps can be rendered。
- manual note checklist can be produced。

不可算 official progress：

- action item reviewed。
- manual note saved。
- lifecycle action applied。

### Phase 3: Data Source Candidate Dry-run

目的：從 replay gaps 反推 P0 data source candidates。

候選缺口：

- corporate action / adjusted price policy。
- industry / sector mapping gaps。
- screening matrix old-payload gap。
- watchlist / portfolio / risk prompt source gaps。
- microstructure restriction metadata。

輸出：

- `candidate_source_id`
- `gap_reason`
- `available_date_policy_needed`
- `missing_policy`
- `expected_validation`

### Phase 4: Execution Realism Candidates

目的：用 replay outcome / event limitations 建立 execution realism backlog，不改 Portfolio / scoring。

候選項：

- bid-ask spread assumption。
- lot sizing / odd-lot residual。
- limit-up / limit-down locked execution。
- gap actual execution model。
- rejected / partially filled virtual order reasons。

輸出：

- research-only execution realism candidate list。
- no broker integration。
- no portfolio position mutation。

### Phase 5: Scheduler Approval Package Rehearsal

目的：用 replay 與 scheduled dry-run 產出「approval package rehearsal」，讓正式 gate 到位後可快速審核。

可完成 simulated Phase 5：

- approval checklist draft。
- rollback / backup checklist draft。
- dry-run report summary。
- source gap acceptance matrix draft。
- production scheduler risk register draft。

不可完成 official Phase 5：

- explicit approval。
- production write-mode scheduler enablement。
- formal DB confirm。

輸出必須寫：

```text
simulated_phase_5_status=simulated_ready
official_phase_5_status=blocked
production_scheduler_allowed=false
reason=Phase 0 official weekly/multi-day/manual approval gates not satisfied
```

## Proposed Components

### DTOs

新增或延伸 read-only DTO：

- `SimulatedPhaseProgressReport`
- `SimulatedPhaseProgressItem`
- `ReplayEvidenceTagSummary`
- `RealWorldValidationPlan`

每個 item 必須包含：

- `phase_id`
- `simulated_status`
- `official_status`
- `source_trace`
- `replay_tags`
- `official_gate_credit`
- `real_world_validation_required`
- `next_real_world_steps`

### Service

新增 `app_module/simulated_phase_progress_service.py`。

責任：

- 讀取 replay JSON summary。
- 讀取 scheduled dry-run latest status / reports。
- 讀取 Pre-V2 readiness report。
- 組合 Phase 0-5 simulated progress。
- 輸出 real-world validation plan。

限制：

- 只讀檔案與 DB。
- 不建立 schema。
- 不寫 DB。
- 不呼叫 scheduler。
- 不跑 replay。

### CLI

新增 `scripts/inspect_simulated_phase_progress.py`。

輸入：

- `--replay-summary-path`
- `--scheduled-output-root`
- `--db-path`
- `--decision-date`
- `--multi-day-record-path`
- `--json-output`
- `--markdown`

輸出：

- official gate summary。
- simulated Phase 0-5 progress。
- replay tag summary。
- real-world validation checklist。

### Optional Workbench Integration

後續可把 simulated progress 加到 Workbench Evidence mode，但第一版不必改 UI。若要接 UI，必須顯示為：

```text
Simulated progress only. Official gate unchanged.
```

## Real-world Validation Plan

### 補 Phase 0

1. 每週用 working-copy DB 產生 weekly review。
2. 人工確認後才用 `--save-history` 保存到 working-copy DB。
3. 累積到 3 筆不同週期。
4. Pre-V2 inspector 確認 `weekly_history >= 3`。

### 補 multi-day dry-run

1. 每個交易日先確認 freshness。
2. 檢查 scheduled dry-run report。
3. 必要時手動 rerun dry-run。
4. 對同日 working-copy DB 跑 confirm smoke repeat=2。
5. 人工打開 Evidence Review / Workbench 做 dashboard review。
6. 填入 `POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`。
7. 累積 3-5 個交易日。

### 補 Phase 3 / 4

1. 對 replay gaps 建立 candidate source backlog。
2. 每個 source 定義 `source_id`、`available_date`、`quality`、`missing_policy`。
3. 只先進 diagnostics / dry-run，不進 `ScoringEngine`。
4. 對 execution realism candidates 先進 research-only sandbox。

### 補 Phase 5

1. 官方 Phase 0 gate 達標。
2. working-copy confirm smoke idempotent。
3. source gaps 無 blocking 或有 signed accepted residual。
4. backup / rollback / recovery checklist 完成。
5. explicit manual approval 後才可設計 write-mode enablement。

## Testing

Focused tests:

- service parses replay summary and scheduled status without writes。
- official gate remains blocked when replay is rich。
- simulated Phase 5 can be `simulated_ready` while official Phase 5 is `blocked`。
- forbidden wording absent。
- CLI emits JSON / Markdown without creating files unless explicit report output is added later。

Suggested commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_simulated_phase_progress_service.py tests\test_simulated_phase_progress_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\simulated_phase_progress_service.py scripts\inspect_simulated_phase_progress.py
git diff --check
```

## Documentation

Must update:

- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/06_qa/` closeout / QA note for simulated progress

Should inspect:

- `PROJECT_SNAPSHOT.md`
- `ROADMAP_6M_ENGINEERING.md`
- `VERSION_ROADMAP_V2_1_TO_V4_0.md`
- `APPLICATION_MANUAL.md`

These should only change if implementation becomes a user-visible CLI / Workbench flow. They must keep official Phase 0 / Phase 5 unchanged unless true real-world gates are satisfied.

## Commit Plan

Implementation should be split into staged commits:

1. DTO / service / tests for simulated phase progress.
2. CLI / Markdown rendering / tests.
3. Documentation and QA closeout.
4. Optional Workbench read-only integration, if explicitly approved after CLI is stable.
