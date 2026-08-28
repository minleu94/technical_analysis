# Prospective Formal Restart — 2026-08-28 staging record

日期：2026-08-25（Asia/Taipei）

## Future clock

- clock：`clock:prospective:20260828:v1`
- activation trading day：2026-08-28
- complete preparation day：2026-08-27
- PIT decision boundary：08:30:00 Asia/Taipei
- owner-bound Rule／Portfolio decision boundary：09:00:00 Asia/Taipei
- clock manifest hash：`sha256:dfcd95b89f02cf1e68de945525694d0d912fd37b138e17c04b5506c7e2655f6d`
- clock file hash：`sha256:85d50c270d9a10098e4e99d4531b0b3ce96eb096797977ab64349bc164c90161`

Clock 是 create-only、planned、prospective-only。`real_money=false`、`broker_execution=false`、`historical_backfill_claimed=false`，並持續 `formal_oos_allowed=false`、ML alpha=0、promotion=false、broker order=false。

## Calendar evidence

2026-08-28 選為 TWSE／TPEX 共同交易日，2026-08-27 保留為完整 preparation day。證據 bundle：

- TWSE holiday schedule：`https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule`
- TWSE response hash：`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`；1150827、1150828 均無 holiday row。
- TPEX calendar：`https://info.tpex.org.tw/api/mktCalendar?ym=202608&lang=zh-tw`
- TPEX response hash：`sha256:8ec36f00753c2a8903ff844fb568235a8fee2f7603feed820ccc2599a28aa463`；20260827、20260828 均 `holiday=false`、`event=false`。

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
- calibration policy hash：`sha256:cba6e1859aa258d0ffc0dcb7758d81d6782b913d8b56549aec89e67bbf61f9f7`

## Official PIT staging

來源只使用上市 TWSE `t187ap03_L` 與上櫃 TPEX `t187ap03_O`；clock universe 不包含興櫃，因此沒有使用 `t187ap03_R`。staging package 位於正式資料根目錄的 `formal_prospective/clock-20260828/staging/pit_source_staging.json`，其 `formal_consumer_compatible=false`，不能作為正式 input。

- row／expected symbol count：1932／1932
- TWSE raw hash：`sha256:9e6f88f30420552e435951193dc44094d726412c8d917d8a975581d8ae083c97`
- TPEX raw hash：`sha256:4f055c3c035d84c75b299211f36ef2dbe01b700c58c2115aeb6630c7628ce835`
- TWSE canonical rows hash：`sha256:612a8adce72c182ee2299aa84147a5c5a84588158a66187311ec168eecea5894`
- TPEX canonical rows hash：`sha256:7b7f111d5a0d9637997cae287628b6ed426b6a4afedabe62afc29ab0ab7272b5`
- licenses：`twse-open-data-license-v1`、`tpex-open-data-license-v1`
- source lineage：publication 2026-08-23／2026-08-24，available capture 2026-08-25，effective_from 2026-08-28。

未使用 `companies.csv` 回填，未建立正式 PIT manifest。

## Readiness

- deferred readiness：`ready_for_future_activation`，3/3 input deferred；hash `sha256:8790853c60ad7167ac15d1bc66c1e07388876f35b2dfbf68de865dd8c148eca4`。
- strict pre-activation readiness：`waiting_for_prospective_inputs`，0/3 ready；hash `sha256:a3bd7d26c660f4d05bf56fbcd20d3f1a3c301efa9995b190457cd885762f1909`。
- activation custody：`scheduled`，`inputs_deferred_until_activation`；hash `sha256:4c32ff3502d338da5d48880a2e5092046f13e50723e383be532eeee05d181218`。
- activation environment preflight：`waiting_for_controlled_environment`；metadata file=`metadata/activation_environment_preflight.json`，file hash=`sha256:bdfa3e943f1968cd2904b32a23260e661fa8dd81c1e0a1249ea62fcc34336861`。三個 BALDR formal path 均 configured 但目前 `file_missing`，controlled store／HMAC secret store 均 configured，未輸出 secret；本文件不修改 Windows environment。
- controlled store 與 HMAC secret store 只確認 configured；沒有輸出 secret。三個 BALDR formal path 在 activation 前保持 file_missing，不註冊新的持續排程。

## 2026-08-28 單次操作入口

到 activation day 後，依序以實際當下 timestamps 執行：

1. 在 PIT 08:30 boundary 以當下可取得的官方 TWSE／TPEX raw capture 建立 clock-bound PIT input；重新驗證 publication／available／effective lineage 與 1932 symbols。
2. 09:00 後取得真實 owner-bound Rule decision，使用已配置 controlled store 的 HMAC attestation 建立 clock-bound Rule history；不得用 staging 或 ML candidate OOS 代替。
3. 使用 2026-08-27 T-1 state 建立第一筆 09:00 simulated Portfolio transition；不得回填、不得自動下單、不得自動再平衡或平倉。
4. 只有三份正式 input 同時存在且均通過 clock／hash／look-ahead／lineage validator，才執行 strict readiness；任何一份缺失都保持 waiting，禁止 partial start。

現有 `scripts/capture_prospective_official_pit_sector.py`、`scripts/publish_prospective_rule_champion_history.py`、`scripts/publish_prospective_simulated_portfolio_ledger.py` 與 `scripts/inspect_prospective_capture_readiness.py` 可作為單次低 CPU 入口；本次沒有註冊新的 continuous scheduler 或 watcher。

## 2026-08-27 current revalidation and one-shot handoff（15:10 Asia/Taipei）

