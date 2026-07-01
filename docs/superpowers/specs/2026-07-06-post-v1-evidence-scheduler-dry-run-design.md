# Post-V1 Evidence Scheduler Dry-run Design

日期：2026-07-06

## Scope

本輪建立 Evidence Pipeline Runner v1，定位為手動執行的 dry-run / working-copy confirm 工具，不是正式 scheduler。它把 Round 1-5 已完成的 source coverage、Daily Decision Desk snapshot capture、evidence event capture、forward outcome calculation、Forward Performance Read Model summary 與 diagnostics report 串成同一個可審核流程。

## Non Goals

- 不建立 Windows Task Scheduler / cron / background job。
- 不預設 `--confirm`，不自動寫正式 DB。
- 不修改 `ScoringEngine`、推薦權重、portfolio position 或 strategy lifecycle state。
- 不導入 ML，不自動 promote / demote / retire。
- 不把 close-to-close forward return 描述為實盤可執行績效。
- 不輸出任何買賣建議、目標價、合理價或高信心交易語氣。

## Architecture

新增 `app_module/evidence_pipeline_runner.py` 作為 application service，`app_module/evidence_pipeline_runner_dtos.py` 定義 request / summary / step / diagnostic DTO。CLI `scripts/run_evidence_pipeline.py` 只負責參數解析、config 建立與輸出 JSON，不直接操作 UI state 或重算 domain logic。

Runner 依序執行：

1. `source_coverage_check`
2. `capture_decision_desk_snapshot`
3. `capture_evidence_events`
4. `calculate_forward_outcomes`
5. `summarize_forward_performance`
6. `write_diagnostics_report`

`capture_evidence_events` 使用既有 `EvidenceCaptureService` 與 importer；Daily Decision Desk 類來源只讀 durable snapshot。`calculate_forward_outcomes` 使用 `ForwardPerformanceService`，dry-run 時不 upsert outcome。`summarize_forward_performance` 使用 `ForwardPerformanceReadModel`，UI 不參與。

## Confirm Gates

- CLI 預設 dry-run。
- `--dry-run` 與 `--confirm` 互斥。
- `--confirm` 必須提供 explicit `--db-path`。
- 疑似 production/default DB 的 confirm 必須再提供 `--allow-production-db-confirm`；本輪測試不使用正式 DB。
- 單一 source 缺資料只會造成 degraded / diagnostic，不偽造 event。

## Readiness

Runner summary 的 readiness 只允許：

- `not_ready`
- `dry_run_only`
- `ready_for_design`
- `ready_for_manual_confirm`

本輪永遠不輸出 `production_ready`。`ready_for_manual_confirm` 只代表 dry-run / working-copy confirm 流程已可被人工審核，不代表正式排程可啟用。

## Production Scheduler Minimum Bar

正式排程之前至少需要：

1. dry-run runner 多次穩定。
2. source coverage 沒有 blocking gaps。
3. Forward Evidence dashboard 可讀。
4. confirm mode 在 working-copy DB 通過。
5. diagnostics report 可人工審核。
6. 人工批准 production scheduler 設計。

未來 production schedule 應排在資料更新完成後，且仍應先 dry-run，再由人工確認；不能直接 confirm。

## Evidence Boundary

Runner 只能累積與檢查 research evidence。Close-to-close forward return 是研究基準，不是可執行實盤績效。任何 event type 的 sample / return / excess return 都不能被解讀為訊號有效性證明。
