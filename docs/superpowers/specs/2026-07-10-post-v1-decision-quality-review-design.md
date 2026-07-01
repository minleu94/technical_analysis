# Post-V1 Decision Quality Review Design

日期：2026-07-10

## Scope

本設計建立 Decision Quality Review v1，用 append-only review / item / action item 記錄週期性決策流程覆盤。它只評估流程 evidence 是否完整：來源追溯、journal 覆盤、manual override 是否有理由、portfolio alert / live gap / signal decay 是否進入人工檢查。

本輪不建立 scheduler、不建立 UI、不改 portfolio、不改 Strategy Lifecycle state、不改 `ScoringEngine`、不改推薦權重，也不把覆盤項目包裝成交易建議。Decision Quality score 是流程品質基點，不是投資能力或市場方向判斷。

## Data Model

新增 `decision_quality_reviews`、`decision_quality_items`、`decision_quality_item_status_history`、`decision_quality_action_items` 四張 SQLite table。

Review 保存：

- review id / hash / period / type
- portfolio mode counts
- evidence event / trade / journal / alert counts
- ignored alert、manual override、missed signal、unreviewed decay、unlinked trade counts
- process / evidence / risk / completeness / total score bp
- review status、quality、warnings、diagnostics、metadata

Item 保存：

- item type、symbol、event / decision date
- source id、trade / position / evidence / gap / decay linkage
- severity、status、reason codes、evidence payload
- suggested review question

Item status 更新會寫入 history，保留 reviewed / dismissed 的變更軌跡。

## Review Item Types

v1 支援：

- `ignored_portfolio_alert`
- `manual_override_without_evidence`
- `trade_without_source_trace`
- `missed_high_quality_signal`
- `unreviewed_signal_decay`
- `large_live_research_gap`
- `low_quality_data_used`
- `regime_profile_mismatch`

所有 item 都必須有 `suggested_review_question`。問題語氣只要求人工補充或確認流程，不說使用者錯，也不推導應該採取任何 portfolio 或 lifecycle action。

## Score Policy

所有 score 使用整數 bp：

```text
decision_quality_score_bp =
0.35 * process_adherence_score_bp
+ 0.30 * evidence_usage_score_bp
+ 0.20 * risk_discipline_score_bp
+ 0.15 * review_completeness_score_bp
```

實作使用整數權重：

```text
(35 * process + 30 * evidence + 20 * risk + 15 * completeness) // 100
```

Components：

- process adherence：source trace、journal linkage、alert review、decay review。
- evidence usage：research source、evidence event、forward evidence、manual override documentation。
- risk discipline：unreviewed alert、large gap、low quality evidence 等流程風險。
- review completeness：open / reviewed / dismissed / action item status。

Boundary：

- insufficient sample => `review_status=incomplete`。
- no real trades => `portfolio_mode=unknown` 或 simulated workflow，不能宣稱 live outcome。
- no journal => warning，不代表使用者錯。
- score 是流程品質，不是投資能力。

## Source Inputs

Service 只讀：

- `PortfolioService.list_trades`
- `PortfolioService.list_positions`
- `JournalService.list_journal_entries`
- `EvidenceEventRepository`
- `LiveResearchGapRepository`
- `SignalDecayRepository`

Service 不呼叫 portfolio mutation、不寫 lifecycle repository、不讀 UI state、不重算 domain scoring。

## CLI

```powershell
.\.venv\Scripts\python.exe scripts\inspect_decision_quality.py --start-date 2026-06-01 --end-date 2026-06-30 --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type weekly --start-date 2026-06-24 --end-date 2026-06-30 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_quality_review.py --review-type monthly --start-date 2026-06-01 --end-date 2026-06-30 --confirm --db-path <working-copy-db> --json-output
```

Capture 預設 dry-run；confirm 必須 explicit `--db-path`。疑似正式 DB 需額外 allow flag；測試不得寫正式 DB。

## Safety Boundary

- 不建立 production scheduler。
- 不建立 Windows Task Scheduler / cron / background job。
- 不改 `ScoringEngine`。
- 不改推薦權重。
- 不導入 ML。
- 不自動 promote / demote / retire。
- 不改 portfolio position / trades。
- 不讀 UI state。
- 不把 close-to-close forward return 說成實盤績效。
- 不輸出交易建議語氣。
- 不用 hindsight blame 使用者。
