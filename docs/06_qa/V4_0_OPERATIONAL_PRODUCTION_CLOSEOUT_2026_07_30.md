# [Historical / Superseded] baldr V4.0 Operational Production 收尾報告

> **2026-08-29 current correction**：本檔保存 2026-07-30 的 engineering／release freeze 與
> 當時命名，不再作目前 product maturity 或 production readiness 權威。現在正確定位是
> `V3.3 Engineering Complete / V4 Evidence Accumulation`，overall=`action_required`；P0
> accepted=`0`、Evidence formal credit 未授予、Paper fills／cost=`0`、Formal inputs=`0/3`，
> production Registry／technical canary 亦未完成。下文的「正式收尾／Operational
> Production」只能按當日 bounded Rule engineering scope 閱讀，不得外推成正式 V4.0。
> Current truth 見 [Program Status Rebaseline](PROGRAM_STATUS_REBASELINE_2026_08_29.md) 與
> [Project Snapshot](../00_core/PROJECT_SNAPSHOT.md)。

- 報告日期：2026-07-30
- 決策資料 freeze：2026-07-30 08:30（Asia/Taipei）
- 報告對象：Technical / Release / Data Governance
- 上線範圍：Decision、Advice、Rule allocation、風控投影、Daily Decision Desk、Evidence Capture、Paper Portfolio、ML Production Co-pilot
- 明確不在範圍：券商連線、自動送單、以未成熟證據啟用非零 ML 權重

## 技術結論：Rule 路徑可正式日常運作，ML 已接通但合法權重仍為 0

**V4.0 的可上線結論是「Rule-only Operational Production + ML Production Co-pilot」；不是「ML 已通過正式投資有效性驗證」。**

1. Decision、結構化 Advice、Rule 配置、確定性風控、Daily Decision Desk、Evidence Capture 與 append-only Paper Portfolio 已具備每日運作入口；所有路徑均維持 `broker_execution=false`。
2. ML 已改為全欄位 PIT feature packs、OOF base experts、Meta Allocator、整數 bp 權重提案及 Rule/ML 同單位混合。四條 alpha lane `0 / 2000 / 3500 / 5000 bp` 已接入每日 runner。
3. 截至本報告 freeze，逐 horizon frozen reference 與 metrics custody 已存在，但全市場 OOC 尚未原子發布、正式 OOS execution replay input 尚未具備，且 5／10／20／60 日各只有 `0/20` 個成熟 shadow 決策日，因此尚不能發布 consumer-compatible promotion evidence。正確且唯一合法的結果為：
   - `production_blend_alpha_bp=0`
   - `formal_oos_allowed=false`
   - operational mode=`rule_only`
4. 這個 `alpha=0` 是安全機制正常生效，不是將缺值視為通過，也不是人工 Gate 尚未簽名。任何自簽、過期、future-dated、untrusted 或 custody hash 不一致的 authorization 都會在 consumer 端重新驗證並原子回退 Rule-only。
5. 資料欄位治理、全市場 raw PIT publication 與 11-symbol 實際訓練已有實體證據。全市場 immutable publication=`pit-4a860a5fa18add4e0e15f2aa`，共 34,447,843 raw rows；`all_field_enriched` 為 15,876,434 rows／52 formal features／214,058,770 values。canonical official-event post-policy training 為 22,093 rows、4 folds、426,624 筆 base OOF predictions、12,984 筆 meta OOF predictions，compact model hash=`sha256:92668aa574967990fa560aef8a48e595296eb22f3fef2a4264cff08210d78b6d`。全市場 direct numeric／OOC v5 仍以年度 checkpoint 執行，完成前不把其稱作正式 dataset 或 OOS。

## 關鍵狀態與證據

| 領域 | 可驗證狀態 | 結論 |
|---|---|---|
| Rule / Advice | 配置、Health/Exit、Why/Why Not、Risk Prompt、target/current/gap 契約已落地 | 可 operational；current weight 未知時不得假設為 0 |
| Paper Portfolio | 平衡型 policy 已採用；每日 T-1 估值、append-only、duplicate-safe | 可 operational；不自動 rebalance、不送單 |
| ML 資料與模型管線 | 全欄位 registry、PIT shard exporter、Teacher、OOF experts、Meta Allocator 與 inference contract 已建立；canonical 11-symbol official-event run 已完成 22,093 rows／4 folds／426,624 base OOF／12,984 meta OOF | Co-pilot 管線已接通；這是工程訓練證據，正式非零 alpha 尚未成立 |
| ML Promotion | reference v2 與逐 horizon metrics custody 已 ready；5／10／20／60 日均為 `0/20`，全市場 OOC／正式 execution replay 尚未完成 | `alpha=0`、`formal_oos_allowed=false` |
| Gate 2–7 | 14 items：8 complete、1 in progress、5 insufficient evidence | 人工 blanket Gate 已解除；證據不足不阻擋 Rule，也不會被偽簽 |
| Production Scheduler | 11 個 Windows tasks 已註冊；ML evidence／Authority／Co-pilot 三段均實際觸發且 `Last Result=0` | 10 個 daily tasks 加 1 個 weekly collection task已接通 |
| Broker | 不存在任何 execution adapter 或 order route | 明確 out of scope |

