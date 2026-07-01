# Post-V1 Live vs Research Gap Linkage Design

日期：2026-07-08

## Scope

本設計建立 Live vs Research Gap event linkage v1。目標是把 portfolio position source trace、Research Run Registry、Strategy Lifecycle evidence 與 Evidence Event / Outcome 串成只讀 gap observation，供後續檢查研究預期、forward evidence 與持倉表現之間的差距。

本輪只建立 evidence linkage，不建立新 UI、不建立正式 scheduler、不修改 portfolio、不修改 Research Run、不修改 Strategy Lifecycle。

## Data Model

新增 `live_research_gap_observations` SQLite table，由 `LiveResearchGapRepository` 管理。資料採 append-only / idempotent save，使用 deterministic `gap_hash` 去重。

最低保存欄位包含 observation date、position id、symbol、portfolio mode、source trace、research run id、strategy version id、recommendation result id、evidence event / outcome id、entry/current price、holding days、portfolio return bp、research expected return bp、forward evidence return bp、benchmark / industry excess bp、gap metrics、regime、data quality、warnings、attribution 與 metadata。

## Matching Policy

明確 source trace 優先：

- `evidence_event_id` 可對應到 event 時，`match_confidence=high`。
- `source_type + source_id` 與 evidence event 明確相符時，`match_confidence=high`。
- 只有 symbol / date 相符時，只列為 candidate，`match_confidence=low`，不得保存為 confirmed evidence link。
- 找不到 outcome 時，保存 `insufficient_evidence` attribution 與 warning，不中斷整批。

## Attribution Policy

v1 採保守 rule-based attribution：

- 缺 source trace：`source_trace_gap`
- 缺 confirmed evidence outcome：`insufficient_evidence`
- entry/current regime 不同：`market_regime_gap`
- liquidity state 降級或偏低：`liquidity_gap`
- data quality missing / degraded：`data_quality_gap`
- entry price 與 source assumed price 存在差距：`execution_gap`
- portfolio return 低於 saved research / evidence / benchmark reference 且沒有更明確原因：`signal_gap`，confidence 只能 low / medium。

## Portfolio Mode

沒有真實交易與人工 override 記錄時，`portfolio_mode` 必須是 `simulated` 或 `unknown`。只有 source summary 明確標示真實交易已記錄時，才能保存為 `real`。本輪不宣稱完整實帳歸因。

## Safety Boundary

- Gap observation 是 evidence，不是 action。
- 不改 `ScoringEngine`。
- 不改推薦權重。
- 不改 portfolio position / trades。
- 不自動 promote / demote / retire。
- 不建立正式 scheduler。
- 不讀 UI state。
- 不在 UI 層重算 domain logic。
- close-to-close forward return 仍是 research basis，不是可執行績效。

## CLI

新增：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_live_research_gap.py --observation-date 2026-07-08 --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-08 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_live_research_gap.py --observation-date 2026-07-08 --confirm --db-path <working-copy-db> --json-output
```

`capture_live_research_gap.py` 預設 dry-run。`--confirm` 必須搭配 explicit `--db-path`，疑似正式 DB 仍需要額外 explicit override。
