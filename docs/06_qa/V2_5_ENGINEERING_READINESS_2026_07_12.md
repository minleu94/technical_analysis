# V2.5 Position Health Foundation Engineering Readiness

> 日期：2026-07-12
> 狀態：`engineering_readiness_recorded`；不是 V2.5 formal closeout。

## 已交付

- `PositionHealthService` 將既有 `PortfolioConditionResult`、feedback gate 與 source trace 投影為 `HEALTHY`、`WATCH` 或 `EXIT_CANDIDATE`。
- 缺 condition 或 source trace 時 fail-closed 為 `WATCH`；condition invalid 或 feedback fail 時僅標示 `EXIT_CANDIDATE`。
- 每個輸出保留 reasons 與 source trace，且 `auto_action_allowed=false` 固定為 false；不下單、不自動減碼、不自動平倉、不改 lifecycle 或資料庫。
- `scripts/inspect_position_health.py --sample --format json` 可產出唯一的唯讀檢查報告，內建樣本明確標示 `research_only=true`。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_position_health_service.py tests\test_position_health_cli.py tests\test_portfolio_condition_monitor.py tests\test_portfolio_feedback_service.py tests\test_portfolio_review_service.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\inspect_position_health.py --sample --format json
```

2026-07-12 結果：15 passed；樣本輸出為 `EXIT_CANDIDATE`，且 `auto_action_allowed=false`。

## 未完成的正式 Gate

2026-07-12 已由 V2.4 真實 saved-Recommendation paper artifact 建立 3 筆 `WATCH` baseline，並確認缺 thesis / invalidation / horizon / review date 時不補值、不自動 action；見 `V2_5_POSITION_HEALTH_BASELINE_2026_07_12.md`。

- 真實 active position 的 entry thesis、invalidation、holding horizon、review date 與人工 override／journal 記錄。
- 真實時間的 state transition evidence 與每筆 transition 的人工決議。
- Exit effectiveness、broker execution、任何自動減碼／平倉均不在範圍內。
