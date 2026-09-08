# V4 機器證據解卡紀錄（2026-09-07）

## 範圍與 owner

本次選定 P0 source acceptance 作為一個可客觀裁決的入口。既有
`SourceAcceptanceGovernance.evaluate` 會固定回傳 `deferred` 並加入
`source_acceptance_not_authorized`；既有 `P0SourceAcceptanceVerifier.verify`
即使程式檢核通過也只回傳 `eligible_for_human_review`。本次保留兩條既有
owner-review 路徑，新增獨立的 machine evidence caller：

- caller：`scripts/append_source_acceptance_decision.py`
- evidence/decision validator：`data_module/source_acceptance_governance.py`
- decision schema／registry validator：`data_module/source_acceptance_decision_registry.py`
- 隔離測試：`tests/test_source_acceptance_machine_review.py` 與既有 source acceptance 測試

`--machine-evidence` 只讀取單一 P0 source 的
`source-acceptance-machine-evidence.v1` 封套，通過後才建立一筆
`limited` machine decision。這條路徑不繞過既有 intake 的 13-source owner review
規則，也不會把 weekly sidecar 的 `pending_human_review` 改成已核准。

## 可裁決輸入

封套的 `content_sha256` 必須等於移除自身欄位後的 canonical JSON SHA-256，且
`policy_version` 必須是 `source-acceptance-machine-review.v1`。每個 license／quality／
PIT／availability 子封套都必須提供 artifact path；caller 會重新讀取實際 bytes、
重算檔案 SHA-256、比對 source／evidence id，並比對既有 producer 程式檔的 SHA-256。
artifact 必須由既有 producer 產出，並以 `producer_code_sha256` 鎖定產生器版本；
只重算外層 JSON 或自行填入布林旗標不足以通過。決策日期與帶時區的決策時間必須一致，
P0 source/version 必須一致。必要檢核包括：

- license：machine producer 產出的 `status=machine_scope_verified`、`license:` evidence id、HTTPS source URL、capture content SHA-256、帶時區 capture 時間、allowlisted host、條款存在旗標；頁面內容不可持久化。
- quality：`status=verified`、quality score 至少 9500 bp、schema/reconciliation/quarantine 三項檢核明確為 true，並有 quality content hash。
- PIT：`status=verified`、`lineage_complete=true`、PIT content hash、至少一筆同 source/version 的 observation；每筆 `available_date` 與帶時區的 `available_at` 必須有效且早於或等於 decision timestamp，狀態不得為 unavailable。
- coverage／row conservation：coverage bp 由獨立 expected-universe denominator 的整數計算重現，至少 8000 bp；raw、accepted、quarantine、blocked 必須非負且保存關係成立，coverage 分子分母不以 raw rows 代替。
- availability／maturity：可得日狀態為 `available` 且有證據 hash／觀測時間；成熟度為 `mature`，完成 period 數達固定最低數量且 lineage complete。
- 用途與回滾：用途只能是 `research_shadow`／`diagnostics`，回滾 reference 不可使用 future-disable sentinel。

任何缺欄、空字串、未驗證狀態、future available date、coverage 不足、row conservation
矛盾、用途越界、bundle hash 不符或 evidence id 前綴不符，均保留具體
`machine_evidence_*` blocker，不會建立決議。

## 決議與安全邊界

成功決議明確記錄：

- `decision_actor=machine:evidence_policy`
- `decision_policy_version=source-acceptance-machine-review.v1`
- `decision_evidence_hash=sha256:...`
- deterministic `decision_reason`
- `reviewer_role=""`，不偽造人類審查者

成功狀態固定為 `limited`，用途只限 research shadow／diagnostics；preview 與
可選的 candidate registry append 均維持 `downstream_eligibility=none`、
`formal_oos_allowed=false`、`production_scheduler_allowed=false`、
`broker_order_allowed=false`。machine review 缺證據時是 evidence remediation
blocker，`human_review_required=false`，不把缺證據重新命名成人工 Gate。

`SourceAcceptanceDecisionRevision` 的 machine metadata 是 additive 欄位；舊 human
payload 不輸出這些欄位，因此既有 persisted payload 的 canonical content hash 維持不變。

## 驗證

已執行：

```text
.\.venv\Scripts\python.exe -m pytest tests/test_source_acceptance_machine_review.py -q -o addopts=
12 passed

.\.venv\Scripts\python.exe -m pytest tests/test_source_acceptance_decision_registry.py tests/test_append_source_acceptance_decision.py tests/test_source_acceptance_governance.py tests/test_p0_source_acceptance_verifier.py -q -o addopts=
30 passed

.\.venv\Scripts\python.exe -m mypy --explicit-package-bases data_module/source_acceptance_governance.py data_module/source_acceptance_decision_registry.py scripts/append_source_acceptance_decision.py
Success: no issues found in 3 source files

.\.venv\Scripts\python.exe -m py_compile data_module/source_acceptance_decision_registry.py data_module/source_acceptance_governance.py scripts/append_source_acceptance_decision.py tests/test_source_acceptance_machine_review.py tests/test_source_acceptance_decision_registry.py
```

測試涵蓋完整 evidence 成功、named reviewer 缺席仍可產生受限決議、caller evidence
binding 與暫存 candidate registry append、bundle／子 artifact tamper、producer code
hash 綁定、非結構化 license、immature/unavailable、capture／observed／PIT 時間負例、
coverage／expected universe／scope 限制、machine metadata round-trip，以及舊 human
payload hash 相容性。

## 官方 source producer E2E（2026-09-07）

本輪完成一條真正的 bounded、唯讀官方 source producer→evaluator→candidate
consumer readback 鏈，source 為 `twse.monthly_revenue_announcement`。producer
重新抓取並保存於隔離 TEMP bundle：

- data.gov.tw metadata：
  `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_machine_bundle_20260907_e2e2\inputs\data_gov_dataset_18420.json`，
  3054 bytes，SHA-256
  `sha256:2be48c7bd7385fbb3522df0e3c1e479dc92a8c66b85bbf1bc115e55182b9e4c7`。
  實際 `result` 為 dataset `18420`、identifier `A45020000D-000354`、標題
  `上市公司每月營業收入彙總表`、provider `N121467221`、publisher OID
  `2.16.886.101.20003.20052.20004`、`license=1`；distribution resource 為
  `https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv`，notes 同時指向官方
  授權頁與 `https://openapi.twse.com.tw/v1/swagger.json`。
- Swagger metadata：同 bundle 的
  `inputs/twse_openapi_swagger.json`，309960 bytes，SHA-256
  `sha256:06e1cea82448361e733a0ad1ae16e52f5d5d6b71905acd078472f852c32c0eb0`；
  真實 `paths` 包含 `/opendata/t187ap05_L`，與 endpoint
  `https://openapi.twse.com.tw/v1/opendata/t187ap05_L` 由 `basePath=/v1` 對應。
- TWSE 條款 capture 的官方文件指紋為 15304 bytes、SHA-256
  `sha256:ae9fa0704103fbae0ed61173a83cf55dca36dba2f7c86936fc018c4c39fb0c2c`、
  `Last-Modified: Fri, 26 Jun 2026 02:46:42 GMT`，producer code SHA-256 為
  `sha256:9de6a763ea978a31a67022f6ad852ebcaa0cae6de2208935e2ca67d7a7d9b069`。
  條款範圍以已核對的文件版本、條款輪廓與 data.gov dataset/resource/endpoint
  mapping 決定；關鍵字只保留為診斷資料，否定條款不能通過。
- source raw payload 與獨立上市清冊均在 `inputs/` 保存 bytes 與 hash；清冊含四碼
  普通股及六碼存託憑證，coverage denominator 獨立於 raw rows。實際結果為
  `1084/1094 = 9908bp`、raw/accepted `1085/1085`、quarantine/blocked
  `0/0`，完成一個 bounded shadow period。
- machine bundle：
  `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_machine_bundle_20260907_e2e2\machine-evidence.json`，
  SHA-256 `sha256:2bb75697847104731bca233afca296b64efec962aa7dfe8dd294af8e5a495953`。
  evaluator 回傳 `machine_verified`，candidate registry append/readback 為
  `limited`，decision content hash 為
  `sha256:2683aaa4ddbd6e1f0f731e68ebf0be872a88b3973fee768f7c74fe454d7cd78e`，
  evidence hash 與 bundle hash 相同；`decision_actor=machine:evidence_policy`、
  `reviewer_role=""`，用途只有 `research_shadow`／`diagnostics`。

本條鏈仍明示 `first_observed_at`，未宣稱官方發布時間、歷史 PIT、正式 OOS、
production scheduler、redistribution 或投資有效性；只寫入 TEMP candidate
SQLite，不寫正式 DB 或 D 原始資料。metadata／Swagger／source raw 任一內容或
hash 竄改都會被 consumer 重新讀取後保留具體 blocker。官方上市清冊的六碼存託
憑證解析與政府 metadata tamper 負例已納入 producer 測試。

本輪 producer／governance 隔離測試為 `46 passed`，另完成四檔 py_compile 與
explicit-package-bases mypy；pytest 僅有既存 `.pytest_cache` 權限警告。這只證明
一條 P0 月營收 research-shadow 鏈已接通，不能宣稱三 formal inputs 或 V4 formal
完成。

本次未啟動交易、未寫正式資料庫或 D 原始資料，未修改中央 roadmap／register 文件。
此結果只解開一個受證據約束的 research-shadow decision 入口，不能宣稱 V4
formal／production／投資有效性已完成。

## 官方 PIT 產業歸屬的 machine operational slice（2026-09-07）

本輪沿用既有 `data_module.pit_sector_membership_machine` 的官方
TWSE `t187ap03_L` 與 TPEx `t187ap03_O` raw bytes，未重做 HTTP。root 已在
隔離 TEMP bundle 完成 1984 筆「source raw → source consumer 重建 → controlled
machine publisher → operational consumer → assembler sector spool」readback：

- source publication：
  `C:\Users\archi\AppData\Local\Temp\technical_analysis_pit_machine_20260907_e2e3\pit-sector-membership-machine.json`，
  1984 rows、檔案 hash
  `sha256:ea2afe0bcb4d4537be762e8218c560b7160e76d1d8798901bc839ce2d4fa506a`。
  `source_ids` 是 `official:tpex:t187ap03_O` 與
  `official:twse:t187ap03_L`，`source_custody_verified=true`、
  `rows_rebuilt_from_raw=true`。
- controlled operational publication：
  `...\operational-publication.json`，1984 rows、檔案 hash
  `sha256:7eea45fca32a7971e474f3492b5e045a8677172ca0a518b887ff08fb904fbf66`；
  `publisher_version=controlled-current-day-pit-publisher.v1`，publisher id
  為 `baldr-rule-champion-controlled-store-v1-03a28a9b25f3405597ba42c3e52fd409`，
  publisher code hash 為
  `sha256:c60fb173a6479063fa89ea47e50bda5287c966f8eaa242340036510d09e8d20a`。
  source capture completion 是 `2026-09-07T09:28:26.628084+00:00`，operational
  decision 是 `2026-09-07T09:43:19.396281+00:00`；此 timestamp gate 通過，
  不把它當作當日 08:30 的資料。
- dispatch output：
  `...\daily-dispatch.json`，assembler memory spool 與 persisted count 都是
  1984；output hash 為
  `sha256:382ea998e9f91a0f9d388eb249f17155a5206fa060294145fa8a70f00e4e48b2`。
  此檔只記錄 TEMP、in-memory、candidate-only 狀態，沒有正式 SQLite／D 原始
  資料寫入，也沒有交易或 training publication。

`scripts/run_daily_ml_allocation_orchestration.py` 現在接受明確的
`--pit-machine-operational-publication` 路徑，將該 path/hash 納入 orchestration
run hash，並在 post-freeze shadow assembly 的同一個 `decision_at` 透過受控
consumer 與 `_spool_sector_memberships` 讀取；沒有自動掃描 TEMP，也不會把
candidate 傳給正式 `PortfolioMLDatasetAssembler.build`。缺檔、尚未 available、
簽章／receipt／source hash 不符時，daily stage 會在 `post_freeze_input` 保留
具體 blocker。

### 產業 feature 的語意與前後差異

產業 entity resolver 綁定凍結 feature registry 的三個明確 ID：
`industry_indices.收盤指數`、`industry_indices.漲跌百分比`、
`industry_indices.漲跌點數`，source 固定為 `sqlite.industry_indices`，市場範圍
記為 `TWSE`。目前 producer（TWSE MI_INDEX）只證明 TWSE 產業收盤指數，
不能從缺少 exchange 欄位的 SQLite table 推導 TPEx；因此只選官方資料庫中精確的
`*類指數` entity；
`*類報酬指數` 不會作為 fallback。registry 不認得的 index kind、錯誤 source
或沒有精確 entity 時，lineage 會是 null 並保留 feature missing。每個 shadow
audit 都保存 `industry_entity_lineage`，包括官方兩碼 sector code 對應到的
實際 entity，不只記一個布林旗標。

以 1984 筆官方 capture 中 daily bounded universe 的 11 檔
`1101,1216,1301,2002,2303,2317,2330,2412,2454,2881,6505` 做唯讀診斷，
嚴格 T-1 參照日為 `2026-09-04`。診斷 artifact 為
`C:\Users\archi\AppData\Local\Temp\technical_analysis_pit_machine_20260907_feature_diag\industry-feature-diagnostic.json`，
file hash `sha256:e214f11f0f6488b4a203963d9762d0f8aee59cff7b736bca6c803917bb8d684d`，
content hash `sha256:420bcc430cd0cd25ed33d0cf600eee932d2623fd83ffaa62f6362442a921617d`。
該 artifact 以 `mode=ro; PRAGMA query_only=ON` 讀取既有 `industry_indices`，
未改寫資料：沒有 membership 時三個 industry feature 的 baseline missing 是
`33`；套用 machine capture、逐一核對 price-index entity 與 T-1 值後，observed
是 `33`、missing 是 `0`。實際 lineage 為：

```text
1101→01→水泥類指數       1216→02→食品類指數
1301→03→塑膠類指數       2002→10→鋼鐵類指數
2303→24→半導體類指數     2317→31→其他電子類指數
2330→24→半導體類指數     2412→27→通信網路類指數
2454→24→半導體類指數     2881→17→金融保險類指數
6505→23→油電燃氣類指數
```

這個前後數字是 source capture 完成後的 bounded current-day／T-1 feature
診斷，不是將 2026-09-07 capture 回填到 2026-09-07 08:30，也不是正式 daily
production run。對應 unit／整合測試另外驗證了 machine candidate 接入後，industry
feature missing `1→0`、lineage 僅選 price index，以及 UTC 23:30 capture 轉為
Taipei 次日 `available_date/effective_from` 的邊界；
`tests/test_formal_machine_consumer_integration.py::test_tpex_membership_same_sector_keeps_twse_industry_feature_missing`
則用同一 sector 的 TWSE／TPEx membership 走過 `_assemble_shadow_rows`，確認
TWSE feature observed、TPEx feature missing 並保留 `industry_scope_mismatch` 原因。

### 實際 assembler post-freeze input（盤後 bounded shadow）

為驗證資料確實走過 `_assemble_shadow_rows`，以官方 SQLite 的一致性 snapshot
（TEMP 路徑
`C:\Users\archi\AppData\Local\Temp\technical_analysis_official_db_snapshot_dndp7x58\twstock.snapshot.sqlite`）
執行 raw PIT exporter。snapshot bytes 是 `3,403,472,896`，`quick_check=ok`，檔案
hash 為
`sha256:f33703823bdbeb31d9e9494389d875008bf89a4f0a2f97fe6e8695fa9f604bd9`。
來源 live connection 的 `data_version` 在觀測期間由 `2` 變為 `27`，所以沒有繞過
exporter 的一致性 fail-closed；snapshot 只作本輪唯讀診斷，不是正式 DB。

raw publication 位於
`C:\Users\archi\AppData\Local\Temp\technical_analysis_postfreeze_raw_e1kb16bv\runs\pit-8fc40fac73840852f177bff7\manifest.json`，
canonical manifest hash 是
`sha256:1fbfaf1c3f0735642a944f562580a5465d15d50a9e49030810295af9222e480e`，
manifest bytes hash 是
`sha256:78d9f633c8d0edaedb5f46286c3de7e611e187b4b3891b0dd8a7f8c177b012fb`；
bounded `all_field_enriched` dataset canonical hash 是
`sha256:57e2911e7d0ac4dafc44ca97729190c6b9d25022247c5f9282e16b23a237d95b`。
該 raw publication 的決策 cutoff 為 `2026-09-07T18:00:00+08:00`，strict T-1
為 `2026-09-04`。

assembler 實際讀回 e2e3 的 controlled operational publication
`sha256:7eea45fca32a7971e474f3492b5e045a8677172ca0a518b887ff08fb904fbf66`，其
官方 source capture completion 為 `2026-09-07T17:28:26.628084+08:00`；因此本次
決策時間明確晚於 source capture，沒有把資料回填到 08:30。產出的 11-row
input 位於
`C:\Users\archi\AppData\Local\Temp\technical_analysis_postfreeze_cli_whk9_n42\post_freeze_shadow_input.json.gz`，
bytes hash 為
`sha256:ed75cda91593159e3c3041c9ffa88c756d32f9ad40bf2a8ffe0bb66357875297`；
audit 位於同目錄 `post_freeze_shadow_input_audit.json`，bytes hash 為
`sha256:bf0fd899927202efbb07fcdacef093758afc005b82af3690b3bedcadec71e188`，
canonical audit hash 為
`sha256:1eefd63af23e791c0b203585aa59d2a98537fc02926527032c50a31ddd8c3b6a`。

這份 input 的 11 rows 全部保存實際
`decision_at=2026-09-07T18:00:00+08:00`，並由 `_assemble_shadow_rows` 的
feature mask 得到 industry 三個 feature `33 observed / 0 missing`；industry
lineage 仍是 11 檔官方 TWSE symbol 對應的 `*類指數`，audit 也保存每個 symbol
的 source（`official:twse:t187ap03_L`）與 market（`TWSE`）。同一份 assembler
結果仍明列其他 family 的現況：`market_sector_cross_section` 與
`price_liquidity_technical` 各有 11 rows missing；這次只證明 industry input
接線與 mask 改善，沒有把整體資料品質宣稱為 complete。post-close decision
支援透過 scoped `post_freeze_shadow_decision_scope` 建立 target-free research
row；formal/training target row 與一般 inference parser 仍維持台北 08:30 邊界，
因此這份產物不是 Formal OOS、promotion 或 production action 授權。

### 驗證與尚存 blocker

本輪隔離驗證結果：

```text
tests/test_formal_machine_consumer_integration.py
tests/test_post_freeze_shadow_decision_scope.py
tests/test_pit_sector_machine_publisher.py
tests/test_pit_sector_membership_machine.py
18 passed

tests/test_daily_ml_allocation_orchestration.py
tests/test_build_ml_allocation_post_freeze_shadow_input_cli.py
tests/test_ml_allocation_contracts.py
35 passed

mypy --explicit-package-bases（11 個相關 source files）
Success: no issues found in 11 source files
```

pytest 只有既存 `.pytest_cache` 權限警告。production daily wiring 的 test 以
明確 TEMP path 檢查 caller→post-freeze consumer 傳遞與 hash binding；未把假資料
當成 official e2e。仍保留的 blocker 是：產業 capture 只有 current natural-day
first-seen、尚未提供正式歷史 PIT universe／完整 expected denominator；operational
publisher 是 controlled machine candidate，`formal_consumer_compatible=false`、
`candidate_only=true`；PIT license 的正式用途核准、Rule Champion history 與
causal non-cash ledger 尚未具備正式 producer／consumer publication。因此這輪
只改善可驗證的 daily shadow feature 輸入，不解除 Formal OOS、promotion、broker
或投資有效性限制。

## 四個缺值特徵的 producer 修復候選（2026-09-07）

本輪查核 frozen registry 與官方 SQLite raw producer 後，確認兩個 market
變化欄的 NULL 不是可用的 0：`data_module/data_loader.py` 的 TWSE
`FMTQIK` 路徑只保留 `收盤指數`／OHLC／成交量，丟掉 `漲跌點數`，也沒有計算
`漲跌百分比`；yfinance fallback 同樣沒有這兩欄。`technical_indicators` 的
`漲跌(+/-)` 是原始 `+`／`-` 分類值，SQLite writer 對非主鍵欄位統一作
`to_numeric` 後會變成 NULL；`technical_indicators.涨跌` 是未定義的 legacy
重複欄位。兩者都不能從空值自我宣稱為 numeric。

新增 `ml_module/allocation_feature_contract.py` 定義
`allocation-feature-contract-market-repair-v2`，並由
`scripts/build_ml_allocation_post_freeze_feature_repair.py` 以保留的 v2 input
與 official `all_field_enriched` raw publication 建立 v3 candidate。market
producer 只接受 TAIEX 的官方 observation；先以帶時區的 `event_at` 轉成台北
交易日，再透過既有 `OfficialTradingCalendar` 對唯讀 calendar database 的逐日
證據選出 expected T-1 與前一個官方交易日。raw 中若缺少 calendar 證明的中間
交易日，不能用排序後的上一筆代替，會 fail closed；週末／明確休市日可跳過，
未知平日則保持 blocked。兩筆 `收盤指數`、`source_row_hash`、`source_value_hash`、
availability 與 quality 都必須通過。點數是當收減前收，百分比是點數除以前收乘
100，計算全程使用 `Decimal`，輸出再以明確 scale=10000、`ROUND_HALF_EVEN`
量化；future availability、重複日期、source／內容 hash 不符也 fail closed。

