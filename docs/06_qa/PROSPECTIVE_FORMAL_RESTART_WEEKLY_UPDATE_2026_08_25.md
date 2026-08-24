# Prospective Formal Restart Weekly Update（2026-08-25）

> 報告自然週：`2026-08-18` 至 `2026-08-24`
>
> 報告截止：`2026-08-25T05:21:31+08:00`（Asia/Taipei，activation day 開盤前）
>
> 狀態：`planned_clock_created / champion_accepted / source_staged / strict_readiness_pending`
>
> 本文件是工程與治理狀態週報，不是 Formal OOS、shadow maturity、promotion 或 broker approval，也不替未完成的 weekly evidence review 寫入 gate history。

## 本週結論

- 2026-08-19 已鎖定 Prospective Formal Restart 方向：舊 `clock:prospective:20260819:v1` 只保留歷史追溯，不重建、不沿用、不回填；所有既有 research／history／current snapshot 不改名為 Formal。
- Owner 已接受唯一 Rule Champion identity：`manual-rule-only-daily-rank-v1` + `foreground-owner-bound-v1`。owner acceptance decision id=`owner-acceptance:prospective-formal-restart:manual-rule-only-daily-rank-v1:20260821:v1`，Champion identity hash=`sha256:cb09ef93b6442d8714d27ed0a7f92aa98fa4cc088301b5797bbadc65d10da2c8`。
- 新 clock `clock:prospective:20260825:v1` 已 create-only 建立：activation trading day=`2026-08-25`，完整準備日=`2026-08-24`，decision time=`08:30:00 Asia/Taipei`。這是 8/25 開盤前的 planned identity，不把尚未到達的決策時間或未生成的 input 當成 evidence。
- 2026-08-25 05:17 左右已完成 TWSE／TPEX activation-only raw source staging；截至報告截止時間三份正式 input 為 `0/3`，strict readiness 仍 `waiting_for_prospective_inputs`。

## Rule Champion 與 frozen identities

### 首選

`manual-rule-only-daily-rank-v1` + `foreground-owner-bound-v1`

- score：base `5000bp`；trend clamp `±2500bp`；momentum clamp `±2500bp`；volume delta `/2` clamp `±1000bp`；final clamp `0..10000bp`；排序為 score descending、symbol ascending；capacity=`1`。
- causal input：只使用 `daily_prices.date < decision_session_date`；20-session ranking history、60-session source window；不使用當日或未來資料。
- Portfolio policy：`paper-portfolio-policy-v2.4`；初始現金 `500000`、min cash `2000bp`、max positions `8`、max single `1500bp`、max sector `3000bp`、target band `300bp`、min trade `200bp`、weekly turnover `2000bp`、cooldown `5 sessions`。
- cost／risk：slippage `10bp/side`、commission `15bp/side`、sell tax `30bp/side`；virtual notional=`50000000` minor units；不建立 broker adapter、不下單、不自動再平衡或平倉。
- 可重播性與穩定性：固定版本、固定排序、Decimal／bp 邊界與 clock-bound identity，適合在正式 input 齊全後重播。資料覆蓋改由當日官方 source custody 驗證；截至本報告尚無正式 post-cost observation，不能用尚未存在的結果宣稱績效優勢。

### 替代方案與排除理由

- `formal-rule-only-20260807-r1`：只保留為既有歷史 Rule-only lane；它綁定舊 session，不能重建、沿用或回填到新 clock。
- ML／research blend：不列入候選，因本 restart 固定 ML alpha=`0`、`formal_oos_allowed=false`，且不得用 ML candidate 的 Formal OOS 結果調整或弱化 Rule baseline。

### Look-ahead bias 自查

- 訊號、排名、特徵與來源窗均以 `daily_prices.date < decision_session_date` 約束；不讀取 same-day close、future teacher target、matured outcome 或未來 sector snapshot。
- 產業歸屬只接受 activation decision 時可得、帶 publication／available／effective lineage 的官方 TWSE／TPEX source；不得用現有 `companies.csv` 回填歷史。
- frozen candidate、score、policy、universe 與 calibration identities 在 clock 建立時固定；不以未來 Formal OOS 或當週結果反向調參。

### Frozen hashes

| Identity | Version／用途 | Hash |
|---|---|---|
| clock manifest | `clock:prospective:20260825:v1` | `sha256:7321d9d6e59acd16d96811ff5cebb58775172e64e7a2313b4f2c08b880f9b866` |
| clock file | `clock/manifest.json` | `sha256:6313c6a8fa3f7e28c78db2e62cbfff1de24708667eabc1b8e58dc92d5a82b943` |
| Rule policy | `foreground-owner-bound-v1` | `sha256:26ac99c06b5afc60f575859730a2185fac83d7714c4369861f2b8a4fa6af4f1b` |
| score config | deterministic manual rank | `sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4` |
| universe | 1932 symbols | `sha256:4e4d9bba29b96134fbf5b13d087cf18b9bdc0ca741af574e265b744dbb597b4b` |
| source policy | official PIT source rules | `sha256:8ab7ec876c5ae1c60de64a05ece98598afe6118f1563b6878a7900a50d4f9cd7` |
| evaluation policy | frozen evaluation rules | `sha256:5e0b4fa316f6fc318f148a3656d19956aa912485265d4bc208957833901f31dd` |
| calibration policy | frozen policy, not passed | `sha256:ed5313c2c946b26e2c02aeb5f0d029a678cccd882a5f7af2271fbe20f9d69aa1` |
| candidate model | disabled challenger identity | `sha256:e0b9256ad5131084e81a27c2a75b8515461985ff2781d7e0840b08ca760f50d6` |
| candidate feature manifest | disabled challenger features | `sha256:92140d5b5305125095d31811b90fdf010d67e2194bc94d9af24620e9247be11b` |
| dataset identity | frozen dataset custody | `sha256:d3b3e722d82114204c966ca6aa9f9e49637f91120081a9fc2aad511f1c865bc0` |

