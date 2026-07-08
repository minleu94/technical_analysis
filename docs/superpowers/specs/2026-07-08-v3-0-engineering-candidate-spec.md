# V3.0 Engineering Candidate Spec

> Automation: `baldr milestone planner 0000`  
> Run date: 2026-07-08  
> Active milestone: V3.0 engineering candidate  
> Decision: `output/automation/version_loop/MORNING_README.md` 與 latest test report 未存在，未看到 `V3_ENGINEERING_CANDIDATE_COMPLETE`；今晚不推 V4/V5，預設目標維持 V3.0 engineering candidate complete。

## 目標

V3.0 engineering candidate 要把既有 V1.5-V2.1 evidence / Workbench / scheduler dry-run 能力，收斂成「Evidence-Validated Decision System」的工程候選：系統能用已累積 evidence 判斷哪些 signal、alert、gate 與 dashboard 值得保留、哪些仍樣本不足、哪些只是資料缺口或流程缺口。

這個 milestone 不宣稱投資有效性，不啟用自動交易，不解除 production scheduler gate，也不讓 AI 或 lifecycle 自動套用 action。人工驗證未完成時，一律標示為 `PENDING_MANUAL_VALIDATION`，但不停止可測、可回滾的工程開發。

## Context Snapshot

- V2.1 / Phase 2 Workbench read-only shell、background evidence feed、read-only Action Items 與 Operating Loop 已完成。
- Phase 0 weekly history 仍為 `0/3`，multi-day dry-run 仍為 `1/3`；historical replay 不可補 Phase 0 official gate。
- Phase 5 production scheduler approval 仍 blocked，`production_scheduler_allowed=false` 必須保留。
- V3.0 的版本定義來自 `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`：Evidence-Validated Decision System，重點是 signal / alert / gate / dashboard 的效果證據、樣本數、confidence、regime / sector 分層與 limitation disclosure。

## Approaches Considered

### A. Read-only evidence maturity layer（建議）

在既有 Evidence Event / Forward Outcome / Live Gap / Signal Decay / Decision Quality / Workbench DTO 上新增 V3 read-only projection、gap classifier、sample sufficiency 與 confidence labels。這個方向最符合現有 architecture：只讀既有資料，先讓早上 closeout 能判斷 V3 candidate 是否完整，不改 scoring、portfolio、scheduler 或 lifecycle。

### B. 直接進 production scheduler approval

此方向不採用。Phase 0 official gate 與 explicit manual approval 尚未完成；把 scheduler approval 當今晚主線會違反 6M Roadmap 與 Manual 的安全邊界。

### C. 直接推 V4/V5 maturity

此方向不採用。V4/V5 需要 V3 已具備可判讀 evidence maturity 與 decision quality maturity；目前沒有 `V3_ENGINEERING_CANDIDATE_COMPLETE` 證據，不能跳級。

## Scope In

- V3 effectiveness read model / DTO：彙總 event family、signal、alert、gate、dashboard source 的 sample count、forward outcome maturity、quality、warnings 與 limitation。
- Gap classifier：把阻塞原因分成 source gap、payload gap、forward outcome gap、sample insufficiency、live gap missing、manual validation pending、accepted residual。
- Sample sufficiency / confidence labels：以明確門檻標示 `insufficient_sample`、`directional_only`、`review_ready`、`needs_manual_validation`，避免把不足樣本包裝成結論。
- Read-only dashboard / disclosure：可放在 Evidence Review / Workbench drill-down；只顯示 V3 evidence maturity，不寫 DB、不觸發 replay、不啟用 scheduler。
- Signal / alert / gate effectiveness review scaffold：建立人工覆盤 scaffold，列出 recommendation、watchlist trigger、portfolio alert、risk prompt、why-not、liquidity gate、screening matrix 等候選項的 evidence status。
- Manual validation report：輸出可給早上 closeout 使用的報告，未完成項標示 `PENDING_MANUAL_VALIDATION`。

## Scope Out

- 不改 `ScoringEngine`、推薦分數、回測績效、Portfolio PnL、持倉或 Strategy Lifecycle 狀態。
- 不寫正式 evidence DB，不建立 migration，不啟用 production scheduler。
- 不自動 demote / retire / promote strategy。
- 不下單、不串 broker、不建立 production order。
- 不用 historical replay、fixture、單次 smoke 或手動改表取代 Phase 0 official gate。
- 不宣稱任一訊號、推薦、alert 或 gate 具有投資有效性。

