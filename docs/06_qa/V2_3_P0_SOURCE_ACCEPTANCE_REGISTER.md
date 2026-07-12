# V2.3 P0 資料來源人工接受台帳

> 日期：2026-07-12
> 狀態：`engineering_readiness_only`；所有列均為 `requires_human_acceptance`
> 適用 Gate：Gate 3 / V2.3 P0 Data Credibility
> 權威邊界：本台帳記錄待決的人工作業；不得將任何列解讀為正式 ingestion、`ScoringEngine` feature、排程核准、投資有效性或交易資格。

## 1. 使用規則

1. 本台帳覆蓋 `ROADMAP_6M_ENGINEERING.md` Gate 3 的 P0 範圍：corporate action、交易限制、三大法人、信用交易、TDCC / 集保持股分散，以及 PIT 月營收 / 季度財報公告日。
2. `candidate status` 是目前工程或資料治理狀態，不是接受結論；`decision_ready_candidate` 也不等於 accepted。
3. 在具名人工決策人、日期、授權 / 使用範圍、品質證據與 PIT 審核均完成前，`human decision` 固定為 `requires_human_acceptance`，`downstream eligibility` 固定為 `none`。
4. 資料缺失、來源中斷、過期、缺 `available_date` 或 `available_date > decision_date` 時，依列示 policy fail-closed 或保留降級診斷；不得補值、不得把 stale 偽裝為 observed。
5. 即使將來人工決定 `limited`，也必須另行記錄可用欄位、使用情境、版本、review date、rollback 指向與允許的 downstream；本文件不預先授權該行為。

## 2. P0 source-by-source 決策表

