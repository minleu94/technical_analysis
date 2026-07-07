# V2.2 Phase 5 Approval Rehearsal Package - 2026-07-07

> 目的：在不等待更多真實時間資料的前提下，先把 Phase 5 production evidence scheduler approval 所需的審核材料做成 read-only rehearsal package。
> 邊界：本文件是 simulated approval rehearsal，不是 official approval，不啟用 scheduler，不寫 DB，不改 lifecycle。

## Executive Summary

Historical Evidence Replay reference-fix summary 已可支援 Phase 0-5 的工程演練：

| Field | Value |
|---|---|
| replay artifact | `historical_replay_2026-01-06_2026-07-06_reference_fix.json` |
| replay_run_id | `hre_eb11c53d4986` |
| replay_mode | `historical_replay` |
| source_label | `simulated_scheduler` |
| replay range | `2026-01-06` to `2026-07-06` |
| replay days | `118` |
| events seen | `118056` |
| outcomes created | `472224` |
| simulated overall status | `simulated_ready` |
| simulated Phase 5 status | `simulated_ready` |
| official Phase 5 status | `blocked` |
| production_scheduler_allowed | `false` |

判讀重點：

- replay 可以先完成 approval package rehearsal。
- replay 不計入 official weekly history。
- replay 不計入 official multi-day dry-run record。
- scheduled dry-run raw status 不等於人工 reviewed multi-day record。
- official Phase 5 仍必須等待真實 weekly / multi-day / manual approval gate。

## Official Completion Waiting List

下列項目不可用 historical replay、fixture、manual edit 或 raw scheduled output 標為已完成：

| 項目 | 目前狀態 | 標為已完成前必須等待 / 取得 |
|---|---|---|
| Phase 0 weekly history | `0/3` | 至少 3 筆不同週期、人工確認後保存到 working-copy DB 的 weekly evidence operations history。 |
| Phase 0 multi-day dry-run | `1/3` | 至少 3 個真實交易日的 freshness、scheduled dry-run、working-copy confirm smoke、Evidence Review / Workbench dashboard review 與人工 notes。 |
| Manual review note rhythm | not established | 真實操作日逐日留下可比較 manual notes；notes 不得包含買賣、倉位或 lifecycle action。 |
| Action item rhythm | read-only UI only | 真實 action item review / dismissed / follow-up 節奏；目前 Action Items 只是 DTO-derived manual queue。 |
| Phase 3 data source acceptance | candidate-only | 每個 source 的 `source_id`、`available_date`、`quality`、`missing_policy` 與 diagnostics dry-run 結果。 |
| Phase 4 execution realism acceptance | research-only candidate | spread、odd-lot、locked limit、gap execution、unfilled reason 等模型在 research-only sandbox 的驗證結果。 |
| Phase 5 scheduler approval | blocked | Phase 0 gate 達標、working-copy confirm smoke idempotent、source gaps 可接受、backup / rollback / recovery 完成、explicit manual approval。 |

## Simulated Phase Package

| Phase | Rehearsal output | Current simulated status | Official status |
|---|---|---|---|
| Phase 0 | observability summary、replay / scheduled dry-run source trace、official blocker list | `simulated_ready` | `official_gate_not_satisfied` |
| Phase 1 | Workbench evidence disclosure input、degraded-state wording、data quality boundary | `simulated_ready` | `official_gate_not_satisfied` |
| Phase 2 | daily first-look / manual queue / weekly / multi-day / manual note / scheduler gate rhythm | `simulated_ready` | `official_gate_not_satisfied` |
| Phase 3 | candidate source backlog draft | `simulated_ready` | `official_gate_not_satisfied` |
| Phase 4 | execution realism candidate backlog draft | `simulated_ready` | `official_gate_not_satisfied` |
| Phase 5 | scheduler approval checklist / rollback checklist / risk register rehearsal | `simulated_ready` | `official_gate_not_satisfied` |

## Data Source Candidate Backlog Draft

| Candidate | Gap reason | Required policy before official acceptance | Validation path |
|---|---|---|---|
| Screening matrix persistence | historical replay still carries `source_missing_screening_matrix` for old recommendation payloads | old payloads remain immutable; new payloads must include pass / fail / degraded / skipped / missing rows | compare new recommendation result coverage and source coverage diagnostics over real operating days |
| Why Not / Liquidity payloads | old recommendation payloads may miss exclusion detail | payload missing is warning / dry-run-only unless explicitly required source is requested | verify new saved recommendation results preserve exclusion payloads |
| Daily Decision durable snapshots | formal DB still has no active snapshot rows in current gate check | snapshot sections must carry quality / as_of / source trace | run source coverage against working-copy DB and verify watchlist / portfolio / risk sections |
| Corporate action / adjusted price policy | replay uses current governed raw price boundary | available-date-safe adjustment policy required before decision features | candidate-only diagnostics; no ScoringEngine integration |
| Microstructure restriction metadata | execution realism requires restriction context | source capability, available_date, missing_policy, license/rate note required | research-only sandbox before portfolio or backtest semantics change |

