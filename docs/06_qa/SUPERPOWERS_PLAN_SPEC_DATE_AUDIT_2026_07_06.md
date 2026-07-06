# Superpowers Plan / Spec Date Audit - 2026-07-06

## Purpose

本紀錄用來釐清 `docs/superpowers/plans/` 與 `docs/superpowers/specs/` 中 2026-07-06 之後的檔名日期：這些日期多數是 Post-V1 milestone sequencing label，不是實際完成日、也不是 roadmap 權威日期。

目前完成狀態仍以 `PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、`VERSION_ROADMAP_V1_1_TO_V2_0.md`、QA closeout 與 Git commit 為準。

## Audit Inputs

- Git log for related plan/spec files.
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/06_qa/*2026_07_*.md`

## Findings

| Milestone file family | Git evidence | Closeout / status evidence | Current interpretation | Rename needed |
|---|---:|---|---|---|
| `2026-07-06-post-v1-evidence-scheduler-dry-run` | Added by `2c9888a` on 2026-07-01 | `POST_V1_EVIDENCE_SCHEDULER_DRY_RUN_QA_2026_07_06.md` | Evidence Pipeline Runner dry-run v1 已完成；production scheduler 未啟用。 | No |
| `2026-07-06-historical-evidence-replay` | Added by `54905a6` on 2026-07-06; plan closeout `6d5f0c1` | `POST_V1_HISTORICAL_EVIDENCE_REPLAY_QA_2026_07_06.md`; reference fix `6eb7f8e`; docs sync `4fca0d4` | Historical replay v1 與 reference return quality audit 已完成，可作 V2.0 Phase 1 simulated evidence input。 | No |
| `2026-07-06-v1-9-read-only-agent-mcp` | Added by `0c6bc3f` on 2026-07-05 | `V1_9_READ_ONLY_AGENT_MCP_CLOSEOUT_2026_07_06.md` | V1.9 read-only evidence access 已完成；仍不可寫 DB、改策略、下單。 | No |
| `2026-07-07-post-v1-production-scheduler-approval` | Added by `cdb94d1` on 2026-07-01 | `POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md` | Approval checklist / working-copy smoke / readiness evaluator 已建立；這不是 production scheduler approval granted。 | No |
| `2026-07-08-post-v1-live-research-gap-linkage` | Added by `c3b93a4` on 2026-07-01 | `POST_V1_LIVE_RESEARCH_GAP_LINKAGE_QA_2026_07_08.md` | Live vs Research Gap linkage v1 已完成；屬 read-only / research attribution support。 | No |
| `2026-07-09-post-v1-signal-decay-monitor` | Added by `c9f32da` on 2026-07-01 | `POST_V1_SIGNAL_DECAY_MONITOR_QA_2026_07_09.md` | Signal Decay Monitor v1 已完成；不自動套用 lifecycle action。 | No |
| `2026-07-10-post-v1-decision-quality-review` | Added by `c3eb3c9` on 2026-07-01 | `POST_V1_DECISION_QUALITY_REVIEW_QA_2026_07_10.md` | Decision Quality Review v1 已完成；是流程覆盤，不改推薦或交易決策。 | No |
| `2026-07-11-post-v1-evidence-review-dashboards` | Added by `a55105a` on 2026-07-01 | `POST_V1_EVIDENCE_REVIEW_DASHBOARDS_QA_2026_07_11.md` | Evidence Review read-only dashboard pack 已完成；manual UI smoke checklist 仍是獨立觀察項。 | No |
| `POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md` | QA checklist only | Manual checklist table remains fillable | 這是人工 UI smoke checklist，不等於所有真實使用觀察已完成。 | No |
| `POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md` | QA record scaffold | Current recorded dry-run count remains below approval threshold | 這是 living record / scaffold；multi-day dry-run gate 尚未完成。 | No |
| `POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md` | SOP only | Explicitly states production scheduler not enabled | 這是 approval SOP，不是 approval result。 | No |

## V2.0 Plan / Spec Check

`2026-07-06-v2-0-unified-decision-workbench.md` and `2026-07-06-v2-0-unified-decision-workbench-design.md` are current as of commit `4fca0d4`.

They now include:

- Phase 1 first screen = 今日任務中控台。
- Evidence mode = drill-down.
- Daily Checklist = daily process checklist.
- Optional `_reference_fix` historical replay JSON summary input.
- `workbench_replay_summary.py` adapter task.
- `--replay-summary-json` CLI boundary.
- Explicit warning that Phase 1 must not scan the replay DB and must not treat replay as production readiness, strategy validity, weekly history, or scheduler approval.

## Rename Decision

Do not rename the future-dated plan/spec files.

Rationale:

- `DOCUMENTATION_INDEX.md`, `PROJECT_SNAPSHOT.md`, and `DEVELOPMENT_ROADMAP.md` already state that these filenames are milestone labels.
- Renaming would create broad cross-link churn with little practical benefit.
- Git history and QA closeouts already provide better completion-date evidence than filenames.
- A dedicated audit record is less disruptive and clearer for future agents.

## Historical Replay Decision

Historical replay analysis is complete enough to unblock V2.0 Phase 1 read-only workbench implementation.

Allowed use:

- Use `_reference_fix` JSON / report as simulated evidence quality context.
- Surface benchmark availability, industry payload gap, screening matrix payload gap, source coverage gap, event family coverage, and outcome maturity.
- Keep it in Evidence mode / quality boundary context.

Not allowed:

- Do not treat replay as investment validity proof.
- Do not treat replay as Phase 0 weekly history completion.
- Do not treat replay as multi-day dry-run completion.
- Do not use it to approve production scheduler or write-mode evidence pipeline.

## Next Action

V2.0 may start now at Phase 1 read-only prototype scope.

Parallel background work should continue:

- true weekly evidence operations + history accumulation;
- multi-day dry-run record accumulation;
- source payload gap analysis, especially `source_missing_screening_matrix`;
- industry / sector payload quality improvement for future recommendations;
- real workflow samples for watchlist / portfolio evidence.
