# Post-V1 Evidence Event Store Design

> **日期**：2026-07-01
> **範圍**：Evidence Event Store v1 + Forward Outcome Calculator v1。
> **狀態**：第一增量設計。此文件定義 evidence/research observation 邊界，不宣稱投資有效性。

## 問題定義

baldr V1 已完成四個產品閉環、Strategy Lifecycle / Portfolio Feedback v1 與 release QA gate。這只代表工程入口、資料契約、操作流程與交付驗證已可用，不代表 Watchlist Trigger、Recommendation、Why Not / Liquidity Gate、Portfolio Alert 或 lifecycle 判斷已被證明具備投資有效性。

Post-V1 主線要補的是 evidence-driven 驗證層：先保存當時系統判斷，再用決策日之後的交易日價格計算 forward outcome，讓後續 dashboard / review 能回答「這類事件後來是否有可觀察 evidence」。

## 非目標

- 不修改 `ScoringEngine`。
- 不修改推薦權重或 profile scoring。
- 不導入 ML。
- 不做 UI dashboard。
- 不自動 promote / demote / retire。
- 不自動修改 portfolio position。
- 不把 close-to-close forward return 稱為實盤績效。
- 不輸出買進、賣出、目標價、合理價或高信心交易語言。

## Event Schema

`evidence_events` 是 append-only table，用來保存「當時系統發生過什麼判斷」。

最低欄位：

```text
event_id TEXT PRIMARY KEY
event_hash TEXT UNIQUE NOT NULL
event_date TEXT NOT NULL
decision_date TEXT NOT NULL
symbol TEXT
event_type TEXT NOT NULL
event_family TEXT NOT NULL
source_type TEXT NOT NULL
source_id TEXT NOT NULL DEFAULT ''
source_snapshot_id TEXT NOT NULL DEFAULT ''
strategy_version_id TEXT NOT NULL DEFAULT ''
profile_id TEXT NOT NULL DEFAULT ''
run_id TEXT NOT NULL DEFAULT ''
reason_codes_json TEXT NOT NULL DEFAULT '[]'
why_not_codes_json TEXT NOT NULL DEFAULT '[]'
risk_codes_json TEXT NOT NULL DEFAULT '[]'
score_bp INTEGER
score_percentile_bp INTEGER
regime TEXT
sector TEXT
concept_basket TEXT
liquidity_state TEXT
data_quality TEXT NOT NULL
warnings_json TEXT NOT NULL DEFAULT '[]'
as_of_date TEXT NOT NULL
available_date TEXT NOT NULL
source_version TEXT NOT NULL DEFAULT ''
cost_model_id TEXT NOT NULL DEFAULT ''
benchmark_id TEXT
industry_benchmark_id TEXT
metadata_json TEXT NOT NULL DEFAULT '{}'
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
```

`event_hash` 由 deterministic JSON payload 產生，至少覆蓋 `event_date`、`decision_date`、`symbol`、`event_type`、`source_type`、`source_id`、`source_snapshot_id`、`reason_codes_json`、`why_not_codes_json`、`risk_codes_json`、`strategy_version_id`、`profile_id`、`run_id`。不同 source 若代表不同判斷，不應被錯誤合併。

## Outcome Schema

`evidence_outcomes` 保存事件後不同 forward windows 的結果。

最低欄位：

```text
outcome_id TEXT PRIMARY KEY
event_id TEXT NOT NULL
window_days INTEGER NOT NULL
window_type TEXT NOT NULL DEFAULT 'trading_days'
return_basis TEXT NOT NULL DEFAULT 'close_to_close_event_date'
event_price_date TEXT
event_close TEXT
outcome_price_date TEXT
outcome_close TEXT
forward_return_bp INTEGER
benchmark_return_bp INTEGER
benchmark_excess_bp INTEGER
industry_return_bp INTEGER
industry_excess_bp INTEGER
max_adverse_excursion_bp INTEGER
max_favorable_excursion_bp INTEGER
tradable_flag INTEGER
limit_up_down_flag INTEGER
suspended_flag INTEGER
liquidity_cost_bp INTEGER
outcome_status TEXT NOT NULL
data_quality TEXT NOT NULL
warnings_json TEXT NOT NULL DEFAULT '[]'
calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
data_as_of_date TEXT
metadata_json TEXT NOT NULL DEFAULT '{}'
UNIQUE(event_id, window_days, return_basis)
```

