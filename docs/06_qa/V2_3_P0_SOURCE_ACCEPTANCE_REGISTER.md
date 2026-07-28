# V2.3 P0 資料來源人工接受台帳

> 日期：2026-07-12
> 狀態：`engineering_readiness_only`；`mops.ezsearch.statement_publication` 已 limited 接受於內部 research PIT availability，其餘列仍為 `requires_human_acceptance`
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
| `mops.ezsearch.statement_publication` | MOPS F26–F29 季度財報表發布時間，供 research PIT availability mapping；M31 混合預告／通過語意，明確排除。 | `mops-ezsearch-statement-publication.v1`。 | 逐事件保存 `period`、`period_end` 與官方 `announcement_at`（Asia/Taipei，秒級）。 | JSON 保存官方 timestamp；date-only mapping 採次一曆日，避免同日盤中 look-ahead；不得由 period end 或 raw CSV 日期推定。 | 2026-07-27..28 live capture 36 events、36 unique projection keys、validator diagnostics 0。 | Owner 接受 public endpoint 唯讀、內部研究、不得再散布；不宣稱來源方額外授權。 | bounded 31-day query；任一 market/item 達 1000 rows 即 fail-closed 並要求縮小區間。 | 本次上市 12、上櫃 24；歷史完整 coverage 與多日 freshness 尚待累積。 | HTTP／JSON／required field／官方 URL／timestamp／period 任一失敗即不產生 artifact；來源空回傳保留 manifest。 | TEMP/shadow only；response hash、event hash、exact duplicate 計數；後續需累積 correction/revision evidence。 | `official_timestamp_artifact_verified` | `limited` | `archi` | `2026-07-27T21:19:18.3035865-07:00` | `research_pit_statement_availability`、`development_shadow_projection`；formal／production=`none` | [adapter](../../data_module/mops_ezsearch_statement_availability.py)；[CLI](../../scripts/fetch_mops_statement_availability.py)；decision `decision:mops.ezsearch.statement_publication:20260727-r1`；artifact SHA-256 `838A7507...DCD602E`；rollback：append disabled revision + revert DEV-66 commit |

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

## 5. 2026-07-26 P0-13 機器稽核與 Blocker 消除紀錄（GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1）

### 稽核與驗證摘要

- **任務 ID**：`GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1`
- **執行日期**：2026-07-26
- **完成狀態**：12 項具備 bounded official probe adapter；`pit.quarterly_financials` 僅具備已提供 MOPS artifact 的解析契約，尚未提供 artifact 時維持 missing。任何 `degraded`、probe 未回傳或缺官方公告時間的來源都仍保留 blocker，不得宣稱工程與機器類 blocker 為 0。
- **安全約束**：所有來源維持 `human_decision="requires_human_acceptance"`、`downstream_eligibility="none"`；`formal_oos_allowed=False`、`production_scheduler_allowed=False`。
- **Handoff JSON**：%TEMP%\technical_analysis_gemini_handoffs\GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1.json。

### 13 項 P0 來源機器驗證矩陣

| # | source_id | machine_status | adapter_status | pit_status | evidence_status | remaining_blocker | minimum_owner_question |
|---|---|---|---|---|---|---|---|
| 1 | `corporate_action.ex_dividend_timeline` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE TWT49U 的除權息時間軸資料作為內部量化研究與歷史回測備選源？ |
| 2 | `corporate_action.reduction_split_par_value` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE TWTAUU 的減資／分割／面額變更資料作為內部量化研究與歷史回測備選源？ |
| 3 | `microstructure.suspended_halt_resume` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE TWTAWU 的停牌／復牌時間資料作為交易限制 preflight 備選源？ |
| 4 | `microstructure.disposition_stock` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE 公告的處置股資料作為交易限制 preflight 備選源？ |
| 5 | `microstructure.periodic_call_auction` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE 處置公告分盤撮合措施作為交易限制 preflight 備選源？ |
| 6 | `microstructure.full_delivery` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE TWT85U 的變更交易全額交割資料作為交易限制 preflight 備選源？ |
| 7 | `microstructure.limit_lock` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE MI_INDEX 的漲跌停鎖死標示作為成交可行性 preflight 備選源？ |
| 8 | `institutional_flows` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE T86 的三大法人買賣超資料作為內部量化研究與歷史回測備選源？ |
| 9 | `credit_transactions` | `verified` | `candidate_adapter_ready` | `pit_date_verified` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE MI_MARGN 的信用交易（融資融券）金額與餘額資料作為內部量化研究與歷史回測備選源？ |
| 10 | `tdcc_shareholding` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TDCC 1-5 開放資料的集保持股分散級距資料作為內部量化研究與歷史回測備選源？ |
| 11 | `twse.monthly_revenue_announcement` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TWSE t187ap05_L OpenData 的上市月營收公告資料作為 PIT 營收比對備選源？ |
| 12 | `tpex.monthly_revenue_announcement` | `degraded` | `candidate_adapter_ready` | `official_publication_timestamp_missing` | `official_endpoint_probed` | `legal_and_license_acceptance_required` | 是否核准將來自 TPEx OpenData 的上櫃月營收公告資料作為 PIT 營收比對備選源？ |
| 13 | `pit.quarterly_financials` | `missing` | `candidate_artifact_not_supplied` | `unavailable` | `candidate_artifact_not_supplied` | `mops_candidate_artifact_not_supplied` | 尚未提供符合 provenance 契約的 MOPS 季報 Artifact；不得核准、不得推定 PIT 可用性。 |

## 6. 2026-07-27 P0-13 官方證據與就緒度強化紀錄（GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1）

### 稽核與驗證摘要