## 全欄位治理已完成登錄，但「已登錄」不等於「可正式訓練」

### SQLite 欄位資格

正式 SQLite 稽核涵蓋 22 tables、408 columns。11 張 ML source tables 已達 `unreviewed=0`；其餘 operational/evidence 欄位若仍為 `unreviewed`，一律 fail closed，不能透過 wildcard 進模型。

本次正式 disposition summary 為 `formal_backfill=52`、`first_seen_only=0`、`research_shadow=32`。

| Dataset / registry | Artifact 特徵數 | Disposition 組成 | Coverage | 正式用途 |
|---|---:|---|---:|---|
| `core_long_history` | 52 | `52 formal_backfill` | 9,749 bp | 長歷史正式核心 |
| `all_field_enriched` | 52 | `52 formal_backfill + 0 first_seen_only` | 9,749 bp | 正式欄位聯集與 missing masks |
| `research_shadow_all_fields` | 84 | `52 formal_backfill + 32 research_shadow` | 9,615 bp | 32 個 shadow 欄位不得混入正式 fit |

`coverage_bp` 是該 manifest 的欄位資料覆蓋指標，不是模型準確率、可成交率或 Gate 7 promotion coverage。

### 檔案型 raw / sidecar inventory

| 指標 | 實際值 |
|---|---:|
| 候選檔案 | 34,970 |
| 去重 source schemas | 313 |
| source fields | 9,619 |
| 已取得明確 disposition 的檔案 | 34,970 |
| disposition coverage | 10,000 bp |
| 未處置檔案 | 0 |

9,619 個 source fields 的狀態為：`availability_only=328`、`blocked_no_provenance=26`、`excluded_identifier=528`、`excluded_leakage=39`、`research_shadow=5,994`、`unreviewed=2,704`。其中 `unreviewed` 是明確的 fail-closed disposition，不代表已核准；舊 prediction、model、replay、outcome、backtest、pickle 與缺公告時間快照均不進正式訓練。

### 歷史資料與 PIT 可用性

- `daily_prices` 約 524 萬列、2,202 symbols，歷史自 2014 起；歷史 P/E 約 295 萬筆非空。
- 原始 ATR／ADX 欄位為空值。年度 exporter 以每檔 T-1 OHLC prefix 因果重算 Wilder(14)；2330/2026 smoke 的 ATR、ADX 各有 134 筆可用。
- 月營收 246,331 筆中有 3,680 筆 row-level first-seen 候選；因來源接受、授權與完整 publication/revision lineage 尚不足，本次正式 eligibility 仍為 `first_seen_only=0`，候選全數只供 Shadow。
- 財報 1,645,555 items 中，目前沒有一筆同時具完整歷史 announcement / revision provenance；不可用期末日或法定期限代替公告時間。
- 現有 `companies.csv` 是當期快照，不能回填成歷史產業歸屬；歷史 PIT universe 與 corporate-action canonical timeline 仍未完備。
- 2026-07-29 的隔離 candidate DB 捕捉到 13,527 筆官方 institutional rows；credit endpoint 為 retryable failure，TDCC 無逐日歷史端點，兩者不能升正式 lane。