v1 只支援 `window_type = trading_days` 與 `return_basis = close_to_close_event_date`。結果是 research evidence，不是可執行績效。

## Source Integration Plan

第一增量只建立 event store、forward calculator 與 inspection CLI。Recommendation / Daily Decision Desk importer 留到下一增量，除非 source 已有持久化 snapshot 且不需 UI state。

後續 importer 原則：

- Recommendation importer 只讀已保存的 `RecommendationResultDTO` / repository result，不重算 scoring。
- Daily Decision Desk importer 只讀已保存 snapshot 或 service contract，不抓 UI state。
- Why Not / Liquidity Gate / Portfolio Alert 只保存原因與品質，不轉成交易建議。

## No-Look-Ahead Policy

- event 必須來自已保存 result / snapshot / event store，不可用今日 live data 重建過去事件。
- outcome calculator 只讀 event 之後的價格來計算事後結果，不可回頭改寫 event reason / score / quality。
- benchmark / industry excess 只能作 outcome 觀察，不能在 event 建立時反向影響事件內容。

## Benchmark / Industry Excess Policy

- benchmark v1 優先讀 SQLite `market_indices`，`benchmark_id` 預設可由 event 提供；找不到時 outcome 保留 `NULL` 並加入 `missing_benchmark` warning。
- industry v1 優先讀 SQLite `industry_indices`，使用 `industry_benchmark_id`；若缺，嘗試使用 `sector`；仍找不到則保留 `NULL` 並加入 `missing_industry_benchmark` warning。
- concept basket 留 schema 欄位，第一增量不計算 concept excess。

## Return Basis Policy

- v1 使用 event price date close 到第 N 個後續交易日 close。
- event price date 是 `daily_prices` 中 `event_date <= price_date` 的最近可用交易日，若 event_date 當天無價，允許使用之後第一個可用交易日並加 warning。
- window 5 / 10 / 20 / 60 是後續交易日數，不是 calendar days。

## Data Quality / Warning Policy

- event 的 `data_quality` 不可省略，只能使用 observed / estimated / degraded / missing。
- outcome 缺未來資料時寫入 `pending` 或 `insufficient_future_data`，不拋出批次錯誤。
- 缺 event price 時寫入 `missing_price`。
- benchmark / industry 缺資料不阻斷 symbol outcome。
- warnings 使用 deterministic JSON array 保存。

## Idempotency / Append-Only Policy

- event insert 以 `event_hash` idempotent：同一事件重送回既有 row。
- 不提供 update event API；若判斷不同，應形成不同 event_hash 的新 event。
- outcome 允許以 `(event_id, window_days, return_basis)` upsert，因為 pending 可能在未來價格補齊後變 ready。

## Migration Safety

- `data_module/evidence_event_migration.py` 提供 schema dry-run report 與 working-copy dry-run。
- 正式 apply 需 backup helper，且只新增 evidence tables / indexes，不修改既有核心表。
- repository `ensure_schema()` 僅建立缺少的 evidence tables，保持可重入。

## Test Plan

- repository：dry-run 不改來源 DB、event idempotency、不同 reason hash 不合併、outcome upsert / list。
- service：required fields fail closed、JSON deterministic serialization、event_hash stable。
- forward calculator：交易日 window、insufficient future data、missing benchmark / industry warning、close-to-close metadata。
- CLI：dry-run 不寫入、不輸出交易建議語言、diagnostics summary 欄位完整。
- governance：執行 `scripts/check_financial_float_boundaries.py` 與 py_compile。

## Handoff Route

1. Recommendation / Daily Decision Desk importer。
2. Forward Performance Dashboard read model。
3. Live vs Research Gap Dashboard。
4. Signal Decay Monitor。
5. Decision Quality Review。

