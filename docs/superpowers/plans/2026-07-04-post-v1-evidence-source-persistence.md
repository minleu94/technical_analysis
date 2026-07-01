# Post-V1 Evidence Source Persistence Plan

> 日期：2026-07-04  
> 對應設計：`docs/superpowers/specs/2026-07-04-post-v1-evidence-source-persistence-design.md`

## Phase A：Durable Daily Decision Desk Snapshot Repository

- [x] 新增 `app_module/decision_desk_snapshot_storage_dtos.py`
- [x] 新增 `app_module/decision_desk_snapshot_repository.py`
- [x] 支援 `save_snapshot`、`get_snapshot`、`list_snapshots`、`find_by_decision_date`、`latest_before_or_on`、`archive`
- [x] 使用 deterministic JSON hash
- [x] 同 hash idempotent
- [x] 同 decision date 新 hash 會 supersede 舊 active snapshot
- [x] 保存 quality / warnings / degraded / missing section payload
- [x] 新增 capture / inspect snapshot CLI

## Phase B：Evidence Capture Durable Provider Wiring

- [x] `capture_evidence_events.py` 查找 durable Daily Decision Desk snapshot
- [x] `watchlist-trigger` 可從 durable snapshot 匯入
- [x] `portfolio-alert` 可從 durable snapshot 匯入
- [x] `risk-prompt` 可從 durable snapshot 匯入
- [x] 缺 snapshot 回 `source_missing_snapshot`
- [x] 不 fallback 到 UI

## Phase C：Recommendation Exclusion Payload

- [x] `RecommendationResultDTO` 新增 optional exclusion payload fields
- [x] 舊 JSON backward compatible
- [x] Recommendation importer 有 payload 時產生 Why Not / Liquidity exclusion events
- [x] 缺 payload 時只 diagnostic，不偽造事件
- [x] 不重算 Why Not / Liquidity Gate

## Phase D：Source Coverage CLI

- [x] 新增 `scripts/inspect_evidence_source_coverage.py`
- [x] 輸出 recommendation / exclusion / DDD snapshot source coverage
- [x] `scheduler_readiness` 僅允許 `not_ready` / `dry_run_only` / `ready_for_design`
- [x] 不輸出 production-ready

## Phase E：Tests / Docs / QA

- [x] 新增 `tests/test_decision_desk_snapshot_repository.py`
- [x] 新增 `tests/test_capture_decision_desk_snapshot_cli.py`
- [x] 新增 `tests/test_decision_desk_snapshot_evidence_importer.py`
- [x] 新增 `tests/test_recommendation_exclusion_payload.py`
- [x] 新增 `tests/test_evidence_source_coverage_cli.py`
- [x] 更新既有 capture CLI 測試的 diagnostic expectation
- [ ] 執行完整驗證命令並更新 QA 結果
- [ ] 更新核心文件

## 剩餘 Blocking Gaps

- Forward Performance Dashboard read-only UI 尚未建立。
- Scheduler 尚未設計；目前最多只能 `ready_for_design`。
- Why Not / Liquidity historical payload 仍取決於 Recommendation result 是否在當時保存 payload；舊結果不會回補。
- Live vs Research Gap event linkage 尚未完成。
- Signal Decay Monitor 尚未完成。
