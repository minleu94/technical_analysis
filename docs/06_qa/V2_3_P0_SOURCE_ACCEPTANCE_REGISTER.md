# V2.3 P0 資料來源人工接受台帳

> 日期：2026-07-12
> 狀態：`engineering_readiness_only`；所有列均為 `requires_human_acceptance`
> 適用 Gate：Gate 3 / V2.3 P0 Data Credibility
> 權威邊界：本台帳記錄待決的人工作業；不得將任何列解讀為正式 ingestion、`ScoringEngine` feature、排程核准、投資有效性或交易資格。

## 1. 使用規則與 P0 覆蓋

1. 本台帳完整覆蓋 `ROADMAP_6M_ENGINEERING.md` Gate 3 P0：除權息 / 除權、減資 / 分割 / 面額變更、停牌 / 復牌、處置、分盤、全額交割、漲跌停鎖死、三大法人、信用交易、TDCC / 集保持股分散，以及 PIT 月營收 / 季度財報公告日。
2. `candidate status` 是工程或資料治理狀態，不是接受結論；`decision_ready_candidate` 也不等於 accepted。
3. 在具名人工決策人、日期、授權 / 使用範圍、quality、PIT、freshness / coverage、missing / outage 與 evidence review 均完成前，`human decision` 固定為 `requires_human_acceptance`，`downstream eligibility` 固定為 `none`。
4. 資料缺失、來源中斷、過期、缺 `available_date` 或 `available_date > decision_date` 時，依列示 policy fail-closed 或保留降級診斷；不得補值、不得把 stale 偽裝為 observed。
5. 現有 registry 的 `ready` / `partial` 只表示 capability metadata，不能取代本台帳的人工作業；未登錄 ID 只用於指出 P0 缺口，不是 adapter、source manifest 或可呼叫資料來源。

## 2. P0 source-by-source 決策表

欄內「未記錄」均表示尚未以真實來源證據完成審核，不能推定為可用。`review` 指向本次 readiness 文件；`rollback` 指向建立本台帳的 commit，未來人工決議必須另記錄其 own rollback SHA。

