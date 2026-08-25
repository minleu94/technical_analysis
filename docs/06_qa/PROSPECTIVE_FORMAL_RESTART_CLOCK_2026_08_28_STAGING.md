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
- controlled store 與 HMAC secret store 只確認 configured；沒有輸出 secret。三個 BALDR formal path 在 activation 前保持 file_missing，不註冊新的持續排程。

## 2026-08-28 單次操作入口

到 activation day 後，依序以實際當下 timestamps 執行：

1. 在 PIT 08:30 boundary 以當下可取得的官方 TWSE／TPEX raw capture 建立 clock-bound PIT input；重新驗證 publication／available／effective lineage 與 1932 symbols。
2. 09:00 後取得真實 owner-bound Rule decision，使用已配置 controlled store 的 HMAC attestation 建立 clock-bound Rule history；不得用 staging 或 ML candidate OOS 代替。
3. 使用 2026-08-27 T-1 state 建立第一筆 09:00 simulated Portfolio transition；不得回填、不得自動下單、不得自動再平衡或平倉。
4. 只有三份正式 input 同時存在且均通過 clock／hash／look-ahead／lineage validator，才執行 strict readiness；任何一份缺失都保持 waiting，禁止 partial start。

現有 `scripts/capture_prospective_official_pit_sector.py`、`scripts/publish_prospective_rule_champion_history.py`、`scripts/publish_prospective_simulated_portfolio_ledger.py` 與 `scripts/inspect_prospective_capture_readiness.py` 可作為單次低 CPU 入口；本次沒有註冊新的 continuous scheduler 或 watcher。

## Rollback

所有 2026-08-28 外部 artifacts 都是新路徑的 create-only output。若 owner 取消此 successor，保留原始 bytes 與 hashes，將 clock 標記為 superseded／cancelled 並停止後續 capture；不刪除、不覆寫、不把它改名成 Formal。程式 contract 變更可用 Git `revert` 依序回滾 commits `73433d6`、`cc831b1`、`4cbae9f`，不影響既有 2026-08-25／2026-08-27 immutable artifacts。