兩個 technical 欄位從 v3 feature set 排除，保留在父 v2 供相容比較；新
contract hash 綁定父 registry hash、完整納入 feature IDs、排除語意、推導
方法與 derived source manifest，不能以任意非空字串或外層 hash 取代來源證據。
v3 的兩個 market 值 source 為
`derived:market_indices.official_consecutive_trade_close.v1`，每列 revision
與 content hash 都包含當／前收、兩個 source row/value hash、官方日期與實際
decision timestamp。v3 明確標記 `new_release_required=true`；舊 v2 inference
consumer 實讀父檔成功並實讀拒絕 v3，直到新 model release 定義此 contract，沒有
改動 frozen registry／feature pack／舊 artifact。

v3 同步重算 effective feature set 的 data-quality metrics，不沿用父 v2
`data_quality.*` 數值。新增 source
`derived:feature_quality.effective_contract.v1`，manifest hash 為
`sha256:926ab1cd8317f6403f0f7d6fba3befdef3371469134b5b19b66b31c8caa8e06d`；
其 content hash 綁定 contract、父 input hash、有效 feature IDs 與每列 base
feature content hashes。11 rows 的
`market_sector_cross_section` 與 `price_liquidity_technical` 均為
`coverage_bp=10000`、`missing_count=0`、`stale_count=0`、
`quality_blocked_count=0`、`max_available_lag_days=3`；consumer 會重新計算並
拒絕竄改 DQ 值。無法由 immutable feature row 分辨 stale／quality-blocked 的
不完整列不會被猜成 0，producer 會 fail closed。

實際 bounded 產物（11 rows，僅 TEMP）為：

- 父 input：`C:\Users\archi\AppData\Local\Temp\technical_analysis_postfreeze_cli_whk9_n42\post_freeze_shadow_input.json.gz`，bytes `sha256:ed75cda91593159e3c3041c9ffa88c756d32f9ad40bf2a8ffe0bb66357875297`，保留不變。
- raw dataset：`C:\Users\archi\AppData\Local\Temp\technical_analysis_postfreeze_raw_e1kb16bv\runs\pit-8fc40fac73840852f177bff7\all_field_enriched\manifest.json`，canonical hash `sha256:57e2911e7d0ac4dafc44ca97729190c6b9d25022247c5f9282e16b23a237d95b`；publication canonical hash `sha256:1fbfaf1c3f0735642a944f562580a5465d15d50a9e49030810295af9222e480e`。
- v3 candidate：`C:\Users\archi\AppData\Local\Temp\technical_analysis_postfreeze_feature_repair_k7dq\post_freeze_shadow_feature_repair.json.gz`，bytes `sha256:fdda4d32c54d4509781ac0597c4b6e8b6709cfd2da0bc526e893759cfee5c735`；dedicated consumer readback 成功。
- v3 audit：同目錄 `post_freeze_shadow_feature_repair_audit.json`，bytes `sha256:69f67260622f53bb00b66fd7e97c7170b3fc804e67dbd12fe5113836dfbaf11b`，canonical audit hash `sha256:fba2b7547b99b0c4c24f8e547c6b4025e6023bab65859c46e9d7d84d5a26cafd`，feature contract hash `sha256:2ccf5ed7043829d8cac15e509e7a73ef78365f72495c6257f99fa0de756011f6`。audit 的 calendar evidence 使用唯讀 snapshot `C:\Users\archi\AppData\Local\Temp\technical_analysis_official_db_snapshot_dndp7x58\twstock.snapshot.sqlite`，provider 為 `data_module.official_trading_calendar.OfficialTradingCalendar`，`allow_online_probe=false`，選出的前一交易日為 `2026-09-03`，evidence hash 為 `sha256:58447aad250ccccc0dc369b33b8420b930e21f538954b030fb57ba7dbed51572`。

同一個實際 source／T-1 consumer 比較結果為 market `漲跌點數` 與
`漲跌百分比` 各由 `11 missing → 11 observed`；前收日期為 2026-09-03、
當收日期為 2026-09-04，所有 rows 均保留
`decision_at=2026-09-07T18:00:00+08:00`。兩個 technical 分類欄由每列移除，
不是以 0 或估計值填補；因此它們沒有在 v3 產生 observed count，需另一次
明確的 categorical feature contract 與新 release 才能重新納入。未執行正式
model inference、training、DB／D 原始資料寫入或交易。

隔離測試為 `tests/test_ml_allocation_post_freeze_feature_repair.py` 的 7
passed，涵蓋 Decimal 推導、calendar provider 的交易日證據、連續交易日選擇、
中間交易日缺漏 blocker、假日跳過、derived source／contract 綁定、technical
排除、v3 readback、舊 consumer 拒絕、contract tamper、future availability 與
未知 calendar evidence blocker；完整舊路徑測試仍沿用上述本輪結果。

## Formal owner packet evidence state（2026-09-07）

本輪把 `app_module/formal_input_owner_packet.py` 從姓名驅動改為 evidence-driven
狀態機。`owner_role` 與 `reviewer_role` 仍保留在 packet 作 metadata，但不再決定
`packet_status`、`formal_ready_input_count` 或 `owner_reviewer_required`；缺來源會
是 `needs_input_evidence`，時間／cutoff 未定會是 `unknown_input_evidence`，consumer
拒絕會是 `input_evidence_invalid`。所有這些狀態的
`human_review_required=false`，避免把資料缺件重新命名成具名人工門檻。

packet caller 可明確傳入 `--formal-ledger-path`、`--formal-rule-history-path`、
`--formal-sector-path` 與共用的 `--formal-training-as-of`。它實際呼叫既有
`load_formal_portfolio_state_ledger`、
`load_verified_rule_champion_snapshot_history` 與 PIT sidecar assembler／discovery，
只有三者都回報 `ready` 且 `formal_consumer_compatible=true` 才計入 formal ready；
candidate inventory 的自填布林欄位不會授予 credit。ledger 的 transition 只有
Taiwan date、沒有 intraday availability，caller 採保守規則：cutoff 的 Taiwan
日必須晚於最後一個 date-only transition；Rule 與 PIT 保留帶時區的完整 cutoff，
同日尚未可得會被 consumer 拒絕。

PIT machine receipt／operational publication 仍可透過既有參數讀回，但只形成
`machine_candidate`，不升 `formal_ready_input_count`。以一項 PIT candidate 加兩項
missing source 的整合測試確認 readiness blocker 現在明示
`formal_input_source_missing:<input>` 與 `formal_input_machine_candidate:<input>`，
不再顯示「需要具名 owner／reviewer」。UI projection 只投影 bounded 的 ready、
candidate、missing、unknown、invalid 與 consumer-compatible 計數。

驗證：

```text
tests/test_formal_input_owner_packet.py
tests/test_formal_machine_consumer_integration.py
tests/test_inspect_ml_formal_input_readiness.py
tests/test_program_readiness_projection.py
28 passed

mypy --explicit-package-bases（formal packet、readiness、program projection、UI formatter）
Success: no issues found in 6 source files

UI formatter 回歸亦已完成：

tests/test_ui_qt_update_view_workbench.py
81 passed

scripts/qa_validate_update_tab.py
通過 25；失敗 0；跳過 4

mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
Success: no issues found in 540 source files
```

另以 repository 既有 ledger／Rule HMAC history／PIT sidecar fixtures 實際跑三個
consumer，驗證無姓名也可得到 `machine_verified`、`formal_ready_input_count=3`；
另有 routing fixture 比較有／無 owner 與 reviewer metadata 的 evidence projection、
status 與計數，輸出一致；
Rule snapshot 在同一台北日 09:00 發布、08:59:59 cutoff 的負例維持
`input_evidence_invalid`。這些都是 read-only TEMP fixtures，沒有寫正式 DB、D
原始資料、broker 或 production gate。Formal OOS、promotion、broker 與自然時間
限制仍未授權。

## 日常正式 Rule／ledger／PIT producer bounded handoff（2026-09-07）

本輪新增 `data_module/formal_daily_input_producer.py`（`bounded-source-handoff.v2`）與
`scripts/run_formal_input_producer_daily.py`。CLI 只讀取當下自然時間，先做
preflight，再把輸出寫入呼叫端指定的 OS TEMP 空目錄；沒有 `--now` 回填、沒有
broker／D 正式資料庫寫入，也不啟動 training 或 promotion。Rule 在啟動日之後可
沿用同一份已驗證 activation clock，仍以台北交易時段、官方交易日與唯讀 market
source 驗證；PIT 只產生官方 TWSE／TPEx response completion timestamp 綁定的
current-natural-day candidate，consumer 重新讀 receipt／raw custody，不能取得
歷史 PIT credit。

causal ledger candidate 只接受真正 append-only Paper snapshot 與 Paper fill SQLite
來源。producer 會以 accepted clock 的 activation day 過濾來源，舊 snapshot/fill 只
保留在 source content hash 的 custody 統計，不會進入候選 transition；snapshot 邊界
必須是官方相鄰交易日；fill 使用 `[start_date, end_date)`
區間（snapshot 是盤前日界，start 日成交可納入，end 日尚未能由 date-only source
證明，故排除），Decimal quantity／cash reconciliation、T-1 state、turnover 與
chain hash 全部由 producer／既有 formal ledger consumer 重驗。兩個來源各自在
同一個 SQLite read transaction 中讀取，aggregate source identity 使用已驗證列的
content hash；projection 的 `file_hash` 只標示 main-db bytes observation，不能當成
含 WAL 的完整來源身份。manifest 另含正式 loader 要求的 `manifest_hash`，再做
consumer readback。

截至本輪，D 上已有 Paper snapshots，但沒有可供日常接入的合規 Paper fill ledger
source；既有 `scripts/append_paper_trade_ledger.py` writer 仍需要明確的真實 fill
輸入。因此 preflight 會輸出 `formal_ledger_paper_fill_source_missing` 並維持
blocked；不能由 snapshot 反推成交。隔離 TEMP fixture 驗證相鄰交易日一筆 start-day fill（另有獨立
官方交易日證據）可產生
`machine_verified_candidate` 並被 `load_formal_portfolio_state_ledger` 讀回，而
end-day fill 會因 `[start, end)` 邊界拒絕，未獲官方開市證據的 fill 日也拒絕。candidate 仍不計入三項正式 controlled
input；只有呼叫端明確給出的三個 formal paths 經既有 consumer 成功 readback 才能
計入 `formal_ready_input_count`。

隔離驗證：

```text
tests/test_formal_daily_input_producer.py
8 passed

py_compile：formal_daily_input_producer.py、run_formal_input_producer_daily.py、
test_formal_daily_input_producer.py 通過
mypy --explicit-package-bases（producer、CLI、tests）
Success: no issues found in 3 source files
```

Rule candidate 另以隔離 market／clock／controlled HMAC fixture 實跑後重新讀取
published prospective history，交給既有
`data_module.prospective_capture_readiness._validate_rule_history_manifest` 驗證
clock、activation、自然 timestamp、snapshot hash 與 HMAC row shape；因此沒有把
prospective schema 誤送給只接受正式 full-history schema 的 consumer。

實際 D source 的 bounded CLI run（2026-09-07）使用既有
`D:\Min\Python\Project\FA_Data\sqlite\twstock.db`、
`output\formal_prospective\clock-20260828` 的 clock／universe／acceptance，及
`output\paper_portfolio\paper_portfolio.sqlite`。market schema 與 26 筆 Paper
snapshot 在唯讀 preflight 通過；目前沒有
`BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH` 對應的合規 Paper fill ledger，因此
`formal_ledger_paper_fill_source_missing` 保持 blocker。官方 holidaySchedule 在
此隔離執行環境無法連線，故當輪 Rule／PIT 也以
`official_calendar_not_proven:twse_holiday_schedule_unavailable` fail closed。receipt
僅寫入 TEMP：`%TEMP%\technical_analysis_formal_daily_real_20260907_c4e2\`；沒有
改動 D／正式 controlled path。已有 fill writer 是
`scripts/append_paper_trade_ledger.py`／`PaperTradeLedgerRepository`，仍需實際
Paper fill source 的明確輸入與自然日 append 後，daily producer 才會從該 source
建立 causal transition；不能由 snapshot 推造成交。

## 日常 Paper execution candidate 與 PIT live readback（2026-09-07）

本輪新增 `data_module/paper_daily_execution_producer.py` 與
`scripts/run_paper_execution_daily.py`，把當日 saved Recommendation、前一個
Paper snapshot 與官方 `daily_prices` 接成一條 bounded producer。producer 只接受
Recommendation 的當日台北自然日，snapshot 必須嚴格早於該日，行情 reference price
必須和官方列一致；target 差額依既有 Paper policy 以整股數建立 Decimal fill，並
保存 tick slippage、commission、賣出稅、turnover、execution gap、source file／
content hash 與 producer code hash。預設 output 是新的 OS TEMP candidate，不更新
snapshot、不寫 market／Formal DB、不連 broker、不啟動 training；指定
`--ledger-db` 並明確要求 append 時才會呼叫既有 Paper fill writer，writer 仍固定
research-only。

既有 `scripts/scheduled/run_paper_portfolio_daily.cmd` 已加入 opt-in hook：只有
呼叫端提供 `PAPER_EXECUTION_RECOMMENDATION_JSON` 才會呼叫上述 producer；state／
market path 可分別由 `PAPER_EXECUTION_STATE_DB`／`PAPER_EXECUTION_MARKET_DB` 指定，
候選輸出預設為新的 TEMP 目錄。hook 不傳入 append 確認參數，因此不會因排程而
追加 ledger。Recommendation 或前一 snapshot 不存在、當日 snapshot 已存在、
reference 不一致、官方交易日曆 unknown，均保留 machine blocker；不以空 fill、0
成本或 snapshot 反推成交。

實際 D preview（未追加 ledger）使用：

- Recommendation：`D:\Min\Python\Project\FA_Data\output\recommendation\runs\scheduled_rec_20260907_051003.json`，file hash `sha256:9330c91d8934405629d9f4f48d2c1a239741f1d886a71bfc75d4086fa33df165`，5 rows，decision date `2026-09-07`。
- State：`D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_portfolio.sqlite`，以 `mode=ro`／`query_only` 讀取；當日 `paper-main-20260907` snapshot 已存在。
- Market：`D:\Min\Python\Project\FA_Data\sqlite\twstock.db`，官方 holidaySchedule 在執行環境被 WinError 10013 阻擋，但 `market_indices` 唯讀日期證據使 `2026-09-07` 判定為交易日；此 fallback 沒有以星期幾猜測。
- Candidate receipt：`C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_execution_20260907_actual2\paper_execution_candidate.json`，producer status=`blocked`，唯一 blocker=`paper snapshot for current decision date already exists`，`append_requested=false`，沒有 fills 或 ledger 寫入。

同日隔離測試以小型 SQLite／Recommendation fixture 驗證 Decimal fill、既有
writer append/readback、空預覽不建 ledger、current snapshot blocker、reference
mismatch、calendar unknown、local `market_indices` fallback 與 historical date 拒絕，
共 8 passed；formal daily producer 另為 12 passed，包含 calendar closed／unknown
時 company PIT response 仍可完成 source publication、receipt、controlled
operational publisher 與 consumer readback，PIT capture `capture_eligible=true`
但 `trading_decision_eligible=false`。

本輪另以實際官方 HTTP response 執行 live readback（只寫 TEMP）：

- capture directory：`C:\Users\archi\AppData\Local\Temp\technical_analysis_pit_live_20260907_a1\`。
- 官方 raw：TWSE `t187ap03_L` 1,326,272 bytes；TPEx `t187ap03_O` 1,070,809 bytes。
- publication：661,017 bytes，file hash `sha256:b32509d55c8ff7a7ab735aa97655d2eb5890850ed1069e316c910ad3001570f1`，content hash `sha256:ced79d77a21b1f553d91e37ad862eca4648358b6e1b509f7df3dc023e10ecdce`，1,984 rows。
- receipt：`status=machine_verified`，file hash `sha256:9500aeba15ab7efa9f4d2c2d24f483dc75336fe0a0b1ed5c95558172857e6476`，content hash `sha256:3b5dc40b57d56205f09e173418c46c62e72e2d8089e8adfb109ce0a6fa87efb1`，`source_custody_verified=true`、`rows_rebuilt_from_raw=true`，capture `2026-09-07T20:50:04.243271+08:00`。
- operational publisher／consumer：在 `decision_at=2026-09-07T12:50:22Z` 讀回成功，operational file hash `sha256:cd8d0eba2c5a396160b7f0721c533a66b79eafe7994d88584d44e9f93f8740fe`，source ids 為 `official:tpex:t187ap03_O`、`official:twse:t187ap03_L`；仍是 `candidate_only=true`、`formal_consumer_compatible=false`。

驗證命令：

```text
.\\.venv\\Scripts\\python.exe -m pytest tests/test_formal_daily_input_producer.py -q -o addopts=
12 passed

.\\.venv\\Scripts\\python.exe -m pytest tests/test_paper_daily_execution_producer.py -q -o addopts=
8 passed

