# Post-V1 Production Scheduler Approval Design

日期：2026-07-07

## Purpose

本設計建立 production scheduler 之前的人工批准框架。Round 7 只新增 working-copy DB smoke、readiness evaluator 與 approval checklist，不啟用正式排程。

## Safety Boundary

- 不建立 production scheduler。
- 不建立 Windows Task Scheduler、cron 或 background job。
- 不預設 confirm。
- 不自動寫 production DB。
- 不修改 scoring、推薦權重、portfolio position 或 lifecycle state。
- 不宣稱 alpha、實盤績效或任一 event type 有效。

## Working-copy Smoke

`scripts/smoke_evidence_pipeline_working_copy.py` 會：

1. 讀取 `--source-db-path`。
2. 若 `--working-copy-db-path` 不存在，使用 `shutil.copy2` 複製 source DB。
3. 僅對 working-copy DB 執行 confirm runner。
4. 預設 repeat 至少 2 次，以檢查 event idempotency 與 outcome upsert stability。
5. 寫出 smoke summary 與 diagnostics report。

Source DB 只讀；working-copy DB 不可與 source DB 相同，也不可指向 production DB path。

## Readiness Evaluator

`app_module/evidence_scheduler_readiness.py` 與 `scripts/evaluate_evidence_scheduler_readiness.py` 輸出：

- readiness
- blocking_gaps
- warnings
- required_manual_checks
- latest_smoke_status
- source_coverage_status
- dashboard_available
- working_copy_confirm_passed
- production_scheduler_allowed

`production_scheduler_allowed` 在本輪固定為 false。Readiness 最高只到 `ready_for_manual_confirm`。

## Approval Checklist

Checklist 要求 preconditions、manual approval steps、future schedule design、rollback / recovery 與 explicit non-goals。它只描述批准門檻，不包含任何正式排程啟用動作。

## Evidence Boundary

Working-copy smoke 證明的是 pipeline 可以在複本 DB 上被審核與重跑；它不能證明訊號有效，也不能把 close-to-close forward return 解讀為可執行績效。
