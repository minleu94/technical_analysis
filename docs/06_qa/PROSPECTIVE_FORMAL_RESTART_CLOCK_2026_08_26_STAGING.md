# Prospective Formal Restart — 2026-08-26 same-day pre-open staging record

日期：`2026-08-26`（Asia/Taipei）

狀態：`clock_created / owner_activation_scheduled / official_pit_staged / formal_inputs_pending_09_00`

## Owner override 與 clock

- Owner 已明確排除本 clock 的完整自然準備日限制；此授權只允許 2026-08-26 08:30 前建立具名同日 pre-open clock，不是全域 bypass。
- clock id：`clock:prospective:20260826:v1`
- activation：`2026-08-26`
- T-1 evidence day：`2026-08-25`
- PIT boundary：`08:30:00 Asia/Taipei`
- Rule／Portfolio boundary：`09:00:00 Asia/Taipei`
- override id：`owner-override:prospective-formal-restart:same-day-preopen:20260826:v1`
- override timestamp：`2026-08-26T05:42:37+08:00`
- clock manifest hash：`sha256:5409fe23d5247dc1698af09a5af9295ad8f7ad3f02c6926233582e11e93efde7`
- clock file hash：`sha256:c8ee8be95936adf48637d9077351bb90ee33b9bf8cc27b7c86780523f0c05784`
- activation manifest hash：`sha256:69446284fe507e1dac4c21e965143abb4aab26e61fdcd8056cbfd7301f167f27`
- activation manifest file hash：`sha256:f83b91b36b2d1fcba9f7522949939ac165c9dd8ed548a63474a4ba8e45de2b6f`

Clock 與 activation custody 均為 create-only；舊 `clock:prospective:20260819:v1`、8/25、8/27 與 8/28 clocks 未修改。市場 DB 未刪除、未覆寫；2026-08-25 有 `1955` rows／`1955` distinct symbols，正是 8/26 Portfolio 所需 T-1。

## 官方交易日證據