.\\.venv\\Scripts\\python.exe -m mypy --explicit-package-bases data_module/paper_daily_execution_producer.py scripts/run_paper_execution_daily.py
Success: no issues found in 2 source files
```

官方 PIT response 曾有一次 TPEX transport 讀取失敗，重試同一 bounded request
後成功；失敗不會由 producer 以空資料補齊。這些產物與測試只證明 current-day
source custody、Paper candidate 與 consumer readback，沒有把它們升格為 Formal
三項完整 input、歷史 PIT、自然 fill ledger、正式 OOS、promotion 或投資有效性。

## Paper execution T+1 時序與排程冪等修正（2026-09-07）

上一段的當日 Recommendation／當日行情描述是早期 candidate contract；本次已由
`paper-execution-daily-producer.v2-t1-open` 取代。Recommendation 在決策自然日
凍結，producer 沿官方證據尋找下一個交易 session；只有主機實際時間到達台北
09:00 open cutoff，才使用 execution 日 `開盤價` 建立 fill。Recommendation 日的
`收盤價` 只作來源 binding；成交量必須是 Recommendation 日收盤時已可取得的
正數，整張 lot 固定 `1000` 股，每檔最多使用 Recommendation 日 `成交股數` 的
`500/10000` participation。execution 日完整 EOD `成交股數` 不會被用來決定
09:00 cap，避免把尚未可得的全天量帶入開盤成交。現有 `daily_prices` 沒有盤中
capture timestamp，所以此入口明確是
`delayed_eod_replay_after_session_close`，保存
`execution_source_capture_at=null`、`execution_source_capture_at_proven=false`
與 `realtime_execution_allowed=false`；缺欄、低流動性、逾期 session 或未知
官方日曆都保持 blocker。這避免把同一日收盤資料當成同 close 成交，也不把前一
自然日合法 Recommendation 誤報為歷史回補。

Snapshot 語意固定為台北 08:30 的 `preopen_t_minus_one_mark_to_market`；它只以
嚴格 T-1 行情做估值，不代表 execution transition。排程
`scripts/scheduled/run_paper_portfolio_daily.cmd` 已先執行 opt-in T+1 candidate、
再執行 snapshot valuation；candidate 的 blocked exit 會保留狀態但不跳過獨立
valuation。下一次自然日 state projection 可在唯讀 ledger 中套用已 append 的
`paper_daily_execution_delayed_eod_replay_v1` transition（並保留舊
`paper_daily_execution_v1` 的讀取相容性）；同日 snapshot 已先存在時，只有同一組
deterministic fill IDs 已完整 readback 才允許 exact idempotent replay，partial／
divergent batch 仍拒絕，絕不覆寫 snapshot 或重造 fill。

隔離測試 `tests/test_paper_daily_execution_producer.py` 為 `14 passed`，覆蓋：
T+1 prior-day Recommendation、next-session open／prior close binding、09:00 前
等待、15:00 EOD replay gate、錯過 session 拒絕、同日 snapshot blocker、append 後同日 exact replay、
推薦日成交量 participation／board-lot 限制、execution 日 EOD 成交量變動不影響
凍結開盤 fill、未知日曆及 local market_indices fallback；
`tests/test_run_paper_portfolio_daily.py` 另為 `8 passed`。py_compile 與 mypy
（producer／兩個 CLI／snapshot runner）均通過。

本次真實 D public runner 只寫新的 TEMP candidate：

- Recommendation：既有 `D:\Min\Python\Project\FA_Data\output\recommendation\runs\scheduled_rec_20260907_051003.json`，file hash `sha256:9330c91d8934405629d9f4f48d2c1a239741f1d886a71bfc75d4086fa33df165`，決策日 `2026-09-07`。
- 執行命令同時以唯讀方式指定既有 state／market／ledger 路徑，output 為
  `C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_execution_t1_public_20260907_061318\paper_execution_candidate.json`。
- Candidate file hash 為 `sha256:94e5a5a9ad7310132d3be5fab2b2e124981221ab31188da0f148a424a77c0b4f`，payload content hash 為 `sha256:495dc775889d49e2440593f556a4621da156899ad9e066d95b8713718e35d6cb`，producer code hash 為 `sha256:2f49d0944729f5ac559dacd8fc6ecdd5c9985306654971dca81cb76b438d6f70`。
- Producer 正確讀到 Recommendation 日 `2026-09-07`，推導下一候選 session
  `2026-09-08`；官方 holidaySchedule 在隔離環境為 WinError 10013，local
  `market_indices` 沒有 2026-09-08 的可驗證列，因此 status=`blocked`、
  blocker=`official_calendar_not_proven:twse_holiday_schedule_unavailable`。
  沒有開啟 state／market 交易寫入，沒有 fills、ledger append、snapshot 覆寫或
  歷史回填；下一個官方 session 證據可取得後才會進入 open／volume／state 階段。

### EOD source availability gate correction（2026-09-07）

針對 `daily_prices` 沒有逐列 capture timestamp 的限制，producer 現在把延遲
EOD replay 的最低可消費時間固定為 execution 日台北 15:00，並在 candidate 保存
`execution_source_available_after`、
`execution_source_availability_policy=conservative_session_close_plus_90m_delayed_eod_replay`、
`execution_source_capture_at=null`、`execution_source_capture_at_proven=false`。
因此 09:00 後但 15:00 前只輸出 `waiting_for_execution_source`，不讀 state／market、
不建立 fill；15:00 後才可讀 execution 日開盤列作延遲重播。推薦日成交量仍是
唯一的 participation cap 輸入，T 日全天量即使出現在 EOD row 也不會改變已凍結
開盤 fill。這條路徑仍為 `candidate_only=true`、`formal_ready=false`、
`realtime_execution_allowed=false`，沒有宣稱 09:00 收到 HTTP 或形成 live fill。

新增 `test_before_delayed_eod_source_waits_without_reading_market_or_state`、
`test_execution_day_eod_volume_cannot_change_frozen_open_fill_or_cap` 與 queue
processed／missing-root receipt 測試後，隔離 producer 測試為 `16 passed`；Paper
runner／排程與相容回歸合計 `22 passed`、
scheduled wrapper checks `28 passed`。py_compile 與 mypy（producer、execution CLI、
snapshot runner）均通過。最新實際 CLI 仍只寫 TEMP：

- output：`C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_execution_t1_public_20260907_10f76ca5dac74ee7999280d771746ecd\paper_execution_candidate.json`。
- status=`blocked`，blocker=`official_calendar_not_proven:twse_holiday_schedule_unavailable`；
  Recommendation 仍為 `scheduled_rec_20260907_051003`，沒有讀寫 state／market／ledger。
- candidate file hash=`sha256:f85248bd4b153051db5b2fd1315fe9d12646eecf74d7a08683b698ff67ec1a8c`，
  payload content hash=`sha256:ef070ee06fada8542ab493d2caca33d0164dc3417cd97af1281950d28d16a069`，
  producer code hash=`sha256:147ef5e164a4cf61945ff94b6f70f71dca1927dcc5fdd39bd5116f1a66045c60`。

由於原本 05:28 的 `baldr-paper-portfolio-daily` 在來源門檻前執行，單次排程不會
等到 EOD replay 可得；已新增獨立的
`baldr-paper-execution-eod-replay-daily`／`run_paper_execution_daily.cmd`，預設
本機 00:05（對應台北 15:05）從 `OUTPUT_ROOT/recommendation/runs` 選取下一
official session 到期的 frozen recommendation，並把 processed／waiting／failed
receipt 保存到 `OUTPUT_ROOT/scheduled/paper_execution_eod_replay/receipts`。它
預設以可配置 `PAPER_EXECUTION_LEDGER_DB` 追加 research-only Paper ledger；設定
`PAPER_EXECUTION_APPEND=0` 才改為 candidate-only，且兩種模式都不跑 valuation。
`register_baldr_scheduled_tasks.cmd`、PowerShell registration、query、unregister
與唯讀 registration inspector 均已納入第 14 個 task；相關 task／wrapper／probe
測試皆通過。若主機時區不是目前的 America/Los_Angeles，owner 應以輸出內的
`execution_source_available_after` 核對排程時間；排程不會將等待或 failed 狀態改為
成功。最新隔離 queue 測試證明 due frozen recommendation 可 append/readback，
processed receipt 會使同一 source 不再重跑；缺少 queue 則輸出可見
`skipped_no_pending_recommendation` 與 `recommendation_root_missing` receipt。
### Queue 唯一 source 與 receipt 完整性修正（2026-09-07）

Root review 指出只排除 `processed` 的 source hash 仍有切換風險：同一
`paper-main + next_official_execution_date` 若有兩份 frozen recommendation，排除
最新 processed hash 後，舊候選可能在下一輪被誤選。本輪 `resolve_pending_recommendation`
改以該組唯一鍵選擇最新建立的 source，並保存舊候選的 immutable
`queue_state=superseded` receipt；已有合法 processed receipt 的 execution session
不再選任何同鍵 source。這只凍結 Paper research queue，不改 Formal／行情資料庫，
也不把 delayed EOD replay 變成 realtime fill。

Queue 在採用 terminal receipt 前會重新驗證 receipt schema、canonical content hash、
source recommendation result／path／file hash、execution date 與 queue state。對
`processed + machine_verified_candidate` 還會以 SQLite `mode=ro/query_only` 讀回
receipt 引用的 fill IDs，確認 append/readback、`research_only=true`、
`broker_order_allowed=false` 與 `auto_rebalance_allowed=false`；不完整、變更或
重新封套後聲稱 processed 的 receipt 不會阻止 source 重試。Recommendation queue 中
壞 JSON 也不再折疊成一般 `no_pending_recommendation`，會在 skipped blocker 中保留
檔名、錯誤類型與具體原因。

隔離驗證（只寫 TEMP）如下：

- `tests/test_paper_daily_execution_producer.py`：`19 passed`，新增同一 execution
  session 多 recommendation 唯一選擇／superseded、rehashed ledger readback／不支援
  schema 不跳過、壞 source 可觀測測試。
- `tests/test_scheduled_paper_execution_wrapper.py`：`1 passed`，以實際
  `cmd.exe /d /c scripts/scheduled/run_paper_execution_daily.cmd` 啟動，未設定
  `PAPER_EXECUTION_RECOMMENDATION_JSON`，queue root 缺失仍落盤
  `skipped_no_pending_recommendation` 與 `recommendation_root_missing` receipt。
- Paper producer／runner／wrapper focused：`28 passed`；scheduled registration、
  README、inspector、wrapper：`35 passed`。mypy（producer／execution CLI）與
  py_compile 通過；僅有既存 `.pytest_cache` 權限 warning。

實際既有 D source 的 scheduled queue run（2026-09-07，`PAPER_EXECUTION_APPEND=0`，
state／market 只讀，output／receipt 皆為 TEMP）為：

- isolated root：
  `C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_queue_actual_9dbc59b3430f43a59adf2c57c406d655\`。
- Queue 自動選取 `D:\Min\Python\Project\FA_Data\output\recommendation\runs\scheduled_rec_20260906_051003.json`，source file hash
  `sha256:101d9593767e895c338358cb3349bf6674e85de3e159eb0c02581daaa46fe1b1`；同一
  2026-09-07 execution session 的較舊 source 被保存為 `superseded`。
- Candidate：
  `candidate/paper_execution_candidate.json`，file hash
  `sha256:b49129066db8c3c53a531e89951d05f06fb98579fa309d344ea21be3e8a7e906`，content
  hash `sha256:7c3b0b2e5e02d5d48ce5503647f6ef05dfd7545a7340d4cd6f4303905f4f6cd6`，
  producer code hash
  `sha256:3e4eb5592a24b3cbc9e74eec3f9235fe2675dd8340bb77f8ac2f216aead47b1b`，
  `decision_date=2026-09-06`、`execution_date=2026-09-07`、
  `execution_source_available_after=2026-09-07T15:00:00+08:00`。
- Result=`blocked`，原因為 `paper snapshot for execution date already exists; run
  execution before preopen snapshot`；沒有 fill、ledger append、snapshot 覆寫或
  Formal／行情寫入。兩份 receipt 的 file hash 分別為：failed
  `sha256:2522dd1e94866b46def19489c151d3df96f8d4ff83a7c440350c7a2bbc73b3d3`、
  superseded
  `sha256:e62204633c0f39c45cc88a507a6e160477e53fd026a9edceba69a256a3678eaf`。
  此輪官方 holidaySchedule HTTP 受 WinError 10013 阻擋，但 local
  `market_indices` 唯讀列證明 2026-09-07 為交易日；calendar unknown 仍會 fail
  closed，沒有以 weekday 猜測下一 session。

## Paper preopen→EOD→retry→next-preopen 串接修正（2026-09-07）

本段修正上一段早期 candidate 的 snapshot 時序描述。台北 08:30 preopen snapshot
是 execution session 的 T-1 起始狀態；EOD writer 只能在延遲來源門檻後追加獨立
postfill transition，因此 snapshot 已先存在不再是人工或排程 blocker。producer 以
`preopen_snapshot_reused_append_only_postfill_transition` 明確記錄此語意；首次
append 與相同 deterministic fill IDs 的 retry 都要通過完整 ledger readback，partial
或 divergent batch 仍 fail closed，絕不覆寫 snapshot。

Recommendation 的自然日與行情 reference date 已分離。producer 以官方日曆或唯讀
`market_indices` 證據找出 decision date 當日或之前最近的實際 session；例如 2026-09-06
週日 recommendation 綁定 2026-09-04 close／volume，不要求 `daily_prices` 出現週日
列，也不以 weekday 推測交易日。candidate 另外保存
`market_reference_session`、`market_reference_date`、`recommendation_reference_date_basis`
與 execution date，讓 consumer 可以重驗自然日與資料日的關係。

下一個 `run_paper_portfolio_daily.py` preopen runner 現在可用 `--ledger-db` 以
`mode=ro/query_only` 讀取已 append 的 research-only Paper fills，依
`prior.decision_date <= event_date < decision_date` 投影現金／股數至新 snapshot；
轉換只接受既有 Paper execution source type，負現金、超額賣出、schema 不完整或
ledger 讀取期間 hash 改變都會拒絕。新 snapshot 不會重用已存在的 `snapshot_id`，
重跑只回報 duplicate，不會再次套用 transition。這條 projection 保持
`research_only=true`、`broker_order_allowed=false`、`auto_rebalance_allowed=false`，
不會修改正式行情／Formal DB 或啟動交易。

隔離驗證：

```text
tests/test_paper_daily_execution_producer.py
21 passed
tests/test_run_paper_portfolio_daily.py
10 passed
兩套合計
31 passed
scheduled registration／wrapper／README／inspector
35 passed
mypy（producer、paper execution CLI、paper portfolio CLI）
Success: no issues found in 3 source files
py_compile（兩 producer 與兩測試檔）通過
```

新增整合測試先建立 execution-date preopen snapshot，再跑 EOD candidate（不 append），
接著明確 append 一次，確認 retry 仍只讀回同一筆 fill、state DB bytes 不變且 ledger
只有一筆；另以既有 `PaperPortfolioSnapshotRepository` 的下一自然日 runner 讀取
同一 ledger，驗證賣出 transition 後現金增加、股數歸零、`total_value == cash`，以及
重跑不重套 transition；再以 producer 的下一 execution session candidate 重讀
同日 postfill event，確認不會以舊持倉重建買單。這些是 research Paper 路徑的真實
producer／consumer 測試，不代表已產生可宣稱為 live 的成交。

實際 D queue 只讀 candidate run（2026-09-07，`PAPER_EXECUTION_APPEND=0`；output／
receipt 寫入 TEMP）如下：

- isolated root：
  `C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_queue_actual_20260907_timingfix2\`；receipt root 為同層的
  `technical_analysis_paper_queue_actual_20260907_timingfix2-receipts\`。
- Queue 選取：
  `D:\Min\Python\Project\FA_Data\output\recommendation\runs\scheduled_rec_20260906_051003.json`，
  source file hash `sha256:101d9593767e895c338358cb3349bf6674e85de3e159eb0c02581daaa46fe1b1`；
  decision date `2026-09-06`、execution date `2026-09-07`、market reference date
  `2026-09-04`。此 reference date 由 actual local `market_indices` row 證明；官方
  holidaySchedule HTTP 在隔離環境仍受 WinError 10013 阻擋，unknown 不會被猜成開市。
- Candidate：隔離 root 下的 `paper_execution_candidate.json`，file hash
  `sha256:bcb60a554ce5ddab0575d47e0600c4871dcf13c714f596227333717e004d0cba`，
  content hash `sha256:f888886a948f6c29fbe5ace1064909e12ffb17350ced4f4b2cb5509910f092a4`，
  producer code hash `sha256:d0bf9f8778dbd7933e4cf073d9b97fa4fa40402e85d58fde173fd995e4c13698`。
- Result=`blocked`，真實來源 blocker 為
  `paper execution liquidity cap exceeded:1418:requested=3000:cap=0:volume=6217:participation_bp=500`。
  這表示 preopen state／官方 reference 已通過讀取，但 1418 的 reference-session
  volume 6217 在 5% participation 與 1000 股整張限制下不能產生合法 fill；不以零
  成交量或人工覆核替代。此次沒有 ledger append、snapshot overwrite、正式資料庫寫入、
  broker order 或歷史 9/7 回填；failure receipt file hash 為
  `sha256:68ec68309bd3f8f85434677c1b9c1d724e9c0a5291039c8b9d726f15d9052da2`，
  superseded receipt file hash 為
  `sha256:439548df0ce8a00230ae979807cac9eaf57e01770ad1cd8adb6da62be23f1975`；兩者
  與 candidate 都留在 TEMP 供 QA 重驗。

## Paper 委託級 partial／rejected 與現金結算修正（2026-09-07）

本輪把正常低流動性從整輪 blocker 改成委託級結果：推薦日收盤成交量的固定
`500/10000` participation cap 先向下取整至 1000 股；cap 為零保存
`status=rejected`，cap 小於 requested 保存 `status=partially_filled`，兩者都保留
`requested_quantity`、`filled_quantity`、`remaining_quantity` 與
`execution_reason`，其他 symbol 繼續依同一份已驗證 source 評估。缺價格／成交量、
帳務不一致、超額賣出或負現金仍在 preflight／projection 階段整輪 fail-closed。
reserve 只限制 buy；期初現金低於 reserve 時，合法 sell 仍可先增加現金。Ledger
仍是 append-only，deterministic fill ID 的 exact retry 不會重複 append，未成交量會
留在下一個自然日 state projection。

`PaperTradeFill.total_cost` 的既有語意維持為 commission + tax + slippage attribution，
不改歷史 payload／hash。由於 `fill_price` 已包含 tick slippage，所有現金 consumer
改採 `cash_settlement_cost=commission + tax`：buy 扣 gross + settlement fees，sell
加 gross 後扣 settlement fees。新增 property 沒有加入 `to_dict()`；candidate 與
projection 另保存 `cash_settlement_semantics=gross_amount_plus_commission_plus_tax_v1`
及 `cost_attribution_semantics=commission_plus_tax_plus_slippage_attribution_v1`。

新增隔離回歸：

- `test_partial_liquidity_continues_other_orders_and_carries_remaining_on_retry`：
  2330 requested=3000 在 cap=1500 下 partial=1000、remaining=2000，2317 的合法買單
  繼續完成；append／exact retry 各一筆，下一日 projection 保留 2330 的 2000 股。
- `test_low_cash_does_not_block_multiple_legal_sell_orders`：期初現金只有 1 元時，
  兩筆合法 sell 都完成，沒有被 minimum cash reserve 錯誤阻擋。
- `test_cash_reconciliation_charges_fees_once_and_keeps_slippage_attribution`：固定
  15bp 手續費（最低 20）／賣出稅 30bp，10.00→10.05 買 1000 股與 10.00→9.99 賣
  1000 股，獨立手算期末現金 `99870.03`；slippage 只作歸因，不重扣。

驗證結果：`tests/test_paper_daily_execution_producer.py` 為 `23 passed`，
`tests/test_run_paper_portfolio_daily.py` 為 `10 passed`，Paper ledger／reconciliation／
formal daily consumer 為 `24 passed`，scheduled wrapper／registration／README 為
`35 passed`；focused 合計 `57 passed`。mypy（ledger、reconciliation、producer、
formal producer、daily runner）與 py_compile 均通過，僅有既有 `.pytest_cache` 權限
warning。

實際官方來源唯讀 candidate（未帶 append flag，output／receipt 均為 TEMP）：

- output：
  `C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_partial_actual_20260907\paper_execution_candidate.json`。
- source recommendation：
  `D:\Min\Python\Project\FA_Data\output\recommendation\runs\scheduled_rec_20260906_051003.json`，
  file hash `sha256:101d9593767e895c338358cb3349bf6674e85de3e159eb0c02581daaa46fe1b1`；
  market reference `2026-09-04` 由 D `market_indices` 唯讀 evidence 證明，execution
  session 為 `2026-09-07`。
- candidate file hash `sha256:d8e6123a229640761223dae189818c290512167c02bd82e92845a86fee6399e2`，
  content hash `sha256:9b7c6ea2d775a18ec459ca8b7934a6fce493a1726d0bd02e50aa288440057295`，
  producer code hash `sha256:9b1c4ead1f81e9a3129ce9870a6d1ebb72f2d19f6c8c2c8e2119bb1da2fda33b`。
- result=`machine_verified_candidate`、`candidate_only=true`、`formal_ready=false`；
  1418 保存 rejected／remaining=3000／reason=`liquidity_cap_zero`，1536 與 1615
  仍各自保存合法 filled event，projection 現金為 `434925.42`。receipt state 為
  `candidate_only_pending_append`，沒有建立 ledger、沒有寫 D state／market／Formal
  DB、沒有 broker order 或歷史回填。

## 日常 Formal producer 的 durable 排程接線（2026-09-07）

本片把已驗證的 `data_module.formal_daily_input_producer` 接到可重複執行的
`scripts/scheduled/run_formal_input_producer_daily.cmd`。它預設把每輪 candidate／Rule
development 放到新的 TEMP 子目錄，把 Rule history／causal Paper ledger 的 immutable
manifest、source custody、publication context、receipt 保存到
`output/formal_daily_publications`，並以原子替換更新 `scheduler/latest_status.json`。
`FORMAL_DAILY_OUTPUT_ROOT` 與 `FORMAL_DAILY_DEVELOPMENT_OUTPUT_ROOT` 是 parent，不能
讓固定非空目錄在第二輪變成來源；每輪 run id 由 wrapper 產生且不回填自然時間。

Rule 的 clock／universe／owner 缺件不再在 wrapper 邊界提前 return；正式 producer 仍會
回報 Rule blocker，同一輪 PIT 現況 capture 可以依自己的官方 response completion 時間
判定。缺 Paper source、calendar、HMAC、consumer custody 或 cutoff 證據仍是具體 blocker。
wrapper 只在 `formal_inputs_machine_verified` 回傳 0；`candidate_only` 與 `blocked` 都
回傳 2，且維持 `formal_ready_input_count=0`、`formal_oos_allowed=false`、
`broker_order_allowed=false`。

隔離回歸：

- `tests/test_scheduled_formal_input_producer.py`：6 passed，覆蓋 Rule source 缺件仍
  傳給 producer、candidate-only 非成功、固定 parent 的兩輪唯一空子目錄、durable
  status 與 status root 越界拒絕，以及使用 fixture 官方 TWSE／TPEx response
  實際跑過 PIT producer 的兩輪同一設定重試。
- `tests/test_scheduled_cmd_scripts_exist.py`、`tests/test_scheduled_cmd_scripts_task_names.py`、
  `tests/test_scheduled_cmd_scripts_no_confirm.py`、`tests/test_scheduled_readme_no_production_confirm.py`：
  28 passed，確認 `baldr-formal-input-producer-daily`、21:25 Pacific local task、query／
  unregister、wrapper path 與 no-confirm 規則一致。
- `tests/test_formal_registration_plan.py`：覆蓋單項 task 的 dryrun、只對該 task
  呼叫 create/query，以及非 Pacific timezone 的 fail-closed；21:25 在 PDT/PST
  分別對應台北 12:25/13:25。
- `tests/test_formal_daily_input_producer.py`：19 passed；Rule／ledger durable receipt
  失敗恢復、刪除 TEMP source 後 custody retry、自然日 cutoff 與現有 machine consumer
  readback 均維持通過。
- `tests/test_formal_pit_candidate_archive.py`：3 passed；PIT archive 會保留兩份
  official raw bytes，刪除 TEMP 後仍可重驗 rows，竄改 raw 或 file hash 會拒絕。

現有排程設定：

```text
task: baldr-formal-input-producer-daily
local schedule: DAILY 21:25 (Windows Pacific Standard Time)
Taipei correspondence: 12:25 PDT / 13:25 PST
wrapper: scripts/scheduled/run_formal_input_producer_daily.cmd
publication root: <repo>/output/formal_daily_publications
```

單項註冊入口為 `scripts\\scheduled\\register_formal_input_producer_task.cmd`。
它先核對 Windows timezone ID 為 `Pacific Standard Time`，再以 21:25 建立或更新
`baldr-formal-input-producer-daily`；該入口只呼叫此 task 的 `schtasks.exe /Create`
與 `/Query`，不會重註冊其他 task。PDT/PST 的台北對應都落在 Rule 09:00–13:30
capture window；其他 timezone 直接 fail closed。排程執行所需的來源路徑仍需在 Windows
使用者環境一次設定；這些是 machine-readable source artifacts，不是具名人工審核欄位：
`FORMAL_DAILY_CLOCK_MANIFEST`、`FORMAL_DAILY_UNIVERSE_SYMBOLS`、
`FORMAL_DAILY_OWNER_ACCEPTANCE`；market／Paper 路徑有明確 default，也可使用
`FORMAL_DAILY_MARKET_DB`、`FORMAL_DAILY_PAPER_SNAPSHOT_DB`、
`FORMAL_DAILY_PAPER_TRADE_LEDGER_DB` 覆寫。設定後可用
`scripts\\scheduled\\register_formal_input_producer_task.cmd dryrun` 審查 task action，
再以同一腳本的 `register` 模式安裝。本片已在 Windows `Pacific Standard Time` 主機
執行該單項 `register` 並立即 query；Task Scheduler 回報 `Status=Ready`、
`Scheduled Task State=Enabled`、`Start Time=21:25`，且只建立／更新
`baldr-formal-input-producer-daily`。Query 同時顯示尚未到首次排程執行
（`Last Run Time=1999/11/30`、`Last Result=267011`），因此這是安裝／query 證據，
不是把排程尚未執行誤報成 terminal success。沒有重註冊其他 task，也沒有寫 D、
Formal controlled DB、行情原始資料、broker 或 ML output。升權 XML query 另確認
`ExecutionTimeLimit=PT1H`、`MultipleInstancesPolicy=IgnoreNew`；Task Scheduler 回報
`InteractiveToken`、`DisallowStartIfOnBatteries=true`、`StopIfGoingOnBatteries=true`，
因此本 task 需要已登入的 Windows 使用者且不代表無人值守服務。

實際執行證據（2026-09-07，當下 clock；未使用 `--now`）：

- durable status：
  `output/formal_daily_schedule_actual_20260907/scheduler/latest_status.json`，
  file SHA-256=`079e36cc9fec186a9f1d05dc9853988612d4e2ee127ecb062081db64fb5c31ad`。
- status=`blocked`、`formal_ready_input_count=0`、`machine_candidate_input_count=0`；
  `PIT capture_eligible=true`，但官方 HTTP socket 受 Windows `WinError 10013` 阻擋，
  未捏造 PIT response。Paper snapshot 是已存在的唯讀來源，Paper trade ledger 缺件；
  Rule 當下已超出台北 regular-session capture window。
- machine blockers 原樣保存為：
  `formal_ledger_source_file_missing`、`formal_rule_history_source_file_missing`、
  `formal_sector_source_file_missing`、`pit_source_production_failed:<WinError 10013>`、
  `rule_capture_outside_taiwan_regular_session`。本次沒有 durable 3/3 或 Formal credit，
  也沒有回填 2026-09-07。

權限邊界補記：一般 sandbox 的獨立 `/Query` 回報 `system cannot find the path
specified`，但 register 所在的升權 Task Scheduler session 立即 `/Query` 成功並
回報上述 `Ready/Enabled`。兩者視圖不同，不能把一般 sandbox 的不可見誤判為 task
不存在；也沒有因此重註冊或觸碰其他 task。

### 允許網路環境的真實 PIT wrapper 產物（2026-09-07）

註冊後以升權 Task Scheduler session 觸發兩次，第一次因 TPEx response 非 UTF-8 JSON
fail-closed，第二次因官方 endpoint 回 HTTP 520 fail-closed；兩次均回 `Last Result=2`，
沒有把錯誤頁或不完整 bytes 當成資料。之後在同一台 Windows `Pacific Standard Time`
主機的允許網路環境，直接執行既有
`cmd.exe /d /c scripts\scheduled\run_formal_input_producer_daily.cmd` 一次，未帶
`--now`、日期覆寫或 fixture。這是 wrapper 的真實 source execution，結果仍依
candidate-only exit policy 回 2。

這次執行的 durable scheduler status 為：

- `output/formal_daily_publications/scheduler/latest_status.json`，file SHA-256
  `sha256:d13822a0b5fe4e72af4b69dfb3b8bc2462245703b516c24eef253fee06480363`；
- `status=candidate_only`、`observed_at=2026-09-07T15:45:16.671019+00:00`、
  `formal_ready_input_count=0`、`machine_candidate_input_count=1`；Rule／ledger／sector
  的來源缺件仍逐項保留，沒有升格 Formal。

PIT 結果由官方 TWSE `t187ap03_L` 與 TPEx `t187ap03_O` response 產生，source custody
與既有 machine consumer readback 通過 1,984 rows。完整 immutable candidate archive
 為：

- `output/formal_daily_publications/pit_candidate_archive/2026-09-07/05cfa45cd06221a6-5c0f35d14dbd4e90/`；
- `archive_manifest.json` file SHA-256
  `sha256:4131bbb22382d95158dbf0f4a005e7332db2c35e4cde6a7fc7d80b47ba4a3346`；
- `publication_content_hash=sha256:05cfa45cd06221a67536f6c412cbf3b91b20c9330c48b830a8d6d5afaaa1228b`；
- archive 內含 publication、receipt、operational envelope 與
  `twse_t187ap03.raw.json`／`tpex_t187ap03.raw.json`。

process 結束後再由 archive manifest 直接 readback（不依賴 TEMP path）回傳
`durable_candidate_readback_verified`、`row_count=1984`、上述兩個 official source ID，
`consumer_verified=true`、`candidate_only=true`、`formal_consumer_compatible=false`。
這證明的是 current natural-day candidate 的可重驗持久 custody；`effective_from` 是
實際 capture 的台北日期 `2026-09-07`，沒有填入歷史 PIT 或自然日 credit。archive
仍不是 `formal_sector_path`，不會改變 formal count、promotion、broker 或 D 寫入邊界。

Task Scheduler 的最新 `Last Result=2` 與上述直接 wrapper 的 candidate status 必須分開
判讀：前者是實際排程嘗試中的官方來源錯誤，後者是允許網路環境取得真實 PIT candidate
並持久保存後的 machine evidence；兩者都不能宣稱三項 Formal 3/3。下一輪仍需在合法
台北 Rule window 取得 Rule source，Paper append-only fill 與 official calendar 才能
產生 causal ledger，並由正式 consumer 對三項來源逐一 readback。

截至本片尚未以這個 scheduled wrapper 取得三個正式來源的 3/3：PIT 的 current
candidate custody 已由官方兩市場 response 完成，但仍不是正式 sector source；Rule
來源要在合法台北 09:00–13:30 capture window 內，causal ledger 仍需 Paper append-only
fills 與官方 calendar。這些缺件會在
`scheduler/latest_status.json` 與各 durable receipt 保留，不能以 owner 名稱、fixture、
歷史 clock 或等待時間補足。

## PIT current archive → history handoff（2026-09-08 台北自然日）

本輪新增 `data_module/formal_pit_history_handoff.py`，並由
`run_daily_formal_input_producer` 在設定 `publication_root` 時實際呼叫。它把已由
machine consumer 驗證的 current PIT archive 重新讀回，保存 archive manifest／
publication／receipt／operational／官方 raw 的 file/content hash、capture／archive
時間、producer 與 source lineage；它不把 current snapshot 轉成歷史 sidecar，也不
提升 `formal_consumer_compatible`。外層 handoff 是 create-only，第一次寫入的實際
`created_at` 在 retry 時保留；projection、外層 hash 或 schema 變更會拒絕 readback。

coverage 的 contract 固定使用台北每日 08:30 cutoff。capture／archive 在某日
cutoff 後只能供下一個自然日使用；官方日曆 unknown、capture／archive 晚於要求的
decision instant、缺日或中間日沒有 source，均保留具體 blocker。PIT denominator
不沿用 Rule universe：呼叫端要用 `--pit-expected-universe`（排程環境
`FORMAL_DAILY_PIT_EXPECTED_UNIVERSE` 或
`BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH`）提供 archive 外部的排序唯一 symbol JSON，
並用 `--pit-history-coverage-start`／
`FORMAL_DAILY_PIT_HISTORY_COVERAGE_START` 指定 coverage 起點。缺少或與 publication
symbols／rows／hash 不一致時，archive custody 仍會列為 valid observation，但不會
納入歷史 lineage 或 coverage；`source union`、非空 license 字串、owner 名稱及
外層重簽 hash 都不能補足此證據。

本輪以 root 已驗收的真實官方 PIT archive 執行 handoff readback：

- archive：`output/formal_daily_publications/pit_candidate_archive/2026-09-07/05cfa45cd06221a6-5c0f35d14dbd4e90/archive_manifest.json`，兩個官方 source、1984 rows、raw custody 與 machine consumer readback 均已驗收。
- handoff：`output/formal_daily_publications/pit_history_candidate/2026-09-08/handoff-6ca3f901e884d194.json`，file hash `sha256:cfb0242debd39cf219da38c1e48c1760d6f26ba2259c6855ce73a68afdb84eb6`；`status=candidate_only`，projection `status=candidate_history_verified`、`valid_archive_count=1`、`formal_ready=false`，實際 handoff decision 使用 2026-09-08 台北自然日當下 clock，沒有回填 2026-09-07。
- 因本次 archive 的 universe basis 是 source union 且未提供外部 denominator，projection 的 `lineage=[]`，並保留 `pit_formal_independent_expected_universe_missing`、`pit_formal_archive_universe_binding_failed:*`、`pit_formal_history_coverage_start_missing`；現行 license 仍是 `declared_official_open_api_identity`，因此另有正式用途／sidecar publication blockers。

隔離驗證 `tests/test_formal_pit_history_handoff.py` 為 `6 passed`，加上
`tests/test_scheduled_formal_input_producer.py` 為 `12 passed`；涵蓋實際 archive
custody、外部 denominator binding 與 archive 內複製檔拒絕、自然日 cutoff、create-only
retry／tamper，以及 public daily runner 的 handoff 接線。相關 4 個 source/CLI 檔案
以 `mypy --explicit-package-bases --follow-imports=skip` 通過，5 個 Python source／
test files py_compile 通過。這一片完成的是 PIT candidate→history handoff 的可驗證
入口；Rule history、causal non-cash ledger 與正式 PIT sidecar 仍須各自的真實來源、
自然時間與正式 consumer readback，沒有宣稱 Formal 3/3、OOS、promotion 或 broker
權限。

## PIT prospective denominator 與 formal sidecar handoff（2026-09-08 台北自然日）

本片新增 `data_module/pit_prospective_denominator.py` 與
`scripts/capture_pit_prospective_denominator.py`。denominator 由兩個獨立
data.gov.tw dataset resource 與其官方 OpenAPI response 綁定產生：TWSE dataset
18419（`t187ap03_L`）及 TPEx dataset 25036（`t187ap03_O`）。producer 同時保存
官方 JSON、data.gov CSV、dataset metadata、Swagger、HTTP requested/final URL、status、
response completion timestamp 與 file/content hash；symbols 與 sector mapping 必須
在 JSON／CSV 兩來源逐一相同，expected universe 不讀 `companies.csv`、不從 archive
反推，也不宣稱歷史回填。

data.gov metadata 的 `license=1`、resource URL、官方 Swagger path 與政府資料開放
授權條款第 1 版由固定政策封套重驗。授權頁的 Cloudflare `data-cfemail` 是每次回應
都會改寫的展示 token；封套保存實際 raw response hash，registered policy hash 只對
該單一展示欄位作窄化 canonicalization，其餘條款內容與 title 必須完全吻合。這不是
關鍵字推論，也沒有填入人工姓名或法律人工簽署；machine scope 只允許
`prospective_pit_sector_membership`／`formal_pit_sector_membership`，仍禁止 OOS、
promotion、production action。

本輪允許網路的真實產物：

- denominator：`output/formal_daily_publications/pit_denominator/2026-09-08-run9/denominator.json`；file SHA-256=`sha256:5efbb578ce34e2c4a9a5ec6913638ce4423e64f73d7bc6c87bc9f55aeac97916`，content hash=`sha256:3fbd81410b272e1a53f80eb37a4392e90c7152993c696455be65e776bc294033`，1984 symbols，symbols hash=`sha256:813318c0ae8323ef569f7d0caacf20e0b441075c37e983032ce61db8f5e90c89`。producer code SHA-256=`sha256:0031b2fdaf71b19b00c1835b212d6d15c79092e5e64ad2f706f648e6fe3d97f8`。
- coverage 起點明確為 `2026-09-08`，source capture date 也是 `2026-09-08`；TWSE JSON publication date=`2026-09-06`、CSV publication date=`2026-09-07`，TPEx 兩者均為 `2026-09-07`。TWSE 的日期差異是兩個官方來源的更新 cadence，因 symbol／sector mapping 完全相同而保留兩欄，不把它們誤寫成同一 publication。
- license raw document bytes=`484470`，raw response hash 在 denominator 的 `license_document.content_sha256` 保存；政策 scope 的 registered canonical hash=`sha256:0072cfbe821d7973236cec81a6551b508467c66da10d0eb3241232686e3cfa4e`。dataset metadata 的 notes 原文仍保存，並核對 `http://data.gov.tw/license`（data.gov 舊欄位拼法）與各自 exact Swagger URL；實際授權文件使用 HTTPS `https://data.gov.tw/license`。

