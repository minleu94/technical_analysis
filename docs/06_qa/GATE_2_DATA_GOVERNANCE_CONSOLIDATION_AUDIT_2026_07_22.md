# Gate 2 Data Governance & P0 Source Baseline Audit Report

*Audited at: 2026-07-21T23:05:19.888177*

> [!IMPORTANT]
> 本報告為唯讀工程稽核，記錄目前 SQLite 數據、P0 資料源治理、PIT 安全與 Gate 狀態。
> **本報告不構成正式 Gate 2 人工 Credit 核准或 Production Enablement。**

## 1. 資料庫基礎設施與資料表統計
- **SQLite 路徑**: `D:\Min\Python\Project\FA_Data\sqlite\twstock.db`
- **檔案存在狀態**: `True`
- **檔案大小**: 3155.63 MB

### 資料表細節:
- **`daily_prices`**:
  - `total_records`: 5236043
  - `unique_stocks`: 2199
  - `min_date`: 20140102
  - `max_date`: 20260721
- **`market_indices`**:
  - `total_records`: 3043
  - `unique_indices`: 0
  - `min_date`: 20140102
  - `max_date`: 20260721
  - `columns`: ['日期', '指數名稱', '收盤指數', '漲跌', '漲跌點數', '漲跌百分比', '開盤價', '最高價', '最低價', '收盤價', '成交量']
  - `null_name_count`: 3043
  - `status`: degraded

## 2. 資料品質異常檢測 (Daily Prices Anomalies)
- **`null_stock_code_count`**: 6
- **`blank_stock_code_count`**: 0
- **`suspicious_weekend_count`**: 8226
- **`duplicate_pk_count`**: 3
- **`invalid_price_range_count`**: 0
- **`suspicious_weekend_dates_sample`**: ['20141227', '20160130', '20160604', '20160910', '20170218', '20170603', '20170930', '20180331', '20181222', '20240106']

## 3. 基本面與估值 PIT 治理狀態
- **`fundamental_monthly_revenues`**: DEGRADED_ANNOUNCED_DATE_PROVENANCE_MISSING (Rows: 246331)
- **`fundamental_statement_items`**: DEGRADED_ANNOUNCED_DATE_PROVENANCE_MISSING (Rows: 1645555)
- **`valuation`**: RESEARCH_SIDECAR_ONLY_0_FORMAL_ROWS (Rows: 0)

## 4. 13 個 P0 資料源接受與權限狀態
| 資料源 ID | 顯示名稱 | 審查狀態 | 下游資格 | 作用中 Blockers 數 |
| :--- | :--- | :--- | :--- | :--- |
| `corporate_action.ex_dividend_timeline` | corporate_action.ex_dividend_timeline | `deferred` | `none` | 9 |
| `corporate_action.reduction_split_par_value` | corporate_action.reduction_split_par_value | `deferred` | `none` | 9 |
| `microstructure.suspended_halt_resume` | microstructure.suspended_halt_resume | `deferred` | `none` | 9 |
| `microstructure.disposition_stock` | microstructure.disposition_stock | `deferred` | `none` | 9 |
| `microstructure.periodic_call_auction` | microstructure.periodic_call_auction | `deferred` | `none` | 9 |
| `microstructure.full_delivery` | microstructure.full_delivery | `deferred` | `none` | 9 |
| `microstructure.limit_lock` | microstructure.limit_lock | `deferred` | `none` | 9 |
| `institutional_flows` | institutional_flows | `deferred` | `none` | 9 |
| `credit_transactions` | credit_transactions | `deferred` | `none` | 9 |
| `tdcc_shareholding` | tdcc_shareholding | `deferred` | `none` | 9 |
| `twse.monthly_revenue_announcement` | twse.monthly_revenue_announcement | `deferred` | `none` | 9 |
| `tpex.monthly_revenue_announcement` | tpex.monthly_revenue_announcement | `deferred` | `none` | 9 |
| `pit.quarterly_financials` | pit.quarterly_financials | `deferred` | `none` | 9 |

## 5. Gate 工程完成度與 Blockers 矩陣
### Gate_2_Evidence_Accumulation
- **`engineering_status`**: CONSOLIDATED_COMPLETE
- **`formal_credit_status`**: 0/3_WAITING_FOR_HUMAN_AUTHORITY
- **`external_approved_projection`**: 2/3_PROJECTED
- **`pending_human_review_count`**: 1
- **`production_scheduler_allowed`**: False
- **`blockers`**: ['requires_explicit_human_authority_credit_signature', 'requires_real_calendar_week_accumulation']
### Gate_3_Data_Credibility
- **`engineering_status`**: CONTRACTS_ENG_COMPLETE
- **`formal_source_acceptance`**: 0_ACCEPTED_13_DEFERRED
- **`blockers`**: ['human_license_and_quality_attestation_required_for_all_13_p0_sources']
### Gate_4_Portfolio_Coach
- **`engineering_status`**: PAPER_SANDBOX_READY
- **`real_trading_allowed`**: False
- **`blockers`**: ['paper_basis_only', 'no_broker_integration']
