# Post-V1 Evidence-Driven baldr Round 3 設計：E2E Smoke 與 Forward Performance Read Model v1

> 日期：2026-07-03  
> 狀態：已實作  
> 範圍：Importer → Event Store → Outcome Calculator E2E smoke；Forward Performance Read Model v1  
> 非目標：Dashboard UI、scheduler、ML、scoring 權重、portfolio position、automatic lifecycle action。

## 1. 問題

Evidence Event Store v1、Forward Outcome Calculator v1 與 Importers v1 已可分別運作，但還需要兩個工程證據：

1. persisted Recommendation result 能在隔離 SQLite DB 中完成 capture → event → outcome → inspect 的端到端 smoke。
2. forward outcomes 需要一個唯讀 read model，供未來 dashboard 使用，但不能把 close-to-close research observation 誤包裝成投資建議。

## 2. 設計原則

- 預設 dry-run；只有 `--confirm` 才寫入 smoke 目標 DB。
- `--db-path` 指向 tmp / working-copy DB，不覆寫正式資料。
- read model 僅讀 `evidence_events` 與 `evidence_outcomes`，不回寫、不重算 scoring、不觸碰 portfolio。
- 只有 `ready` outcome 納入平均報酬、勝率與 benchmark / industry excess 計算；pending / missing 只進樣本覆蓋、品質與 warning 計數。
- 所有 return / rate 使用整數 basis point；不新增金融核心裸 `float`。
- summary 不輸出交易建議、不宣稱 alpha、不稱為實盤績效。

## 3. E2E Smoke Contract

新增 `scripts/smoke_evidence_pipeline.py`：

- 輸入：`--db-path`、`--recommendation-result-id`、`--decision-date`、`--start-date`、`--end-date`、`--windows`、`--limit`、`--dry-run`、`--confirm`、`--json-output`。
- 流程：建立 evidence schema、使用 Recommendation importer capture events、讀取 event summary、在 confirm 模式計算 forward outcomes、輸出 JSON summary。
- summary 包含 event / outcome 數量、duplicate、pending / missing price / missing benchmark / missing industry、quality、warnings 與 sample rows。
- close-to-close basis 以 `return_basis=close_to_close_event_date` 揭露。

## 4. Forward Performance Read Model Contract

新增 `app_module/forward_performance_read_model.py`：

- Filters：日期、event type / family、source type、symbol、regime、sector、profile、strategy version、window。
- Group by：`event_type`、`event_family`、`source_type`、`regime`、`sector`、`profile_id`、`score_percentile_bucket`、`liquidity_state`、`data_quality`。
- Metrics：sample size、pending / missing count、mean / median forward return、mean / median benchmark excess、mean / median industry excess、positive rate、benchmark / industry win rate、MAE / MFE、quality counts、warning counts、first / last event date、summary status。
- Score percentile bucket 只讀既有 `score_percentile_bp`，不重新計算 percentile：`0-2000`、`2001-4000`、`4001-6000`、`6001-8000`、`8001-10000`、`missing`。

## 5. Summary Status

- `INSUFFICIENT_SAMPLE`：ready sample size 小於 `min_sample_size`。
- `MISSING_BENCHMARK`：ready rows 多數缺 benchmark excess。
- `MISSING_INDUSTRY`：ready rows 多數缺 industry excess。
- `DEGRADED`：有 pending / missing rows，或少數 benchmark / industry 缺失。
- `READY`：樣本數達標且 benchmark / industry 資料完整。

## 6. CLI Contract

新增 `scripts/summarize_forward_performance.py`：

- 支援 `--db-path`、filters、`--window`、`--group-by`、`--min-sample-size`、`--json-output`、`--csv-output`。
- JSON deterministic：排序 key、固定欄位。
- CSV 只輸出 summary rows，不輸出建議文字。

## 7. 風險與限制

- Recommendation importer 的 benchmark / industry 欄位若來源未保存，outcome 可 ready 但會以 warnings 與 degraded / missing status 揭露。
- DDD 類來源仍缺 durable snapshot repository；目前 DTO/provider importer 不等於可排程來源。
- read model 只能回答「已保存事件的 forward research observations」，不能證明 alpha、交易可執行性或任何策略應自動升降級。
- Scheduler readiness：not ready for production schedule；下一步只能做 dry-run scheduler design。
