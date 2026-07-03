# Post-V1 Decision Desk Evidence Working-Copy Smoke（2026-07-03）

## 目的

本紀錄保存 2026-07-03 針對 Daily Decision Desk durable snapshot 與 Evidence Pipeline working-copy confirm smoke 的 follow-up 結果。這是程式路徑與 working-copy 寫入驗證，不是 production scheduler 啟用紀錄，也不是投資有效性結論。

## 背景

同日第一個 weekly evidence operations + history run 顯示：

- `decision_desk_snapshot_missing`
- `recommendation_persisted_missing`
- `working_copy_confirm_smoke_missing_or_failed`

後續追查發現 batch / CLI 路徑使用空的 `DecisionDeskSnapshotBuilder()`，沒有接上 UI 已使用的 Market Breadth、Sector Rotation、Relative Strength / Liquidity、Watchlist Trigger、Portfolio Alert 與 Market Regime provider。因此 durable snapshot 會被保存，但所有 section 可能降級為 `missing`，使 evidence source coverage 誤判 Daily Decision Desk 類來源不可用。

## 修補範圍

- 新增 non-UI `app_module/decision_desk_builder_factory.py`，集中建立 service-backed `DecisionDeskSnapshotBuilder`。
- `scripts/capture_decision_desk_snapshot.py` 改用 service-backed builder。
- `app_module/evidence_pipeline_runner.py` 的 snapshot step 改用 service-backed builder。
- `app_module/decision_desk_dtos.py` 的 `_as_dict()` 補上 numpy scalar 正規化，避免 `market_regime.meta` 內的 `numpy.bool_` 造成 snapshot storage JSON 序列化失敗。

修補不寫正式 DB、不讀 UI state、不偽造 watchlist / portfolio / recommendation 事件。