| source id | 用途 | source version | as_of_date | available-date | quality | license | rate limit | freshness / coverage | missing / outage policy | quarantine / retry | candidate status | human decision | owner | date | downstream eligibility | evidence / review / rollback links |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `corporate_action.ex_dividend_timeline` | 僅除權息 / 除權的 decision-time 事件時間軸候選；不涵蓋減資 / 分割 / 面額變更。 | 未記錄；ingestion 前逐事件必填。 | 公告日、除權息 / 除權生效日逐事件必填；目前未審核。 | 逐事件必填，且僅 `available_date <= decision_date` 可供後續審核。 | `partial`；尚未 ingestion，adjusted-price policy 仍 candidate-only。 | local governed use；來源條款與再散布限制未審核。 | 未記錄；須由人工決定。 | 未量測；無 formal coverage 結論。 | `fail_closed_for_adjusted_decision_features`。 | 未配置；必須先定義隔離、重試與 stale 標示。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none`（僅 policy / diagnostics） | [registry](../../data_module/data_source_capability_registry.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `unregistered.corporate_action.reduction_split_par_value` | 減資、分割、面額變更的 P0 corporate-action 缺口；非既有 `ex_dividend_timeline` capability。 | 未指定。 | 事件公告 / 生效日期語意未選定。 | 尚無受治理 contract；不得由 event date 或 raw 檔日期推定。 | `missing`；無 source manifest / PIT evidence。 | 未指定。 | 未指定。 | 未量測；無 coverage。 | `fail_closed`；不得產生 adjusted 或 decision-time feature。 | 未配置；先建立 quarantine / retry contract。 | `unregistered_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none` | evidence：未建立；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `unregistered.microstructure.suspended_halt_resume` | 停牌 / 復牌狀態與生效時間的 P0 交易限制缺口。 | 未指定。 | 停牌 / 復牌公告、生效與解除日期語意未選定。 | 尚無受治理 contract；不得由缺席日價或後見資料推定。 | `missing`；無 source manifest / PIT evidence。 | 未指定。 | 未指定。 | 未量測；無 coverage。 | `fail_closed`；未知時不得假設可交易 / 可成交。 | 未配置；先建立 quarantine / retry contract。 | `unregistered_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none` | evidence：未建立；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `microstructure.disposition_stock` | 處置股交易限制 preflight 候選。 | 未記錄；ingestion 前逐列必填。 | 限制公告 / 生效日期逐列必填。 | 必須保存限制生效日與 `available_date <= decision_date`。 | `partial`；未正式 ingestion。 | local governed use；官方條款未審核。 | 未記錄；須由人工決定。 | 未量測；無 formal coverage 結論。 | `degrade_preflight_and_warn`；不可視為 unrestricted。 | 未配置；隔離 / retry / stale 行為待決。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none`（僅 diagnostics） | [registry](../../data_module/data_source_capability_registry.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `microstructure.periodic_call_auction` | 分盤交易限制 preflight 候選。 | 未記錄；ingestion 前逐列必填。 | 限制公告 / 生效日期逐列必填。 | 必須保存生效日與 `available_date <= decision_date`。 | `partial`；未正式 ingestion。 | local governed use；官方條款未審核。 | 未記錄；須由人工決定。 | 未量測；無 formal coverage 結論。 | `degrade_preflight_and_warn`。 | 未配置；隔離 / retry / stale 行為待決。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none`（僅 diagnostics） | [registry](../../data_module/data_source_capability_registry.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `microstructure.full_delivery` | 全額交割限制 preflight 候選。 | 未記錄；ingestion 前逐列必填。 | 限制公告 / 生效日期逐列必填。 | 必須保存生效日與 `available_date <= decision_date`。 | `partial`；未正式 ingestion。 | local governed use；官方條款未審核。 | 未記錄；須由人工決定。 | 未量測；無 formal coverage 結論。 | `degrade_preflight_and_warn`。 | 未配置；隔離 / retry / stale 行為待決。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none`（僅 diagnostics） | [registry](../../data_module/data_source_capability_registry.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `microstructure.limit_lock` | 漲跌停鎖死與成交可行性 preflight 候選。 | 未記錄；ingestion 前逐列必填。 | 交易日 / 成交狀態逐列必填。 | 必須由決策當下可得的同日價格 / 成交量證據推導。 | `partial`；未正式 ingestion。 | local governed use；市場資料條款未審核。 | 未記錄；須由人工決定。 | 未量測；無 formal coverage 結論。 | `degrade_preflight_and_warn`；未知時不得假設可成交。 | 未配置；隔離 / retry / stale 行為待決。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none`（僅 diagnostics） | [registry](../../data_module/data_source_capability_registry.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `institutional_flows` | 三大法人買 / 賣 / 淨買賣 source candidate。 | 每列必填；目前不以 sample version 代表正式版本。 | 交易日 / 資料截止日逐列必填。 | 每列 explicit `available_date`，且不晚於 `decision_date`。 | 僅 candidate dry-run；`observed` / `governed` / `verified` 是列級診斷條件，非人工接受。 | 官方 / 供應者條款與使用範圍未審核。 | 未記錄；須由人工決定。 | 未量測；無正式來源 coverage。 | 缺 DB / table / required field / available date 或 future data 時 fail-closed。 | 未配置；保留 diagnostics，隔離 / retry 待決。 | `decision_ready_candidate_possible` | `requires_human_acceptance` | 未指定 | 未填 | `none`（不進 score、Advice、Portfolio 或 scheduler） | [candidate service](../../app_module/source_candidate_readiness.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `credit_transactions` | 融資買進、融資餘額、融券賣出、融券餘額 source candidate。 | 每列必填；目前不以 sample version 代表正式版本。 | 交易日 / 資料截止日逐列必填。 | 每列 explicit `available_date`，且不晚於 `decision_date`。 | 僅 candidate dry-run；`financing` / `securities_lending` 缺值不得補。 | 官方 / 供應者條款與使用範圍未審核。 | 未記錄；須由人工決定。 | 未量測；無正式來源 coverage。 | 缺 DB / table / required field / available date 或 future data 時 fail-closed。 | 未配置；保留 diagnostics，隔離 / retry 待決。 | `decision_ready_candidate_possible` | `requires_human_acceptance` | 未指定 | 未填 | `none`（不進 score、Advice、Portfolio 或 scheduler） | [candidate service](../../app_module/source_candidate_readiness.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `tdcc_shareholding` | TDCC / 集保持股分散、持股級距、大戶 / 散戶比例候選。 | 每列必填；目前不以 sample version 代表正式版本。 | 週期資料的資料截止日逐列必填。 | 週資料與公告延遲資料皆須 explicit `available_date <= decision_date`。 | 僅 candidate dry-run；未有任一候選 payload 時為 `source_not_ingested`。 | TDCC / 供應者條款與使用範圍未審核。 | 未記錄；須由人工決定。 | 未量測；無正式來源 coverage。 | 缺 DB / table / candidate payload / available date 或 future data 時 fail-closed。 | 未配置；保留 diagnostics，隔離 / retry 待決。 | `decision_ready_candidate_possible` | `requires_human_acceptance` | 未指定 | 未填 | `none`（不進 score、Advice、Portfolio 或 scheduler） | [candidate service](../../app_module/source_candidate_readiness.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `twse.monthly_revenue_announcement` | PIT 月營收公告日 mapping 候選。 | 每筆 mapping 必填；builder 可產生版本前綴，尚非人工接受版本。 | 月營收 period / 公告日逐列必填。 | 僅採有效公告日 / mapping 的 explicit date；raw CSV 不可推定。 | candidate mapping；需保留 source version 並通過公告日合理性審核。 | 官方 OpenAPI / 文件條款與使用範圍未審核。 | 未記錄；須由人工決定。 | 未量測；無 formal coverage 結論。 | 缺 mapping、公告日、source version 或超出合理窗口時不產生 normalized record。 | 未配置；候選 mapping 的隔離 / retry 待決。 | `pit_mapping_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none`（既有 guarded research path 不因本台帳而升級） | [availability builder](../../data_module/monthly_revenue_availability_builder.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `tpex.monthly_revenue_announcement` | OTC PIT 月營收公告日 mapping 候選。 | 每筆 mapping 必填；尚無人工接受版本。 | 月營收 period / 公告日逐列必填。 | 僅採有效公告日 / mapping 的 explicit date；raw CSV 不可推定。 | candidate mapping；需保留 source version 並通過公告日合理性審核。 | 官方 OpenAPI / 文件條款與使用範圍未審核。 | 未記錄；須由人工決定。 | 未量測；無 formal coverage 結論。 | 缺 mapping、公告日、source version 或超出合理窗口時不產生 normalized record。 | 未配置；候選 mapping 的隔離 / retry 待決。 | `pit_mapping_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none`（既有 guarded research path 不因本台帳而升級） | [availability history](../../data_module/monthly_revenue_availability_history.py)；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |
| `unregistered.pit_quarterly_financials` | PIT 季度財報公告日與 statement items 的待登錄 P0 source；非既有 adapter。 | 未指定。 | 財報 period、公告 / 更正日期語意未選定。 | 尚無受治理 contract；不得由 period end 或 raw 檔日期推定。 | `missing`；無 source manifest / PIT evidence。 | 未指定。 | 未指定。 | 未量測；無 coverage。 | `fail_closed`；不產生正式 decision-time feature。 | 未配置；先建立 quarantine / retry contract。 | `unregistered_candidate` | `requires_human_acceptance` | 未指定 | 未填 | `none` | evidence：未建立；[review](V2_3_ENGINEERING_READINESS_2026_07_12.md)；rollback `53ca505` |

## 3. 人工接受前檢核

每一列在填入 `accepted`、`limited`、`rejected` 或 `deferred` 前，人工決策人必須逐項完成並保留 evidence link：

- source manifest、`source_version`、授權、rate limit 與使用範圍；
- `as_of_date`、`available_date`、時區、修訂 / backfill 與 look-ahead 自查（所有可下游列均符合 `available_date <= decision_date`）；
- freshness、coverage、schema、quality、missing / outage、quarantine、retry 與 stale 行為；
- 對應的 shadow / diagnostics / Evidence Review、受限使用情境與 rollback SHA；
- 分離記錄的 owner、日期、結論與明確 downstream eligibility。

在這些欄位全數完成前，任何 `decision_ready_candidate` 僅表示該次列資料通過候選診斷，不能改寫為 accepted feature。

## 4. 2026-07-17 Owner 候選稽核紀錄（append-only）

### Owner 使用意圖聲明

Project Owner 已聲明下列意圖適用於 13 項 P0 來源：可作內部研究、可自動抓取與保存、不可再散布。此為專案 Owner 的使用意圖，**不是**來源方授權、開放資料條款、書面許可或正式 `accepted` 決議的替代證據；因此所有來源的 `human decision` 仍為 `requires_human_acceptance`，`downstream eligibility` 仍為 `none`。

### 單日唯讀候選探測

- 執行日期：2026-07-17（探測資料日：2026-07-16）。
- 指令：`.\.venv\Scripts\python.exe scripts\run_p0_candidate_audit.py --decision-date 2026-07-16 --output <isolated-temp-output>`。
- 寫入邊界：不寫正式資料庫；`production_scheduler_allowed=false`；不改 `ScoringEngine`、Advice、Portfolio 或交易／排程路徑。
- 驗證：相關 pytest 28 passed；信用交易候選解析器已對齊 TWSE 現行重複欄名的明細表結構。

| source id | 本次候選狀態 | 筆數 | 品質／待補證據 |
|---|---|---:|---|
| `institutional_flows` | `observed_candidate` | 13,821 | `degraded`；僅有 first-observed time，缺正式 publication timestamp。 |
| `credit_transactions` | `observed_candidate` | 1,284 | `degraded`；僅有 first-observed time，缺正式 publication timestamp。 |
| `tdcc_shareholding` | `observed_candidate` | 68,170 | `degraded`；僅有 first-observed time，缺正式 publication timestamp。 |
| 其餘 10 項 P0 | `not_started_no_candidate_adapter` | 0 | 尚未建立 candidate adapter；不得據此推定來源不可用、品質合格或已接受。 |

### 後續續作入口

1. 先取得逐來源的授權／條款、rate limit、正式公告時間與修訂政策證據。
2. 為尚未接線的 10 項建立 source-specific candidate adapter、raw manifest、quarantine 與可得時間契約。
3. 以多個實際日期累積 coverage、schema drift、缺漏與修訂證據後，再由 Owner 逐項作出具名決議。
