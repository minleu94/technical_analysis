# Post-V1 Evidence Source Persistence Design

> 日期：2026-07-04  
> 範圍：Durable Daily Decision Desk snapshot、Evidence source coverage inspection、Recommendation exclusion payload optional persistence  
> 狀態：v1 完成；Why Not / Liquidity payload 為 partial，取決於 Recommendation result 是否已保存 payload

## 目標

本增量補齊 Post-V1 evidence pipeline 的來源持久化缺口，讓未來 scheduler dry-run design 與 Forward Performance Dashboard read-only UI 可以讀取可靠資料來源。

本設計不新增 scheduler、不新增 dashboard UI、不修改 `ScoringEngine`、不改推薦權重、不修改 portfolio position，也不把任何 evidence summary 包裝成交易建議。

## 新增資料來源

### Daily Decision Desk Snapshot Repository

新增 `DecisionDeskSnapshotRepository`，以 SQLite 保存 append-only / idempotent Daily Decision Desk snapshot。

保存欄位包含：

- `snapshot_id`
- `snapshot_hash`
- `decision_date`
- `as_of_date`
- `source_version`
- `builder_version`
- `data_quality`
- `warnings_json`
- `market_regime_json`
- `market_breadth_json`
- `sector_rotation_json`
- `relative_strength_liquidity_json`
- `watchlist_trigger_json`
- `portfolio_alert_json`
- `risk_prompt_json`
- `fundamental_diagnostics_json`
- `metadata_json`
- `snapshot_status`
- `created_at`

`snapshot_hash` 使用 deterministic JSON content hash。`generated_at` 會保存於 metadata，但不進入 content hash，避免同內容重跑時因時間戳造成重複版本。

同一 `snapshot_hash` idempotent；同一 `decision_date` 若保存不同 hash，舊 active snapshot 會標記為 `superseded`，新 snapshot 成為 active。

### Capture CLI

新增 `scripts/capture_decision_desk_snapshot.py`：

```powershell
python scripts/capture_decision_desk_snapshot.py --decision-date 2026-06-30 --dry-run
python scripts/capture_decision_desk_snapshot.py --decision-date 2026-06-30 --confirm
```

CLI 預設 dry-run，只有 `--confirm` 寫入。snapshot 只從 service builder 取得，不讀 UI state。section 不可用時保存 `missing` / `degraded` 與 warnings，不補空中性 payload。

新增 `scripts/inspect_decision_desk_snapshots.py` 用於唯讀檢視 snapshot count、latest snapshot 與 snapshot metadata。

## Evidence Capture Wiring

`scripts/capture_evidence_events.py` 現在會在 CLI 中查找 durable Daily Decision Desk snapshot，並以該 snapshot 提供：

- `watchlist-trigger`
- `portfolio-alert`
- `risk-prompt`

若 snapshot 不存在，CLI 回傳 `source_missing_snapshot` diagnostic，提示先執行 `capture_decision_desk_snapshot.py`，不 fallback 到 UI，也不偽造 event。

`--source all` 順序仍先處理 `recommendation` persisted source，再處理 Daily Decision Desk snapshot sources。

## Recommendation Exclusion Payload

`RecommendationResultDTO` 新增 backward-compatible optional fields：

- `excluded_candidates_json`
- `why_not_payload_json`
- `liquidity_gate_payload_json`
- `exclusion_quality`
- `exclusion_warnings_json`

舊 JSON 缺欄位仍可讀，預設為空 payload。Importer 不重算 Why Not / Liquidity Gate，只消費已保存 payload。

有 payload 時產生：

- `WHY_NOT_EXCLUDED`
- `LIQUIDITY_GATE_EXCLUDED`

metadata 保存：

- `exclusion_reason_codes`
- `threshold_name`
- `observed_value`
- `required_value`
- `quality`
- `warnings`
- `source_result_id`

缺 payload 時維持 `source_missing_exclusion_payload` diagnostic，不偽造排除事件。

## Source Coverage Inspection

新增 `scripts/inspect_evidence_source_coverage.py`，輸出：

- `recommendation_persisted_available`
- `recommendation_exclusion_payload_available`
- `decision_desk_snapshots_count`
- `latest_decision_desk_snapshot_date`
- `watchlist_trigger_capture_ready`
- `portfolio_alert_capture_ready`
- `risk_prompt_capture_ready`
- `why_not_capture_ready`
- `liquidity_gate_capture_ready`
- `scheduler_readiness`
- `blocking_gaps`

`scheduler_readiness` 僅允許：

- `not_ready`
- `dry_run_only`
- `ready_for_design`

本增量不得輸出 `production_ready`。

## Evidence 邊界

本增量能累積更多來源事件，但仍不能證明任何訊號、警示、排除規則或策略生命週期判斷具備投資有效性。Forward outcomes 仍是 close-to-close research basis，不是可執行績效。

## 不做事項

- 不建立 scheduler。
- 不建立 dashboard UI。
- 不從 UI state 擷取資料。
- 不在 UI 層重算 domain logic。
- 不改 ScoringEngine 或推薦權重。
- 不修改 portfolio position。
- 不導入 ML。
- 不自動 promote / demote / retire。