`data_module/formal_pit_history_handoff.py` 現在把 denominator 的 verified state、file hash、
content hash、coverage start、source capture dates、producer code hash 與 machine license
scope 綁回 handoff；同時以當下 decision instant 驗證 denominator，避免把 decision 後
才完成的 source 當成 PIT evidence。空的 `required_trading_dates` 會明確產生
`pit_formal_required_trading_dates_empty`；若 decision 早於當日台北 08:30，當日不計入
covered dates，保留 `pit_formal_decision_before_current_day_cutoff:<date>` 與 missing
natural-day blocker。

實際 handoff readback：

- `output/formal_daily_publications/pit_history_candidate/2026-09-08/handoff-d20ec7335d0d9913.json`；file SHA-256=`sha256:6a35a99f9d9e7c7b0afb3a004f981b61c416017ab854e69afbcebd40adef1473`。其 independent denominator file hash/content hash 分別綁定上述 run9 的 `sha256:5efbb578...`／`sha256:3fbd8141...`，不是只記錄路徑。
- Official holidaySchedule 回報 `2026-09-08` 為 `twse_holiday_schedule_open`；decision 約 01:12 Taipei，required=`[2026-09-08]`、covered=`[]`、missing=`[2026-09-08]`。因此 handoff 雖已移除獨立 universe、source license 與 row binding 缺件，仍是 `candidate_only`，沒有歷史 credit。

本片新增 `data_module/formal_pit_sector_publisher.py`，只接受上述 handoff 的 objective
conditions，create-only 發布正式 PIT sector sidecar，然後呼叫既有
`portfolio_ml_dataset_assembler._load_sector_membership_sidecar`／
`_spool_sector_memberships` 做 in-memory consumer readback。receipt 綁定 sidecar file
hash、canonical hash、rows hash、handoff／denominator hash、publisher code hash、
consumer version、decision timestamp 與 assembler row count；sidecar、receipt 或 source
被竄改均拒絕。receipt 寫入中斷後，重試會重驗既有 sidecar 並補同一份 receipt，不覆寫
sidecar；blocked receipt 則把 decision、來源路徑與 publisher code 納入 immutable identity，
避免跨 clock／code retry 碰撞。

在上述自然日 cutoff 前的真實 publisher run 只產生：

- `output/formal_daily_publications/pit_sector_membership_formal/2026-09-08/blocked-receipt-8310871f4159e93f.json`；receipt file SHA-256=`sha256:dc00b6a52babc19def08a4733f39d9293e486fd1b7a140d909d2246ff278e045`，綁定上述 run9 denominator 與 d20 handoff。
- blockers=`pit_formal_decision_before_current_day_cutoff:2026-09-08`、
  `pit_formal_handoff_coverage_incomplete`、
  `pit_formal_history_missing_natural_days:2026-09-08`；`formal_ready=false`、
  `candidate_only=true`，沒有建立 `sidecar.json`，也沒有寫入 SQLite、D、broker 或 ML
  output。這是自然時間尚未成立的 fail-closed 結果，不能以測試 clock 或等待時間替代。

隔離回歸：

- `tests/test_pit_prospective_denominator.py`、`tests/test_formal_pit_denominator_handoff.py`、
  `tests/test_formal_pit_history_handoff.py`、`tests/test_formal_pit_sector_publisher.py`：
  合計 23 passed（7+5+6+5）；涵蓋 official JSON／CSV cadence、data.gov resource/license/Swagger
  mapping、child/raw hash tamper、coverage start 及 Taipei cutoff、空 trading dates、
  durable archive 移除 TEMP 後發布、assembler 真 consumer readback、sidecar tamper、
  receipt 中斷恢復、同一 clock retry、prospective 起點前舊 archive 不 credit，以及
  public `scripts/publish_formal_pit_sector_sidecar.py` 只用當下 clock 的 blocked 行為。
- `tests/test_formal_pit_sector_publisher_cli.py` 另有 2 passed；因此上述 handoff／
  sidecar 五檔合計為 25 passed（核心四檔 23 + CLI 2），不是核心四檔 25。
- `mypy --explicit-package-bases` 對 denominator、handoff、publisher 三個 data module
  通過；相關 Python 檔案 `py_compile` 通過。

這片完成的是 PIT denominator → handoff → formal sidecar publisher／assembler consumer
的可驗證接線。它只會在 prospective coverage、official calendar、source custody、
license scope 與 08:30 cutoff 都成立後發布 PIT input；Rule history 與 causal ledger
仍需各自的真實 source／自然時間／consumer receipt，整體 `formal_ready_input_count`
仍不是 3/3，沒有把 PIT input 單獨投影成整體 Formal ready。

## PIT 盤前 capture → 盤後 archive readback 排程（2026-09-08 台北自然日）

本片把 PIT 的日常流程拆成兩個受自然時鐘約束的入口。盤前入口
`data_module.formal_daily_input_producer.capture_pit_candidate_before_cutoff` 只允許
在台北 08:30 前開始，且兩個官方 HTTP response 的 completion timestamp、archive
timestamp 都必須嚴格早於 cutoff；盤後入口
`scripts/scheduled/run_formal_pit_sidecar_postcutoff.py` 只讀這份 archive，未到
08:30 回傳 `waiting_for_taipei_cutoff`，不以新的同日 HTTP response 取代盤前證據。
`scripts/scheduled/run_formal_input_producer_daily.cmd` 透過
`FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT` 使用相同 archive-only 模式。

在台北 08:30 前以新公開 producer 入口完成一輪真實官方抓取：

- archive manifest：
  `output/formal_daily_publications/pit_candidate_archive/2026-09-08/14f45ce6c086b5ce-10254c8e32c177fe/archive_manifest.json`；
- manifest file SHA-256：
  `sha256:6b940cd7ae4aa4bf268030b315126f195eb549f32ac6c7c99f2a3af3f2db7503`；
- `captured_at=2026-09-08T01:29:49.566013+08:00`、`archived_at=2026-09-07T17:29:49.874294+00:00`、
  `row_count=1984`；
- `publication_content_hash=sha256:14f45ce6c086b5ce955fe71bbfeb602dde2265d8a067d5dc97afa596609969d0`，
  producer code hash=`sha256:6f8c33ddcb816e19348b4cb5180c46f7e4a6f0a93350b83064cb010841d03a93`；
- source IDs 為 `official:twse:t187ap03_L` 與 `official:tpex:t187ap03_O`，archive
  readback、官方 raw custody 與 machine consumer readback 均為 true。這仍是
  `candidate_only=true`、`formal_consumer_compatible=false` 的 current observation，
  沒有轉成歷史 PIT credit。

本機此自然日的驗證過程已保存三個不同 capture content；最新 handoff
`output/formal_daily_publications/pit_history_candidate/2026-09-08/handoff-b3c5cb3732a42989.json`
的 file SHA-256 為
`sha256:b99962536cc0d0cd89ea30c5cca7c6b8f35d3635f74183fa3da071685a6cf682`，
`valid_archive_count=3`。它以獨立 denominator 與官方日曆重新檢查 coverage，並保留
`pit_formal_multiple_distinct_captures_for_natural_day:2026-09-08`、
`pit_formal_decision_before_current_day_cutoff:2026-09-08`、
`pit_formal_history_missing_natural_days:2026-09-08` 與
`pit_formal_sidecar_publication_required`；因此多重 capture 仍 fail closed，沒有
假定其中一份是唯一正式來源，也沒有為了求通過刪除既有 archive。

在目前真實 clock（約台北 01:32）執行盤後公開入口，產物為
`output/formal_daily_publications/scheduler/pit_sidecar/latest_status.json`，
`status=waiting_for_taipei_cutoff`、`same_day_post_cutoff_http_refetch=false`，
且 `formal_ready=false`。這是自然時窗尚未到達的可觀測等待狀態；不能以測試 clock、
等待文字或本次 preopen candidate 先行發布 sidecar。下一個合法動作是台北 08:30
後由 publisher 讀取已保存 archive；若 coverage、唯一 source、license scope 或
consumer readback 任一不成立，仍只寫具體 blocked receipt。

