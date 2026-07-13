# V3.0 Engineering Candidate Manual Validation Report

## Scope

本報告覆蓋 V3.0 engineering candidate 的唯讀工程候選：effectiveness read model、gap classifier、sample sufficiency / confidence disclosure、signal / alert / gate review scaffold，以及 readiness inspector。此報告不宣稱投資有效性，不啟用 production scheduler，不執行交易或 lifecycle action。

## Engineering Artifacts

| Artifact | Status |
|---|---|
| `app_module/v3_effectiveness_dtos.py` | implemented |
| `app_module/v3_gap_classifier.py` | implemented |
| `app_module/v3_effectiveness_read_model.py` | implemented |
| `app_module/v3_effectiveness_dashboard_service.py` | implemented |
| `app_module/v3_effectiveness_review_scaffold.py` | implemented |
| `scripts/inspect_v3_evidence_effectiveness.py` | implemented |
| `scripts/build_v3_effectiveness_review_scaffold.py` | implemented |
| `scripts/inspect_v3_engineering_candidate_readiness.py` | implemented |

## Evidence Sources Reviewed

- Existing evidence events / outcomes are represented through read-only row payloads.
- Forward outcome maturity is summarized as ready / pending / missing counts.
- Gap classification keeps source / payload / forward outcome / sample / live gap / manual validation categories explicit.
- Historical replay or sample payloads do not count as official Phase 0 evidence.

## Sample Sufficiency Summary

The current engineering slice labels evidence as:

- `insufficient_sample`
- `directional_only`
- `review_ready`
- `needs_manual_validation`

These labels are disclosure states only. They do not represent win rate, expected return, trade quality, or investment effectiveness.

## Gap Classifier Summary

| Gap | Classification | Manual Validation |
|---|---|---|
| `source_missing_screening_matrix` | payload_gap | NOT_REQUIRED |
| `missing_industry_benchmark` | accepted_residual | NOT_REQUIRED |
| `forward_outcome_missing` | forward_outcome_gap | NOT_REQUIRED |
| `sample_below_minimum` | sample_insufficiency | NOT_REQUIRED |
| `live_gap_missing` | live_gap_missing | NOT_REQUIRED |
| `manual_validation_missing` | manual_validation_pending | PENDING_MANUAL_VALIDATION |

## Signal / Alert / Gate Review Items

The scaffold maps candidate evidence families into human review categories:

| Family | Review Category | Boundary |
|---|---|---|
| recommendation | signal | Manual review only |
| watchlist | signal | Manual review only |
| portfolio_alert | alert | Manual review only |
| risk_prompt | alert | Manual review only |
| why_not | gate | Manual review only |
| liquidity | gate | Manual review only |
| screening_matrix | gate | Manual review only |
| decision_quality | dashboard | Manual review only |

## Manual Validation Status

- Overall: PENDING_MANUAL_VALIDATION

## Safety Boundary

- production_scheduler_allowed=false
- auto_trading=false
- lifecycle_action=false
- scheduler_write_mode=false
- no investment effectiveness claim
- no production DB write
- no scoring / portfolio / lifecycle mutation

## Pending Human Checks

| Check | Status | Required Human Action |
|---|---|---|
| Sample sufficiency threshold acceptance | PENDING_MANUAL_VALIDATION | Confirm thresholds are acceptable for V3 engineering candidate. |
| Signal / alert / gate review wording | PENDING_MANUAL_VALIDATION | Confirm no wording implies investment effectiveness. |
| Dashboard disclosure readability | PENDING_MANUAL_VALIDATION | Review UI / markdown output. |

## Morning Validation Notes

- Engineering candidate readiness can be inspected with `scripts/inspect_v3_engineering_candidate_readiness.py --sample --json-output`.
- If manual validation remains pending, status should stay `ready_for_manual_validation`, not official investment maturity.
- Phase 0 weekly history, multi-day dry-run, source acceptance, backup / rollback / recovery evidence, and explicit approval remain separate official gates.

## 2026-07-08 06:00 Finish Sprint Disclosure Addendum

V3.0 engineering candidate 的工程面驗證可進入 `ready_for_manual_validation`，但人工驗證仍維持 `PENDING_MANUAL_VALIDATION`。本段只補 06:00 finish sprint 的 closeout 披露，不升級為投資有效性、V3/V4 成熟度、production scheduler approval、write-mode evidence 或 lifecycle action。

### 03:33 QA Checkpoint Summary

- `output/automation/version_loop/20260708-0333-milestone-qa-checkpoint.md/json` 記錄 `ENGINEERING_CANDIDATE_PASS`。
- Focused V3 tests 通過：effectiveness dashboard/read model/review scaffold/readiness 共 10 passed。
- Changed Python files py_compile 通過。
- 金融數值邊界測試通過：43 passed。
- V3 sample CLI、readiness sample CLI、review scaffold sample CLI、mypy 與 focused healthcheck tests 均通過。
- P0 缺口不是程式測試失敗，而是 `PENDING_MANUAL_VALIDATION` 與允許路徑下缺少 implementation handoff artifact。

### 04:40 / 05:00 / 05:15 Scheduled Chain Notes

