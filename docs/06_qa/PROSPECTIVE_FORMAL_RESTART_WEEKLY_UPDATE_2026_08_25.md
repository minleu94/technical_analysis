# Prospective Formal Restart Weekly Update（2026-08-25）

> 報告自然週：`2026-08-18` 至 `2026-08-24`
>
> 報告截止：`2026-08-25T13:56:45+08:00`（Asia/Taipei，2026-08-28 activation 前）
>
> 狀態：`planned_clock_created / champion_accepted / source_staged / strict_readiness_pending`
>
> 本文件是工程與治理狀態週報，不是 Formal OOS、shadow maturity、promotion 或 broker approval，也不替未完成的 weekly evidence review 寫入 gate history。

## 本週結論

- 2026-08-19 已鎖定 Prospective Formal Restart 方向：舊 `clock:prospective:20260819:v1` 只保留歷史追溯，不重建、不沿用、不回填；所有既有 research／history／current snapshot 不改名為 Formal。
- Owner 已接受唯一 Rule Champion identity：`manual-rule-only-daily-rank-v1` + `foreground-owner-bound-v1`。owner acceptance decision id=`owner-acceptance:prospective-formal-restart:manual-rule-only-daily-rank-v1:20260821:v1`，Champion identity hash=`sha256:cb09ef93b6442d8714d27ed0a7f92aa98fa4cc088301b5797bbadc65d10da2c8`。
- 舊 successor `clock:prospective:20260825:v1` 只保留 immutable 歷史追溯；其 clock file hash=`sha256:6313c6a8fa3f7e28c78db2e62cbfff1de24708667eabc1b8e58dc92d5a82b943`，不重建、不沿用、不回填。
- 新 clock `clock:prospective:20260828:v1` 已 create-only 建立：activation trading day=`2026-08-28`，完整準備日=`2026-08-27`，PIT decision boundary=`08:30:00`，owner-bound Rule／Portfolio decision boundary=`09:00:00 Asia/Taipei`。clock manifest hash=`sha256:dfcd95b89f02cf1e68de945525694d0d912fd37b138e17c04b5506c7e2655f6d`，file hash=`sha256:85d50c270d9a10098e4e99d4531b0b3ce96eb096797977ab64349bc164c90161`。
- 2026-08-25 已完成 TWSE／TPEX source staging 與 deferred activation custody；截至報告截止時間三份正式 input 仍為 `0/3`，strict readiness 仍 `waiting_for_prospective_inputs`，不把 staging／deferred bytes 當成 formal evidence。

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
| clock manifest | `clock:prospective:20260828:v1` | `sha256:dfcd95b89f02cf1e68de945525694d0d912fd37b138e17c04b5506c7e2655f6d` |
| clock file | `clock/manifest.json` | `sha256:85d50c270d9a10098e4e99d4531b0b3ce96eb096797977ab64349bc164c90161` |
| Rule policy | `foreground-owner-bound-v1` | `sha256:26ac99c06b5afc60f575859730a2185fac83d7714c4369861f2b8a4fa6af4f1b` |
| score config | deterministic manual rank | `sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4` |
| universe | 1932 symbols | `sha256:4e4d9bba29b96134fbf5b13d087cf18b9bdc0ca741af574e265b744dbb597b4b` |
| source policy | official PIT source rules | `sha256:8ab7ec876c5ae1c60de64a05ece98598afe6118f1563b6878a7900a50d4f9cd7` |
| evaluation policy | frozen evaluation rules | `sha256:5e0b4fa316f6fc318f148a3656d19956aa912485265d4bc208957833901f31dd` |
| calibration policy | frozen policy, not passed | `sha256:cba6e1859aa258d0ffc0dcb7758d81d6782b913d8b56549aec89e67bbf61f9f7` |
| candidate model | disabled challenger identity | `sha256:e0b9256ad5131084e81a27c2a75b8515461985ff2781d7e0840b08ca760f50d6` |
| candidate feature manifest | disabled challenger features | `sha256:92140d5b5305125095d31811b90fdf010d67e2194bc94d9af24620e9247be11b` |
| dataset identity | frozen dataset custody | `sha256:d3b3e722d82114204c966ca6aa9f9e49637f91120081a9fc2aad511f1c865bc0` |

## 官方日曆與 PIT source lineage

### Clock calendar

- 官方 evidence：TWSE `holidaySchedule/holidaySchedule` 與 TPEX `mktCalendar 202608` cross-check。
- `2026-08-28` 判定為共同交易日，`2026-08-27` 保留為至少一個完整準備日；TWSE response hash=`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`，TPEX response hash=`sha256:8ec36f00753c2a8903ff844fb568235a8fee2f7603feed820ccc2599a28aa463`。

### Official company master sources