官方回補只接受可證明的 publication / revision / first-seen 時間。來源包括[政府資料開放平台月營收](https://data.gov.tw/dataset/94026)、[MOPS 財報公告](https://mops.twse.com.tw/mops/web/t05st48_q1)、[財報開放資料](https://data.gov.tw/dataset/91967)、[TDCC 持股分散](https://data.gov.tw/dataset/11452)、[信用交易](https://data.gov.tw/dataset/11387)、[借券餘額](https://data.gov.tw/dataset/11632)、[除權息](https://data.gov.tw/dataset/11633)、[證券基本資料](https://data.gov.tw/dataset/11425)與[政府資料開放授權條款](https://data.gov.tw/license)。

### Raw PIT shard 的完成邊界

全市場 immutable raw publication 已原子發布，並保留 bounded official-event artifact 供目前可執行的正式 Co-pilot：

| Dataset | Rows | Shards | Feature policy |
|---|---:|---:|---|
| 全市場 raw publication | 34,447,843 | 28 | publication=`pit-4a860a5fa18add4e0e15f2aa` |
| 全市場 `all_field_enriched` | 15,876,434 | 年度 shards | 52 formal features／214,058,770 values；manifest=`sha256:e6fcfa6c19e5ab2c453096e1db165744972100eec29d2321e2715b77ecebae37` |
| 全市場 `research_shadow_all_fields` | 2,694,975 | 年度 shards | 32 個 research-shadow features；不進 Formal |
| bounded `core_long_history` | 312,982 | 13 | 52 個 `formal_backfill` features |
| bounded `all_field_enriched` | 312,982 | 13 | 目前 11-symbol Co-pilot 的 official-event dataset 上游 |
| bounded `research_shadow_all_fields` | 49,525 | 2 | 32 個 `research_shadow` features |

全市場 raw publication 已完成，不再是 staging。其 direct numeric／OOC v5 轉換仍以年度 checkpoint 執行，尚未產生 complete `latest_manifest.json`，所以不得把 raw rows 直接稱作正式 OOC training rows。本次正式 eligibility 固定為 `52 formal_backfill + 0 first_seen_only`；32 個 `research_shadow` 欄位另行隔離，故不得寫成「shadow／first-seen 欄位已完整回補至 2014」。

### Bounded 實際訓練證據

| 訓練證據 | 實際值 | 可宣稱邊界 |
|---|---:|---|
| Universe | 11 symbols | bounded，不代表全市場 |
| Training rows | 22,093 | official-event post-policy dataset 已組裝並完成訓練 |
| Expanding outer folds | 4 | 具 purge／embargo 的工程 walk-forward；不是 Formal OOS promotion 結論 |
| Base OOF predictions | 426,624 | 供 Meta Allocator 的 OOF 管線證據 |
| Meta OOF predictions | 12,984 | bounded meta OOF 證據 |
| Compact artifact hash | `sha256:92668aa574967990fa560aef8a48e595296eb22f3fef2a4264cff08210d78b6d` | 目前 canonical actual training artifact；非 promotion authorization |
| Replay hash | `sha256:ba0eb2456569d55d5981d97b612f109818c4acc01881e07ca9d1d6bf2042092d` | 相同資料、模型與政策 custody 的工程重播識別 |

上述 run 證明 actual training 已完成；但工程 OOF 不等於 freeze 後 Formal OOS，尚未成熟的 calibration、drift、成本後 lane comparison 與 20 日 shadow observation 仍不改變 `alpha=0`。

### 全種類 Research 配置訓練已實際接通

`research_shadow_challenger_all_fields` 將正式配置 training rows 與 `research_shadow_all_fields` 依 `symbol + decision_at` 做 PIT-safe as-of join，沿用 causal portfolio state、Teacher targets、5／10／20／60 日 labels 與 purge/embargo folds。所有 snapshot 只可從 `first_seen_at` 往後出現；尚未可得、stale 或 quality-blocked 的欄位以 missing mask 進模型，不以 0 或現在值回補。

| Research-only 證據 | 實際值 |
|---|---:|
| 年度／配置訓練 rows | 2014–2026／22,093 |
| 顯式 features / packs | 150／8 |
| Corporate observed／total feature values | 44,186／88,372（coverage 5,000 bp） |
| 遞迴 ledger 決策日／非現金 state 日 | 2,533／2,493 |
| Ledger add／reduce transitions | 792／754 |
| Expanding outer folds | 4 |
| Base／Meta OOF | 1,137,664／12,984 |
| Model hash（雙訓一致） | `sha256:dd512d6d32d853db151e971e816d514cd81c6b1cbf143289fc719ae41009a705` |
| Audit file hash（雙訓一致） | `sha256:8a95519bd0f20b2cfabe119f0b91d3a160262f9f02b307ab13d114f370b6eefa` |
| Training manifest file hash（雙訓一致） | `sha256:ae511983a486317bd8c412934f280ed09e6df0aa3278e9d8ab1183d5d8337d19` |
| Replay hash（雙訓一致） | `sha256:b7dce1751da79b2269228f6c16b93615a309b3b6b4d173087de3e08392b9764a` |

8 packs 為 `price_liquidity_technical=41`、`market_sector_cross_section=11`、`fundamental_growth_quality=33`、`valuation=2`、`flow_chip=28`、`corporate_microstructure=4`、`rule_portfolio_health=6`、`data_quality=25`。Official event overlay 只使用 publication-time 可證明且 `result_only=false` 的停復牌／交易限制事件；除權息／減資 result-only event 不反推歷史公告時間。`rule_portfolio_health` 由 T-1 遞迴 Rule／Risk Budget／Inverse Volatility state 派生，不讀同日 Advice、不回灌 Teacher target；thesis／Health/Exit 歷史仍明確缺少。

Family weights 為 `corporate_microstructure=123`、`data_quality=2,893`、`flow_chip=123`、`fundamental_growth_quality=0`、`market_sector_cross_section=2,118`、`price_liquidity_technical=1,771`、`rule_portfolio_health=2,972`、`valuation=0 bp`，嚴格合計 10,000 bp。整個 dataset 沒有 observed 值的 fundamental／valuation family 固定為 0，不以 missing pattern 取得權重。Canonical research artifact 是 `ml_research_shadow_challenger_causal_official_events_a`，B 僅保留 deterministic 重播證據。

這條 lane 的 publication／training manifest 永久固定 `research_only=true`、`formal_oos_allowed=false`、`production_alpha_bp=0`、`promotion_eligible=false`、`formal_consumer_compatible=false`，並使用正式 loader 不接受的 `allocation-research-training-manifest-v1`。因此它完成「八類 schema 都進入隔離配置訓練並讓 Meta 實際學習非零權重」，但不污染 Formal、不取得 Promotion credit，也不改變 Rule-only 上線狀態。

### Promotion reference 不再有永久 schema blocker

Canonical frozen promotion reference v2 已由正式 model／dataset custody 重新產生：22,093 rows、62 features／3 formal families，reference hash=`sha256:8ee81ae9c5691c6e10d95f14eac293b2ecd121a53877f0d0de73e20b514dd5b0`、file hash=`sha256:d02ab09f8cfa19449b7524d4ca12139a9e27e55b2f4d78f70cbc1be15821800f`。它綁定 model `92668a…`、dataset identity `f7ed2f…`、promotion policy `b19636…` 與 outcome contract `sha256:95172f7d8678fd6ecde83c1c166b56878b0d3b769750290acb5b0b3753c96a11`，分別保存 5／10／20／60 日 calibrated／uncalibrated downside baseline、逐 feature frozen bins 與 family coverage bins。

Daily Evidence Collector 會把 strict post-freeze inference rows、proposal 與同一 frozen model 重播成各 horizon calibrated／uncalibrated probability及 current distributions，並把四條 alpha lane、Paper current state、風控投影與結構化 Advice寫入獨立 append-only sidecar。Outcome 只採每檔下一可交易 OPEN 到第 h 個 session CLOSE、同區間 TAIEX、買入 25 bp／賣出 55 bp，且價格列、availability、revision、交易日曆與公司行動 publication 均納入 hash custody；缺任一項即不產生標籤。同日重跑採 custody idempotency；同日修訂不增加成熟交易日 denominator。最新 2026-07-31 observation revision=7，shadow evidence hash=`sha256:82332fb24eb62dcf2018e8d940d9f7e4faa21dd83a5e9bd48990dbd2d6d36669`、metrics hash=`sha256:607adf7b48f4210809ee2f31d355d3adfef56027cb0d7d6322db3fd02dda750d`；該 observation 的 `promotion_day_credit_allowed=false`。5／10／20／60 日 promotion 計數均為 `0/20`，所以 ECE／兩種 Brier／feature PSI／family PSI 均為 `null / NOT EVALUATED`；這是機器證據尚未成熟，不是缺 artifact schema，也不能人工跳過。

## Gate 2–7 已由人工等待改為機器證據與確定性政策

| Gate | 最新狀態 | 已完成決議 | 仍不足的證據 |
|---|---|---|---|
| Gate 2：Data Governance | weekly item `complete`；forward item `insufficient_evidence` | 欄位 registry、PIT policy、multi-day dry-run 3/3；Weekly Review `4/3` | forward matured denominator 尚未形成 |
| Gate 3：13 P0 sources | `complete`（逐源處置） | 13/13 均有 disposition | `accepted=0`、`research_shadow=12`、`blocked_no_provenance=1` |
| Gate 4：Paper policy | policy `complete` | cash / symbol / sector / turnover / lot / cost policy 固定 | 至少一個完整真實 Paper 週期尚未累積 |
| Gate 5：Strategy pruning | `complete` | 保留 Rule champion；低證據 challenger 限制於 shadow | 不以開發期 replay 取代 forward effectiveness |
| Gate 6：Health / Exit | policy `complete` | 缺 thesis→WATCH；invalidation→EXIT；transition 由狀態機測試 | Exit outcome matured denominator 尚不足 |
| Gate 7：ML | policy `complete`；revalidation `in_progress` | 四 alpha lane、promotion/rollback policy、consumer revalidation | 正式 OOS、calibration、PSI、bootstrap、20 真實 shadow days |

Gate 3 的 `complete` 只表示「13 個來源都已被明確接受、降級或拒絕」，不是 13 個來源全部 accepted。這項區分避免用一次人工簽核掩蓋 license、PIT 或品質缺口。

## ML Promotion：沒有正式 metrics，就不能產生非零權重

### 最新正式決議

| 指標 | Promotion 要求 | 截至 freeze 的正式結果 |
|---|---:|---|
| PIT / future-prefix / constraint violations | 全部為 0 | `NOT EVALUATED`（尚無完整正式 promotion artifact） |
| 有效 outer folds | 至少 4；至少 3 folds 成本後勝 Rule | `NOT EVALUATED`（engineering training 有 4 folds，但尚未完成 Formal OOS lane 判定） |
| Bootstrap 95% excess lower bound | `>= 0 bp` | `NOT EVALUATED` |
| Calibration ECE | `<= 500 bp` | **`NOT EVALUATED`；不得填 0** |
| Brier | calibrated 不劣於 uncalibrated | **`NOT EVALUATED`** |
| PSI | `< 2,500 bp` | **`NOT EVALUATED`** |
| Core / enriched / feasible-fill coverage | `>=9,500 / 9,000 / 9,500 bp` | `NOT EVALUATED`；dataset static coverage 不等於 promotion cohort／fill coverage |
| MDD / CVaR 相對 Rule 惡化 | 各 `<=100 bp` | `NOT EVALUATED` |
| Weekly turnover | `<=2,000 bp`，相對 Rule 增量 `<=500 bp` | `NOT EVALUATED` |
| 真實 shadow trading days | `>=20` | `NOT EVALUATED`；歷史 replay 不計 elapsed days |
| 最終 alpha | 最小通過 `2000→3500→5000`，否則 0 | `0 bp` |
| Formal OOS | 只由完整 promotion artifact 產生 | `false` |

最新 runner artifact 的四條 lane 均為 `evaluated=false`；downstream promotion 仍顯示 `promotion_evidence_missing`，因為 Shadow Collector 的唯一成熟交易日為 `0/20`，尚不能發布 compatible evidence。Frozen calibration／PSI reference 本身已 ready，不再缺 schema。Formal Calibration ECE／Brier、PSI drift 與 alpha OOS lane comparison仍一律為 `NOT EVALUATED`；22,093-row 工程 training 數字不得被改寫成上述 promotion metrics。

### Promotion consumer 已完成的安全硬化

1. Request / service 不得自行把非零 alpha 變成有效權重；未通過 consumer-side revalidation 時，有效 alpha 固定為 0。
2. Authorization 使用 trusted issuer HMAC allowlist，並檢查 issued time、decision window、expiry、freeze 與 custody id；self-signed、wrong-key、future、expired 或 untrusted issuer 全部 fail closed。
3. Consumer 只在 trusted custody roots 內重新讀取 registry revision、model、dataset manifest、OOF、shadow 與 evidence 實體檔，並逐一驗 SHA-256；缺檔或篡改即回退 Rule-only。
4. Causal portfolio state 包含完整持倉 symbol universe 與 state hash；漏持倉、cash/context 不一致或非 T-1 state 會輸出 `NO_NEW_POSITION` 且不產生 executable weights。
5. 05:17 Evidence Builder 只讀 formal OOC v5、兩次獨立 portfolio replay、Shadow sidecar 與 reference metrics；缺件時只發布 blocked status，不建立 compatible pointer。
6. OOS replay producer 只接受 formal training run 內 hash-bound execution ledger、Rule baseline 與 realized daily returns。現有 store 若缺這些輸入，會輸出精確 blocker，禁止用 teacher target／horizon label 合成績效。
7. 05:18 Authority 使用 Windows user-scope DPAPI 保護 key；05:20 Co-pilot 還會要求授權 model／dataset 與實際 inference release 完全相同，避免用另一個模型的好成績授權目前模型。

### 權重模型與確定性風控

模型內部可在隔離的 sklearn 邊界使用浮點，但公開與持久化契約只接受 int bp、股數、縮放整數及 `Decimal`。Rule 與 ML 權重以整數 largest-remainder 演算法混合，symbol 同餘數按股票代碼排序，確保 replay deterministic。

混合後依序投影：

1. Hard risk、交易限制與 Position Health / Exit。
2. WATCH 不加碼、REDUCE 不增加、EXIT target 固定 0。
3. 現金至少 2,000 bp、最多 8 檔、單檔最多 1,500 bp、產業最多 3,000 bp。
4. 買量不超過 T-1 二十日中位成交量 5%；流動性或產業未知不得新增。
5. 每週 turnover 2,000 bp、band 300 bp、minimum trade 200 bp、cooldown 5 日。
6. 整張 1,000 股、買進成本 25 bp、賣出成本 55 bp，交易後現金必須仍可行。

## Daily Operating Loop 已接通，休市與 timeout 現在 fail closed

Windows Task Scheduler 已接通 10 個 daily task 加 1 個 weekly task；新增的 ML evidence／Authority／Co-pilot 三段均已實際觸發且 `Last Result=0`：

| Host local time | Task | 作用 |
|---:|---|---|
| 04:20 | `baldr-data-update-quick-daily` | 市場資料更新 |
| 04:50 | `baldr-official-market-events-daily` | 官方 market-event append-only backfill |
| 05:00 | `baldr-data-freshness-check-daily` | freshness 檢查 |
| 05:10 | `baldr-recommendation-snapshot-daily` | Rule recommendation snapshot |
| 05:15 | `baldr-evidence-pipeline-dry-run-daily` | evidence preflight |
| 05:17 | `baldr-ml-promotion-evidence-daily` | formal OOC／雙 replay／Shadow／metrics unsigned evidence |
| 05:18 | `baldr-ml-promotion-authority-daily` | DPAPI machine authorization；證據不足即不簽 |
| 05:20 | `baldr-ml-allocation-copilot-daily` | 四條 alpha lane / Rule-only fallback |
| 05:25 | `baldr-decision-evidence-capture-daily` | Decision Desk snapshot + Evidence events |
| 05:28 | `baldr-paper-portfolio-daily` | T-1 Paper ledger |
| 週日 18:00 | `baldr-v2-2-weekly-collection` | weekly evidence append-only sidecar 與自動重驗 |

決策時間固定為 Asia/Taipei 08:30；scheduler trigger 時間是 host local time。

最新 Decision/Evidence artifact 的 decision date 為 2026-07-31 08:30 Asia/Taipei、資料 cutoff 為 T-1=2026-07-30；保存 7/7 sections、1,580 events、0 failures，其中 `degraded=1,569`、`estimated=3`、`observed=8`，另有 371 warnings。因此「capture 成功」不應解讀成所有來源品質皆 observed。Paper artifact 為 3 檔持倉、`cash=341000.00`、`total_value=484200.00`，重跑以 duplicate-safe 成功。

Scheduler hardening 已加入：

- TWSE `holidaySchedule` 年度表；週末固定休市，平日不在休市表才開市，「開始／最後／恢復／照常交易」可明確標為開市。
- 官方日曆取得失敗時為 `degraded_calendar_unknown`；休市為 `skipped_non_trading_day`。兩者都不新增 ML shadow、Paper snapshot 或 Evidence events。
- ML 開市且 alpha=0 的狀態改為 `passed_rule_only`；非零正式 blend 才是 `passed_ml_blend`。
- Decision/Evidence subprocess 預設 120 秒 timeout；timeout 狀態會持久化。
- Snapshot 必須具有完整 7 sections；Evidence 必須 `events_seen>0`，並且 inserted 或 duplicate 至少一項大於 0。duplicate-only 可視為 idempotent success。

上述 `Enabled`／`Ready`／`Last Result=0` 是 Windows Task Scheduler 的 process-level 實證；它不表示每個資料來源都已 observed，也不表示 Formal ML promotion 已通過。各 runner 的資料品質與 promotion eligibility 仍須讀取其 `latest_status.json` 與不可變 evidence artifact。

## 驗證證據與尚未完成的正式 QA

### 已完成

| 驗證 | 結果 | 判讀 |
|---|---|---|
| `inspect_pre_v2_readiness.py` | exit 0 | multi-day 3/3、source gaps ready；weekly `4/3 complete` |
| `evaluate_evidence_scheduler_readiness.py` | exit 0；`operational_production` | `blocking_gaps=[]`、Rule／Evidence scheduler 允許運作；ML 非零 alpha 仍為 false |
| `inspect_source_candidate_readiness.py` | exit 0 | 正式 institutional / credit / TDCC tables 仍空或 degraded |
| `build_ml_revalidation_runbook.py ...` | exit 0；12 steps | Runbook 已建立，不代表 12 個 artifacts 已全部完成 |
| Update Workbench Qt | **38 passed / 2.79s** | 指定 `-o addopts=` 核心 UI suite 全數通過 |
| Update Tab QA | **23 passed / 0 failed / 4 skipped** | skipped 為刻意不執行大量下載與正式資料合併 |
| 完整指定 mypy scope | **Success / 472 source files** | 無型態錯誤 |
| `py_compile ui_qt/main.py` | exit 0 | 主 UI 入口語法通過 |
| 完整 pytest | **2,969 passed / 1 skipped / 0 failed / 32 warnings / 513.51s** | 2,970 tests 全部有終態；skip 為既有環境條件 |
| V4 allocation／promotion 關鍵 suite | **159 passed / 26.41s** | 契約、Teacher、OOF、權重守恆、replay、authority、orchestration 與禁止手動注入 |
| Test inventory audit | **571 filesystem files／571 inventory entries／2,970 tests；passed** | missing、stale、doc drift、collection errors、blockers 均為空 |
| Scheduler / calendar / Phase3C / ML / Paper focused suite | **44 passed** | 含官方休市表、timeout、7-section、zero-event、duplicate、alpha status regression |
| Promotion / custody / causal-state red-team focused suite | **77 passed** | 含 consumer revalidation、自簽／future／tamper fail-closed、持倉 universe |
| Targeted mypy（scheduler hardening 4 files） | Success | 無型態錯誤 |
| Targeted `py_compile`（scheduler hardening 4 files） | Success | 無語法錯誤 |
| Quant guard | float 與 look-ahead guards 通過 | 未新增裸 float 金融決策或可辨識 future read |

`inspect_pre_v2_readiness.py` 的 `production_scheduler_allowed=false` 只限制尚未成熟的 formal evidence credit；同一份結果已明示 `rule_operational_scheduler_allowed=true`。V4 Evidence Scheduler evaluator 另回報 `operational_production` 與 `blocking_gaps=[]`。兩者都不表示 Formal ML 時間證據已成熟。

### TODO：最終 release validation（完成前不得把本表改成 passed）

- [x] `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=` → 38 passed。
- [x] `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py` → 23 passed、0 failed、4 skipped。
- [x] `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` → 472 source files 無錯誤。
- [x] `.\.venv\Scripts\python.exe -m py_compile ui_qt/main.py` → exit 0。
- [x] `.\.venv\Scripts\python.exe -m pytest` → 2,969 passed、1 skipped、0 failed、32 warnings，513.51 秒。
- [x] 已保存上述命令的最終 exit code、passed / failed / skipped 數量與 log 摘要；數字直接來自 full suite。
- [x] 以 hardening 後 runner 重跑 production latest status：官方交易日 open、ML status=`passed_rule_only`／alpha=0、Decision 7/7 sections、Evidence events_seen=1,580／failures=0、Paper 3 positions／T-1／market DB `ro/query_only`。
- [x] 全市場年度 raw PIT exporter 已原子發布：34,447,843 raw rows；`all_field_enriched` 15,876,434 rows／52 features／214,058,770 values，manifest=`sha256:e6fcfa6c19e5ab2c453096e1db165744972100eec29d2321e2715b77ecebae37`。
- [ ] 全市場 direct numeric／OOC v5 仍由 background checkpoint pipeline 執行；Gate revision 6 記錄時完成 2014–2018，live checkpoint 隨後已至少完成至 2019 並自動續跑。整體完成前不得宣稱正式 OOC dataset／Formal replay／非零 alpha。
- [x] canonical 11-symbol official-event artifact 已組裝 22,093 個 `PortfolioMLDatasetRow` 並完成 4-fold actual training（426,624 base OOF／12,984 meta OOF）；compact artifact hash=`sha256:92668aa574967990fa560aef8a48e595296eb22f3fef2a4264cff08210d78b6d`。
- [ ] 由正式全市場 raw PIT artifact 重建全市場 trainable rows、inference 與 lane replay；bounded 完成不得替代全市場 publication。
- [ ] 產生正式 `calibration-drift.json`、`portfolio-lane-comparison.json` 與受信任 custody 下的 promotion authorization；在此之前 ECE、Brier、PSI、OOS excess 與非零 alpha 均維持「未驗證」。

## 限制、失敗模式與自動 fallback

1. **歷史 universe、產業歸屬與公司行動不完整**：無可信 timeline 的欄位與受影響 horizon fail closed，不以 2026 快照倒灌。
2. **13 個 P0 沒有正式 accepted source**：12 個留 research shadow、1 個 blocked provenance；這不阻擋價格／Rule core，但限制 enriched formal coverage。
3. **Evidence capture 品質仍多為 degraded**：最新重跑看到 1,580 events、failures=0，其中 observed=8、estimated=3、degraded=1,569；可保存不等於可升正式信用。
4. **ML 沒有 Formal OOS 結果**：不能宣稱優於 Rule、不能填入 calibration / PSI 數字，也不能把 seen history 政名 Formal OOS。
5. **全市場 raw shard 已發布、direct numeric／OOC 尚未原子發布**：15,876,434-row `all_field_enriched` 已具 immutable manifest；逐年 direct store 與正式 OOC training 仍須完成 `latest_manifest.json` 後才可被 Promotion Builder 消費。
6. **Engineering replay 不等於 Formal replay**：producer／consumer 已可逐日重算現金、持倉、成本、turnover、隔夜報酬與 hash chain，但現行 artifact 明確帶 `formal_semantic_validation.verified=false`、`promotion_eligible_input=false`。正式升級還必須由獨立 verifier 重建官方交易日曆、production Rule Champion、六頭 Meta OOF 投影與 retro raw derivation，且至少涵蓋 4 個 Meta OOF folds。
7. **Shadow 保存不代表累積 promotion day**：現行 observation 會正常 append，但因缺正式 Rule weight snapshot 與 sector／thesis／health 歷史 context，固定 `promotion_day_credit_allowed=false`；`0/20` 不會靠 current holdings 或重跑灌水。
8. **Promotion authority 已獨立，proposal 不具自行授權力**：unsigned Evidence Builder、Windows user-scope DPAPI Authority 與 consumer revalidation 已分離。每日 requested weights 只有在相同 model／dataset／decision／custody 下通過 authority 與 consumer 驗證才可能影響配置；缺件即回退 0。
9. **沒有券商執行**：所有 executable weights 與股數只屬 Paper / decision support。

完整 pytest 的 32 個 warnings 為既有且已揭露的兩類：8 個 pandas incompatible-dtype `FutureWarning`，以及 24 個 Recommendation Portfolio「同日收盤訊號／同日收盤成交」理想化研究假設 `UserWarning`。本次沒有 warning 被用來掩蓋失敗或 Formal ML eligibility。

自動 fallback 順序：

```text
all_field_enriched
  → core_long_history
  → Rule / Risk Budget / Inverse Volatility
  → 100% cash / NO_NEW_POSITION
```

- 欄位缺 provenance、license、PIT 或 quality：不進正式模型。
- Calendar closed / unknown：不新增 elapsed record。
- Promotion evidence / authorization / custody 任一失效：`alpha=0`、Rule-only。
- Portfolio state 不完整、current weight 未知或 T-1 不成立：不得假設為 0；輸出 `NO_NEW_POSITION` 或無 executable weights。
- 混合權重不可行：確定性硬風控投影；仍不可行則 100% cash。

## 建議的自動收尾順序

1. 讓已啟動的全市場 direct numeric checkpoint 完成 2014–2026，原子發布 store `latest_manifest.json`；不得直接消費 staging。
2. 由 continuation 自動執行四個以上 expanding outer folds、60 trading-day purge、5-day embargo，保存 fold-local imputer／normalizer／calibration、OOF hashes，並另建 hash-bound causal execution replay source；禁止用 Teacher labels 代替實際投組 replay。
3. 獨立 semantic verifier 從官方交易日曆、production Rule Champion snapshot、六頭 Meta OOF 與 raw PIT custody 重建 requested／blended／projected holdings；只有 `verified=true`、blockers 為空且 Meta OOF folds 至少 4 個時，replay 才可送入 Promotion Builder。
4. 每個正式交易日照常保存四條 alpha lane；只有具有正式 Rule/context custody 的 observation 才累積 promotion day，滿 20 個真實 shadow days及 matured labels 後才計算 calibration、PSI、bootstrap 與成本後 lane comparison。
5. Promotion consumer 每日重新驗 issuer、時效、freeze、custody 與實體檔 hashes；最小 lane 通過才升 `2000 bp`，任一條件失效立即回退 0。
6. 延續官方月營收、財報、法人、信用、TDCC、公司行動與歷史 universe 回補；找不到歷史公告時間時只從 first-seen 往後使用。
7. 每次程式變更後重跑完整 release QA，將實際 log 數字補入本報告，不從預期結果或局部 suite 外推。

## 尚待後續回答的工程問題

1. 是否要為每日 `MLAllocationProposal` 增加獨立 authority signature 與 replay nonce，以縮小 model identity 到 requested weights 之間的信任區間？
2. 歷史產業歸屬與 corporate-action timeline 哪一個官方來源能提供足夠的 publication / revision 證據，而不需要 first-seen-only 降級？
3. Full suite 與實際全市場 training 完成後，哪一項資料 family 對 OOS allocation 有增量價值，哪些只增加 missingness、turnover 或 drift？

## 證據入口

- [PROJECT_SNAPSHOT](../00_core/PROJECT_SNAPSHOT.md)
- [Gate 2–7 External Validation Register](GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)
- [Gate 7 ML Shadow Engineering](GATE_7_ML_SHADOW_ENGINEERING.md)
- [Application Manual](../07_guides/APPLICATION_MANUAL.md)
- `runbook_prod.json`
- `OUTPUT_ROOT/release_v4/feature_eligibility_matrix.json`
- `OUTPUT_ROOT/release_v4/core_long_history_manifest.json`
- `OUTPUT_ROOT/release_v4/all_field_enriched_manifest.json`
- `OUTPUT_ROOT/release_v4/research_shadow_all_fields_manifest.json`
- `OUTPUT_ROOT/release_v4/ml_file_field_inventory.json`
- `OUTPUT_ROOT/release_v4/engineering_gate_registry.sqlite`
- `OUTPUT_ROOT/scheduled/ml_allocation_copilot/latest_status.json`
- `OUTPUT_ROOT/scheduled/decision_evidence_capture/latest_status.json`
- `OUTPUT_ROOT/scheduled/paper_portfolio_daily/latest_status.json`
