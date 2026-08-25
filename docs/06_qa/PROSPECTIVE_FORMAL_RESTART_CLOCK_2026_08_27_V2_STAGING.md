# Prospective Formal Restart — 2026-08-27 successor staging record

日期：2026-08-25（Asia/Taipei）

> 狀態：`rejected / superseded-by-clock-20260827-v3`。此 v2 clock 的
> calibration file 仍綁定 v1 identity，deferred readiness validator 已拒絕它；
> v2 bytes 保留 immutable、不得採用或覆寫。正式 successor 改用
> [clock-20260827-v3 staging](C:/Projects/PythonProjects/technical_analysis/docs/06_qa/PROSPECTIVE_FORMAL_RESTART_CLOCK_2026_08_27_V3_STAGING.md)。

## Future clock

- clock：`clock:prospective:20260827:v2`
- activation trading day：2026-08-27
- complete preparation day：2026-08-26
- PIT decision boundary：08:30:00 Asia/Taipei
- owner-bound Rule／Portfolio decision boundary：09:00:00 Asia/Taipei
- clock manifest hash：`sha256:2f934df46c26603b822e4a7d9ed9bc23419af74a1f0462048ee9004a8cb83762`
- clock file hash：`sha256:cb5daf976ea3e9ca329ee7dbb5ab1563d74067707f7ef999182c298146fb0c79`
- clock path：`D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260827-v2\clock\manifest.json`

這是新的 create-only、planned、prospective-only successor；沒有修改
`clock:prospective:20260825:v1`、`clock:prospective:20260827:v1` 或
`clock:prospective:20260828:v1`。`real_money=false`、`broker_execution=false`、
`historical_backfill_claimed=false`，並持續 `formal_oos_allowed=false`、ML alpha=0、
promotion=false、`broker_order_allowed=false`。

## 為何不把 2026-08-25 補寫成新的 split clock

目前實際 Asia/Taipei 時間已越過 2026-08-25，且既有 8/25 clock 的 immutable
owner／Rule boundary 是 08:30、沒有 separate `pit_decision_time`。它的 PIT
sidecar 已以 1932 symbols 通過既有 validator，但不能在事後把 09:00 owner-bound
Rule／Portfolio decision 倒填進同一 clock。8/25 bytes 保留作歷史追溯，不重建、不沿用、
不回填；v2 是距離最近、仍保留一個完整準備日的合法 successor。

## Calendar evidence

2026-08-27 為 TWSE／TPEX 共同交易日，2026-08-26 保留為完整 preparation day。

- TWSE holiday schedule：`https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule`
- TWSE response hash：`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`
- TPEX calendar：`https://info.tpex.org.tw/api/mktCalendar?ym=202608&lang=zh-tw`
- TPEX response hash：`sha256:8ec36f00753c2a8903ff844fb568235a8fee2f7603feed820ccc2599a28aa463`

## Frozen identities

- strategy：`manual-rule-only-daily-rank-v1`
- policy：`foreground-owner-bound-v1`
- policy hash：`sha256:26ac99c06b5afc60f575859730a2185fac83d7714c4369861f2b8a4fa6af4f1b`
- score configuration hash：`sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4`
- universe hash：`sha256:4e4d9bba29b96134fbf5b13d087cf18b9bdc0ca741af574e265b744dbb597b4b`（1932 symbols）
- source policy hash：`sha256:8ab7ec876c5ae1c60de64a05ece98598afe6118f1563b6878a7900a50d4f9cd7`
- candidate model hash：`sha256:e0b9256ad5131084e81a27c2a75b8515461985ff2781d7e0840b08ca760f50d6`
- candidate feature manifest hash：`sha256:92140d5b5305125095d31811b90fdf010d67e2194bc94d9af24620e9247be11b`
- dataset identity hash：`sha256:d3b3e722d82114204c966ca6aa9f9e49637f91120081a9fc2aad511f1c865bc0`
- calibration policy hash：`sha256:edc1c02469f80ed9e9b572e909b329a8dbc32d6378cfd1cd7106d60fada6100b`

## Official PIT staging

來源只使用上市 TWSE `t187ap03_L` 與上櫃 TPEX `t187ap03_O`；clock universe
不包含興櫃，因此沒有使用 `t187ap03_R`。staging package 位於：

`D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260827-v2\staging\pit_source_staging.json`

其 file hash 為 `sha256:f683c4c225b0215e0e59e7441f0e531aaf8f4d9de4059701bead561787199b74`，
`formal_consumer_compatible=false`，不能冒充正式 PIT manifest。row／expected
symbol count 為 `1932／1932`，staging 已重新綁定 v2 clock 與 universe hash。

| Market | Official source／license | Publication at | Available at | Effective from | Raw hash | Canonical rows hash |
|---|---|---|---|---|---|---|
| 上市 | [TWSE `t187ap03_L`](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)／`twse-open-data-license-v1` | `2026-08-22T09:00:00-07:00` | `2026-08-24T14:17:05.498298-07:00` | `2026-08-27` | `sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97` | `sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894` |
| 上櫃 | [TPEX `t187ap03_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)／`tpex-open-data-license-v1` | `2026-08-23T09:00:00-07:00` | `2026-08-24T14:17:05.498298-07:00` | `2026-08-27` | `sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835` | `sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5` |

Raw bytes are separately retained under the v2 staging directory. No
`companies.csv` fallback or historical sector backfill was used.

## Single-run activation handoff

On 2026-08-27, use actual timestamps and the existing fixture-only CLIs:

1. At the PIT 08:30 boundary, re-capture official TWSE／TPEX raw bytes and publish
   the v2 clock-bound PIT manifest.
2. After 09:00, use the real owner-bound controlled-store HMAC snapshot to publish
   the v2 Rule history; no manual score or ML OOS substitute is allowed.
3. Use the 2026-08-26 T-1 market state and the v2 clock's 09:00 boundary to append
   the first non-cash simulated Portfolio transition, then publish its manifest.
4. Run strict readiness only after all three formal inputs exist; no partial start.

The current v2 directory has staging/custody only. Formal Rule, Portfolio and PIT
manifests are intentionally not present before their real boundaries. No new
continuous scheduler, legacy Direct/OOC watcher, training, retraining, promotion,
broker adapter, order, rebalance or auto-liquidation is registered.

## Rollback

Retain all v2 immutable bytes. If this successor is cancelled, stop consumer
adoption and create another successor; do not delete, overwrite, or rename staging
to Formal. The Portfolio clock-bound-time fix is reverted with its own Git commit,
without touching external immutable data.