兩個 dedicated task 的註冊 dryrun 與實際 register 都已通過，未建立或改動其他
task：
`baldr-pit-sector-membership-preopen-capture-daily` 在 Pacific 16:00（PDT 台北
07:00／PST 台北 08:00）執行，`baldr-formal-pit-sidecar-postcutoff-daily` 在
Pacific 18:00（PDT 台北 09:00／PST 台北 10:00）執行。既有
`baldr-formal-input-producer-daily` 仍在 Pacific 21:25（PDT 台北 12:25／PST 台北
13:25）進行 Rule／Paper formal handoff；Rule 合法窗口仍是台北 09:00–13:30。
三個入口均不接受 `--now` 或日期覆寫，並將 candidate／blocked 以非零狀態保存到
durable `latest_status.json`。註冊命令為
`scripts\scheduled\register_pit_sector_handoff_tasks.cmd dryrun`，要實際建立 task
才使用同一命令的 `register` 模式。

本機 Query 已確認兩項 task 均為 `Ready`／`Enabled`，Task To Run 分別指向上述兩個
CMD wrapper，`MultipleInstances=IgnoreNew`、最長執行時間 1 小時；排程帳戶目前是
`Interactive only`，電池模式會停止／不啟動。register 後尚未到下一次實際 task run，
因此 `Last Run Time` 仍是初始值、`Last Result=267011`；這只表示尚未由 Task Scheduler
執行，不能當成 source capture 成功。可審查的真實 source evidence 來自本片 01:29:49
的公開 producer run，task 首次執行後仍須以其 `scheduler/pit_preopen_capture/latest_status.json`
與 sidecar status／receipt 讀回結果判定。

新增 `tests/test_pit_preopen_schedule.py` 為 9 passed；涵蓋 cutoff 前拒絕、盤前
archive 在盤後 readback 且不 refetch、晚於 cutoff archive 拒絕、formal daily runner
archive mode、archive 持久化晚於 cutoff 拒絕、scheduled status、盤後等待與
Pacific/Taipei 排程映射。加上本節前述 handoff／sidecar 25 passed，這次 focused 驗證共
34 passed；`mypy --explicit-package-bases`
與 `py_compile` 亦通過。Rule 的 09:00–13:30 及 Paper causal ledger 仍只在真實
合法時窗與實際 Paper append source 成立後累積，沒有在本次 01:32 等待狀態偽造
Formal 3/3、歷史 PIT、交易或 D 寫入。

## PySide6 UI 縮放／鍵盤／長表格驗證（2026-09-07）

本片先用現有 PySide6 `MainWindow` 做 full offscreen smoke，再以新 runner
`scripts/qa_validate_ui_scaling_keyboard.py` 在隔離 `DATA_ROOT`／`OUTPUT_ROOT`
建立真實主視窗、左側工作區導覽、Runtime 狀態，以及推薦分析與持倉管理實際頁面。
runner 將隔離測試 DataFrame 透過替換的 `PandasTableModel` 接到兩頁的
`results_table`／`positions_table`，以固定 1366×768 logical viewport 執行；另保留一個
獨立 table host 作為基準。runner 用 `QTest` 以 `Space` 啟動「市場探索」及「Runtime」
並確認焦點保留；以 `PageDown` 推進頁面內長表格、`Ctrl+Home` 返回頂端，另保存主視窗、
實際頁面與基準表格 PNG。這些操作只在隔離輸出進行，不寫正式資料、SQLite、D、broker 或 ML。

可重跑命令：

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_ui_scaling_keyboard.py `
  --output-dir "$env:TEMP\baldr_ui_scaling_keyboard" `
  --scale 1.5 `
  --scale 2.0
```

本輪實際產物為
`C:\Users\archi\AppData\Local\Temp\baldr_ui_keyboard_scaling_20260907\summary.json`：

- `evidence_kind=offscreen_qtest`；1.5 與 2.0 的 requested／observed scale factor
  均一致。
- 兩個 scale 均通過工作區 Space 導覽，Runtime workspace／狀態文字可見；基準表格與
  實際推薦／持倉頁面各有 600 列，viewport 均可見，`PageDown` 推進後由
  `Ctrl+Home` 回到 `0`。summary 同時保存 logical viewport 尺寸與 DPR。
- 每個 scale 都保存 `mainwindow_scale_*.png`、`long_table_scale_*.png` 與
  `recommendation_page_scale_*.png`／`portfolio_page_scale_*.png`；可用 `view_image`
  或一般圖片檢視器做 offscreen 外觀檢查。
- `screenreader=not_tested`。CUA trusted RPC 在本機未配置（`cua.getState()` 的
  native apps 為空），因此沒有 Windows 前景鍵盤、實體顯示器 150%／200% 或
  screenreader 證據，不能把本片結果宣稱為真人互動驗證。

既有 full MainWindow offscreen smoke 亦在隔離輸出
`C:\Users\archi\AppData\Local\Temp\baldr_ui_offscreen_full_20260907\20260907_104637\`
通過：8 個工作區切換、1500×900 與 390×844 resize 均 matched，UpdateView
取消探針未呼叫 destructive action；同樣只屬 offscreen。既有強制 UI test
`tests/test_ui_qt_update_view_workbench.py` 為 81 passed，`scripts/qa_validate_update_tab.py`
為 25 passed、0 failed、4 skipped。新回歸 `tests/test_ui_qt_scaling_keyboard.py`
為 1 passed；本片另修正 Profile 建議的 application policy，沒有調整工作區資料或
互動資料語意。原生 Windows 前景與 screenreader 仍未測試。

## Profile 風險建議政策與實際頁面長表格回歸（2026-09-07）

本片修正 `ui_qt/views/recommendation_view.py` 原先以
`confidence >= 0.7` 優先 high-risk Profile 的 UI 決策。風險選擇現在由
`app_module/recommendation_profile_service.py` 的
`suggest_profile_for_regime` 負責：已選的 user Profile 保留；沒有 risk budget
時，只從 Regime 相容且具明確 risk level 的 Profile 選最低風險研究建議；缺
risk policy、未知 Regime 或預算不相容時回報具體 blocked／unavailable。方法不接收
Regime confidence，UI 只顯示「Regime 判讀信心」，並明示這不代表獲利機率、風險
預算或個人適配。這保留現有 Profile-Regime 相容性與明確 risk policy，沒有把
任何 confidence、獲利結果或未來資料帶入決策。

新增 application policy regression：
`tests/test_recommendation_profile_policy.py` 9 passed；既有加強的
`tests/test_ui_qt_recommendation_profiles.py` 7 passed；涵蓋 Trend 高信心仍選
medium `long_term`、明確 user Profile 保留、selected 與 low／invalid budget
衝突、selected 缺 risk metadata、selected Regime mismatch、缺 risk metadata 拒絕、
自訂預算不相容與未知 Regime。這 16 項測試不涉及正式資料或交易。

同一個 `scripts/qa_validate_ui_scaling_keyboard.py` 現在會把 runner 建立的隔離測試
DataFrame 接到真實 MainWindow 內嵌的 `recommendation.results_table` 與
`portfolio.positions_table`；實際上這些是 600-row 測試資料與替換的 `PandasTableModel`，不是 production
DTO hydration，也不代表真實持倉 summary 與欄位資料已接通。測試以固定 1366×768
logical viewport、1.5／2.0 的模擬 DPR 執行焦點、`PageDown` 與 `Ctrl+Home`，並保存兩頁
screenshot；這些 logical 尺寸與 DPR 不等於實體 1366×768 螢幕的 150%／200% Windows
顯示設定。
實際產物：
`C:\Users\archi\AppData\Local\Temp\baldr_ui_keyboard_scaling_pages_fixed_20260907\summary.json`。
兩個 scale 都回報頁面可見、viewport 有效、測試 model 的 600 rows、scroll 前進後回頂端，且
`device_pixel_ratio` 與 requested scale 相符；這補足實際頁面 widget 的鍵盤／viewport
路由範圍，但不補 production presenter、DTO、summary 或真實持倉資料接線。
該產物仍是 `evidence_kind=offscreen_qtest`，沒有 Windows 前景互動或 screenreader
證據。新增的 `tests/test_ui_qt_scaling_keyboard.py` 以同一 summary 驗證實際頁面
欄位與固定尺寸，為 1 passed。Profile policy、UI profile、實際頁面 runner 合計
17 passed；pytest cache permission warning 不影響結果。

## Formal 日常排程與自然時鐘機器盤點（初始盤點，2026-09-08）

本節的 scheduler query 是 Paper task 專用註冊前的基線；後續「缺接線修正」節
記錄實際註冊後的 query 與 runner 結果。初始 query 的 16/17 與 Paper 缺失不應
被解讀為修正後的目前狀態。

本片新增唯讀 auditor：
`data_module/formal_operational_readiness.py`，公開入口為
`scripts/inspect_formal_operational_readiness.py`。入口只取主機實際
`datetime.now(timezone.utc)`，再轉 `Asia/Taipei` 判定自然日與窗口；公開 CLI
沒有 `--now`，測試才可注入 clock。它重算 PIT archive 內每個列出的檔案 hash、
readiness report hash、scheduler query report hash，並將 PIT／Rule／Paper 分 lane
保存。每個 lane 的 `formal_credit` 固定為 false，缺件、未來 timestamp、不同自然日、
排程漏跑、登入／電池限制與 EOD 尚未可得均輸出具體 blocker。

2026-09-07T18:30:32.790126Z（台北 2026-09-08 02:30:32.790126+08:00）實際
盤點產物為
`output/qa/formal_operational_readiness_20260908_final.json`，
`content_sha256=sha256:cca8e337bf20ba9d9b20beb5164b499dbd4f8de74d1f33bc18e33191b99c33a4`，
狀態為 `blocked_no_formal_credit`、`decision=no_credit`。當時 phase 是
`before_pit_cutoff`；PIT 08:30、Rule 09:00–13:30、Paper 延遲 EOD 15:00
都尚未到達，因此沒有把等待時間或候選輸入升格為 Formal。

PIT 當日 archive 可由 auditor 重新驗證：
`output/formal_daily_publications/pit_candidate_archive/2026-09-08/14f45ce6c086b5ce-10254c8e32c177fe/`，
1984 rows、TWSE／TPEx 官方 source IDs、`consumer_verified_at_capture=true`，
manifest file hash=`sha256:6b940cd7ae4aa4bf268030b315126f195eb549f32ac6c7c99f2a3af3f2db7503`；
它仍是 `candidate_only=true`、`formal_consumer_compatible=false`。持久
`scheduler/pit_sidecar/latest_status.json` 只回報同日
`waiting_for_taipei_cutoff`，盤前 status 檔尚不存在；Rule status 是前一自然日
的 `candidate_only`，Ledger／Rule 的正式來源路徑仍缺件。readiness report
`output/qa/formal_input_readiness_machine_current_20260908_final.json` 的
hash=`sha256:c6eec4c9b63063f34f3da81b35e594aa80a15287851a823c26e748d231bfa4cd`，
只證明 1/3 `machine_verified`、0/3 ready、0/3 formal consumer compatible。

以升權 Windows `schtasks /Query /V /FO LIST` 的 query-only 產物
`output/qa/scheduled_task_registration_formal_20260908.json`（
`captured_at=2026-09-07T18:29:10Z`、file hash=`sha256:b66f71eec9a3ef1df053257d438e1f51bc132376858f5c594ba287c0e2266036`）
核對四項正式 handoff：16/17 預期 task 可查、wrapper 全部存在且可見 action 相符；
PIT preopen 與 postcutoff task 均 `Ready`／`Enabled`，但 `Last Result=267011`、
`Last Run Time=1999/11/30`，代表尚無成功執行觀測；formal producer
`Last Result=2`。四項已保存的條件顯示 `Logon Mode=Interactive only` 及
`Power Management=Stop On Battery Mode, No Start On Batteries`，auditor 因此明示
`scheduler_task_requires_interactive_login:*` 與
`scheduler_task_battery_power_restricted:*`，不宣稱未登入或電池狀態下可無人執行。
Paper EOD task 查詢不到，輸出 `scheduler_task_unavailable:baldr-paper-execution-eod-replay-daily`；
因此漏跑／未註冊和來源 receipt 缺失均維持 no-credit。

可重跑命令（只寫指定 QA output）：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_formal_operational_readiness.py `
  --publication-root output\formal_daily_publications `
  --readiness-path output\qa\formal_input_readiness_machine_current_20260908_final.json `
  --scheduler-registration output\qa\scheduled_task_registration_formal_20260908.json `
  --paper-receipt-root D:\Min\Python\Project\FA_Data\output\scheduled\paper_execution_eod_replay\receipts `
  --output output\qa\formal_operational_readiness_20260908_final.json
