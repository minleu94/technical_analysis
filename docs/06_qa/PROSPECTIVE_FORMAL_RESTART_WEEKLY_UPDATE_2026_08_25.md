# Prospective Formal Restart Weekly Update（2026-08-25）

> 報告自然週：`2026-08-18` 至 `2026-08-24`
>
> 報告截止：`2026-08-25T14:21:00+08:00`（Asia/Taipei，2026-08-27 successor activation 前）
>
> 狀態：`successor_clock_created / champion_accepted / source_staged / strict_readiness_pending`
>
> 本文件是工程與治理狀態週報，不是 Formal OOS、shadow maturity、promotion 或 broker approval，也不替未完成的 weekly evidence review 寫入 gate history。

## 本次週報更正（2026-08-25 14:21 Asia/Taipei）

前一版把 successor 往 2026-08-28 延後，與本任務的最近合法未來日期原則不一致。本版以實際執行時間重算：2026-08-25 已過 activation boundary，不能把 09:00 owner-bound decision 倒填回既有 8/25 clock；因此建立距離最近、仍保留 2026-08-26 完整準備日的 `clock:prospective:20260827:v3`。v2 因 calibration clock identity mismatch 已被 validator 拒絕並標記 superseded；既有 8/25 PIT sidecar 保留 immutable 追溯，不修改、不重新掛接成 split-time formal set。

## 本週結論

- 2026-08-19 已鎖定 Prospective Formal Restart 方向：舊 `clock:prospective:20260819:v1` 只保留歷史追溯，不重建、不沿用、不回填；所有既有 research／history／current snapshot 不改名為 Formal。
- Owner 已接受唯一 Rule Champion identity：`manual-rule-only-daily-rank-v1` + `foreground-owner-bound-v1`。owner acceptance decision id=`owner-acceptance:prospective-formal-restart:manual-rule-only-daily-rank-v1:20260821:v1`，Champion identity hash=`sha256:cb09ef93b6442d8714d27ed0a7f92aa98fa4cc088301b5797bbadc65d10da2c8`。
- 舊 successor `clock:prospective:20260825:v1` 只保留 immutable 歷史追溯；其 clock file hash=`sha256:6313c6a8fa3f7e28c78db2e62cbfff1de24708667eabc1b8e58dc92d5a82b943`，不重建、不沿用、不回填。
- 新 successor `clock:prospective:20260827:v3` 已 create-only 建立：activation trading day=`2026-08-27`，完整準備日=`2026-08-26`，PIT decision boundary=`08:30:00`，owner-bound Rule／Portfolio decision boundary=`09:00:00 Asia/Taipei`。clock manifest hash=`sha256:43d3872b4646d7565762a16104e9e53302885adcad0ad6a7596ce75853806882`，file hash=`sha256:4387ba3809b86c053b32833732e2640044d181cc377b319ee1b9933afeee68db`。
- 2026-08-25 已完成 v3 TWSE／TPEX raw custody 與 preactivation staging；staging file hash=`sha256:7c9f915b16122892a7db8d740605bac6432a465f0118470f8aa8f7c09ea1c3fb`、1932/1932 rows。deferred readiness 已為 `ready_for_future_activation`，三份 v3 正式 input 尚未到達 8/27 真實 boundary；不把 staging／deferred bytes 當成 formal evidence。

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
| clock manifest | `clock:prospective:20260827:v3` | `sha256:43d3872b4646d7565762a16104e9e53302885adcad0ad6a7596ce75853806882` |
| clock file | `clock/manifest.json` | `sha256:4387ba3809b86c053b32833732e2640044d181cc377b319ee1b9933afeee68db` |
| Rule policy | `foreground-owner-bound-v1` | `sha256:26ac99c06b5afc60f575859730a2185fac83d7714c4369861f2b8a4fa6af4f1b` |
| score config | deterministic manual rank | `sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4` |
| universe | 1932 symbols | `sha256:4e4d9bba29b96134fbf5b13d087cf18b9bdc0ca741af574e265b744dbb597b4b` |
| source policy | official PIT source rules | `sha256:8ab7ec876c5ae1c60de64a05ece98598afe6118f1563b6878a7900a50d4f9cd7` |
| evaluation policy | frozen evaluation rules | `sha256:5e0b4fa316f6fc318f148a3656d19956aa912485265d4bc208957833901f31dd` |
| calibration policy | v3 frozen policy, not passed | `sha256:86af3d00e46bd2b8c2f029693efe2926def0c141d81facf45a5baae03a74b6d5` |
| candidate model | disabled challenger identity | `sha256:e0b9256ad5131084e81a27c2a75b8515461985ff2781d7e0840b08ca760f50d6` |
| candidate feature manifest | disabled challenger features | `sha256:92140d5b5305125095d31811b90fdf010d67e2194bc94d9af24620e9247be11b` |
| dataset identity | frozen dataset custody | `sha256:d3b3e722d82114204c966ca6aa9f9e49637f91120081a9fc2aad511f1c865bc0` |

