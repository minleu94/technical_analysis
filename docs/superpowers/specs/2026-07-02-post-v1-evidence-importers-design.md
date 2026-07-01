# Post-V1 Evidence Importers Design

## Goal

在 V1 Evidence Event Store 之上新增第一版 evidence capture pipeline，將已存在的推薦結果、Daily Decision Desk snapshot 類 DTO、watchlist trigger、portfolio alert 與 risk prompt 轉成可追蹤、可去重的 Evidence Event。

## Non-Goals

- 不新增 scheduler。
- 不新增 UI dashboard。
- 不重跑 ScoringEngine、推薦權重、ML、策略生命週期或 portfolio position 邏輯。
- 不從 UI state 擷取資料。
- 不因單一 bad event 讓整批 capture 失敗。

## Boundaries

- 寫入邊界：只能經由 `EvidenceEventService.record_event()`。
- 推薦來源：只讀 `RecommendationRepository` 載入的 `RecommendationResultDTO`。
- Daily Decision Desk 類來源：只讀注入的 snapshot/summary provider 或 DTO。
- Portfolio 來源：只讀 `PortfolioAlertSummary` / attribution，不呼叫交易或清倉 API。
- Risk prompt：只讀 `DecisionDeskRiskPromptSummary`，保留既有 sanitize 後的文字，不新增買賣/目標價語意。

## Import Sources

### Recommendation

輸入為 persisted `RecommendationResultDTO`。每個 included recommendation 產生 `RECOMMENDATION_INCLUDED` event，保存 profile、regime、score、score percentile、reason、quality、warnings 與 source metadata。

若 `score_percentile_bp` 缺失，保留 `NULL` 並加入 `score_percentile_missing` warning，不重新計算 percentile。

若 source 未提供 why-not 或 liquidity exclusion payload，回傳 `source_missing_exclusion_payload` diagnostic，不建立 excluded events。

### Watchlist Trigger

輸入為 `WatchlistTriggerSummary`。依 `top_signal` 與 warnings 產生：

- `WATCHLIST_TRIGGER_ADDED`
- `WATCHLIST_TRIGGER_STRENGTH_UP`
- `WATCHLIST_TRIGGER_STRENGTH_DOWN`
- `WATCHLIST_TRIGGER_RISK_ALERT`

若 summary 只提供 `triggered_codes` 而無可判別的 signal，退回 `WATCHLIST_TRIGGER_ADDED`，並在 metadata 標記 fallback。

### Portfolio Alert

輸入為 `PortfolioAlertSummary` 與 `PortfolioAlertAttribution`，產生：

- `PORTFOLIO_ALERT_CONDITION_WARNING`
- `PORTFOLIO_ALERT_CONDITION_INVALID`
- `PORTFOLIO_ALERT_CHIP_RISK`
- `PORTFOLIO_ALERT_DATA_QUALITY`

若一筆 attribution 同時有多個風險，使用最高優先事件型別，並把完整 reasons / data quality flags 放入 metadata。

### Risk Prompt

輸入為 `DecisionDeskRiskPromptSummary`，依 prompt category/source 產生：

- `RISK_PROMPT_LOW_LIQUIDITY`
- `RISK_PROMPT_RELATIVE_WEAKNESS`
- `RISK_PROMPT_FUNDAMENTAL_DIAGNOSTIC`
- `RISK_PROMPT_DATA_QUALITY`

無 symbol 的 market-level prompt 使用 `MARKET` 作為 evidence symbol，避免破壞 event store 的非空 symbol contract。

## Capture Behavior

- CLI 預設 dry-run。
- 只有 `--confirm` 會寫入 DB。
- dry-run 會回傳 deterministic event hash sample，不寫 DB。
- 寫入時先用 event hash 檢查重複，重複計入 `events_skipped_duplicate`。
- 單一 event 失敗只增加 diagnostic / failed count，不中斷整批。
- `--source all` 遇到未支援或未注入 provider 的 source，要記錄 unsupported diagnostic 並繼續執行其他 source。

## Summary Contract

`EvidenceCaptureSummary` 至少輸出：

- `source_name`
- `decision_date`
- `dry_run`
- `events_seen`
- `events_valid`
- `events_inserted`
- `events_skipped_duplicate`
- `events_failed`
- `warnings_count`
- `diagnostics_by_code`
- `event_type_counts`
- `quality_counts`