- **任務 ID**：`GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1`
- **執行日期**：2026-07-27
- **CLI 入口**：`scripts/run_p0_source_evidence_audit.py`
- **預設模式**：非連線模式（只產出未探測／既有 MOPS artifact 的現況）；Live 模式必須顯式帶入 `--live` 與 `--confirm-live-readonly`。
- **5 大群組化 Owner 決策包**：將 13 項 P0 來源收斂為 5 個聚焦於內部研究意圖/條款接受度的群組化決策問題，完全不要求 Owner 審視逐列 raw data：
  1. `twse_market_corporate`: 除權息與減資/分割/面額變更（2 項）
  2. `twse_microstructure`: 停復牌、處置股、分盤撮合、全額交割與漲跌停鎖死（5 項）
  3. `twse_flows_credit`: 三大法人買賣超與信用交易（2 項）
  4. `tdcc_distribution`: TDCC 集保持股分散級距（1 項）
  5. `mops_monthly_quarterly`: TWSE/TPEx 月營收公告與 MOPS 季度財報 Artifact（3 項）
- **安全約束**：所有來源維持 `human_decision="requires_human_acceptance"`、`downstream_eligibility="none"`；`formal_oos_allowed=False`、`production_scheduler_allowed=False`；所有 formal clock zeros 維持 0。
- **Handoff JSON**：%TEMP%\technical_analysis_gemini_handoffs\GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1.json。
- **Handoff 限制**：CLI 自動輸出的 `status=audit_generated_not_validation_handoff`；它不會自行宣稱 pytest、mypy 或 Git 終態已通過，這些只能由獨立審查流程填入。

## 7. 2026-07-27 MOPS 季報官方時間 limited 決議（DEV-66）

- **Owner 決議**：owner=`archi` 明確核准 `mops.ezsearch.statement_publication` 供內部 `research_pit_statement_availability` 與 `development_shadow_projection`；狀態=`limited`，不得再散布、正式 ingestion、Formal credit、Scoring、Advice、Portfolio、scheduler 或交易。
- **決議 ID**：`decision:mops.ezsearch.statement_publication:20260727-r1`；content hash `sha256:520aa2d2e56e497a658659816677e541b095c63689dcbb36f2a4a1a2b179f930`。
- **官方證據**：MOPS 公告快易查 `F26`–`F29`，capture range=`2026-07-27..2026-07-28`；36 events、36 unique event hashes、36 unique projection keys、invalid/future=`0`，artifact SHA-256 `838A7507655934646D5118E3111118679D15DC935E5FA1E4372F8F060DCD602E`。
- **validator**：date-only mapping SHA-256 `E621D19863BE40641EBDA7F9A6F83A5B78243D2CDA2D90E459D2EFA0DDBE838F`；accepted=`36`、diagnostics=`0`。官方延後公告採實際 timestamp，不再被 120 天推定窗口誤判；mapping 仍採次一曆日避免同日盤中 look-ahead。
- **解除 blocker**：`candidate_artifact_not_supplied`、`mops_candidate_artifact_not_supplied`、季報 blanket `official_publication_timestamp_missing`，以及 registry 對所有 `limited`／`accepted` 決議的一律拒絕。registry 現改為 evidence-gated applying state：缺 allowed use case、owner/reviewer、時區、license／quality／PIT evidence、rollback，或仍有 blocker 時一律拒絕。
- **仍保留**：歷史完整 coverage、correction/revision、多日 freshness/outage、正式 apply 與 Formal source lane。M31 不是財報發布證據，因其同時包含未來董事會預告與已通過財報。
- **rollback**：在 TEMP working-copy decision registry append `disabled` revision；程式／文件以 DEV-66 單一 commit revert。TEMP artifact 與 working-copy SQLite 不納入 Git。

## 8. 2026-07-28 富邦 shadow 與 Formal Rule-only lane 分流決議（DEV-67）

- **Owner 決議**：owner=`archi` 核准建立新的 Rule-only／candidate-source-exclusion observation lane；決議 ID=`decision:formal.rule_only_candidate_exclusion:20260728-r1`，content hash=`sha256:961f425ceae517fe6ba96363657ae4608d4a78f76792453c2c92e2c26ead602c`。
- **富邦用途**：`fubon.marketdata` 繼續依 `FubonShadowComputationAuthorization` 供 decision-time、historical-PIT 與 candidate Score／Recommendation／Portfolio／Exit shadow 計算；不得因此取得 Formal decision influence、Formal evidence credit、production blend、broker、training、promotion 或 scheduler 權限。
- **Formal lane whitelist**：僅 `daily_prices`、`industry_indices`、`market_indices`、`technical_indicators`；富邦與本台帳尚未正式接受的 P0 candidates 全數排除。`fubon_shadow_usable=true` 與 `fubon_formal_credit_allowed=false` 必須同時呈現，避免把「可做 shadow」誤讀成「可取得 Formal credit」。
- **forward binding**：在 append 前重新檢查 registry，確認交易時段未使用後，綁定 `holdout_id=formal-rule-only-20260729-r1` 至 `2026-07-29`。既有 2026-07-21 snapshot 不回填、不重算、不追認。
- **目前 blocker**：只剩 2026-07-29 真正 decision-time 的 Rule-only `manual_observed` artifact；這是等待真實時間，不是未完成的 owner 人工審核。snapshot count、outcome revision、matured denominator、Formal credit 與 consumption increment 在本次均為 0。
- **rollback**：append 一筆引用本決議的 `formal-observation-lane-disabled.v1`，不得刪除或改寫既有 decision／binding；程式與文件以 DEV-67 單一 commit revert。TEMP artifact 不納入 Git。
