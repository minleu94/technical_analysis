# V2.5 Position Health Baseline

> 日期：2026-07-12
> 狀態：第一個 paper-position health baseline 已建立；不是 V2.5 formal closeout。

- 輸入：V2.4 `baseline_20260712.json` 的 3 筆非零 paper allocations。
- 產物：`D:/Min/Python/Project/FA_Data/output/position_health/baseline_20260712.json`。
- 三筆狀態均為 `WATCH`。
- `entry_thesis`、`invalidation`、`holding_horizon`、`review_date` 均維持 null，列為 `required_human_fields`，沒有由系統捏造。
- `research_only=true`、`writes_positions_db=false`、`auto_action_allowed=false`。

本產物驗證缺 thesis 時會 fail-closed；尚未具備真實人工 thesis、state transition、override / journal 或 exit effectiveness，因此不得升級為 V2.5 formal closeout，也不得解讀為退出指令。