## 官方日曆與 PIT source lineage

### Clock calendar

- 官方 evidence：TWSE `holidaySchedule/holidaySchedule` 與 TPEX `mktCalendar 202608` cross-check。
- `2026-08-27` 判定為共同交易日，`2026-08-26` 保留為至少一個完整準備日；TWSE response hash=`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`，TPEX response hash=`sha256:8ec36f00753c2a8903ff844fb568235a8fee2f7603feed820ccc2599a28aa463`。

### Official company master sources

| Market | Source／license | Raw custody | Official publication field | Canonical custody |
|---|---|---:|---|---|
| 上市 | [TWSE `t187ap03_L`](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)，license=`twse-open-data-license-v1`（[license](https://openapi.twse.com.tw/)） | 1,327,422 bytes；1,095 raw rows；raw hash=`sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97` | `出表日期=1150823` → `2026-08-23T00:00:00+08:00` | canonical hash=`sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894` |
| 上櫃 | [TPEX `t187ap03_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)，license=`tpex-open-data-license-v1`（[license](https://www.tpex.org.tw/openapi/)） | 1,070,712 bytes；890 raw rows；raw hash=`sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835` | `Date=1150824` → `2026-08-24T00:00:00+08:00` | canonical hash=`sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5` |

- raw bytes 的 available_at=`2026-08-25T05:17:05.498298+08:00`；v2 staging effective_from=`2026-08-27`；canonical capture 覆蓋 clock universe=`1932/1932`，staging package 尚未升格為 formal PIT。
- clock universe 不含興櫃，故沒有呼叫或註冊 TPEX `t187ap03_R`。source registry、first-seen capture producer、raw／canonical hash、publication／available／effective、license 與 clock／universe lineage 均保留在受控 staging；截至本週報截止不宣稱為正式 PIT manifest。

## Readiness、測試與 gates

### Strict readiness

- `rule_champion_history/manifest.json`：尚未到 2026-08-27 09:00 owner-bound decision，未建立。
- `portfolio_ledger/manifest.json`：尚未有 2026-08-26 T-1 state，未建立。
- `pit_sector_membership/manifest.json`：尚未到 2026-08-27 08:30 PIT boundary，未建立；v2 staging 明確為 `formal_consumer_compatible=false`。
- v3 deferred readiness：`ready_for_future_activation`，3 input deferred，readiness hash=`sha256:3cd4ddb22678378dc1853b6df7ea05ea5f4f3f39a976c0792fa8eb0699d750ad`；strict readiness 尚未啟動，因三份正式 input 仍不存在。到 activation 時必須以同一 timestamp contract 執行，禁止 partial start。controlled store 與 HMAC secret store 僅顯示 configured，沒有輸出 secret。
- 受控 market DB `daily_prices` 目前已確認至 `2026-08-24`；8/27 activation 所需的 8/26 T-1 尚未存在，不能提前宣稱，也不以回填、watcher 或人工拼接解決。
- activation environment preflight：三個 BALDR formal path 均 configured，但尚未綁定 v2 formal files；controlled store／HMAC secret store configured，secret 未輸出。這是 activation 前的一次性 path binding，不是修改既有 clock 的理由。
- v3 activation custody：`scheduled`，activation manifest hash=`sha256:2391875ddd031b55d2c8b3557038d96a485a491d58902d168c6b06b2b52ba45f`；不以 8/28 successor 或 rejected v2 的 readiness bytes 冒充 v3。

### 已執行／已完成的 QA

- focused prospective tests：`51 passed`。
- prospective regression suite：`108 passed`。
- combined prospective／formal simulated-ledger recheck：`114 passed`。
- changed Python files `py_compile`：通過。
- Portfolio clock-bound decision-time regression：`6 passed`。
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

待 2026-08-27 真實 08:30／09:00 boundary、2026-08-26 T-1、controlled path 一次性綁定與當日 source lineage 均合法，再依序：重新確認官方 raw bytes → 產生正式 PIT manifest → 取得 owner-bound Rule snapshot 後產生 clock-bound Rule history → 產生首日 simulated Portfolio transition → 三份一起執行 strict readiness。現有 scripts 已是低 CPU 單次入口；本週不註冊新的持續排程。任一 input 缺失或 schema／source／時間／代碼不成立仍必須 fail closed，不能用人工 bypass。

本週及 activation pre-open 沒有：回填過去日期、修改舊 clock、使用 `companies.csv` 回填 sector、啟動 legacy Direct／OOC watcher、training／retraining、promotion、Recommendation／Advice／正式 Portfolio ML 權重變更、broker adapter、下單、自動再平衡或自動平倉。

## 2026-08-27 pre-activation continuation addendum（06:41 Asia/Taipei）

- 本次唯讀核對顯示台北時間為 `2026-08-27T06:41`；尚未到 v3 的 PIT `08:30` 或 owner-bound Rule／Portfolio `09:00` boundary。`clock:prospective:20260827:v3` 仍為唯一待啟用 successor，activation=`2026-08-27`、完整準備日=`2026-08-26`。
- 受控唯讀 market DB `daily_prices` 已有 exact 2026-08-26 T-1 state（`1966` rows），最新日期為 `20260826`；本次未刪除、未 drop、未覆寫、未回填，也未把資料庫改成符合日期的假資料。
- v3 `pit_sector_membership/manifest.json`、`rule_champion_history/manifest.json`、`portfolio_ledger/manifest.json` 與 `readiness/strict_readiness.json` 目前均不存在，`.activation_staging` 亦不存在；因此目前仍是 `0/3` formal inputs，沒有 partial start 或假冒 Formal evidence。
- 一次性 completion heartbeat 仍為 ACTIVE；它只在真實 09:00 後呼叫既有低 CPU atomic runner，並在所有三份 input 完整後才建立 strict readiness。本週沒有新增持續排程，也沒有啟動 Direct／OOC watcher、training、retraining、promotion 或 broker。
- 本 addendum 只校正截至目前的 current status，不改寫前述 8/26 activation miss、v3 staging、官方日曆與 immutable custody 歷史證據；若 activation 成功，另以實際 timestamp、manifest hash 與 readiness hash 追加結果。

## 變更與回滾

- Repo 分批提交：`73433d6`（split PIT／owner decision boundaries）、`cc831b1`（split clock staging record）、`4cbae9f`（readiness routes PIT boundary）、`49f7bc2`（readiness rollback／compatibility documentation）、`4887362`（split timestamp focused tests）；本次 Portfolio clock-bound fix 與 v2 文件另以後續 commits 保存。
- 受控 D 槽資料採 create-only／append-only；外部 artifact 失敗時保留 immutable bytes、停止 consumer 採用並建立 successor clock，不刪除或覆寫原始資料。舊 `clock-20260819` 與 8/25、8/27 v1 不變更。
- Repo 回滾採逐一 `git revert <docs-commit>` 或依檔案 review 後 revert，不使用 `git reset --hard`／`git checkout --` 覆寫其他工作；本週報不會藉回滾刪除外部受控資料。

## Activation handoff preparation addendum（2026-08-26 01:56 Asia/Taipei）

- 唯讀重新取得台北時間為 `2026-08-26T01:56:58+08:00`；v3 activation 仍是 `2026-08-27`，因此尚未產生任何三份 formal manifest，也沒有把 deferred/staging input 宣稱為 ready。
- `development_module/prospective_rule_only_decision.py` 與 `scripts/run_prospective_rule_only_decision.py` 已接上 v3 owner acceptance、frozen universe、T-1 `daily_prices`、受控 HMAC artifact 與 exact safety flags；Rule observation 允許在 09:00 boundary 後真實取得，但不可早於 boundary。
- `scripts/run_prospective_formal_activation_once.py` 已準備低 CPU 單次入口：官方 PIT → owner-bound Rule history → T-1 simulated Portfolio → strict readiness；所有 formal output create-only，任何既有 output、source、schema、T-1 或 HMAC 不成立即停止。
- Rule coverage 的唯讀 probe 發現 `1341` 有無成交列缺少 close；producer 不前填、不補造數值，只從固定 60-session causal window 取最近 20 個有效觀測。probe 在目前資料下仍覆蓋 frozen 1,932 symbols；此 probe 不是 Formal evidence，activation 時會重新讀取實際 T-1。
- Portfolio capture CLI 已改用 activation-time clock loader；既有 clock bytes、market DB 與外部 raw custody 均未覆寫。上述新增程式可逐一 revert；外部 v3 artifact 若失敗則保留 immutable bytes，改用 successor clock 回滾 consumer adoption。

## Owner same-day pre-open override addendum（2026-08-26 05:45 Asia/Taipei）

- Owner 明確要求排除本 clock 的完整自然準備日循環延期。較新的具體授權已在權威方向文件記為只限 2026-08-26、08:30 前、具名、不可回填的窄例外；不改變其他 clock，也不放寬 PIT／T-1／strict readiness／ML／promotion／broker Gate。
- 新 `clock:prospective:20260826:v1` 已 create-only 建立；clock manifest hash=`sha256:5409fe23d5247dc1698af09a5af9295ad8f7ad3f02c6926233582e11e93efde7`、file hash=`sha256:c8ee8be95936adf48637d9077351bb90ee33b9bf8cc27b7c86780523f0c05784`。8/27 v3 與 8/28 v1 均保持 immutable，不刪除、不改掛。
- 8/25 market DB 已有 1,955 rows／1,955 symbols，直接成為 8/26 T-1；沒有 drop、回填或 same-day close。官方 calendar 證明 8/26 是 TWSE／TPEX 共同交易日。
- 官方 PIT raw first-seen 為 2026-08-25 13:40:58+08:00，早於 8/26 PIT boundary；新 clock staging coverage=`1932/1932`、file hash=`sha256:30e09b71d1415c63d690df048848a3026d8779cdfbbe4882e9c59c686be967b7`。
- 一次性 Codex automation `prospective-formal-20260826-one-shot-activation` 已實際註冊為 `ACTIVE`，於 8/26 09:00 Asia/Taipei 執行一次，不是 suggestion card 或每日排程。三份正式 inputs 與 strict readiness 仍須等真實 09:00 transaction；pre-open 維持 0/3，不提前冒充 Formal。
- 完整 hash、source lineage、QA、rollback 與安全狀態見 [2026-08-26 same-day staging record](PROSPECTIVE_FORMAL_RESTART_CLOCK_2026_08_26_STAGING.md)。

## 2026-08-27 activation attempt and validator repair（09:00 Asia/Taipei）

- 依 v3 heartbeat 在台北時間 `2026-08-27T09:00:10+08:00` 以實際時間執行一次且僅一次 `scripts/run_prospective_formal_activation_once.py`；唯讀 market DB 的 exact `2026-08-26` T-1 已確認為 `1,966` rows，未修改、刪除、drop 或回填。
- activation 在正式 publish 前 fail closed，錯誤為 `ProspectiveSimulatedLedgerManifestError: ledger must contain transitions and a positive non-cash state day count`。四個正式 output（Rule／Portfolio／PIT／strict readiness）均不存在；本次建立的空 `.activation_staging` 父目錄已清除，故沒有 partial formal output 或 readiness credit。
- 根因是 `summarize_simulated_ledger()` 將 `non_cash_state_day_count` 計算在 cash-only T-1 `input_state`，而 prospective 首筆 transition 的合法語意是 cash seed input → non-cash decision-date output。已修正為計算 `output_state`，並保留 append-only、T-1、hash chain 與 future-input guards。
- 修正後 activation／ledger／manifest／readiness focused suite=`27 passed`；changed Python `py_compile`、full mypy（`515` files）、`check_look_ahead_bias.py` 與 `quant_guard_linter.py` 均通過。新增 regression 覆蓋單筆 cash-seed→non-cash-output manifest。
- 本次一次性 heartbeat 已消耗且不重跑 runner；因此 v3 目前仍是 `0/3` formal inputs、strict readiness 未建立。calibration、shadow maturity、Formal OOS、promotion、ML alpha 與 broker gates 均維持未通過／關閉；未啟動 Direct／OOC、training、retraining、promotion 或 broker。

## 2026-08-27 current continuation and next legal activation（15:10 Asia/Taipei）

- 本週報不把 8/27 失敗的一次性 heartbeat 重算為 Formal evidence：根因已在 `2f13df0` 修正，`4338fe1` 已記錄實際 failure、零 partial output 與回滾邊界。v3 四個 formal output 仍不存在，strict readiness 未建立。
- 8/27 15:10 的唯讀核對確認，下一個合法 prospective clock 是既有 create-only `clock:prospective:20260828:v1`：activation=`2026-08-28`、完整 preparation day=`2026-08-27`、PIT=`08:30`、Rule／Portfolio=`09:00` Asia/Taipei；clock hash=`sha256:dfcd95b89f02cf1e68de945525694d0d912fd37b138e17c04b5506c7e2655f6d`，file hash=`sha256:85d50c270d9a10098e4e99d4531b0b3ce96eb096797977ab64349bc164c90161`。
- 官方日曆現行重查：TWSE holiday schedule response hash=`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`，1150828 無 holiday row；TPEX 202608 calendar response hash=`sha256:153d3d091a2d84befe33cc7fcc6a230360df7086753ef5a21afe0cc56d347f84`，20260828=`holiday=false`、`holidayList=[]`。這是日曆證據重查，不是回填或改寫舊 clock。
- 受控唯讀 market DB 目前最新為 `20260826`；20260826=`1,966` rows、20260827=`0` rows。因此 8/28 的 Portfolio manifest 仍待自然資料流程產生 8/27 T-1；本 restart 不會修改或捏造 market DB。這是唯一尚未滿足的 activation-time data prerequisite。
- 已建立一次且僅一次的 Codex heartbeat `Prospective Formal 20260828 one-shot activation`，於 8/28 09:00 Asia/Taipei 執行同一低 CPU runner；它會先唯讀確認 T-1，成功時以 atomic staging transaction 同步產生 Rule／Portfolio／PIT 與 strict readiness，失敗時維持 `0/3`，不留下 partial input。
- 8/28 PIT staging 維持 TWSE `t187ap03_L`／TPEX `t187ap03_O`，1932/1932 coverage；raw hashes 分別為 `sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97` 與 `sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835`，canonical hashes 分別為 `sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894` 與 `sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5`；沒有使用 `t187ap03_R`，沒有使用 `companies.csv`。
- 本次續行仍維持 `formal_oos_allowed=false`、ML alpha=`0`、`promotion_eligible=false`、`broker_order_allowed=false`；calibration、shadow maturity、promotion 與 broker gates 未通過，且未啟動 Direct／OOC watcher、training、retraining、promotion 或 broker adapter。

## 2026-08-28 one-shot activation outcome（09:01:50 Asia/Taipei）

- activation preflight 於 `2026-08-28T09:01:27.687113+08:00` 取得台北時間；未修改 market DB。exact `2026-08-27` T-1 已自然存在，為 `1,961` rows／`1,961` symbols，並為 latest date；8/28 共同交易日與 8/27 完整 preparation day 沿用既有 TWSE／TPEX 官方日曆證據。
- 既有 `clock:prospective:20260828:v1` 僅執行一次 atomic runner；結果在正式 publish 前 `status=blocked`，錯誤為 `staged strict readiness did not reach ready after all three manifests`。正式 Rule／Portfolio／PIT／strict readiness 保持 `0/3`、無 partial output，未重跑、未手動偽造。
- 三個 producer 的唯讀 diagnostic 均通過 validator：ledger `1` decision date／`1` non-cash state day，ledger manifest hash=`sha256:1264949e65bccf174e8b94204418f9bb6d07b5b65f208bc2eae2f449f9bf667e`；Rule `1` snapshot 且 HMAC attestation present（只確認狀態，未輸出 secret）；PIT `1,932` rows，官方 source ids=`official:tpex:t187ap03_O`／`official:twse:t187ap03_L`，canonical hash=`sha256:5c01b1b56b0f597ccd05b449e7b6e8b754e20cb49b7c93fdd193712dd825b7b2`、rows hash=`sha256:532c647adefe889f6cfd078393682e1fda1aeb550984562c373f5fe7dc11aa09`。
- 根因是 readiness status contract bug：三項全 ready 時錯誤回傳 `ready_for_future_activation`，runner 只接受 `ready`。已修正 strict/deferred status 分流並加入 regression test；修正後 focused tests=`29 passed`、py_compile 通過、mypy=`118 source files / no issues`、no-look-ahead 與 quant guard 通過。由於本 automation 已消耗其唯一 execution，不在本次 heartbeat 重跑 runner。
- calibration、shadow maturity、Formal OOS、promotion 與 broker gates 仍未通過／關閉；安全旗標維持 `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`promotion_eligible=false`、`broker_order_allowed=false`。未啟動 Direct／OOC watcher、training、retraining、promotion 或 broker adapter。