## 驗證命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_builder_factory.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_capture_decision_desk_snapshot_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_pipeline_runner.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\decision_desk_builder_factory.py app_module\decision_desk_dtos.py app_module\evidence_pipeline_runner.py scripts\capture_decision_desk_snapshot.py tests\test_decision_desk_builder_factory.py
.\.venv\Scripts\python.exe scripts\capture_decision_desk_snapshot.py --decision-date 2026-07-03 --db-path tmp\evidence_ops_continue_20260703\twstock_working.db --data-root D:\Min\Python\Project\FA_Data --output-root tmp\evidence_ops_continue_20260703\output --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_decision_desk_snapshot.py --decision-date 2026-07-03 --db-path tmp\evidence_ops_continue_20260703\twstock_working.db --data-root D:\Min\Python\Project\FA_Data --output-root tmp\evidence_ops_continue_20260703\output --confirm --json-output
.\.venv\Scripts\python.exe scripts\inspect_evidence_source_coverage.py --db-path tmp\evidence_ops_continue_20260703\twstock_working.db --decision-date 2026-07-03 --json-output --output-root tmp\evidence_ops_continue_20260703\output
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline_working_copy.py --source-db-path D:\Min\Python\Project\FA_Data\sqlite\twstock.db --working-copy-db-path tmp\evidence_ops_continue_20260703\twstock_working.db --decision-date 2026-07-03 --sources watchlist-trigger,portfolio-alert,risk-prompt --repeat 2 --report-output tmp\evidence_ops_continue_20260703\reports\ddd_working_copy_smoke_after_factory.json --json-output --output-root tmp\evidence_ops_continue_20260703\output
```

## 結果摘要

| 項目 | 結果 |
|---|---|
| factory regression tests | `3 passed` |
| snapshot CLI tests | `4 passed` |
| evidence runner tests | `10 passed` |
| py_compile | passed |
| snapshot dry-run / confirm | exit 0 |
| snapshot quality | `degraded` |
| snapshot seen sections | `market_regime`, `market_breadth`, `sector_rotation`, `relative_strength_liquidity`, `risk_prompt` |
| snapshot missing sections | `watchlist_trigger`, `portfolio_alert` |
| risk prompt candidates | `895` |
| source coverage risk prompt | `risk_prompt_capture_ready=true` |
| working-copy smoke event count | run 1: `895`; run 2: `895` |
| working-copy smoke outcome count | run 1: `3580`; run 2: `3580` |
| duplicate events | `false` |
| idempotency | `passed` |
| readiness after smoke | `not_ready` |
| persisted recommendation follow-up | `20` recommendations saved to ignored output root |
| recommendation + risk-prompt requested run | run 1 inserted `20` recommendation events / `80` outcomes; run 2 inserted `0` events |
| final working-copy evidence events | `915` |
| final working-copy outcomes | `3660` |

Working-copy smoke 第一次寫入 `895` 筆 `risk_prompt` events 與 `3580` 筆 outcomes；第二次重跑時 events 沒有膨脹，`events_skipped_duplicate=895`，outcomes 維持 `3580` 筆並以 update 路徑處理。

後續同日使用既有 `RecommendationService` 與 `RecommendationRepository`，在 `output_root=tmp/evidence_ops_continue_20260703/output` 保存 working-copy Recommendation result：`rec_working_copy_20260703_regime_default`，共 `20` 筆 recommendation，可讀回。這不是 production recommendation repository，也不是交易建議。

再以 `scripts/run_evidence_pipeline.py --sources recommendation,risk-prompt --result-id rec_working_copy_20260703_regime_default --confirm` 對同一份 ignored working-copy DB 跑兩次：

- run 1：`events_inserted=20`，`events_skipped_duplicate=895`，`outcomes_created=80`，`outcomes_updated=3580`。
- run 2：`events_inserted=0`，`events_skipped_duplicate=915`，`outcomes_created=0`，`outcomes_updated=3660`。
- final DB count：`recommendation_included=20`、`risk_prompt_low_liquidity=885`、`risk_prompt_relative_weakness=10`；`evidence_events=915`、`evidence_outcomes=3660`。

Requested sources (`recommendation,risk-prompt`) 的 runner summary 可達 `ready_for_manual_confirm`，但整體 source coverage 仍因 watchlist / portfolio / exclusion payload 缺口維持 `not_ready`。

## 剩餘 gaps

Daily Decision Desk follow-up 後的 source coverage 曾顯示：

- `recommendation_persisted_missing`
- `watchlist_trigger_snapshot_section_missing`
- `portfolio_alert_snapshot_section_missing`
- `why_not_exclusion_payload_missing`
- `liquidity_gate_payload_missing`

保存 working-copy Recommendation result 後，final source coverage 收斂為：

- `watchlist_trigger_snapshot_section_missing`
- `portfolio_alert_snapshot_section_missing`
- `why_not_exclusion_payload_missing`
- `liquidity_gate_payload_missing`

Working-copy smoke 對 requested Daily Decision Desk sources 的 blocking gaps 收斂為：

- `watchlist_trigger_not_ready`
- `portfolio_alert_not_ready`

判讀：

- `decision_desk_snapshot_missing` 已解除；durable snapshot 可由 batch 路徑產生並保存。
- `risk_prompt_capture_ready` 已變為 `true`，且可在 working-copy confirm smoke 中寫入事件與 outcomes。
- `watchlist_trigger` 仍 missing，原因是目前 output root 的 default watchlist 沒有項目；不應用測試資料偽造 ready。
- `portfolio_alert` 仍 missing，原因是目前 portfolio 沒有 active positions；不應用測試持倉偽造 ready。
- `recommendation_persisted_missing` 已在這份 working-copy 中解除；但此操作仍屬人工受控 tmp run，尚未代表 production scheduler 可用。
- why-not / liquidity payload 仍缺，因目前 Recommendation result 保存路徑不會產生 exclusion payload；需後續明確設計或 workflow 補齊。

## 邊界

- 未寫正式 `D:/Min/Python/Project/FA_Data/sqlite/twstock.db`。
- 未啟用 production scheduler。
- 未建立 Windows production write task。
- 未新增或偽造 watchlist / portfolio / recommendation source data。
- 未產生 lifecycle action。
- 未產生買賣建議。

## 下一步

1. 補齊 Recommendation why-not / liquidity exclusion payload 的正式產生與保存路徑；不得由 evidence importer 重算或偽造。
2. 以人工建立的實際 watchlist 與實際 / 模擬持倉資料重跑 Decision Desk snapshot，確認 `watchlist_trigger` 與 `portfolio_alert` 是否由 `missing` 轉為 `observed` / `degraded`。
3. 在上述 source gaps 解除前，production scheduler 維持 disabled。