| Time | Source | Result | Closeout interpretation |
|---|---|---|---|
| 04:40 | `D:/Min/Python/Project/FA_Data/output/scheduled/data_update_quick/latest_status.json` | `status=passed` | 市場資料更新至 2026-07-08；`writes_market_data_db=true`，`writes_evidence_db=false`，warnings 為空；8 檔仍為 insufficient-data diagnostics。 |
| 05:00 | `D:/Min/Python/Project/FA_Data/output/scheduled/data_freshness/latest_status.json` | `status=passed` | read-only freshness check 通過；TWSE/TPEX latest daily CSV、SQLite daily prices 與 technical indicators 均到 20260708。 |
| 05:15 | `D:/Min/Python/Project/FA_Data/output/scheduled/evidence_pipeline_dry_run/latest_status.json` | `status=passed` | evidence pipeline 只做 dry-run；`dry_run=true`、`writes_evidence_db=false`、`pipeline_blocking_gaps=[]`、`source_coverage_blocking_gaps=[]`、`pipeline_warnings_count=1865`、scheduler readiness 只到 `ready_for_manual_confirm`。 |

Task Scheduler observation from the finish plan: 04:40、05:00、05:15 三個 scheduled tasks 均回 `Last Result: 0`。這些結果可作工程 closeout 判讀，但不能折抵 official Phase 0 gate。

### Required Caveats Kept Visible

- Manual validation remains `PENDING_MANUAL_VALIDATION`。
- 05:30 read-only morning report artifact 在 repo 與 `$CODEX_HOME/automations` 可見位置皆未找到；06:00 closeout 以既有 scheduled status/report files 產生 replacement handoff。
- `D:/Min/Python/Project/FA_Data/output/scheduled/recommendation_snapshot/latest_status.json` 未存在；若 Workbench 顯示 scheduled recommendation readiness，必須把 scheduled snapshot missing 與人工觀察結果分開揭露。
- Evidence dry-run 使用 `dry_run_transient_decision_desk_snapshot` 作 source coverage basis；這不是 durable official gate credit。
- `source_missing_screening_matrix` 舊 payload gap、`missing_industry_benchmark` residual、sample insufficiency 與 1,865 warnings 仍需可見，不得被轉成 pass。
- Production scheduler remains disabled: `production_scheduler_allowed=false`。

## 2026-07-08 Evening Closeout Handoff

本段給夜間排程使用：今晚目標是把 V3.0 engineering candidate 收成可人工驗證的 closeout package，而不是再開新功能。

### Completed Inputs

- `SCORE_EFFECTIVENESS_AUDIT_ENGINEERING_CANDIDATE_COMPLETE`
- `PHASE_3C_SOURCE_CANDIDATE_DRY_RUN_COMPLETE`
- `V3_0_ENGINEERING_CANDIDATE_CLOSEOUT_TARGET_READY_FOR_TONIGHT`

| Area | Implemented artifacts | Boundary |
|---|---|---|
| Score bucket audit | `app_module/score_effectiveness_dtos.py`, `app_module/score_effectiveness_read_model.py`, `scripts/inspect_score_effectiveness.py` | Read-only raw bucket / forward outcome audit；不改分數、不改 threshold。 |
| Threshold robustness | `app_module/threshold_robustness_read_model.py` | 檢查鄰近參數穩定性；不選最佳參數、不 auto-promote。 |
| Component ablation readiness | `app_module/component_ablation_readiness.py` | 標示 component payload availability；舊 evidence 不回補重算。 |
| ML readiness contract | `app_module/ml_readiness_contract.py`, `scripts/inspect_ml_readiness_contract.py` | Shadow-only feature / label / split / calibration / meta-label / ranking contract；不訓練 production model。 |
| Phase 3C source candidates | `app_module/source_candidate_readiness.py`, `scripts/inspect_source_candidate_readiness.py` | 三大法人 / 信用交易 / TDCC candidate-only diagnostics；不正式 ingestion、不接 `ScoringEngine`。 |

### Tonight Closeout Checklist

- Run focused tests for score effectiveness, threshold robustness, component ablation, ML readiness, and source candidate readiness.
- Run py_compile on changed score/source readiness modules and CLIs.
- Ensure `docs/00_core/PROJECT_SNAPSHOT.md`, `ROADMAP_6M_ENGINEERING.md`, `VERSION_ROADMAP_V2_1_TO_V4_0.md`, `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`, `DEVELOPMENT_ROADMAP.md`, `DOCUMENTATION_INDEX.md`, this QA report, and the score/ML plan/spec all agree on the closeout target.
- Final status may be `ready_for_manual_validation` only if safety boundaries remain visible.

### Still Not Allowed

- Do not enable production scheduler.
- Do not write production evidence DB.
- Do not connect candidate sources to `ScoringEngine`.
- Do not change recommendation thresholds, profile weights, portfolio logic, lifecycle state, or broker behavior.
- Do not claim investment effectiveness, V4 readiness, or production ML readiness.

### Finish Sprint Status

- Engineering candidate closeout: `ready_for_manual_validation`
- Manual validation status: `PENDING_MANUAL_VALIDATION`
- Official effectiveness readiness: `false`
- Evidence DB write in this sprint: `false`
- Production scheduler approval: `false`
- Auto trading / broker order / lifecycle action: `false`

## 2026-07-12 Metric Applicability Follow-up

- 已新增 event-family metric applicability contract，將 Recommendation ranking 類事件標示為 `score_required`。
- `risk_prompt` 與 `decision_quality` 類事件標示為 `score_not_applicable`，不再被 V3 TotalScore 報表誤報為 `event_missing_score_bp`。
- 未知或尚未治理的 family 維持 `score_optional`；不回填 score，也不因此取得 effectiveness credit。
- 此修正只改善資料品質診斷，不改 score、threshold、Profile、lifecycle 或任何 production boundary。
