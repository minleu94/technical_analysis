# Broker Flow SQLite Dashboard 效能收口

量測日期：2026-07-13（America/Los_Angeles）
結論：**未通過整體驗收**。Week 與 month dashboard warm p95 均超過門檻；detail、branch tracker、UI loading／heartbeat 與 production DB 零寫入檢查通過。

## 量測方法

- 正式資料庫：`D:/Min/Python/Project/FA_Data/sqlite/twstock.db`，以 SQLite URI `mode=ro` 與 `PRAGMA query_only=ON` 讀取。
- 每條路徑執行 1 次 warm-up，再保存 20 筆 measured raw samples；p95 採 nearest-rank。
- Dashboard 保留完整市場母體與 Top／Bottom 50，不以 ETF heuristic 排除資料。
- Week／month 分開執行，避免長命令逾時遺失另一期間的完整證據。
- `dashboard_without_semantics` 僅用於根因診斷，不是替代正式 dashboard gate 的簡化版本。

正式資料形狀：732,020 rows、178 個交易日、51 個分點、2,115 個證券代號。每次 dashboard 回傳 100 個 signals 與 100 份 semantics。

## Gate 結果

| 路徑 | Cold | Warm p95 | Gate | 結果 |
|---|---:|---:|---:|---|
| Week Top／Bottom 50 | 3,912.106 ms | 3,965.556 ms | cold `< 5,000`、warm `< 2,000` ms | **FAIL** |
| Month Top／Bottom 50 | 4,693.749 ms | 5,684.536 ms | cold `< 5,000`、warm `< 3,000` ms | **FAIL** |
| Stock branch detail（week run） | 16.191 ms | 16.096 ms | warm `< 500` ms | PASS |
| Stock branch detail（month run） | 10.423 ms | 10.431 ms | warm `< 500` ms | PASS |
| Branch tracker（week run） | 17.818 ms | 19.976 ms | warm `< 1,000` ms | PASS |
| Branch tracker（month run） | 19.224 ms | 22.614 ms | warm `< 1,000` ms | PASS |
| UI loading／heartbeat（week run） | loading 0.306 ms | heartbeat 2.558 ms | 各 `< 300` ms | PASS |
| UI loading／heartbeat（month run） | loading 0.374 ms | heartbeat 2.846 ms | 各 `< 300` ms | PASS |

嚴格小於門檻才算通過。Month cold 仍低於 5 秒，但其 warm gate 失敗，因此整條 month dashboard 路徑判定 FAIL。

## Phase 與 query-count 診斷

| Period | 不含 semantics warm p95 | 完整 dashboard warm p95 | p95 差額（診斷值） |
|---|---:|---:|---:|
| Week | 659.481 ms | 3,965.556 ms | 3,306.076 ms |
| Month | 2,489.451 ms | 5,684.536 ms | 3,195.085 ms |

Dashboard snapshot 公開計數為 repository 2 statements、semantic batch 1 invocation。依 batch adapter 的固定內部結構，semantic invocation 包含 broker-flow batch 2 statements 與 price batch 1 statement，因此完整 dashboard 每次共 5 個 SQLite statements；不是依股票數量增長的 N+1。Detail 與 branch tracker 每次各 2 statements。

目前證據顯示主要 blocker 是 100 檔 semantics phase，約增加 3.2–3.3 秒 p95；month 的不含 semantics 聚合本身亦為 2,489.451 ms，雖低於 month 3 秒門檻，但改善餘裕有限。此 closeout 不修改正式 score、資料庫 index 或 ETF 篩選規則。

## Production DB 完整性

兩次 final run 的量測前後結果均一致：

- SHA256：`604e8fc5c046e40faeddd5a6e183d088f6bd90d0e462d2c8e4e96101c0b6d8b4`
- mtime_ns：`1783944933260382000`
- size、SHA256、mtime_ns before／after 全相等：PASS

## Raw samples（ms）

Week dashboard：

`3545.486, 3362.033, 3449.847, 3656.044, 4153.328, 3965.556, 3514.058, 3562.813, 3488.319, 3526.848, 3481.403, 3514.077, 3588.624, 3689.383, 3648.405, 3706.237, 3610.660, 3635.043, 3737.582, 3800.422`

Week dashboard without semantics：

`604.289, 609.831, 579.625, 601.105, 557.809, 563.606, 659.481, 585.661, 579.729, 564.891, 571.328, 576.227, 613.784, 739.862, 604.233, 582.151, 550.248, 591.766, 558.823, 581.216`

Week detail：

`15.221, 13.803, 15.704, 14.305, 14.718, 14.686, 14.695, 14.135, 14.848, 15.937, 14.424, 16.096, 16.035, 15.513, 16.153, 15.182, 13.989, 14.239, 13.479, 14.636`

Week branch：

`17.482, 18.568, 17.012, 17.825, 19.756, 18.666, 17.185, 16.541, 16.922, 19.954, 16.470, 15.752, 17.106, 19.976, 18.291, 18.245, 100.984, 18.910, 17.697, 17.772`

Month dashboard：

`5191.703, 5200.146, 5313.805, 5174.815, 5501.806, 5396.708, 5447.976, 5320.590, 5729.336, 5483.023, 5194.430, 5684.536, 5437.288, 5658.174, 5308.048, 5446.484, 5282.379, 5345.780, 5255.701, 5567.440`

Month dashboard without semantics：

`2354.238, 2489.451, 2290.902, 2516.110, 2176.080, 2403.613, 2206.881, 2442.924, 2112.777, 2430.633, 2197.173, 2362.918, 2176.136, 2334.297, 2243.171, 2438.888, 2265.418, 2399.511, 2376.885, 2286.153`

Month detail：

`11.436, 9.943, 10.116, 10.431, 8.418, 8.578, 8.611, 9.729, 9.211, 7.634, 8.141, 9.059, 8.469, 7.833, 7.814, 7.441, 7.779, 8.073, 7.633, 7.755`

Month branch：

`18.684, 19.380, 20.246, 21.043, 18.909, 18.576, 18.404, 18.953, 18.727, 17.271, 20.981, 21.398, 21.688, 21.573, 20.889, 22.983, 20.086, 20.197, 20.134, 22.614`

## Evidence artifacts

- Week JSON：`$env:TEMP/technical_analysis_parallel/C/task-5-latency-closeout/production-latency-week-final.json`，SHA256 `e78adfe85459f26af100c7dc70158b2586045b3ea23c634a9630005b6daca1f5`
- Month JSON：`$env:TEMP/technical_analysis_parallel/C/task-5-latency-closeout/production-latency-month-final.json`，SHA256 `189949754ac95f58711cac9eaf5818063c758a8298bc90f8df0cd382166e2e16`

## Blockers 與後續方向

1. **Blocking gate：** Week dashboard warm p95 需由 3,965.556 ms 降至 `< 2,000 ms`。
2. **Blocking gate：** Month dashboard warm p95 需由 5,684.536 ms 降至 `< 3,000 ms`。
3. 優先 profile batch semantics 的 Python 計算與 60-day broker-flow／price materialization；不得以減少正式 Top／Bottom 母體、ETF 名稱猜測或跳過 semantics 冒充改善。
4. Month source-only phase 應一併 profile query plan／聚合成本；若提出 index，先在 DB working copy 驗證，不得直接寫 production DB。

因此本文件是誠實的 **failed-gate closeout evidence**，不是效能完成證明。
