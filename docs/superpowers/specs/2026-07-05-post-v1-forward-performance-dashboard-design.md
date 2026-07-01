# Post-V1 Forward Performance Dashboard Read-only UI Design 2026-07-05

## Scope

本設計建立 Forward Performance Dashboard read-only UI v1。Dashboard 只檢查已保存 Evidence Event / Outcome 經 `ForwardPerformanceReadModel` 彙總後的結果，不捕捉 UI state、不寫 evidence、不重算 domain logic、不改策略、不排程。

## Placement

採 Option C：掛在 Research Lab / 策略回測的結果分頁，新增 `Forward Evidence` tab。

選擇原因：

- Forward performance 是研究證據檢查層，語意上靠近 Research Lab 與 Registry 比較。
- 不新增頂層 workspace，降低 navigation、manual 與 MainWindow smoke 變更面。
- 既有 Research Lab 結果區已支援 service-backed 子頁模式。

## Read-only Contract

- UI 只呼叫 `ForwardPerformanceDashboardService`。
- Dashboard service 只呼叫 `ForwardPerformanceReadModel.summarize()`。
- UI 不直接 import SQLite repository、不直接讀 DB、不 import scoring / portfolio mutation path。
- service factory 使用 read-only SQLite connection；缺 evidence DB 或 schema 時回 empty / degraded diagnostic，不建 schema、不偽造資料。
- Dashboard 不寫 event、不寫 outcome、不改 portfolio、不建立 scheduler。

## Filters

Dashboard v1 支援：

- `start_date`
- `end_date`
- `event_type`
- `event_family`
- `source_type`
- `symbol`
- `regime`
- `sector`
- `profile_id`
- `strategy_version_id`
- `window_days`
- `group_by`
- `min_sample_size`

預設：

- `window_days = 20`
- `group_by = event_type`
- `min_sample_size = 10`

## Group By

支援：

- `event_type`
- `event_family`
- `source_type`
- `regime`
- `sector`
- `profile_id`
- `score_percentile_bucket`
- `liquidity_state`
- `data_quality`

## Summary Cards

顯示：

- total events
- ready outcomes
- pending outcomes
- missing outcomes
- ready groups
- insufficient sample groups
- degraded groups
- missing benchmark count
- missing industry count
- warnings count

## Main Table

表格欄位：

- group key
- window days
- sample size
- pending count
- missing count
- mean / median forward return
- mean / median benchmark excess
- mean / median industry excess
- positive rate
- win vs benchmark / industry
- mean MAE / MFE
- summary status
- first / last event date
- quality counts
- warning counts

內部 DTO 保留整數 bp；Qt table model 只在 display role 轉成人類可讀百分比。

## Detail Panel

選中 group 後顯示：

- definition
- applied filters
- sample / pending / missing
- quality breakdown
- warning breakdown
- benchmark availability
- industry benchmark availability
- return basis
- limitations

## Empty / Degraded States

- 無資料：尚無足夠 forward evidence，需先 capture events 並 calculate outcomes。
- missing benchmark：Benchmark 缺失，無法判斷相對大盤超額。
- insufficient sample：樣本不足，只能作資料品質檢查，不可作訊號有效性判斷。

## Safety Language

Dashboard 明確顯示：

- 這是 research evidence，不是買賣建議。
- close-to-close forward return 不代表實盤可執行績效。
- 樣本不足、benchmark 缺失、industry 缺失與 data quality degraded 必須人工判讀。

## Non-goals

- 不建立 scheduler。
- 不做 lifecycle promote / demote / retire action。
- 不修改 ScoringEngine 或推薦權重。
- 不修改 portfolio position。
- 不宣稱任一事件類型有效。
- 不宣稱 alpha。