- 唯讀取得台北時間為 `2026-08-27T15:10:48+08:00`；8/27 v3 的 08:30／09:00 activation window 已經結束，沒有偽造 timestamp，也沒有重跑已消耗的 v3 one-shot。8/27 v3 四個 formal output 仍為 `0/3` manifests、strict readiness 未建立。
- 既有 `clock:prospective:20260828:v1` 的 clock manifest 以現行 validator 唯讀檢查為 `ready_for_activation`；clock manifest hash=`sha256:dfcd95b89f02cf1e68de945525694d0d912fd37b138e17c04b5506c7e2655f6d`、file hash=`sha256:85d50c270d9a10098e4e99d4531b0b3ce96eb096797977ab64349bc164c90161`。既有 staging／raw／auxiliary metadata 均保留 immutable，不把 auxiliary metadata 冒充 formal input，也不覆寫既有 bytes。
- 重新查詢官方日曆：TWSE `holidaySchedule/holidaySchedule` 現行 response hash=`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`，1150828 無 holiday row；TPEX `mktCalendar?ym=202608&lang=zh-tw` 現行 response hash=`sha256:153d3d091a2d84befe33cc7fcc6a230360df7086753ef5a21afe0cc56d347f84`，20260828 的 `holiday=false`、`holidayList=[]`。因此 8/28 仍是下一個可用的共同交易日，8/27 是完整 preparation day。
- 受控唯讀 market DB 最新日期為 `20260826`；20260826 有 `1,966` rows，20260827 目前為 `0` rows。8/28 activation 只會接受自然產生且已存在的 20260827 T-1；本流程不修改、刪除、drop、回填或拼造 market DB。
- 已在 Codex app 建立一次且僅一次的 `Prospective Formal 20260828 one-shot activation`，預定於 2026-08-28 09:00 Asia/Taipei 喚醒，使用既有低 CPU atomic runner。runner 會先讀取 T-1，再由同一 staging transaction 產生 Rule／Portfolio／PIT 三份正式 manifest 與 strict readiness；任一 T-1、schema、source lineage 或 controlled-store 條件不成立，維持零 partial output。
- 本次 8/27 validator repair 已由 `2f13df0` 保存，失敗與修正證據由 `4338fe1` 保存；修正後 focused activation／ledger／manifest／readiness suite=`27 passed`、py_compile、full mypy、`check_look_ahead_bias.py` 與 `quant_guard_linter.py` 均通過。
- 這次 handoff 全程維持 `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`promotion_eligible=false`、`broker_order_allowed=false`；未啟動 Direct／OOC watcher、training、retraining、promotion 或 broker adapter，也未輸出 HMAC secret。

## 2026-08-28 one-shot activation result（09:01:50 Asia/Taipei）

- 本次唯讀 preflight 取得台北時間 `2026-08-28T09:01:27.687113+08:00`；官方日曆既有證據確認 8/28 為 TWSE／TPEX 共同交易日，8/27 為完整 preparation day。market DB 未修改；exact `2026-08-27` T-1 為 `1,961` rows／`1,961` symbols，且為目前 latest date。
- 既有 create-only `clock:prospective:20260828:v1` 未被重建、覆寫或回填；本次一次且僅一次執行 `scripts/run_prospective_formal_activation_once.py`。執行在 publish 前 fail closed：`status=blocked`，錯誤為 `staged strict readiness did not reach ready after all three manifests`。正式 Rule／Portfolio／PIT 與 strict readiness 均維持 `0/3`、不存在；runner 已清理 activation staging，沒有 partial output。
- 後續唯讀 diagnostic 證明三個 producer validator 的資料本身均已 ready：Portfolio `decision_date_count=1`、`non_cash_state_day_count=1`、ledger manifest hash=`sha256:1264949e65bccf174e8b94204418f9bb6d07b5b65f208bc2eae2f449f9bf667e`、transition chain hash=`sha256:300d7e5fa0dbc0ef5e80e4235af1561090f3cb95493b987e1b1d7017f42f3cbe`；Rule snapshot count=`1` 且 HMAC attestation present（未輸出 secret）；PIT row count=`1,932`、source ids=`official:tpex:t187ap03_O`／`official:twse:t187ap03_L`、canonical hash=`sha256:5c01b1b56b0f597ccd05b449e7b6e8b754e20cb49b7c93fdd193712dd825b7b2`、rows hash=`sha256:532c647adefe889f6cfd078393682e1fda1aeb550984562c373f5fe7dc11aa09`。
- failure 根因為 readiness builder 將「strict 三項全 ready」錯誤標成 `ready_for_future_activation`，而 atomic runner 合約要求嚴格字串 `ready`；不是 T-1、官方 source、schema 或 lineage 缺失。已修正為 deferred 仍為 `ready_for_future_activation`、strict 全 ready 才為 `ready`，並補上 regression test；依本次 automation 的一次性限制不重跑 runner、不手動發布 formal files。
- 修正後 QA：focused prospective／formal simulated-ledger tests=`29 passed`；changed Python `py_compile` 通過；`mypy data_module development_module`=`Success: no issues found in 118 source files`；`check_look_ahead_bias.py` 與 `quant_guard_linter.py` 通過。全程仍為 `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`promotion_eligible=false`、`broker_order_allowed=false`，沒有啟動 Direct／OOC watcher、training、retraining、promotion 或 broker adapter。

## Rollback

所有 2026-08-28 外部 artifacts 都是新路徑的 create-only output。若 owner 取消此 successor，保留原始 bytes 與 hashes，將 clock 標記為 superseded／cancelled 並停止後續 capture；不刪除、不覆寫、不把它改名成 Formal。程式 contract 變更可用 Git `revert` 依序回滾 commits `73433d6`、`cc831b1`、`4cbae9f`，不影響既有 2026-08-25／2026-08-27 immutable artifacts。