## Execution Realism Candidate Backlog Draft

| Candidate | Why it matters | Current boundary | Validation path |
|---|---|---|---|
| Bid-ask spread assumption | close-to-close return may overstate executable result | not applied to official PnL | research-only simulation with explicit bps assumptions |
| Odd-lot / lot residual | allocation may leave uninvested cash or unfilled target weight | V1.8 uses lot sizing diagnostics only | compare target vs actual allocation weight in sandbox |
| Limit-up / limit-down locked execution | close price may be unavailable to execute | no broker/order simulation | mark locked execution as rejected / partially filled candidate |
| Gap actual execution model | next open can differ materially from decision close | gap risk is diagnostic, not PnL mutation | validate gap severity and execution assumption separately |
| Unfilled / partially filled reason taxonomy | approval needs explainable execution limits | virtual trace is research-only | enumerate rejected / partial reasons before any broker integration |

## Scheduler Approval Rehearsal Checklist

This checklist is ready for rehearsal now, but every official checkbox stays blocked until true data gates are met.

| Checklist | Rehearsal status | Official status |
|---|---|---|
| Confirm evidence DB path and write target | draft ready | blocked until approval uses explicit working-copy / production path policy |
| Verify latest Pre-V2 readiness output | ready to inspect | blocked by weekly `0/3` and multi-day `1/3` |
| Verify working-copy confirm smoke repeat=2 | existing prior smoke evidence available | must be rerun on current candidate approval day |
| Verify source gaps | ready to summarize | blocked if current source coverage has blocking gaps |
| Verify scheduled dry-run history | raw reports available | blocked until reviewed multi-day record reaches gate |
| Backup formal DB before write-mode | checklist draft ready | not executed in this rehearsal |
| Rollback and recovery steps | checklist draft ready | must be tested / signed before approval |
| Manual approval | form draft ready | no approval recorded |
| Enable production evidence scheduler | not allowed | blocked |

## True-Data Runbook

When real data is available, use this sequence. Do not backfill historical replay rows into official gate records.

1. Run read-only Pre-V2 readiness:
   ```powershell
   .\.venv\Scripts\python.exe scripts\inspect_pre_v2_readiness.py --db-path <working-copy-db> --decision-date <YYYY-MM-DD> --multi-day-record-path docs\06_qa\POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md --json-output
   ```
2. Inspect simulated progress for comparison only:
   ```powershell
   .\.venv\Scripts\python.exe scripts\inspect_simulated_phase_progress.py --db-path <working-copy-db> --replay-summary-path D:\Min\Python\Project\FA_Data\output\evidence_pipeline\historical_replay_reference_fix_20260706\historical_replay_2026-01-06_2026-07-06_reference_fix.json --scheduled-output-root D:\Min\Python\Project\FA_Data\output\scheduled\evidence_pipeline_dry_run --decision-date <YYYY-MM-DD> --json-output
   ```
3. For weekly history, save only after human review and explicit approval on a working-copy DB.
4. For multi-day dry-run, record only a real operating day with freshness, dry-run status, working-copy confirm smoke, dashboard review, and manual notes.
5. Re-run scheduler readiness evaluator after the official gates are satisfied.
6. Keep production evidence scheduler disabled until explicit manual approval is recorded.

## UI Readability Follow-up

This package also exposes a product design issue: Market Watch, Daily Decision Desk, Evidence Review, Workbench and Portfolio drill-down now overlap in user intent. The next discussion should be an information architecture pass, not another evidence gate change.

Initial framing:

- Workbench should be the first operational screen for "what do I need to look at today?"
- Market Watch should remain market context and discovery.
- Daily Decision Desk should become an explainable source panel or drill-down, not a competing home screen.
- Evidence Review should be an audit / QA workspace, not daily first-look.
- Portfolio should remain position and thesis follow-up.

No UI change is made by this package.

## Decision

The system is ready for Phase 5 approval rehearsal, not official Phase 5 approval. The next official completion labels must wait for real weekly history, real multi-day dry-run records, manual review rhythm, accepted source gaps, backup / rollback / recovery evidence and explicit approval.