```

本片 auditor／registration probe 回歸為 16 passed（pytest cache 權限 warning 不影響
結果），`mypy --explicit-package-bases` 3 個相關 Python 檔與 `py_compile` 通過。
所有本片檢查仍 `read_only=true`、未發 HTTP、未寫來源 SQLite／D／Formal controlled
input、未啟動 broker 或訓練；實際註冊 task 的登入／電池設定與 Last Result 是
可觀測環境限制，不能被測試 fixture 折抵。
並由機器將 PIT task 的初始 `Last Run Time=1999/11/30` 投影為
`scheduler_task_never_successfully_run:*`；Paper task 也維持未註冊／未觀測。

## Formal／Paper 排程缺接線修正與實際執行證據（2026-09-07）

本片針對上一節查出的兩個可修復問題做有界修正：Paper EOD task 缺失已由
`scripts/scheduled/register_paper_execution_task.cmd` 提供單項 dryrun／register
入口；Formal producer 則保留 blocked 的非零 exit policy，新增可重驗的 invocation
與 append-only attempt log，讓 `LastResult=2` 能對應到實際命令、工作目錄、參數及
來源 blocker，而不是把排程失敗改寫成成功。兩個入口都不接受日期或測試 clock
覆寫，沒有變更其他 task，也沒有增加 broker、D 原始資料或 Formal controlled DB
寫入權限。

Paper task 的 register 已在 Windows `Pacific Standard Time` 主機實際執行；只呼叫
`baldr-paper-execution-eod-replay-daily` 的 `/Create`、設定一小時上限／
`MultipleInstances=IgnoreNew`，並立即 query。可重驗的 query 產物是
`output/qa/scheduled_task_registration_formal_20260908_paper_registered.json`：
`task_count=17`、`available_count=17`、`configuration_ready=true`、
`all_actions_observed=true`、`all_actions_match=true`；該檔案 SHA-256 為
`sha256:008e2193845a7c30a2bba3319bc8bd09948ac42ef1fad260ba7999a1a23cd6bc`。
Paper action 為
`cmd.exe /c "<repo>\scripts\scheduled\run_paper_execution_daily.cmd"`，wrapper
存在且 hash 已保存；Formal action 同樣與
`run_formal_input_producer_daily.cmd` 相符。Paper task 的首次 query 仍是
`Status=Ready`、`Enabled`、`Last Run Time=1999/11/30`、`Last Result=267011`，
下一次為 Pacific 00:05；這代表 task 尚未成功執行，不代表 Paper fill 已完成。
它仍是 `Interactive only`，且 `Stop On Battery Mode, No Start On Batteries`，
所以未登入／電池狀態不能被宣稱為無人值守成功。Pacific 00:05 在 PDT／PST 分別
對應台北 15:05／16:05，均在延遲 EOD source gate 之後。

Formal task 的同一份 query 顯示 action／wrapper 正確，但 `LastResult=2`。
這個值與 runner 的明確政策一致：只有 `formal_inputs_machine_verified` 才回傳
0，`candidate_only` 或 `blocked` 回傳 2；因此保留非零訊號，不以 scheduler
query 的可用性冒充 producer 成功。最近一次實際 runner 的 durable status 是
`output/formal_daily_publications/scheduler/latest_status.json`，其中：

- `status=blocked`、`exit_code=2`、`formal_ready_input_count=0`、
  `machine_candidate_input_count=0`；
- `observed_at=2026-09-07T18:41:33.367648+00:00`，工作目錄為 repo root；
- `command` 是
  `C:\Projects\PythonProjects\technical_analysis\.venv\Scripts\python.exe`
  加上 `scripts\scheduled\run_formal_input_producer_daily.py`，沒有額外參數；
- `attempt_log_path` 指向
  `output/formal_daily_publications/scheduler/attempts.jsonl`。該 JSONL 保存
  `schema_version=formal-input-scheduled-attempt.v1`、entrypoint、Python executable、
  cwd、arguments、wrapper command、exit code、status 與 blocker；不保存完整環境或
  secret。當時 status 檔案 SHA-256 為
  `sha256:09044f8578df77ebfee6c0d07db7e179d7de7cb55972eba784d7c14db67edb93`，
  attempt log SHA-256 為
  `sha256:fec6ce5e6ae9ba50d885b56a30266f4fac8878a4c6f6b965bb7787ddaca92c10`。

這次真實 attempt 的 blockers 逐項為：
`formal_ledger_source_file_missing`、`formal_rule_history_source_file_missing`、
`formal_sector_source_file_missing`、
`pit_source_production_failed:preopen PIT archive consumer cannot run before Taipei 08:30 cutoff`、
`rule_capture_outside_taiwan_regular_session`、`rule_clock_source_missing`、
`rule_clock_source_missing_or_invalid`、`rule_owner_acceptance_source_missing`、
`rule_universe_source_missing`。因此 Formal LastResult=2 是有內容的 fail-closed
結果；不是把 shell／cwd／參數錯誤藏起來，也不是人工姓名缺失。`human_review_required`
與 `owner_reviewer_required` 均為 false，缺 source 仍以具體來源缺件與自然時窗
blocker 表示。

為確認 Paper runner 的缺接線修正可讀回，另以實際 recommendation queue、實際
官方 calendar probe、實際 market／paper snapshot 只讀來源，並設定
`PAPER_EXECUTION_APPEND=0` 做隔離執行。一般 sandbox 的官方 calendar request
因 `WinError 10013` 受網路環境阻擋而產生一份 `blocked` receipt；在允許網路的
執行環境以相同 source、相同 runner 重試後，產生：
`output/qa/paper_execution_eod_scheduler_probe_receipts/paper_execution_2026-09-08_9330c91d89344056_20260907T184023988760Z.json`。
該 receipt 的 source recommendation hash 為
`sha256:9330c91d8934405629d9f4f48d2c1a239741f1d886a71bfc75d4086fa33df165`，
receipt content hash 為
`sha256:82550c0723cd52e8cfbec4a11beb0a37c568f258aba7282f4d713691473d27f9`，
結果是 `status=waiting_for_execution_session`、execution date
`2026-09-08`，blocker 為台北 09:00 下一 official session 尚未開始。這證明
持久 queue resolver、自然 T+1 clock 與 receipt 路徑可運作；append 被明確關閉，
沒有建立 Paper ledger fill，也沒有寫 D 或 broker。Task Scheduler 的第一次真正
執行仍須等下一個排程時間，不能以這份隔離 probe 冒充 task 已成功。

以新 query 及上述 receipt 重跑唯讀 auditor，產物為
`output/qa/formal_operational_readiness_20260908_paper_registered.json`，
`content_sha256=sha256:817805e39c2cc5f6ec1686c242ee9adc8b2309aec013305d9f1818a4211997d5`。
報告確認 Paper task 已可查但仍有初始 LastResult／登入／電池 blockers，Formal
status 為 exit 2 且三項 source 缺件，PIT 仍在台北 08:30 前等待；
`machine_verified_input_count=1`、`formal_ready_input_count=0`、
`formal_consumer_compatible_count=0`，所以沒有給予 Formal 3/3、OOS、promotion、
交易或歷史 PIT credit。

本片 focused 回歸為：
`tests/test_formal_operational_readiness.py tests/test_scheduled_formal_input_producer.py tests/test_paper_execution_registration_plan.py tests/test_scheduled_paper_execution_wrapper.py`
共 `20 passed`；相關 source 的 `mypy --explicit-package-bases` 與
`py_compile` 通過。上述測試只驗證 invocation／status／registration contract，
不能取代下一個自然 PIT／Rule／Paper 時窗的實際 source receipt；未登入、電池、
官方來源不可得及三項正式 consumer 缺件仍由機器保持 no-credit。

## Paper 排程 scope 修正與受控 probe（2026-09-07）

上一節的 Paper query 是修正前基線：它的 action 仍指向通用
`run_paper_execution_daily.cmd`，而該 wrapper 可從環境變數取得 D 的 output／ledger
路徑。先前 `PAPER_EXECUTION_APPEND=0` probe 只證明該次 probe 的環境，不能證明
Task Scheduler action 的 scope。因此先以 elevated `schtasks /Change ... /DISABLE`
停用唯一 `baldr-paper-execution-eod-replay-daily`；沒有修改其他 task。完成 scope
修正後，`scripts/scheduled/register_paper_execution_task.cmd register` 才重新建立並
啟用同一 task，action 改為
`cmd.exe /c "<repo>\scripts\scheduled\run_paper_execution_daily_isolated.cmd"`。

專用 adapter `scripts/scheduled/run_paper_execution_daily_isolated.py` 不接受
`DATA_ROOT`、`OUTPUT_ROOT` 或 `PAPER_EXECUTION_*` 的路徑覆寫。既有 D
`output\paper_portfolio\paper_portfolio.sqlite`、`sqlite\twstock.db` 及
`output\recommendation\runs` 僅以 SQLite `mode=ro/query_only`／唯讀 queue scan
讀取；candidate、receipt 與研究用 append-only ledger 固定位於
`<repo>\output\paper_execution_eod_replay`。`scope_manifest.json` 會在任何 output
建立前解析並驗證 operation root、candidate、receipt、ledger 與 manifest 都仍在
repository `output` 子樹，且均不落入解析後的 D `DATA_ROOT`；operation root 為
reparse point 指向 repository 外部時直接拒絕。來源檔只宣稱讀取前後 metadata
signature 不變，沒有把 size／mtime 當作內容 hash。

受控 real-source probe 由修正版 `.cmd` 直接執行，沒有設定 append opt-out。它在
`2026-09-07T19:08:38.882827Z` 讀取上述 D source，因官方 holiday calendar
request 受到 `WinError 10013` 阻擋而保存具體
`official_calendar_not_proven:twse_holiday_schedule_unavailable`；結果是
`status=blocked`、`queue_state=failed`、`candidate_only=true`、`formal_credit=false`。
這輪沒有建立 D ledger（`D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_trade_ledger.sqlite`
仍不存在），也沒有 broker／Formal write。可讀回的產物如下：

- scope manifest：`output/paper_execution_eod_replay/scope_manifest.json`，SHA-256
  `f6841a77b6b74053655c755868eb6f5aa13113593657dfea634c03774d666262`。
- candidate：`output/paper_execution_eod_replay/candidates/run_97c528429b9d4eadaecd2e4327a842f1/paper_execution_candidate.json`，檔案 SHA-256
  `210c8dca67d156c27be7f60f6bcb442cf960fe5f520c8206d3b6998bb8072f22`。
- operational receipt：`output/paper_execution_eod_replay/receipts/paper_execution_2026-09-07_9330c91d89344056_20260907T190838882827Z.json`，檔案 SHA-256
  `48acecf1d4c16be3508e78396b00dbd835fe2b920e11d592525b77e216426014`。
- probe 摘要：`output/qa/paper_execution_isolated_scope_probe_20260908.json`，保存
  source path／`ro/query_only`、repo writer target、candidate／receipt hash、D ledger
  存在性、scope manifest 與 scheduler query/XML 參照，檔案 SHA-256
  `618e707ae42054ca7b5f990932e48b9bb27b2cb88842ce49c6c368b9ff5ac2f9`。

重新註冊後的 elevated query-only 產物為
`output/qa/scheduled_task_registration_formal_20260908_paper_isolated.json`，檔案
SHA-256 `1b293cb5cf0212d0eaa9287f99f46ac0ad514815d878fa25d6677484764854be`；
`task_count=17`、`available_count=17`、`configuration_ready=true`、
`all_actions_observed=true`、`all_actions_match=true`。Paper task 的 wrapper path
是 isolated `.cmd`，狀態為 `Ready`／`Enabled`，`Last Result=267011`、首次成功執行
尚未觀測；它仍是 `Interactive only`，且電池模式停止／不啟動。Formal task 的
`Last Result=2` 維持原本 blocked／candidate-only 語意。原始 Task Scheduler XML
另保存於 `output/qa/scheduled_task_paper_execution_20260908_isolated.xml`，可解析且
SHA-256 為 `7bbd4b13a98bec843ebb3fcfcc5825046337427c77dbff114401305f5d91a081`；其中
`Command=cmd.exe`、`Arguments` 指向 isolated wrapper、`ExecutionTimeLimit=PT1H`、
`MultipleInstancesPolicy=IgnoreNew`。

以這份 query 與 isolated receipt 重跑唯讀 readiness auditor 的產物為
`output/qa/formal_operational_readiness_20260908_paper_isolated.json`，檔案 SHA-256
`f53ac0e1ec834c0041a3f5bec6acf05c1950415dda532b9dfc939d26a633ee7c`。報告的實際
clock phase 是 `before_pit_cutoff`；Paper lane 為 `waiting_for_eod_window`，保留
`paper_eod_source_window_not_reached`，Rule／PIT 及 scheduler 的登入／電源／LastResult
blocker 也都保留。它因此不給 Paper fill、Formal 3/3 或任何 promotion credit。

本片 focused 回歸為 `68 passed`，涵蓋 Paper producer／通用 wrapper 回歸、isolated
adapter、registration／inspector／formal schedule contract 與 reparse-point 負例；
`mypy --explicit-package-bases`（producer、isolated adapter、readiness）及
`py_compile` 通過。UI QA 文字同步修正為：長表格資料是 runner 建立的隔離測試
DataFrame 與替換 `PandasTableModel`，不是 production DTO hydration；1366×768 是
logical QTest viewport，1.5／2.0 是模擬 DPR，不等於實體螢幕的 Windows 150%／200%。
原生前景互動、真實 production presenter／summary 一致性與 screenreader 仍未取得
證據。Task 的第一次自然執行、官方 calendar 可用性與實際 Paper append 仍待後續
自然窗口；本片不把 probe 或註冊成功報為 Paper fill、Formal 3/3 或 source success。

## TWSE annual calendar cache 接線與真 consumer probe（2026-09-07）

為解除官方 holidaySchedule 網路短暫不可得造成的 calendar blocker，新增
`data_module/official_trading_calendar_cache.py` 與
`scripts/capture_official_trading_calendar_cache.py`。capture 必須明確帶
`--confirm-network`，對 TWSE annual endpoint 發出 bounded GET，將實際 response bytes
、HTTP status／headers、request URL、response SHA-256、requested／captured completion
時間與七日 freshness window 保存為 create-only
`official-trading-calendar-cache.v1`。validator 會重算外層 content hash、raw bytes hash、
payload、年份、完整 365 日 normalized projection 與 timestamp chain；缺 cache、過期、
竄改或錯年份均維持 unknown，不以 weekdays、行情列或空結果代替。

本次官方唯讀 capture 的來源與產物為：

- endpoint：`https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule?queryYear=115`，HTTP 200。
- response SHA-256：`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`。
- cache：`output/paper_execution_eod_replay/calendar_cache/twse_holiday_schedule_2026_20260907_capture1.json`。
- cache file SHA-256：`sha256:74790d36d0cd66398c37a729bfce243e1a03358f93afd256c523e2549c6d6c93`。
- captured completion：`2026-09-07T19:20:27.355937+00:00`；expires：`2026-09-14T19:20:27.355937+00:00`。
- coverage：2026-01-01..2026-12-31、365 日、`complete_year=true`。

`OfficialTradingCalendar(calendar_cache_path=...)` 已接入 isolated Paper queue resolver，
優先消費驗證通過的 cache；真實 D state／market SQLite 仍以
`mode=ro/query_only` 讀取。受控 wrapper probe 讀回 cache 的
`source_evidence.mode=hash_bound_official_calendar_cache`，目標 2026-09-08 判定為
`twse_holiday_schedule_cache_open`，不再產生
`official_calendar_not_proven:twse_holiday_schedule_unavailable`。實際 candidate／receipt
摘要保存於 `output/qa/paper_execution_calendar_cache_probe_20260908.json`，檔案
SHA-256 為 `sha256:1553a7d66521e856fac6a0418c36223ca6a03cb7985e35f7af2abcf43f9eb5df`。

該次真 consumer 結果為 `status=waiting_for_execution_session`，blocker 是實際
`paper_execution_waiting_for_next_session_open:2026-09-08T09:00:00+08:00`；這是自然時間
尚未到達的合法等待，不是 calendar blocker。candidate-only、Formal credit、broker execution
與 market DB write 仍是 `false`，D ledger 仍不存在。第一次 Scheduler 自然執行及 15:00
台北 EOD replay 仍待實際窗口，不能將本次 cache readback 報成 fill 或 Formal 3/3。

驗證新增 cache、resolver、Paper consumer 與隔離接線測試共 `41 passed`（pytest cache
權限 warning 不影響結果）；排程／readiness 合併 focused 回歸為 `83 passed`；原有
isolated scope focused suite 的 68 項回歸仍維持通過。

## TWSE annual cache operational refresh 與臨時休市界線（2026-09-07）

本片新增 `refresh_twse_calendar_cache()`，由 isolated Paper adapter 在 source／writer
scope 通過後呼叫。有效 cache 不發網路請求；過期、缺失、錯年份或竄改時，最多對同一
年度官方 `holidaySchedule` 發出兩次 bounded request，只有 response bytes、HTTP status、
final URL、完整年度、raw／outer hash 與 timestamp chain 全部驗證後才建立新的 create-only
檔案。舊 cache 不覆寫、不刪除；失敗會將每個舊檔的 hash／失敗原因及 retry 次數寫入
`receipts/calendar_refresh_*.json`，下輪仍可重試，避免一次網路故障變成永久人工卡點。

refresh root 固定在 `output/paper_execution_eod_replay/calendar_cache` 之下，且再次檢查
不得穿越 operation root 或 D source。2026-09-07 的現有 cache 仍可作離線 readback；新
refresh 檔案會額外保存 `source.response_url`，拒絕 redirect 或錯 endpoint 綁定。新增
refresh／保留舊檔／bounded failure／錯年份／Taipei 跨年選年與 wrapper receipt 測試，
並以同一套 resolver 驗證臨時事件 sidecar 的覆蓋與拒絕條件。

Annual `holidaySchedule` 的 `complete_year=true` 只證明該次官方年表的排定休市投影；
工作日缺列是 `planned_open`，不能當成 capture 後才公布的颱風或其他天然災害臨時休市
事件。TWSE 的天然災害處理規則頁
`https://www.twse.com.tw/zh/clearing/suspended.html` 已被保存為 policy-only source，
明示臨時事件需要另一份官方公告的日期與內容證據；本片沒有把規則頁或行情有無當作
休市事件，也沒有將 365 日 projection 宣稱為即時完整。尚未捕獲臨時事件時，annual
result 的 evidence 會保留 `temporary_closure_scope.event_evidence_required=true`，
不虛構事件或歷史時間；後續若遇公告，須以官方公告 response bytes／URL／capture time
建立獨立事件 evidence 後才可覆蓋指定日期。
refresh／保留舊檔／bounded failure／錯年份／Taipei 跨年選年與 wrapper receipt 測試，
本片 calendar／resolver／isolated focused 為 `25 passed`。

## TWSE 臨時休市公告自動發現 operational probe（2026-09-07）

手動 `capture_twse_temporary_closure_cache.py` 不再是日常流程的唯一入口。
isolated Paper adapter 每輪先讀取 TWSE 官方 newsList，再對清單中最多 8 筆標題明示
單日全面休市的公告讀取 newsDetail；每筆 sidecar 都保存公告清單 raw bytes、明細
raw bytes、final URL、HTTP status、公告 `zhId`、日期、發布時間及各自實際 response
completion time。年度假期公告、日期區間公告、policy page、weekday 或行情列都不會
被轉成臨時事件。清單／明細不可得或 schema、URL、hash、日期、時間鏈不符時，runner
保留 `temporary_closure_discovery_blocked` 或 `temporary_closure_events_partial`，
下一輪可 bounded 重試。

本次 elevated、唯讀官方來源 probe 實際完成如下：

- 清單 endpoint：
  `https://www.twse.com.tw/rwd/zh/news/newsList?tag=%E4%BC%91%E5%B8%82&response=json`，
  HTTP 200，raw response SHA-256
  `sha256:f481e1e33886777079bf735cb26e33898cef1582aaac149d926b3ed9f13a8880`。
- 明細 endpoint：
  `https://www.twse.com.tw/rwd/zh/news/newsDetail?id=8a8216d69ef76943019f46cb86bf0111`，
  HTTP 200，raw response SHA-256
  `sha256:af23f921a3376a5aaded78a31e239dd68f3261a741ce3387bb80814803ca06fb`。
- 公告事件：`2026-07-10` TWSE 全日休市，官方發布時間為
  `2026-07-09T20:11:00+08:00`；sidecar 實際 response completion／available time
  為 `2026-09-07T20:00:50.478433+00:00`。
- sidecar：
  `output/paper_execution_eod_replay/calendar_cache/twse_temporary_closure_20260710_af23f921a3376a5a.json`，
  content hash `sha256:f0ea950660a90459fdab2094e130ef7de94a056a93da8feb2e948e335bdf5edb`，
  file SHA-256
  `sha256:e547914241a29eb9e8b722b236159e583e95bceed14a0bb54b0c08c268681722`。
- combined calendar receipt：
  `output/paper_execution_eod_replay/receipts/calendar_refresh_20260907T200128224706Z.json`，
  file SHA-256
  `sha256:0170b834d1718ab42f84f2e1d5f2a5a589e66fa1b0aa6e0cfdf793b2e6b7fec0`；其中
  `news_list_requests=1`、`detail_requests=1`、`status=temporary_closure_events_updated`，
  事件為 `existing_verified`，表示本輪已由同一 loader 驗證 list/detail custody。
- 真實 consumer readback：
  `OfficialTradingCalendar.is_official_trading_day(2026-07-10)` 回傳
  `(False, "twse_temporary_closure_official")`，evidence mode 為
  `hash_bound_official_temporary_closure`。

同一 runner 的最新 Paper candidate 為
`output/paper_execution_eod_replay/candidates/run_24ceb19b24914c1ebb839bf29232201c/paper_execution_candidate.json`，
file SHA-256
`sha256:0ce4be5a7ed974291402c5684c59db56fab39b087a1d4988df1a80df845be5c5`，
但因自然 T+1 session 尚未到達而回報
`paper_execution_waiting_for_next_session_open:2026-09-08T09:00:00+08:00`；它仍
`candidate_only=true`、`formal_credit=false`、`broker_execution=false`，沒有 D 或正式
ledger write。這份公告事件是 operational 日曆來源證據，不是把 2026-07-10 回填成
目前的 Formal/Paper 信用，也不代表三項正式輸入已完成。

新增公告 parser／discovery／raw list tamper／錯誤 final URL／不可得與 isolated 接線
回歸後，calendar cache＋isolated focused suite 為 `21 passed`；兩個變更 source 的
`mypy` 與 `py_compile` 均通過。第一次 probe 曾因 run-start observation 與 response
completion 的自然時間差回傳 partial，但 create-only sidecar 未被刪除；下一次 runner
以當前 observation 重新驗證為 `existing_verified`。這保留了實際時間證據並使故障可
觀測，不把一次失敗當成成功。正式 Rule／PIT／causal ledger 與 Paper 自然 append
仍是後續未完成項；UI production DTO hydration 已在本片完成頁面接線，但不因此取得
Formal credit。

## PIT prospective denominator 與 Formal runner 自動 resolver（2026-09-07）

盤前 PIT task 新增當日 denominator resolver。它先在 publication root 的
`pit_denominator\<Taipei date>-run-*\denominator.json` 查找並以完整 child bytes
重驗既有封套；只有找不到當日可驗證封套時，才呼叫 bounded official producer 抓取
TWSE／TPEx OpenAPI、data.gov CSV／metadata、官方 Swagger 與固定版本授權文件。錯誤、
竄改、錯年或 coverage 起點不等於當日台北自然日都會留下具體 blocker，不使用舊日清冊
補當日，也不以任意非空 license 字串給予信用。正式日常 runner 同樣會自動讀取當日
denominator 與已由 assembler readback 的 formal PIT sidecar；明確環境路徑仍可覆寫，
但不再要求每日人工修改 path。preflight 驗證到的官方 calendar service 也會傳入 PIT
history handoff，避免同一輪已取得的日曆證據被丟失。

本機當下 UTC `2026-09-07T20:15:40.593666+00:00`（台北 `2026-09-08`）的唯讀 resolver
probe 保存於 `output/qa/v4_operational_pit_resolver_probe_20260908.json`。它重驗並重用
既有 denominator：

- 路徑：`output/formal_daily_publications/pit_denominator/2026-09-08-run9/denominator.json`。
- file SHA-256：`sha256:5efbb578ce34e2c4a9a5ec6913638ce4423e64f73d7bc6c87bc9f55aeac97916`。
- denominator content hash：`sha256:3fbd81410b272e1a53f80eb37a4392e90c7152993c696455be65e776bc294033`。
- scope：`verified_prospective_denominator`、`coverage_start=2026-09-08`、1984 symbols、
  data.gov license scope `machine_scope_verified`；本次 refresh `network_attempted=false`。

同一 probe 在目前台北 08:30 前只回報
`current_formal_pit_sidecar_or_receipt_missing`，沒有把尚未到達的盤後 publication
當成成功。自動 resolver routing 與 preflight→handoff calendar reuse 的回歸，加上既有
PIT／denominator／scheduled／history suite，共 `36 passed`（pytest cache permission warning
不影響結果）；三個變更 Python source 的 `mypy --explicit-package-bases` 與
`py_compile` 均通過。上一輪真實 Formal runner 仍為 `candidate_only`：官方 PIT capture
1984 rows／consumer readback 成功，但當下自然 cutoff 前、同日已有多個 immutable
capture，故保留 multiple-capture 與 sidecar blockers；Rule／causal ledger 缺來源也
仍明示，沒有 Formal 3/3、broker 或 D write。

## PIT 盤前 retry 的 archive reuse operational probe（2026-09-07）

盤前 task 若因喚醒、重試或重複排程再次啟動，會先讀取當日台北自然日的
`pit_candidate_archive`，以官方 raw／publication／receipt／operational bytes 完整
重驗 custody，並要求 source completion 與 archive persistence 都早於 08:30。只有
當日沒有任何 archive 時才進入一次 live capture；存在但竄改或不完整的 archive 會
fail closed，不以新的 capture 掩蓋既有證據。這避免同一自然日因不同 capture timestamp
產生多份互相衝突的 PIT history。

本機實際時間為 UTC `2026-09-07T20:27:05.855479+00:00`（台北
`2026-09-08T04:27:05.855479+08:00`）。執行公開盤前 wrapper：

```text
.\\.venv\\Scripts\\python.exe scripts\\scheduled\\run_pit_sector_membership_preopen_capture.py --publication-root output\\formal_daily_publications
```

實際 status 為 `machine_verified_candidate`、`capture_mode=reused_existing_verified_archive`，
沒有再次 HTTP 抓取；status path 是
`output/formal_daily_publications/scheduler/pit_preopen_capture/latest_status.json`，file
SHA-256 為 `sha256:b040bc56a58b9d2d719067e9d6e0ce49d694291a47c8b16b1e2f05da8f8d216e`。
它重讀 archive
`output/formal_daily_publications/pit_candidate_archive/2026-09-08/9a0ec7518fd56783-5ff5b605ac4334b1/archive_manifest.json`，
archive manifest file SHA-256 為
`sha256:40e957a5f7bd1774c537b45b0993c0cd7dd5472e639fc0ac0fb8ee79745f662d`，
publication content hash 為
`sha256:9a0ec7518fd5678300b49fd3d3dde3cb9d23b746256ee925dd0ead4a0cacf4c7`，
1984 rows，machine consumer readback `true`。同輪 denominator 也重用
`pit_denominator/2026-09-08-run9/denominator.json`（`network_attempted=false`）。

新增 archive reuse／有效來源不重抓與不完整 archive fail-closed 測試後，
`tests/test_pit_preopen_schedule.py` 為 `14 passed`。這仍是 PIT candidate-only
來源接線；自然盤後 sidecar、Rule history 與 causal Paper ledger 缺件仍不得計入
Formal 3/3 或 promotion。

同一時間點的唯讀 Formal operational readiness auditor 產物為
`output/qa/formal_operational_readiness_current_20260908.json`，file SHA-256 為
`sha256:95fa8a27be86fb6f382eb0fbd489f8865403f7761d41cb113258e765a1d3bc67`。
它明確記錄 `phase=before_pit_cutoff`、`status=blocked_no_formal_credit`、
`formal_ready_input_count=0` 與 `machine_verified_input_count=0`；Rule history、
causal ledger 與 formal sidecar 的來源缺件，以及自然時間尚未到達，仍由機器
逐項列出。這份報告是目前真實可執行來源的 readback，不把現有 PIT candidate
或舊日 research ledger 當作正式輸入。

## Operational calendar refresh 與 UI DTO 接線補充（2026-09-07）

isolated Paper runner 實際執行命令：

```text
.\\.venv\\Scripts\\python.exe scripts\\scheduled\\run_paper_execution_daily_isolated.py
```

本次 run 的 UTC observation 是 `2026-09-07T20:34:38.971836+00:00`，annual
`holidaySchedule` 由 repo cache 離線重驗，`status=cache_valid`、
`network_attempts=0`、cache file SHA-256 為
`sha256:74790d36d0cd66398c37a729bfce243e1a03358f93afd256c523e2549c6d6c93`，
expires 為 `2026-09-14T19:20:27.355937+00:00`。同輪自動公告查詢保留具體
`temporary_closure_discovery_blocked`（newsList 的網路請求受執行環境拒絕），
沒有將無法取得公告誤判為開市或休市；refresh receipt 是
`output/paper_execution_eod_replay/receipts/calendar_refresh_20260907T203438569398Z.json`，
file SHA-256 為
`sha256:c1430a37bf6d8e7360b3a2c20d0292d3dd60a9778e7c21e5f78b12831f96345c`。
Paper consumer 只回報等待下一官方 session 的 candidate，沒有 ledger、D 或
broker 寫入。