| Market | Source／license | Raw custody | Official publication field | Canonical custody |
|---|---|---:|---|---|
| 上市 | [TWSE `t187ap03_L`](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)，license=`twse-open-data-license-v1`（[license](https://openapi.twse.com.tw/)） | 1,327,422 bytes；1,095 raw rows；raw hash=`sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97` | `出表日期=1150823` → `2026-08-23T00:00:00+08:00` | canonical hash=`sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894` |
| 上櫃 | [TPEX `t187ap03_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)，license=`tpex-open-data-license-v1`（[license](https://www.tpex.org.tw/openapi/)） | 1,070,712 bytes；890 raw rows；raw hash=`sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835` | `Date=1150824` → `2026-08-24T00:00:00+08:00` | canonical hash=`sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5` |

- source metadata hash=`sha256:1544e82b1bfb8e142d101d8c12717891a36531c3c931415a8eaed237706497fc`；raw bytes 的 available_at=`2026-08-25T05:17:05.4982984+08:00`；effective_from=`2026-08-28`；canonical capture 覆蓋 clock universe=`1932/1932`。
- clock universe 不含興櫃，故沒有呼叫或註冊 TPEX `t187ap03_R`。source registry、first-seen capture producer、raw／canonical hash、publication／available／effective、license 與 clock／universe lineage 均保留在受控 staging；截至本週報截止不宣稱為正式 PIT manifest。

## Readiness、測試與 gates

### Strict readiness

- `rule_champion_history/manifest.json`：尚未到 2026-08-28 09:00 owner-bound decision，未建立。
- `portfolio_ledger/manifest.json`：尚未有 2026-08-27 T-1 state，未建立。
- `pit_sector_membership/manifest.json`：尚未到 2026-08-28 08:30 PIT boundary，未建立；現有 PIT bytes 仍標記 `formal_consumer_compatible=false` staging。
- 結果：`0/3`，`waiting_for_prospective_inputs`；三份 input 不可 partial start。controlled store 與 HMAC secret store 僅顯示 configured，沒有輸出 secret。
- 受控 market DB `daily_prices` 最新 session=`2026-08-24`；這是目前可證明的最新資料，不能提前宣稱 2026-08-27 T-1，也不以回填、watcher 或人工拼接解決。
- activation environment preflight：三個 BALDR formal path 均 configured，但目前檔案不存在且尚未綁定 `clock-20260828`；controlled store／HMAC secret store configured，secret 未輸出。這是 activation 前的一次性 path binding，不是修改既有 clock 的理由。
- deferred readiness hash=`sha256:8790853c60ad7167ac15d1bc66c1e07388876f35b2dfbf68de865dd8c148eca4`；strict pre-activation readiness hash=`sha256:a3bd7d26c660f4d05bf56fbcd20d3f1a3c301efa9995b190457cd885762f1909`；activation custody hash=`sha256:4c32ff3502d338da5d48880a2e5092046f13e50723e383be532eeee05d181218`。

### 已執行／已完成的 QA

- focused prospective tests：`51 passed`。
- prospective regression suite：`108 passed`。
- changed Python files `py_compile`：通過。
- changed source `mypy data_module development_module`：`0 issues`（117 files）。
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

待 2026-08-28 真實 08:30／09:00 boundary、2026-08-27 T-1、controlled path 一次性綁定與當日 source lineage 均合法，再依序：重新確認官方 raw bytes → 產生正式 PIT manifest → 取得 owner-bound Rule snapshot 後產生 clock-bound Rule history → 產生首日 simulated Portfolio transition → 三份一起執行 strict readiness。現有 scripts 已是低 CPU 單次入口；本週不註冊新的持續排程。任一 input 缺失或 schema／source／時間／代碼不成立仍必須 fail closed，不能用人工 bypass。

本週及 activation pre-open 沒有：回填過去日期、修改舊 clock、使用 `companies.csv` 回填 sector、啟動 legacy Direct／OOC watcher、training／retraining、promotion、Recommendation／Advice／正式 Portfolio ML 權重變更、broker adapter、下單、自動再平衡或自動平倉。

## 變更與回滾

- Repo 分批提交：`73433d6`（split PIT／owner decision boundaries）、`cc831b1`（split clock staging record）、`4cbae9f`（readiness routes PIT boundary）、`49f7bc2`（readiness rollback／compatibility documentation）、`4887362`（split timestamp focused tests）；本週報本次修正另以 docs commit 保存。
- 受控 D 槽資料採 create-only／append-only；外部 artifact 失敗時保留 immutable bytes、停止 consumer 採用並建立 successor clock，不刪除或覆寫原始資料。舊 `clock-20260819` 不變更。
- Repo 回滾採逐一 `git revert <docs-commit>` 或依檔案 review 後 revert，不使用 `git reset --hard`／`git checkout --` 覆寫其他工作；本週報不會藉回滾刪除外部受控資料。