- TWSE：[holidaySchedule](https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule)，1150826 無 holiday row；response hash=`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`。
- TPEX：[mktCalendar 202608](https://info.tpex.org.tw/api/mktCalendar?ym=202608&lang=zh-tw)，`20260826` 存在且 `holiday=false`、`holidayList=[]`；本次 response hash=`sha256:237e3ce533e2ed10a8888f48e2323ed6f425b6f079db946d5aac19fc812107ab`。
- calendar bundle file hash=`sha256:c7da2c5d417e9cb5100a40a1225ed4ea166fb9e5a76a234836509074f868009c`。

因此 2026-08-26 是 TWSE／TPEX 共同交易日，2026-08-25 是既存、不可刪除的 causal T-1 evidence day。

## Frozen Rule identity

- strategy=`manual-rule-only-daily-rank-v1`
- policy=`foreground-owner-bound-v1`
- owner acceptance=`owner-acceptance:prospective-formal-restart:manual-rule-only-daily-rank-v1:20260821:v1`
- Champion identity hash=`sha256:cb09ef93b6442d8714d27ed0a7f92aa98fa4cc088301b5797bbadc65d10da2c8`
- policy hash=`sha256:26ac99c06b5afc60f575859730a2185fac83d7714c4369861f2b8a4fa6af4f1b`
- score config hash=`sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4`
- universe hash=`sha256:4e4d9bba29b96134fbf5b13d087cf18b9bdc0ca741af574e265b744dbb597b4b`（1932 symbols）
- source policy hash=`sha256:8ab7ec876c5ae1c60de64a05ece98598afe6118f1563b6878a7900a50d4f9cd7`
- candidate model hash=`sha256:e0b9256ad5131084e81a27c2a75b8515461985ff2781d7e0840b08ca760f50d6`（disabled）
- candidate feature hash=`sha256:92140d5b5305125095d31811b90fdf010d67e2194bc94d9af24620e9247be11b`（disabled）
- dataset hash=`sha256:d3b3e722d82114204c966ca6aa9f9e49637f91120081a9fc2aad511f1c865bc0`
- calibration policy hash=`sha256:6678938859f99421e2dbfb3f831aa5d6bb2d4ebb629385f127c9229c46f48611`
- evaluation policy hash=`sha256:5e0b4fa316f6fc318f148a3656d19956aa912485265d4bc208957833901f31dd`

Rule score、cash、成本、單檔與產業限制沿用 owner 已接受的 weekly proposal；ML candidate 不參與 Rule 排名或調參，production alpha 維持 0。

## TWSE／TPEX PIT staging

只使用 TWSE `t187ap03_L` 與 TPEX `t187ap03_O`；1932-symbol clock universe 不含興櫃，未使用 `t187ap03_R`，也未讀取 `companies.csv`。

| Source | Publication | First-seen available | Raw hash | Canonical rows hash | Registry hash |
|---|---|---|---|---|---|
| TWSE `t187ap03_L` / `twse-open-data-license-v1` | `2026-08-23T00:00:00+08:00` | `2026-08-25T13:40:58.076859+08:00` | `sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97` | `sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894` | `sha256:e74d4be2bc2f7998ac7101316554b22704578c6c16cde17034fde7312e22c386` |
| TPEX `t187ap03_O` / `tpex-open-data-license-v1` | `2026-08-24T00:00:00+08:00` | `2026-08-25T13:40:58.076859+08:00` | `sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835` | `sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5` | `sha256:cd41be8a1e755ce2387aa1cc32f8c9838207dc770246d66888a707c8c2dfac4a` |

兩份來源都在 2026-08-26 08:30 前可得，effective_from=`2026-08-26`；clock-bound coverage=`1932/1932`，staging file hash=`sha256:30e09b71d1415c63d690df048848a3026d8779cdfbbe4882e9c59c686be967b7`。Staging 仍是 `formal_consumer_compatible=false`，只在 09:00 transaction 中轉成正式 PIT manifest。

## Readiness 與一次性排程

- deferred readiness=`ready_for_future_activation`，hash=`sha256:14e11dbaaf45e1b0f38a48d4017bff64584c96e79f5e330487d1d8001f0ba6dc`，file hash=`sha256:fa973e55c0984859a75e91f12e812c36b2d50fd74eaad0a141f09858ab7a13e7`。
- strict pre-activation baseline=`waiting_for_prospective_inputs`，0/3 ready，hash=`sha256:b3c78a739c5e0f72235d3860c2af044ced8aef94d03a82e28bf2b5162e55d3eb`。
- 三個 `BALDR_ML_FORMAL_*` path 均 configured 但 file missing；controlled store 與 HMAC secret store configured。只記錄布林狀態，未輸出 secret。
- Codex automation `prospective-formal-20260826-one-shot-activation` 已實際註冊為 `ACTIVE`，在 2026-08-26 09:00 Asia/Taipei 執行一次後結束；不是 suggestion card，也不是每日循環。電腦與 Codex desktop 必須在執行時間保持開啟。
- 一次性 runner 只在真實 09:00 後使用 8/25 T-1；PIT／Rule／Portfolio 先進隔離 staging，三份均通過 strict readiness 才一起 publish。失敗時 rollback staging publication，不留 partial formal output。

## Pre-open QA 與安全狀態

- same-day clock／publisher／activation／one-shot tests：`42 passed`。
- clock loader focused rerun：`19 passed`。
- prospective／formal simulated portfolio regression：`131 passed`。
- changed files `py_compile`：passed。
- full prescribed package mypy：`0 issues`（515 source files）。
- Look-ahead：Rule SQL 固定 `date < 2026-08-26`；Portfolio 固定 2026-08-25 T-1 cash seed；PIT source first-seen 早於 08:30；不讀 same-day close、Teacher target 或 matured outcome。
- `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`promotion_eligible=false`、`broker_order_allowed=false`。

三份正式 manifests 與 final strict readiness 要到真實 09:00 transaction 完成後才能記為 ready；本 pre-open record 不提前宣稱 3/3。

## Rollback

Repo contract 變更以 `git revert 0f536d3` 回復；文件以後續獨立 docs commit 回復。外部 `clock-20260826-v1` 是 create-only custody，不覆寫或刪除；若 activation 失敗，保留 clock／raw／staging bytes，停止 consumer adoption並記錄失敗。不得用 `git reset --hard`、不得刪除 8/25 DB rows，也不得將失敗 artifact 改名為 Formal。