Form runner 最新 status path 是
`output/formal_daily_publications/scheduler/latest_status.json`，file SHA-256
為 `sha256:877bcd114d52c99127c32726a0436580fa4a970c35fa8f139bb9810a295483cb`；
它使用 `output/paper_execution_eod_replay/calendar_cache` 與隔離
`output/paper_execution_eod_replay/paper_trade_ledger.sqlite` 設定，但目前
status=`blocked`、`exit_code=2`、`formal_ready_input_count=0`。具體 blocker 仍是
Rule history、causal ledger、顯式 PIT source 缺件與自然時點尚早；不把 cache
驗證或 PIT candidate readback 當成 Formal 3/3。

UI production page 的 `PortfolioView.refresh_all()` 現在以一次取得的
`PortfolioDTO` 同時供摘要卡、持倉表、stress 與 monitoring projection，避免
`get_portfolio()`／`list_positions()` 跨版本讀取。`tests/test_ui_qt_portfolio_view.py`
新增 DTO-only service 回歸，`test_portfolio_page_hydrates_summary_and_table_from_one_portfolio_dto`
驗證同一 DTO 的持倉代號、active count 與投入金額在摘要／表格一致；該檔為
`22 passed`，連同 condition monitor 與既有 deepening focused suite 為 `29 passed`。
這是 page wiring／DTO fixture 證據，不代表 D 來源已具備 Formal credit。UI 強制
workbench test 為 `81 passed`，`scripts/qa_validate_update_tab.py` 為 25 passed、
0 failed、4 skipped；本片 targeted mypy 與 py_compile 均通過。隨後完整 repo mypy
為 `Success: no issues found in 559 source files`。

隨後在允許網路的受控環境再次執行同一 isolated Paper wrapper；本次只重用
已驗證的 annual cache 並成功完成 TWSE newsList→newsDetail custody，沒有建立
新的事件檔或寫入 D。refresh receipt 為
`output/paper_execution_eod_replay/receipts/calendar_refresh_20260907T203934399366Z.json`，
file SHA-256 為
`sha256:2cf6b9d6124147669a72e78d282f649834b7a047e5eeee857b6a454c186155b5`；
newsList HTTP 200、detail HTTP 200、`network_attempts=2`，事件
`2026-07-10` 為 `existing_verified`，仍由 source/detail raw hash 重驗。當輪
Paper candidate 是
`output/paper_execution_eod_replay/candidates/run_dab23b7251354b33b2355159d138d889/paper_execution_candidate.json`，
file SHA-256 為
`sha256:a7507556d2aa578d19bfcaaafeff5219a5b0b490ea0d4ade6f0e09bb2fb7e9d6`；
真實 consumer 回報 `waiting_for_execution_session`（下一官方 session
`2026-09-08T09:00:00+08:00`），沒有 fill、正式 credit、D 或 broker write。

## Paper isolated task elevated readonly 核對（2026-09-07）

為釐清先前狀態摘要的矛盾，重新以 elevated readonly 執行：

```text
schtasks /Query /TN baldr-paper-execution-eod-replay-daily /XML
schtasks /Query /TN baldr-paper-execution-eod-replay-daily /FO LIST /V
```

目前實際狀態為 `Ready`、`Enabled`，`Next Run Time=2026/9/8 00:05:00`，
`Last Run Time=1999/11/30 00:00:00`、`Last Result=267011`，表示尚無成功的
排程執行證據；本次未修改 task。XML action 綁定
`cmd.exe /c "C:\Projects\PythonProjects\technical_analysis\scripts\scheduled\run_paper_execution_daily_isolated.cmd"`，
工作為 `Interactive only`，電池模式禁止啟動且啟動後停止，`ExecutionTimeLimit=PT1H`，
`MultipleInstancesPolicy=IgnoreNew`。因此 isolated runner 的實際公告 refresh probe
不能被誤寫成排程已成功跑過；下一次自然 task 執行仍須以 Last Result、receipt 與
consumer readback 驗證。

同次 elevated readonly 核對 `baldr-formal-input-producer-daily` 為 `Ready`、
`Enabled`，Next Run=`2026/9/7 21:25:00`、Last Run=`2026/9/7 08:44:17`、
Last Result=`2`；action 綁定同一 repository 的
`scripts/scheduled/run_formal_input_producer_daily.cmd`。這個非零結果是目前
來源／自然時間尚未就緒的阻塞證據，不是 Formal 成功；下一次執行仍需讀取新的
status、各 input receipt 與 consumer readback。

本批收尾回歸為 `tests/test_formal_daily_input_producer.py`、
`tests/test_pit_preopen_schedule.py`、`tests/test_scheduled_formal_input_producer.py`
合計 `43 passed`；cache-aware calendar 會由 public runner 傳入 ledger producer，
不會在 Paper source ready 時退回未配置 cache 的第二個 calendar instance。

## Workbench／Scheduled Evidence 機器狀態與 stale 讀取（2026-09-07）

本片新增 `app_module/machine_status_classification.py`，由 read model 統一區分
`source_missing`、`waiting_for_time`、`invalid_evidence`、`human_review`、
`machine_candidate`、`machine_verified`、`stale` 與 `unknown`。只有明確的
`human_review` 證據會進人工覆盤排序；來源缺件、自然時間等待及無效證據仍保留
其真實 blocker，不會因舊的 `action_required` 或具名 owner 欄位而被誤標人工。
`passed` 搭配 `screening_matrix_missing` 的回歸也固定分類為 `source_missing`。

`ScheduledEvidenceStatusService` 現在以 `load_state`、`load_checked_at` 與
`last_good_loaded_at` 描述讀取本身：三份 status 初次缺失或部分缺失時保留
`unknown`/具體來源缺件，完整讀取才是 `current`；已讀取成功後若最新檔案損壞或
消失，保留 last-known-good 並標示 `stale`、原成功時間及 loader diagnostic，修復
後才恢復 `current`。`ScheduledEvidenceStatusView` 對每張狀態卡都顯示 stale，空白
例外訊息也會落到「未提供錯誤訊息」並將焦點移到 Retry。

Workbench 的 machine-only Action Items 不再顯示「今日所有風險已確認」；初次無
可信 DTO 顯示 `unknown`，來源錯誤保留完整 last-good DTO、stale banner、成功載入
時間與 Retry focus。`Workbench` 與 `Scheduled Evidence` 的 Retry 控制均有可及名稱
與說明。這是 read model/UI 的狀態語意修正，不授予 Formal credit、不寫 DB、不中介
broker，也不改動 D 原始資料。

本片驗證：

* `tests/test_machine_status_classification.py`、`tests/test_scheduled_evidence_status_service.py`、`tests/test_workbench_read_only_composer.py`、`tests/test_workbench_view_presenter.py`、`tests/test_ui_qt_evidence_review_dashboards.py`、`tests/test_ui_qt_workbench_view.py`：`67 passed`。
* UI 強制作業 `tests/test_ui_qt_update_view_workbench.py`：`81 passed`；
  `scripts/qa_validate_update_tab.py`：`25 passed`、`0 failed`、`4 skipped`。
* 本片變更檔 `py_compile` 與 targeted mypy（9 files）通過；隨後完整 repo mypy
  為 `Success: no issues found in 559 source files`。

## Portfolio 背景刷新與 generation custody（2026-09-07）

`ui_qt/main.py` 的 production `PortfolioView` 入口已使用 `async_refresh=True`。
`ui_qt/views/portfolio_view.py` 以既有 `TaskWorker` 在背景讀取單一 `PortfolioDTO`，
再由主執行緒把同一份 DTO 套用到摘要卡、持倉表、stress 與 monitoring projection；
worker 不直接碰 Qt model。同步相容模式仍保留給既有嵌入呼叫端，明確的背景入口才是
主視窗路徑。

每次 refresh 會增加 generation；新請求會合作式取消舊 worker 並排隊最新一輪，舊
generation 的完成／錯誤回呼不會覆蓋目前 DTO。`cancel_refresh()` 與 `closeEvent()`
只設取消旗標，不呼叫 `terminate()`；關閉時若 worker 尚在執行會先保留視窗，工作安全
結束後須再次關閉才能完成關閉。首次讀取失敗顯示 unknown，已有成功 DTO 時保留最近內容並顯示
失敗原因，避免錯誤回呼把畫面清成看似正常的空狀態。

本片驗證：

* `tests/test_ui_qt_portfolio_view.py`：`22 passed`，含真實 QThread worker 的舊
  generation 取消／新 generation 重跑、單一 DTO hydration、舊 generation callback
  不覆蓋新狀態，以及實際 QMainWindow 關閉協調器撤銷 Portfolio pending generation
  並等待原生 thread 結束。
* `tests/test_ui_qt_portfolio_condition_monitor.py`、`tests/test_portfolio_deepening.py`
  與上述測試合計 `29 passed`。
* `ui_qt/views/portfolio_view.py`、`ui_qt/main.py` targeted mypy 與 py_compile
  通過；同日完整 repo mypy 為 `Success: no issues found in 559 source files`。

這是 UI 讀取生命週期與一致性修補，不代表 Portfolio D 或 Formal 三項輸入已取得
正式信用；不啟用 broker、不寫 D 原始資料、不重訓 ML。

## Formal 日常來源解析與自然時窗狀態（2026-09-08）

本片在 `2026-09-07T21:48:23.300030+00:00`（台北
`2026-09-08T05:48:23.300030+08:00`）以唯讀方式核對排程來源。`scripts/scheduled/run_formal_input_producer_daily.cmd`
現在提供 `FORMAL_DAILY_RULE_SOURCE_ROOT`，預設指向 D 槽既有
`output/formal_prospective`；Python wrapper 會從該根目錄找完整的
`clock-*/clock/manifest.json`，並同時要求 `metadata/universe_symbols.json`、
`metadata/universe_identity.json`、`metadata/owner_acceptance.json`。identity 的
schema、symbols、candidate count、T-1 session dates、source window hash、clock
universe hash 與安全旗標均需一致；`universe_hash` 依既有 Rule producer 契約綁定
候選分數，不能誤以純 symbols 檔 hash 取代。實際 resolver 會再以既有唯讀 loader
重算 source window hash；目前 D `clock-20260828` 的 `source_window_hash`
與當前 `twstock.db` 的重算值不同，因此 resolver **拒絕**該 bundle，並保留
`rule_source_bundle_not_verified:...:market_revalidation_ValueError`。這是來源
內容漂移的實質 blocker，不能以相同 scored-universe hash 或 owner 姓名放行；D 槽
來源只讀，沒有搬移或覆寫。

當下 preflight 的 Rule source 因上述 source window drift 保持缺件，且台北 09:00
時窗尚未到；它同時保留 `rule_clock_source_missing` 與自然時窗 blocker，沒有以
未來時間重跑。當日 PIT archive 雖可供 capture candidate
重驗，正式 sidecar／receipt 尚未存在；PIT 的 08:30 decision cutoff 必須由之後的
consumer 讀取已完成 archive。Paper snapshot 為 D 槽唯讀 27 rows，但 repo 隔離
`output/paper_execution_eod_replay/paper_trade_ledger.sqlite` 尚不存在，沒有可供
causal ledger 的真實 Paper fills，故不產生或補造 transition。

Elevated readonly scheduler query 的營運條件仍須保留：Formal task 為
`Ready/Enabled`、上一結果 `2`；PIT preopen、PIT postcutoff 與 Paper EOD task
為 `Ready/Enabled`，上一結果 `267011`，尚無成功執行證據。這些結果不能被解讀成
Formal 3/3。下一次自然執行須以新 status、各 producer receipt、檔案 hash 與正式
consumer readback 驗收；candidate-only 或 blocked 仍回傳 exit code 2。

本片回歸為 `tests/test_scheduled_formal_input_producer.py` 與
`tests/test_formal_daily_input_producer.py` 合計 `31 passed`；包含完整 identity
自動解析、既有 read-only `daily_prices` 重算 scored-universe/source-window hash、
symbols 或市場資料竄改拒絕（含不改 score 的舊列數值）、PIT 缺 Rule 時仍可走 candidate capture、隔離 Paper ledger
path、狀態持久化與 retry 既有案例。scheduled wrapper `py_compile` 與 targeted
mypy 通過。當前正式 machine readiness 仍為 `0/3`；剩餘條件是 Rule
自然 09:00–13:30 且 source/clock 可被 producer 實際讀回、PIT 08:30 後由已捕捉
archive 建立並讀回正式 sidecar，以及 Paper 真實 Decimal fill ledger。任何一項
缺件都維持具體 machine blocker，不轉換成具名人工審核門檻。

## Paper 開盤資料至 Formal causal ledger 隔離接線（2026-09-08）

新增 `tests/test_paper_formal_daily_source_chain.py`，以隔離 TEMP source
實際呼叫公開 `scripts.run_paper_portfolio_daily.run`、
`run_paper_execution_daily_from_queue` 與
`run_daily_formal_input_producer`，串成盤前 snapshot → 下一官方 session 的
開盤資料 queue → Decimal Paper fill append/readback → 下一盤前唯讀 transition
projection → Formal causal ledger manifest/SQLite/receipt →
`load_formal_portfolio_state_ledger` readback。測試保留
`execution_event_time_proven=false` 與 `delayed_eod_replay_after_session_close`；
這是隔離的研究回歸，不能當成即時成交或正式信用。

同一檔另驗 durable causal ledger 的中斷恢復：manifest、SQLite 與 source
custody 已寫入而 receipt 寫入失敗時，public runner 回報具體 blocked；刪除一次性
snapshot／Paper ledger 後，下一輪只由相同 durable run 補回 receipt，重驗同一
manifest／SQLite／custody，沒有另造 chain。這兩項測試共 `2 passed`；連同 Paper
queue/preopen 回歸與本片 Formal 來源回歸的命令結果分開記錄如下：

```text
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_paper_formal_daily_source_chain.py -q -o addopts= -p no:cacheprovider
2 passed in 2.22s
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_paper_formal_daily_source_chain.py tests\\test_paper_daily_execution_producer.py tests\\test_run_paper_portfolio_daily.py -q -o addopts= -p no:cacheprovider
36 passed in 2.91s
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_scheduled_formal_input_producer.py tests\\test_formal_daily_input_producer.py -q -o addopts= -p no:cacheprovider
31 passed in 2.97s
```

可供獨立核對的 isolated success artifact（由 pytest `--basetemp` 留存）位於
`%TEMP%\\v4_paper_formal_chain_20260907_run\\test_isolated_paper_open_data_0`；
causal ledger run 的 manifest SHA-256 是
`sha256:91d629bc372da029383ad4fd96e3aba06c07c66fdc10a829669edb3717b05e84`，
`portfolio_ledger.sqlite` SHA-256 是
`sha256:dce95486f967aa87c88ae9d1e45bc41a718d67896afaeac3cf18c41c22193d33`，
receipt SHA-256 是
`sha256:87fd90a4a55af299e6d1f33f91d2a25c2376a47bd7421e7592feb185edc93f67`。
Paper candidate 與 isolated ledger 的 SHA-256 分別為
`sha256:32a24630791efc379f4ad91154ceff56b4a8c6690bac2732c059360d1d15015d` 與
`sha256:d63e1dd335ab58315d2130783725c35c374b78a5b05f4b34617b83121bd5fc8a`。
這些檔案只在 TEMP 隔離樹，沒有寫 D 槽原始 DB、Formal controlled DB 或 broker。

目前實際 D／排程狀態仍須另行以 elevated readonly receipt 驗證；在真實下一個
可用 session 前，Paper queue 若沒有可讀的開盤 source 只應留
`waiting_for_execution_source`，Formal readiness 不得由上述 isolated fixture
升為 `3/3`。本片證明公開 writer/consumer 接線及 receipt recovery，沒有宣稱
真實 D Paper fill 或 Formal 3/3 已完成。

## Paper／Formal scheduled source path contract（2026-09-07）

本片以 repo 設定與隔離 path contract 核對 production scheduled 參數，修正盤前
runner 與 EOD isolated writer 使用不同 Paper ledger 的分裂。盤前入口
`scripts/scheduled/run_paper_portfolio_daily.cmd` 現在只呼叫
`scripts/scheduled/run_paper_portfolio_daily_isolated.py`。它將
`DATA_ROOT\output\paper_portfolio\paper_portfolio.sqlite` 以
`mode=ro/query_only` 的 consistent backup seed 到
`<repo>\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite`，
再由公開 preopen runner append repository state；D snapshot 永遠不是 writer target。
EOD 與 Formal 讀取同一份 repository state，不把 snapshot 覆寫成成交，也不把市場 DB
當 writer。

Formal 排程入口
`scripts/scheduled/run_formal_input_producer_daily.cmd` 明確傳遞同一個
`<repo>\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite` 作為
`FORMAL_DAILY_PAPER_SNAPSHOT_DB`，以及同一份 repository EOD ledger 作為
`FORMAL_DAILY_PAPER_TRADE_LEDGER_DB`；`FORMAL_DAILY_MARKET_DB` 明確指向
`DATA_ROOT\sqlite\twstock.db`。scheduled Python status 會保存 snapshot 的實際解析路徑、
`sqlite_mode_ro_query_only`、ledger 路徑與 readback 邊界，讓正式 consumer 使用的
source 可稽核。candidate／manifest／receipt 仍寫 repository publication output，沒有
寫 D 原始資料、Formal controlled DB、broker 或真實交易。

新增 `tests/test_scheduled_production_path_contract.py`，覆蓋 `.cmd` 的預設路徑、
scheduled `_build_paths` 的 repository snapshot／repo ledger／D market 對齊，以及 durable status
對唯讀模式與非正式狀態的記錄：`3 passed`。既有排程／Paper/Formal focused 回歸為
`47 passed` 與 `16 passed` 兩組；`py_compile` 已檢查 scheduled Formal wrapper 與
contract test。這些是設定與隔離接線證據；Paper 的第一次自然排程成功、真實 fill
累積及 Formal 3/3 仍須由實際 receipt／consumer readback 另行驗收。

## 2026-09-07 repository state path correction 與單一排程更新

上一段已記錄 repository-isolated state path contract；本節補記 scheduler trigger
的實際核對與單一 task 更新。`run_paper_portfolio_daily.cmd` 現在只呼叫
`scripts/scheduled/run_paper_portfolio_daily_isolated.py`：它把
`D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_portfolio.sqlite`
以 SQLite `mode=ro/query_only` 的 consistent backup seed 到
`<repo>\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite`，
並以 `state_seed_manifest.json` 保存來源 main/WAL/SHM hash、實際 seed time、初始
target hash 與 scope。公開 `scripts/run_paper_portfolio_daily.py` 只在此 repository
state append；每次 append 後另以 `state_head_manifest.json` 保存最新 state hash，
使 EOD 與 Formal 可以讀回同一份可驗證 state。D snapshot、baseline、market SQLite
只讀，沒有 D writer。

`run_paper_execution_daily_isolated.py` 的 `STATE_DB` 已與盤前 adapter 指向相同
repository path；EOD 會要求 seed manifest/head 通過 hash／integrity 驗證，缺少
provenance 或 state 被未發布地改動時保留 blocked receipt。Formal cmd 也固定將
`FORMAL_DAILY_PAPER_SNAPSHOT_DB` 指向同一 repository state，並沿用同一份
repository EOD ledger。這個 state path contract 不會把 candidate-only Paper
結果升格為 Formal 3/3。

排程設定檔已修正為 Pacific 16:30 喚醒：2026 PDT 轉為台北次日 07:30，2026 PST
轉為台北次日 08:30；adapter 以真實 Asia/Taipei 08:30 cutoff guard，PDT 早到時
等待後才執行，不能把 PST 的 09:30 視為盤前。本 sandbox 的非 elevated
`schtasks /Query` 仍可能回傳 `The system cannot find the path specified`，所以先保存
受控 elevated 唯讀基線：更新前 `baldr-paper-portfolio-daily` 為
`Ready`／`Enabled`，Next Run 為 `2026-09-08 05:28` local，Last Run 為
`2026-09-07 05:28:01`、Last Result `0`，action 已引用目前 repository
`run_paper_portfolio_daily.cmd`。基線 XML 保存在
`output/scheduler_backups/baldr-paper-portfolio-daily_20260907_160747.xml`。

`register_paper_portfolio_task.cmd dryrun` 先確認 16:30 Pacific 與 PDT/PST 的台北
映射；之後只在受控 elevated session 執行該單一 script 的 `register`。既有 task
走 `schtasks /Change`，沒有啟動 wrapper、沒有使用 aggregate register、沒有碰其他
task。更新後的 elevated 唯讀 query 顯示 `Ready`／`Enabled`，Next Run 為
`2026-09-07 16:30:00` local，Last Run 仍為 `2026-09-07 05:28:01`、Last Result
`0`，action 仍引用目前 repository wrapper；`Interactive only`、電池限制與 72 小時
執行上限均保留。更新後 XML 與前後比較分別保存在
`output/scheduler_backups/baldr-paper-portfolio-daily_20260907_160825_after.xml`
及 `output/scheduler_backups/baldr-paper-portfolio-daily_20260907_160825_comparison.json`；
比較結果為 `command_preserved=true`、`arguments_preserved=true`、
`principal_preserved=true`、`settings_preserved=true`，只改變 StartBoundary
`05:28` → `16:30`。這是 task 註冊／query 證據，不是 16:30 自然執行成功證據；
既有 Last Result 也不作隔離 adapter 的成功證據。未寫 D 或 broker。