| source id | 用途 | available-date | quality | license | missing / outage policy | candidate status | human decision | owner / date | downstream eligibility |
|---|---|---|---|---|---|---|---|---|---|
| `corporate_action.ex_dividend_timeline` | 除權息、減資、分割與面額變更的 decision-time 事件時間軸候選。 | 必須保存公告 / 生效與 `available_date`；僅 `available_date <= decision_date` 可供後續審核。 | `partial`；尚未 ingestion，且 adjusted-price policy 仍是 candidate-only。 | local governed use；擴充 ingestion 前須人工確認來源條款與再散布限制。 | `fail_closed_for_adjusted_decision_features`；缺資料不得使用 adjusted decision feature。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none`（僅 policy / diagnostics） |
| `microstructure.disposition_stock` | 處置股交易限制 preflight 候選。 | 必須保存限制生效日與 `available_date`，並在決策日可得。 | `partial`；未正式 ingestion。 | local governed use；須人工確認官方來源條款。 | `degrade_preflight_and_warn`；缺失時明示風險，不得視為 unrestricted。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none`（僅 diagnostics） |
| `microstructure.periodic_call_auction` | 分盤交易限制 preflight 候選。 | 必須保存生效日與 `available_date <= decision_date`。 | `partial`；未正式 ingestion。 | local governed use；須人工確認官方來源條款。 | `degrade_preflight_and_warn`；缺失時明示風險。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none`（僅 diagnostics） |
| `microstructure.full_delivery` | 全額交割限制 preflight 候選。 | 必須保存生效日與 `available_date <= decision_date`。 | `partial`；未正式 ingestion。 | local governed use；須人工確認官方來源條款。 | `degrade_preflight_and_warn`；缺失時明示風險。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none`（僅 diagnostics） |
| `microstructure.limit_lock` | 漲跌停鎖死與成交可行性 preflight 候選。 | 必須由決策當下可得的同日價格 / 成交量證據推導。 | `partial`；未正式 ingestion。 | local governed use；須人工確認原始市場資料條款。 | `degrade_preflight_and_warn`；未知時不得假設可成交。 | `registry_partial_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none`（僅 diagnostics） |
| `institutional_flows` | 三大法人買 / 賣 / 淨買賣的 source candidate。 | 每列必須 explicit `available_date`，且不晚於 `decision_date`。 | 僅 candidate dry-run；只有 `observed` / `governed` / `verified` 列可通過 quality 診斷，仍非人工接受。 | 官方 / 供應者條款、使用範圍與 rate limit 尚待人工審核。 | 缺 DB / table / required field / `available_date` 或 future data 只回 diagnostics，fail-closed。 | `decision_ready_candidate_possible` | `requires_human_acceptance` | 未指定 / 未填 | `none`（不進 score、Advice、Portfolio 或 scheduler） |
| `credit_transactions` | 融資買進、融資餘額、融券賣出、融券餘額的 source candidate。 | 每列必須 explicit `available_date`，且不晚於 `decision_date`。 | 僅 candidate dry-run；`financing` / `securities_lending` 為 optional，缺值不得補。 | 官方 / 供應者條款、使用範圍與 rate limit 尚待人工審核。 | 缺 DB / table / required field / `available_date` 或 future data 只回 diagnostics，fail-closed。 | `decision_ready_candidate_possible` | `requires_human_acceptance` | 未指定 / 未填 | `none`（不進 score、Advice、Portfolio 或 scheduler） |
| `tdcc_shareholding` | TDCC / 集保持股分散、持股級距、大戶 / 散戶比例候選。 | 週資料與公告延遲資料皆須 explicit `available_date <= decision_date`。 | 僅 candidate dry-run；未有任一候選 payload 時為 `source_not_ingested`。 | TDCC / 供應者條款、使用範圍與 rate limit 尚待人工審核。 | 缺 DB / table / candidate payload / `available_date` 或 future data 只回 diagnostics，fail-closed。 | `decision_ready_candidate_possible` | `requires_human_acceptance` | 未指定 / 未填 | `none`（不進 score、Advice、Portfolio 或 scheduler） |
| `twse.monthly_revenue_announcement` | PIT 月營收公告日 mapping 候選。 | 僅採有效公告日 / mapping 的 explicit `available_date`；raw 月營收 CSV 不可推定可得日。 | candidate mapping；需保留 source version 並通過公告日合理性審核。 | 官方 OpenAPI / 文件條款與使用範圍尚待人工審核。 | 缺 mapping、公告日、source version 或超過合理公告窗口時回 diagnostics，不產生 normalized record。 | `pit_mapping_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none`（既有 guarded research path 不因本台帳而升級） |
| `tpex.monthly_revenue_announcement` | OTC PIT 月營收公告日 mapping 候選。 | 僅採有效公告日 / mapping 的 explicit `available_date`；raw 月營收 CSV 不可推定可得日。 | candidate mapping；需保留 source version 並通過公告日合理性審核。 | 官方 OpenAPI / 文件條款與使用範圍尚待人工審核。 | 缺 mapping、公告日、source version 或超過合理公告窗口時回 diagnostics，不產生 normalized record。 | `pit_mapping_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none`（既有 guarded research path 不因本台帳而升級） |
| `unregistered.pit_quarterly_financials` | PIT 季度財報公告日與 statement items 的待登錄 P0 source。此為台帳識別字，非已存在 adapter。 | 來源、公告日語意與 `available_date` contract 尚未選定；不得由 period end 或 raw 檔日期推定。 | `missing`；尚無可接受的 source manifest / PIT evidence。 | 未指定；必須先完成供應者、用途與授權審核。 | `fail_closed`；沒有受治理 source 時不產生正式 decision-time feature。 | `unregistered_candidate` | `requires_human_acceptance` | 未指定 / 未填 | `none` |

## 3. 人工接受前檢核

每一列在填入 `accepted`、`limited`、`rejected` 或 `deferred` 之前，人工決策人必須逐項確認：

- source manifest、版本、授權 / rate limit 與使用範圍；
- `as_of_date`、`available_date`、時區與修訂 / backfill 語意；
- coverage、freshness、schema、quality、missing / outage、quarantine 與 retry 證據；
- look-ahead 自查：所有可下游使用的列均符合 `available_date <= decision_date`；
- 對應的 shadow / diagnostics / Evidence Review 證據、受限使用情境與 rollback 指向；
- 決策人姓名、決策日期、結論與明確 downstream eligibility。

在這些欄位全數完成前，任何 `decision_ready_candidate` 僅表示該次列資料通過候選診斷，不能改寫為 accepted feature。
