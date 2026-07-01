# Post-V1 Signal Decay Monitor Design

日期：2026-07-09

## Scope

本設計建立 Signal Decay Monitor v1，用已保存 Evidence Event / Outcome、Forward Performance Read Model 與 Live vs Research Gap observation 檢查事件類型、事件家族、策略版本與 Profile 的近期 evidence 是否相對長窗轉弱。

本輪只建立 append-only evidence observation、rule-based diagnostic、CLI 與 lifecycle proposed payload。它不建立正式 scheduler、不建立 UI、不修改策略權重、不修改 portfolio position、不改 Strategy Lifecycle state，也不宣稱任何訊號有效或失效。

## Data Model

新增 `signal_decay_observations` SQLite table，由 `SignalDecayRepository` 管理。資料採 append-only / idempotent save，以 deterministic `decay_hash` 去重。

主要欄位：

- `decay_id` / `decay_hash`
- `observation_date`
- `signal_scope_type` / `signal_scope_id`
- `strategy_version_id` / `profile_id` / `event_type` / `event_family` / `factor_name`
- short / long window 與 sample size
- forward benchmark excess、win rate、MAE、live gap metrics
- `decay_score_bp`
- `decay_status`
- `suggested_lifecycle_action`
- `confidence`
- quality / warnings / diagnostics / metadata

JSON 欄位使用 deterministic serialization；舊 evidence 不回補、不重算推薦或排除理由。

## Decay Dimensions

v1 支援：

- `event_type`
- `event_family`
- `strategy_version`
- `profile`

`factor_name` 與 portfolio source type 尚未有一致 evidence scope key，本輪只列為後續 deferred，不偽造 scope。

## Window Policy

v1 以 event-count window 為主要判讀：

- short default：30 events
- long default：120 events
- short day metadata：60 days
- long day metadata：240 days

CLI 接受 day window 參數，但 v1 只把 day window 保存為 metadata；實際樣本以已保存 ready outcome 的事件數為準。若 short 或 long sample 小於 `min_sample_size`，狀態必須是 `insufficient_sample`，且 lifecycle suggestion 必須是 `none`。

## Metrics

v1 使用整數 bp 聚合：

- mean / median benchmark excess
- win rate vs benchmark
- mean industry excess
- mean MAE
- mean live gap vs forward evidence
- mean live gap vs benchmark
- quality degraded ratio

pending / missing outcome 不進平均數。缺 benchmark 或 live gap 時保留 diagnostic 並降低 confidence。

## Decay Score

`decay_score_bp` 是 0 至 10000 的 rule-based 分數，不使用 ML：

- short benchmark excess 明顯低於 long：加分
- short win rate 明顯低於 long：加分
- short MAE 更差：加分
- short live gap 明顯低於 long：加分
- short quality degraded ratio 較高：加分

狀態：

- `no_data`
- `insufficient_sample`
- `stable`
- `watch`
- `decaying`
- `severe_decay`

建議：

- `none`
- `hold`
- `watch`
- `demote_candidate`
- `retire_candidate`

`retire_candidate` 只允許在樣本足夠、benchmark 與 live gap 都存在、short/long evidence 都偏弱且 live gap 支持時出現。其他衰退情境最多只產生 `demote_candidate` 或 `watch`。

## Lifecycle Evidence Policy

本輪新增 `SignalDecayLifecycleEvidenceAdapter`，只產生 payload：

- `source=signal_decay_monitor_v1`
- `status=proposed`
- `apply_action=false`
- 保存 decay scope、metrics、quality、warnings、diagnostics 與 suggestion

預設不寫 `LifecycleEvidenceRepository`，也不 apply promote / demote / retire。既有 lifecycle repository 仍適合 Research Run decision evidence，不適合任意 signal scope 直接寫入。

## CLI

```powershell
.\.venv\Scripts\python.exe scripts\inspect_signal_decay.py --observation-date 2026-07-09 --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-09 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\capture_signal_decay.py --observation-date 2026-07-09 --confirm --db-path <working-copy-db> --json-output
```

`capture_signal_decay.py` 預設 dry-run。`--confirm` 必須搭配 explicit `--db-path`；疑似正式 DB 仍需要 `--allow-production-db-confirm`，測試不得寫正式 DB。

## Safety Boundary

- 不改 `ScoringEngine`。
- 不改推薦權重。
- 不導入 ML。
- 不自動 promote / demote / retire。
- 不修改 portfolio position / trades。
- 不建立 Windows Task Scheduler / cron / background scheduler。
- 不建立 UI。
- 不從 UI state 抓資料。
- 不把 close-to-close forward return 說成實盤績效。
- 不把 decay observation 包裝成買賣建議。
- 小樣本近期轉弱只能標示 `insufficient_sample`，不能當作策略失敗。