新增／更新驗收：

- `tests/test_paper_portfolio_isolated_scheduler.py`：9 tests，新增 cutoff guard、注入時鐘等待
  與實際 `main`→公開 runner 路由，另涵蓋 isolated adapter、D source bytes 不變、
  seed/head 重跑、缺 D source、state tamper、EOD/Formal 共用 path 與 PDT/PST wake-up。
- `tests/test_paper_portfolio_registration_plan.py`：5 tests，涵蓋單 task dryrun／受控 fake
  register／非 Pacific 拒絕；trigger 為 16:30，並明示 07:30 PDT／08:30 PST。
- `tests/test_paper_execution_isolated_scope.py`：既有 scope/junction 測試改以
  repository state seed，確保 EOD 不回讀 D state。
- `tests/test_scheduled_production_path_contract.py`、
  `tests/test_paper_daily_execution_producer.py`、
  `tests/test_scheduled_cmd_scripts_task_names.py`：wrapper／cmd／16:30 static
  contract 回歸。
- `scripts/scheduled/register_paper_portfolio_task.cmd`：只更新
  `baldr-paper-portfolio-daily` 的 16:30 trigger/action；既有 task 走
  `schtasks /Change` 保留其餘設定，只有明確 not-found 才建立且不使用 `/F`；query
  或權限錯誤會 fail closed，不會碰其他 task。上述 focused command 共 `66 passed`
  （6.26 秒）。

上述為 repository 隔離與公開 writer 接線證據；尚未宣稱實際 scheduled 首次成功、
真實 Paper fill 已累積或 Formal 3/3 完成。自然時間與來源若不可得，仍保留具體
blocked／waiting 狀態。

## Formal source resolver 與 2026-09-08 盤前唯讀 preflight

本次先處理排程環境仍殘留 `BALDR_ML_*` 舊 activation path 的設定風險。當
`run_formal_input_producer_daily.cmd` 設定 `FORMAL_DAILY_RULE_SOURCE_ROOT` 時，
四項 Formal source（PIT sector、Rule history、causal ledger、PIT denominator）
改由目前 root 掃描與 consumer 驗證；即使 legacy 檔案存在也不會優先採用。明確的
`FORMAL_DAILY_*` path 仍可作為受控 override，Paper 隔離 snapshot／ledger 的 repo
default 不受影響。新增的
`tests/test_scheduled_formal_input_producer.py::test_scheduled_source_root_ignores_existing_legacy_formal_paths`
以實際存在的 legacy fixtures 驗證四個 finder 仍改讀 current publication。

在台北 `2026-09-08 07:24:17` 左右，以當下 clock 執行
`cmd.exe /d /c scripts\\scheduled\\run_formal_input_producer_daily.cmd`；沒有
`--now`、日期覆寫或 fixture。公開 wrapper 的 durable status 為
`output/formal_daily_publications/scheduler/latest_status.json`，file SHA-256
為 `c3aa2faa091d463f83ab6966b7bcb15ecc3cc1a9677a7b08a196c2a642a7507b`，其中：

- `rule_source_resolution.mode=auto_discovery_failed`、`source_root` 為
  `D:\\Min\\Python\\Project\\FA_Data\\output\\formal_prospective`，並列出
  已存在但被新 root policy 忽略的三個 legacy environment names；沒有把
  `clock-20260819` 當作 source。`discovery_reason` 現在保留逐 bundle 驗證原因：
  `clock-20260827-v2` 與 `clock-20260827-v3` 缺少
  `metadata/universe_identity.json`（`FileNotFoundError`），最新完整 metadata
  bundle `clock-20260828` 則因目前唯讀 market DB 的
  `source_window_hash` 與持久 identity 不一致而拒絕；這不是泛稱的 missing env。
- D `twstock.db` 只以 `ro/query_only` 讀取；其 market source SHA 為
  `sha256:5954d9d0901fdd2654ab6eff93898fe584d0ecc608d87783030e554f2e48bda0`。
  repo publication 仍是 append-only；`writes_market_database=false`、
  `writes_formal_controlled_paths=false`。
- 當日 PIT archive 已由既有 preopen producer 留下 `1,984` 筆且 capture
  consumer verified，但在台北 08:30 前正式 sidecar 保持 waiting；這次 wrapper
  的 `pit_candidate` 因自然 cutoff 回報
  `pit_source_production_failed:preopen PIT archive consumer cannot run before Taipei 08:30 cutoff`。
- Rule 目前回報 `rule_capture_outside_taiwan_regular_session`、clock／universe／
  owner source 缺件；causal ledger 同時缺 repo Paper snapshot、Paper fill 與
  durable publication。`formal_ready_input_count=0`、`machine_candidate_input_count=0`、
  `human_review_required=false`，wrapper exit policy 仍以 2 表示 blocked。

同一時鐘的唯讀 auditor 產物為
`output/qa/formal_operational_readiness_20260908_preopen_current.json`，file
SHA-256=`fc0cbf71b6b30ef022f09e1eac7ecd0fda7479e98054daa38971e4abce5317eb`；
`phase=before_pit_cutoff`、`credit_decision=no_credit`、三項 machine verified
count 均為 0。它明確列出下一可驗證時窗：PIT sidecar 在台北 08:30 後由排程讀取
既有 archive，Rule source 只能在台北 09:00–13:30 以當日實際來源捕捉，Paper
EOD source 最早台北 15:00；不能以等待、舊 clock 或本次 preflight 充作正式信用。
auditor 本身 `network_requests=false`、`read_only=true`，未寫 D、Formal controlled
input、broker 或 ML。

本片新增 resolver regression 後，`tests/test_scheduled_formal_input_producer.py`
為 `12 passed`；changed scheduled producer 另通過 `mypy --explicit-package-bases`
與 `py_compile`。這是新 source root 避開舊 environment 的接線及當下自然窗口
preflight 證據，不是 Rule／PIT／causal ledger 正式 3/3，也不是排程已成功執行的證據。

## 2026-09-08 當日 Rule source machine revalidation

本片補上舊 `clock-20260828` source window hash 漂移後的可重驗當日 Rule source。
`data_module/formal_rule_source_producer.py` 從唯讀 D 槽 `twstock.db` 讀取完整
T-1 window，以既有 owner policy、score policy 與 universe symbols 為 parent，重新
計算當日 source window／universe，並以官方 TWSE holidaySchedule hash-bound cache
確認 `2026-09-08` 是交易日。它只建立 repository 下的 candidate publication；不改寫
8/28 parent、不寫 D、不開啟 Formal OOS、promotion 或 broker。

實際觀測時間為 `2026-09-07T23:41:28.090570+00:00`（台北
`2026-09-08 07:41:28.090570`），產物為：

`output/formal_daily_publications/rule_source/clock-20260908-machine-v2-c74c55a516b6-85d50c270d9a/`

- `clock/manifest.json` 的邏輯 manifest hash 為
  `sha256:f393ff7f86ddfa75edd4a95f825c818efbef9bd0d019fec0b03ee82f3a738308`；
  receipt 綁定的實體檔案 hash 為
  `sha256:8196a3b2bddd072164d2c17beca3c71d54f00f8abeb27b60e96a6732c27f8f65`。
- `metadata/machine_revalidation_receipt.json` 綁定 producer
  `machine-revalidated-rule-source.v2`、machine identity
  `formal-rule-source-revalidator.v1`、固定 reason、四個 child hashes、parent
  policy hashes、D market DB hash、source window hash 與觀測時間。receipt 實體檔案
  hash 為 `sha256:8e083f87790c80008925cde6f0765cd22c6b99c6e85f3c353461bf894897a1ab`。
- 當日來源為 `1932` 個 symbols、`60` 個完整 T-1 sessions，source window hash 為
  `sha256:c74c55a516b61fe5179a03d9ef46fc0dade48b9e870dcf5da75c2ab2a840dfa3`，
  max available 為 `2026-09-07T18:10:20.268470+00:00`；重算 universe hash 為
  `sha256:5bc52f13ce7cda4b936737b446559ce6f0be298b180fb0aa5501159ba8b3dde1`。
- D market DB 只用 SQLite `mode=ro`／`query_only`，檔案 hash 為
  `sha256:5954d9d0901fdd2654ab6eff93898fe584d0ecc608d87783030e554f2e48bda0`。
  官方日曆 cache 為
  `output/paper_execution_eod_replay/calendar_cache/twse_holiday_schedule_2026_20260907_capture1.json`，
  cache 檔案 hash 為 `sha256:74790d36d0cd66398c37a729bfce243e1a03358f93afd256c523e2549c6d6c93`，
  其中官方 response hash 為
  `sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`。

正式 consumer 會讀取同一份 market DB，再次計算 T-1 source hash、session dates、
候選 universe hash，並在讀取前後檢查 DB file hash；receipt 或 owner 自填
`acceptance_source` 都不能略過這個檢查。實際 readback 結果為
`validate_machine_revalidation_bundle -> machine_revalidation_verified`，
scheduled resolver 回傳 `auto_discovered_latest_verified_bundle`，
`formal_daily_input_producer._acceptance_projection` 為 `blockers=[]`、
`machine_revalidation.status=machine_revalidation_verified`。status snapshot 位於
`output/formal_daily_publications/rule_source/scheduler/rule_source_latest_status.json`，
當次檔案 hash 為
`sha256:51d070b511f2f273e412d4b565366bf3ba27f95771b21e7961623567e4ba2fdd`。
其後於 `2026-09-07T23:54:16.962485+00:00` 以同一 public wrapper 重試，結果為
`status=rule_source_bundle_reused`、`write_performed=false`、exit code `0`；最新
status snapshot hash 為
`sha256:ac32bb4d440f9122fd3b897d25db0d56c91271478361b50411bca57632e83490`。
完成 receipt safety 與 source readback 強化後，於
`2026-09-07T23:56:09.502641+00:00` 再次以該 public wrapper 實跑，仍為
`status=rule_source_bundle_reused`、`write_performed=false`、exit code `0`；最新
status snapshot hash 為
`sha256:6d89023705f2ac3253eaf55c98cf904c97c1cedc0a86c12661b093bbde1e56c3`。

舊的 `clock-20260908-machine-v1-c74c55a516b6-85d50c270d9a` 保留作歷史輸出，因
缺少 v2 receipt completeness 而由 resolver 拒絕；沒有刪除或覆蓋。新的 v2 producer
由 `scripts/scheduled/run_formal_rule_source_preopen.cmd` 執行，並由既有
`run_pit_sector_membership_preopen_capture.cmd` 在 PIT pre-open wrapper 中先呼叫；
formal Rule capture 仍須在台北 `09:00–13:30` 以自然 clock 執行。若 pre-open window
已過且沒有同日 immutable bundle，入口回傳
`same_day_rule_source_preopen_window_missed`；不會用事後時間建立 clock。

本片定向驗證為 `tests/test_formal_rule_source_producer.py`、
`tests/test_scheduled_formal_input_producer.py`、`tests/test_pit_preopen_schedule.py`
合計 `35 passed`（pytest cache 權限 warning 不影響結果）；changed Python files 也
通過 `py_compile` 與 `mypy --explicit-package-bases`。這是當日 machine candidate
source 與正式 resolver/acceptance readback 證據，不是 Rule capture 已完成、不是
Formal 三項 `3/3`，也不是排程自然成功。仍待自然 Rule window 及 causal Paper
ledger／PIT formal consumer 各自取得真實來源後，才可取得相應正式信用；缺件、晚到、
hash 漂移與不一致 identity 會保留具體 machine blocker。

## Task 3 最終 readback：Formal／Paper／frozen inference（2026-09-08）

本節是 Task 3 的最終機器 readback，不重跑既有 immutable block、PIT publication、
官方價格 overlay 或 bounded union；所有上游產物均保留原路徑、原 manifest 與原 hash。
容量保護沿用並驗證既有收緊後政策：heavy chain safety reserve 至少 `200 GiB`，
scheduled raw／Direct 的 `35 GiB` persistent + `40 GiB` temporary 需要 `275 GiB`
headroom，standalone PIT／Direct／raw-to-OOC／OOC 各為 `1/1 GiB`；canonical OS lock、
preflight、取鎖後重查與 checkpoint／summary encoded-size projection 均 fail-closed。
本次沒有為驗證而重建 v2，也沒有放寬容量或自動清理既有 artifact。

### 上游 v2 既有成功產物重用與 24 檔排除判定

從 `output/v4_ml_research_shadow_union_bounded_20260907_v2/qa/` 的既有 QA 產物獨立
讀回結果如下：

- `overlay_readback_20260520_final_v4.json`（檔案 hash
  `sha256:9d22b05fe9202a3737b83dac1d49ed46941780fbdd255adb8c29193d3dc7d031`）確認官方
  價格 overlay `33/33`、PIT overlay `33 symbols / 99 rows`，但
  `pit_available_before_decision_row_count=0`；union 交集 `9/33`、direct 交集
  `1/33`，且 `selected_source_manifests_readback_complete=true`。
- `union_coverage_20260520_v2.json`（檔案 hash
  `sha256:6f690ba0806332ac33bff7b70c5add0585c0d18e1592ebcb37d716fa13aa8d38`）確認
  union sample 缺少 `24` 檔。`cause_contract` 綁定
  `data_module/portfolio_ml_dataset_assembler.py` 的
  `_corporate_action_effective_date_in_horizon`／`_labels_for_decision`，排除區間是
  `[decision_date, 60-trading-day horizon end]`，每一檔都因官方結果型除權息事件
  使完整四 horizon tuple 不成立；這不是宣稱 raw price rows 不存在，也不是以空列補齊。
- 因此 24 檔的排除規則判定為「合理且保守」：它避免把除權息後結果資訊帶進當期
  label／sample，並可由事件檔 hash、union manifest hash 與 assembler code evidence
  重播。`union_coverage` 的 `historical_pit_backfill_claimed=false`、
  `formal_training_allowed=false`、`production_alpha_bp=0` 仍有效。

### Frozen inference 最終公開入口 readback

- `frozen_inference_audit_final_v4.json`（檔案 hash
  `sha256:4fb68c157acaa9f45e59d2daf7c2076f14991b16390eafdce2da8de0390091cd`）為
  `independent_v3_release_audit_passed`／`verified_after_publish`，11 rows 完整對讀；
  `formal_oos_allowed=false`、`production_action_allowed=false`、
  `broker_order_allowed=false`、`production_alpha_bp=0`、`promotion_eligible=false`。
- `frozen_inference_readback_final_v4.json` 的
  `inference_readback_mode=post_freeze_research_shadow`、`fallback_reason=null`；
  未執行 promotion authorization、rule weight blend、portfolio risk projection、
  advice composition 與 broker routing。此 readback 是 frozen inference 的研究影子
  驗證，不是正式績效或可下單證明。

### 當日公開入口與真實自然時間狀態

觀測時間為台北 `2026-09-08 12:58` 左右；當日所有 wrapper 均使用自然 clock，沒有
`--now`、事後補造 clock 或重新 fetch 舊來源。

- `run_formal_input_producer_daily.cmd` 修正混合換行後，以 `cmd.exe` 實跑的 outer
  與 inner exit 均為 `2`，不再出現 batch parser 噪音或 exit code 不一致。最新 durable
  status `output/formal_daily_publications/scheduler/latest_status.json` 的檔案 hash
  為 `sha256:663a5c63cf8c4126a51e9d4c71687892be74d7f1a40a3366ee8ed2cd014b6e50`，
  `status=candidate_only`、`formal_ready_input_count=1/3`、
  `formal_consumer_compatible_count=1/3`、`machine_candidate_input_count=2`、
  `formal_oos=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。唯一取得
  Formal-ready／consumer-compatible 的是 Rule history；PIT 仍是 machine candidate，
  causal Paper ledger／sector formal source 仍缺件，因此不升格為 3/3。
- PIT sidecar public entry `scripts/scheduled/run_formal_pit_sidecar_postcutoff.cmd`
  實跑 exit `2`。`output/formal_daily_publications/scheduler/pit_sidecar/latest_status.json`
  hash 為 `sha256:912af781495a294d2d0541fbbc96d6f104a3b1597d35a57e19e08ad8c0c592e0`，
  `status=blocked`，保留 `pit_formal_calendar_unknown:2026-09-08`、同日多重 capture
  與 `pit_formal_required_trading_dates_empty`；沒有把候選 archive 轉成 Formal credit。
- Paper isolated public entry
  `scripts/scheduled/run_paper_execution_daily_isolated.cmd` 實跑 exit `0`，新增的
  durable receipt 為
  `output/paper_execution_eod_replay/receipts/paper_execution_2026-09-08_9330c91d89344056_20260908T045711848641Z.json`
  （檔案 hash `sha256:829749629505fefc5e76c2aad87182a423b47b31ec236469347ee398bfc1bc53`）。
  receipt 的 candidate content hash 是
  `sha256:eac06b94fc209fb3535f688456ade527d3db8297bd8401a565bd39fca3a50839`，
  candidate file hash 是 `sha256:08f0c5b3c56f37bca0952da6e37b9caab652553d7e6a09db6dbda62d88a99d16`，
  狀態為 `waiting_for_execution_source`，`execution_source_available_after=15:00`
  （台北）、`ledger=null`、`formal_credit=false`、`broker_execution=false`。這證明
  Paper 入口會產生 hash-bound candidate／receipt 並等待自然 EOD，不會提前製造 fill。

### 排程、分類器與 readiness 結論

升權唯讀 scheduler inspection
`output/qa/scheduled_task_registration_task3_elevated_current.json`（capture
`2026-09-08T04:58:03+00:00`，檔案 hash
`sha256:2e1790609a7e86ea8653971feac357588bd122054a83a6d40b0da45dc8b3ec5b`）確認
`17/17` tasks available、`configuration_ready=true`、17/17 action matches、所有
action 均已觀測、`query_only=true`、`side_effect_free=true`。四個必要 task 的 LastResult
分別為 PIT pre-open `0`、PIT sidecar `2`、Formal producer `-1073741510`、Paper
EOD `267011`；均為 `Interactive only` 且 `Stop On Battery Mode, No Start On
Batteries`。所以「已註冊／action 正確」與「自然執行已產生可驗證證據」被明確分開。

最後的唯讀 operational auditor
`output/qa/formal_operational_readiness_task3_current_v3.json`（檔案 hash
`sha256:a94defdd6ce5043918e3583a962f3df49ce3f3c2a0f20f9e4d7beaa34cf41164`）為
`status=blocked_no_formal_credit`、`credit_decision=no_credit`；lane readback 為
Rule `blocked`、PIT `machine_candidate`、Paper `waiting_for_eod_window`。本次沒有
注入舊的 ML readiness report，因此 `formal_readiness.state=not_supplied` 會如實成為
blocker，而不是以 stale／research readiness 偽造正式信用。auditor safety flags 為
`read_only=true`、`network_requests=false`、`writes_source_database=false`、
`writes_formal_controlled_paths=false`、`broker_order_allowed=false`、
`formal_oos_allowed=false`、`training_started=false`。

auditor process exit `0` 僅代表唯讀稽核完成，不代表 Formal pass。分類器的狀態集合
明確保留 `ready`、`complete`、`pending_natural_window`、`pending_upstream`、
`blocked_missing_evidence`、`failed_retryable`、`failed_terminal` 與 `stale`；
目前尚未有 `complete`，而是以各 lane 的具體證據落點顯示。Paper 的 EOD 未到是
`pending_natural_window`，PIT sidecar／
causal ledger 證據不足是 `blocked_missing_evidence`，未成功的 scheduler LastResult
是 `failed_retryable`／`stale` 的執行觀測，不會被壓成 `complete`；只有三個 consumer
receipt、自然時間與內容／hash replay 同時成立才可進入 `ready`／`complete`。等待不是
failure，也不是 pass。

下一個合法自然時窗：

- Paper：台北 `2026-09-08 15:00` 後 EOD source 才可用，排程 wrapper 為 `15:05`；
  在此之前只能保持 waiting，不能宣稱 fill 或 Paper performance。
- PIT：`2026-09-08` 的 pre-open cutoff `08:30` 已過；下一個官方交易日須在
  `08:30` 前捕獲新的同日 archive，再於 cutoff 後由 sidecar readback；不接受事後
  fetch、舊 capture 或多重 capture 猜選。
- Rule：當日自然窗口為 `09:00–13:30`；現有 machine revalidation 不足以補足 PIT／
  causal ledger，下一次必須在下一個合法 session 重新取得缺件並由同一 consumer 驗證。

本次工程驗證為 66 個受影響 test files、`445 passed`；UI workbench `81 passed`；
Update Tab QA `25 passed / 0 failed / 4 skipped`；22 個 Python 檔案 `py_compile`；
21 個 Formal／Paper 核心檔案及全 core/UI scope `mypy --explicit-package-bases`
均無錯誤。新增 `*.cmd text eol=crlf` repo contract 與 line-ending regression test，
以固定 Windows 公開入口的可重現性。
