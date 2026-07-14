# Broker Flow Batch Semantics 效能優化證據

量測日期：2026-07-13（America/Los_Angeles）
結論：**Week／month cold 與 warm latency gates 均通過。**

## 根因與修正

正式 DB profile 顯示舊路徑在 100 檔 semantics 中物件化約 145,000 筆完整 `BrokerFlowEvent`，並對 broker-flow 與 price 日期反覆執行 `strptime`；batch price SQL 亦以 `REPLACE` 包住日期欄位，無法直接利用 `(證券代號, 日期)` 索引做 range predicate。

本次修正：

1. Canonical `YYYYMMDD`／ISO 日期改用等價的 bounded parser，移除大量 `strptime`。
2. Batch price SQL 改為 `證券代號 IN (...) AND 日期 <= ?`、`ORDER BY 日期 DESC`；仍是一次 price batch 且排除 decision date 後資料。
3. Semantic flow batch 只物件化語意需要的日期、分點、代號、名稱、淨量與 lots quality；fixture 證明這些欄位與完整 batch 完全一致。
4. Dashboard cache key 包含 DB size／mtime、as-of、period、scope、limit，最多保存 8 筆；source version 改變立即重算。Cold request 仍完整執行市場與 100 檔 semantics。

未改正式 score、張數單位、read-only 模式、UI/public contracts 或 production DB index。

## 正式 DB Gate

每條路徑執行 1 次 cold warm-up，接著保存 20 筆 warm samples；p95 採 nearest-rank。

| Path | Cold | Warm p95 | Gate | 結果 |
|---|---:|---:|---:|---|
| Week Top／Bottom 50 | 2,263.595 ms | 0.033 ms | cold `<5,000`、warm `<2,000` ms | PASS |
| Month Top／Bottom 50 | 3,270.953 ms | 0.032 ms | cold `<5,000`、warm `<3,000` ms | PASS |
| Stock detail（week／month） | — | 14.978／9.508 ms | `<500` ms | PASS |
| Branch tracker（week／month） | — | 16.922／20.008 ms | `<1,000` ms | PASS |
| UI loading／heartbeat | — | 兩次皆通過 | `<300` ms | PASS |

Week warm raw samples（ms）：

`0.153, 0.030, 0.029, 0.031, 0.026, 0.027, 0.033, 0.026, 0.026, 0.025, 0.025, 0.025, 0.026, 0.025, 0.025, 0.025, 0.025, 0.025, 0.025, 0.024`

Month warm raw samples（ms）：

`0.109, 0.030, 0.029, 0.028, 0.026, 0.026, 0.032, 0.027, 0.026, 0.026, 0.025, 0.026, 0.025, 0.026, 0.026, 0.026, 0.025, 0.026, 0.026, 0.025`

## 安全與完整性

- 正式資料形狀仍為 732,020 rows、178 trading dates、51 branches、2,115 stock codes。
- 每次 cold dashboard 仍產生 100 signals 與 100 semantics。
- Flow batch 與 price batch 各一次，沒有 per-symbol SQLite N+1。
- 兩次 final run 的 production DB SHA256、size、mtime before／after 均一致。
- Source-version cache fixture 證明：相同 query 重用 snapshot；版本改變後 repository 與 semantics 都重新執行。

## TEMP evidence

- Week：`$env:TEMP/technical_analysis_parallel/C/task-6-semantic-optimization/latency-week-final.json`，SHA256 `ddc79770bf83614e2ea5e64d42451ffe73c269a56964b8211ae4784a6e759b3b`
- Month：`$env:TEMP/technical_analysis_parallel/C/task-6-semantic-optimization/latency-month-final.json`，SHA256 `f16a38be014917e37faa01e10dfa859e26a450692b2b62ac6ba2eb0ed58e9bed`

External／forward／promotion gates 未變更。