## 官方日曆與 PIT source lineage

### Clock calendar

- 官方 evidence：TWSE `holidaySchedule/holidaySchedule` 與 TPEX `mktCalendar 202608` cross-check。
- `2026-08-25` 判定為共同交易日，`reason_code=twse_holiday_schedule_open`；`2026-08-24` 作為至少一個完整準備日。
- calendar evidence hash=`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`。

### Official company master sources

| Market | Source／license | Raw custody | Official publication field | Canonical custody |
|---|---|---:|---|---|
| 上市 | [TWSE `t187ap03_L`](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)，license=`twse-open-data-license-v1`（[license](https://openapi.twse.com.tw/)） | 1,327,422 bytes；1,095 raw rows；raw hash=`sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97` | `出表日期=1150823` → `2026-08-23T00:00:00+08:00` | canonical hash=`sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894` |
| 上櫃 | [TPEX `t187ap03_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)，license=`tpex-open-data-license-v1`（[license](https://www.tpex.org.tw/openapi/)） | 1,070,712 bytes；890 raw rows；raw hash=`sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835` | `Date=1150824` → `2026-08-24T00:00:00+08:00` | canonical hash=`sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5` |

- source metadata hash=`sha256:1544e82b1bfb8e142d101d8c12717891a36531c3c931415a8eaed237706497fc`；raw bytes 的 available_at=`2026-08-25T05:17:05.4982984+08:00`；effective_from=`2026-08-25`；canonical capture 覆蓋 clock universe=`1932/1932`。
- clock universe 不含興櫃，故沒有呼叫或註冊 TPEX `t187ap03_R`。source registry、first-seen capture producer、raw／canonical hash、publication／available／effective、license 與 clock／universe lineage 均保留在受控 staging；截至 pre-open 不宣稱為正式 PIT manifest。

## Readiness、測試與 gates

### Strict readiness

- `rule_champion_history/manifest.json`：missing。
- `portfolio_ledger/manifest.json`：missing。
- `pit_sector_membership/manifest.json`：missing。
- 結果：`0/3`，`waiting_for_prospective_inputs`；三份 input 不可 partial start。controlled store 與 HMAC secret store 僅顯示 configured，沒有輸出 secret。
- 本機 market DB `daily_prices` 最新 session=`2026-08-21`，`2026-08-24` T-1 rows 尚不存在；不以回填、watcher 或 DB 寫入解決。

### 已執行／已完成的 QA

- focused prospective tests：`20 passed`。
- prospective regression suite：`106 passed`。
- changed Python files `py_compile`：通過。
- changed source `mypy`：`0 issues`。
- quant guard／no-look-ahead checks：通過；未新增裸 `float` 核心計算。
- 以上 QA 只證明工程與 contract；不把 fixture、staging 或 test pass 升格為 Formal evidence。

### 尚未通過 gates

| Gate | 狀態 |
|---|---|
| calibration | identity 已凍結，但 `quality_pass=false`，尚未通過 |
| shadow maturity | 尚未開始，成熟 shadow days=`0` |
| Formal OOS | `formal_oos_allowed=false` |
| promotion | `promotion_eligible=false`，未通過且禁止 |
| ML alpha | `production_blend_alpha_bp=0` |
| broker | adapter 未建立、未呼叫，`broker_order_allowed=false` |

## 下一步與禁止事項

待真實 08:30 後且 T-1、controlled paths、當日 source lineage 均合法，再依序：重新確認官方 raw bytes → 產生正式 PIT manifest → 產生 clock-bound Rule history → 產生首日 simulated Portfolio transition → 三份一起執行 strict readiness。任一 input 缺失或 schema／source／時間／代碼不成立即 fail closed；不註冊新的持續排程。

本週及 activation pre-open 沒有：回填過去日期、修改舊 clock、使用 `companies.csv` 回填 sector、啟動 legacy Direct／OOC watcher、training／retraining、promotion、Recommendation／Advice／正式 Portfolio ML 權重變更、broker adapter、下單、自動再平衡或自動平倉。

## 變更與回滾

- Repo 分批提交：`002c36c`（official PIT source custody）、`ec05c28`（clock-bound Rule universe）、`c21cd1e`（restart staging record）、`d6c611c`（rollback record correction）；本週文件與本週報另以後續 docs commit 保存。
- 受控 D 槽資料採 create-only／append-only；外部 artifact 失敗時保留 immutable bytes、停止 consumer 採用並建立 successor clock，不刪除或覆寫原始資料。舊 `clock-20260819` 不變更。
- Repo 回滾採逐一 `git revert <docs-commit>` 或依檔案 review 後 revert，不使用 `git reset --hard`／`git checkout --` 覆寫其他工作；本週報不會藉回滾刪除外部受控資料。
