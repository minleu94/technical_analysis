# Prospective Formal Restart — 2026-08-27 v3 successor staging

日期：2026-08-25（Asia/Taipei）

## Clock and custody

- clock：`clock:prospective:20260827:v3`
- activation：`2026-08-27`
- complete preparation day：`2026-08-26`
- PIT boundary：`08:30:00 Asia/Taipei`
- Rule／Portfolio boundary：`09:00:00 Asia/Taipei`
- clock manifest hash：`sha256:43d3872b4646d7565762a16104e9e53302885adcad0ad6a7596ce75853806882`
- clock file hash：`sha256:4387ba3809b86c053b32833732e2640044d181cc377b319ee1b9933afeee68db`
- calibration policy hash：`sha256:86af3d00e46bd2b8c2f029693efe2926def0c141d81facf45a5baae03a74b6d5`
- calibration file hash：`sha256:4e4a563832376ba7347f21a8d99636021535d941236ef47e4d9a31bdd67f1f91`

External root：

`D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260827-v3`

v3 是 create-only、planned、prospective-only successor；不修改 8/25、8/27 v1、
8/27 v2 或 8/28 bytes。所有安全旗標固定為
`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、
`promotion_eligible=false`、`broker_order_allowed=false`、`real_money=false`。

## Official calendar and PIT staging

2026-08-27 已由 TWSE holiday schedule 與 TPEX 202608 calendar cross-check 為共同交易日；
2026-08-26 保留一個完整準備日。

- TWSE endpoint：`https://openapi.twse.com.tw/v1/opendata/t187ap03_L`
- TPEX endpoint：`https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O`
- TWSE calendar response hash：`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`
- TPEX calendar response hash：`sha256:8ec36f00753c2a8903ff844fb568235a8fee2f7603feed820ccc2599a28aa463`
- licenses：`twse-open-data-license-v1`、`tpex-open-data-license-v1`
- clock universe：1932 symbols，universe hash=`sha256:4e4d9bba29b96134fbf5b13d087cf18b9bdc0ca741af574e265b744dbb597b4b`

v3 staging package：

`D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260827-v3\staging\pit_source_staging.json`

file hash=`sha256:7c9f915b16122892a7db8d740605bac6432a465f0118470f8aa8f7c09ea1c3fb`，
row／expected symbol count=`1932／1932`，`formal_consumer_compatible=false`。
它不是正式 PIT manifest。

| Market | Publication at | Available at | Effective from | Raw hash | Canonical rows hash |
|---|---|---|---|---|---|
| TWSE listed `t187ap03_L` | `2026-08-22T09:00:00-07:00` | `2026-08-24T14:17:05.498298-07:00` | `2026-08-27` | `sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97` | `sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894` |
| TPEX OTC `t187ap03_O` | `2026-08-23T09:00:00-07:00` | `2026-08-24T14:17:05.498298-07:00` | `2026-08-27` | `sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835` | `sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5` |

No `t187ap03_R` was used because the v3 universe does not contain emerging-market
symbols. No `companies.csv` fallback or historical sector backfill was used.

## Deferred readiness and activation custody

- deferred readiness：`ready_for_future_activation`
- deferred readiness hash：`sha256:3cd4ddb22678378dc1853b6df7ea05ea5f4f3f39a976c0792fa8eb0699d750ad`
- deferred readiness file hash：`sha256:eed7a6fdeb429bfa7b6ce7b8d15f89300792364c84060b2d852f617d9b4430c3`
- activation custody：`scheduled`
- activation manifest hash：`sha256:2391875ddd031b55d2c8b3557038d96a485a491d58902d168c6b06b2b52ba45f`
- activation file hash：`sha256:9c37e954e1c0a74036b6d6926bc6352d435b4f87eee89df11257a438ca9df33f`

The three formal input paths remain deferred. Controlled path／store／HMAC checks
only record configured booleans; no secret value was emitted.

## Single-run activation handoff

On 2026-08-27, run the existing fixture-only low-CPU entries with actual timestamps:

1. 08:30：re-capture official TWSE／TPEX raw bytes and publish v3 PIT manifest.
2. after 09:00：consume the real owner-bound controlled-store HMAC artifact and publish v3 Rule history.
3. after the 2026-08-26 close: use the 2026-08-26 T-1 state and v3 09:00 boundary to append the first non-cash simulated Portfolio transition, then publish its manifest.
4. only after all three exist: run strict readiness; partial start is forbidden.

No continuous scheduler, Direct/OOC watcher, training, retraining, promotion,
broker adapter, order, automatic rebalance or automatic liquidation is enabled.

## Rollback

Keep v3 immutable bytes. If v3 is cancelled, stop consumer adoption and create a
new successor; do not delete, overwrite, or rename staging as Formal. The v2
rejected bytes remain available only for audit.