## Proposed Architecture

```text
Existing read-only evidence sources
  Evidence events / outcomes
  Forward summary read model
  Live vs Research Gap observations
  Signal Decay observations
  Decision Quality reviews
  Workbench / Pre-V2 readiness payloads
        |
        v
V3EffectivenessReadModel
        |
        +--> V3GapClassifier
        +--> SampleSufficiencyPolicy
        +--> ConfidenceLabelPolicy
        |
        v
V3EffectivenessDashboardDTO
        |
        +--> inspect_v3_evidence_effectiveness.py
        +--> Evidence Review / Workbench read-only disclosure
        +--> V3 manual validation report
```

所有元件都位於 application / presentation boundary。UI 只讀 DTO；CLI 只讀 explicit DB / report / summary path；任何 missing DB / missing table 都回 diagnostics，不建立 schema。

## Candidate Data Model

- `V3EffectivenessSlice`
  - `slice_id`
  - `event_family`
  - `event_type`
  - `source_type`
  - `dashboard_surface`
  - `decision_date_range`
  - `sample_count`
  - `ready_outcome_count`
  - `pending_outcome_count`
  - `missing_outcome_count`
  - `benchmark_coverage_bp`
  - `industry_coverage_bp`
  - `quality`
  - `warnings`
  - `limitations`

- `V3GapClassification`
  - `gap_code`
  - `severity`
  - `classification`
  - `source_trace`
  - `closeout_requirement`
  - `manual_validation_status`

- `SampleSufficiencyLabel`
  - `insufficient_sample`
  - `directional_only`
  - `review_ready`
  - `accepted_residual`

- `ConfidenceLabel`
  - `none`
  - `low`
  - `medium`
  - `needs_manual_validation`

Labels 是 disclosure，不是投資信號。`confidence=medium` 只代表 engineering review 可讀性較高，不代表勝率、報酬或交易品質。

## Milestone Backlog

1. V3 effectiveness read model + gap classifier
2. Read-only dashboard / CLI disclosure surface
3. Sample sufficiency + signal / alert / gate effectiveness review scaffold
4. Manual validation report + candidate readiness inspector

每個任務都必須可測、可回滾，且不得寫正式資料。UI 改動若發生，必須同步 `APPLICATION_MANUAL.md` 與 UI gates。

## Validation Strategy

- Unit tests for DTO serialization, classifier determinism, sample sufficiency labels and no-write boundary.
- CLI tests for missing DB / missing table / sample payload / markdown and JSON output.
- Import-boundary tests blocking scoring, portfolio mutation, scheduler registration and broker/order APIs.
- If Qt UI is touched:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
  - `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
  - `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`
- Always run syntax checks on changed Python files.
- Financial boundary / no-look-ahead self-check is required for any task that touches strategy, recommendation, backtest, portfolio or benchmark semantics. This plan is read-only projection work and must remain outside core calculation mutation.

## Completion Criteria

V3.0 engineering candidate can be marked as engineering complete only when:

- V3 read model can produce deterministic JSON / Markdown from read-only sources.
- Gap classifier maps every candidate source gap to blocking / warning / accepted residual / `PENDING_MANUAL_VALIDATION`.
- Dashboard / CLI clearly exposes sample sufficiency and confidence labels.
- Signal / alert / gate review scaffold exists and does not auto-apply lifecycle actions.
- Manual validation report exists with unresolved human checks marked `PENDING_MANUAL_VALIDATION`.
- Read-only / no scheduler / no trading boundaries are tested.
- Core docs are updated only after implementation changes user-facing behavior or current roadmap status.

## Manual Validation Policy

Manual validation is required for V3 closeout, but it must be represented as structured state:

- `PENDING_MANUAL_VALIDATION`: human review not yet done; engineering may continue.
- `MANUAL_VALIDATION_READY`: report has enough evidence for human review.
- `MANUAL_VALIDATION_ACCEPTED`: human explicitly accepted.
- `MANUAL_VALIDATION_REJECTED`: human rejected and blockers must be fixed.

Tonight's output should leave manual validation as `PENDING_MANUAL_VALIDATION`.
