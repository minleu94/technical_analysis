# PIT Historical Data Repair Closeout（2026-07-15）

## 1. 結論

E2 已完成 PIT contract、月營收／季度財報 mapping、corporate timeline、`p0-ml-eligibility.v1` 與正式 DB 唯讀 coverage audit tooling。工程 tooling 可重跑，但實際歷史 coverage 尚未完成，來源 acceptance 與 production apply 全部保持 pending／deferred。

本 closeout 是 `engineering_complete_with_coverage_deferred`，不是資料修復正式上線、source accepted、ML promotion 或 formal OOS 核准。

## 2. 已完成工程能力

- Backfill date、available-before-announcement、revision no-overwrite、event／announcement／effective distinction、coverage-unknown label blocker contracts。
- 月營收 official／observed-only／unmatched mapping與 as-of revision visibility。
- 季度財報 statement type／scope／revision natural key與 explicit staging CLI。
- Corporate-action／restriction append-only timeline；restriction release 是新事件。
- Strict／research `p0-ml-eligibility.v1`，deterministic hash且不含 machine path。
- 正式 SQLite `mode=ro` source/year/family coverage audit；missing DB fail closed。

既有 E2 commits：

- `9b1d7711c93b894e77e4a4d4485f68669622485c`：PIT contracts。
- `81c414d0f01ccdd677ce5e71127edb75a1264314`：月營收／季度財報 mapping。
- `32660f61843457defe011603d662835dbdbbd7bd`：corporate timeline／ML eligibility。

本 closeout slice 尚待 Git Coordinator commit／push。

## 3. 正式 DB 唯讀 audit 證據

執行日期：2026-07-13。Audit cutoff：`2024-12-31`。

- DB：`D:\Min\Python\Project\FA_Data\sqlite\twstock.db`
- SHA-256：`604e8fc5c046e40faeddd5a6e183d088f6bd90d0e462d2c8e4e96101c0b6d8b4`
- Size：`3,308,916,736` bytes
- mtime UTC：`2026-07-13T12:15:33.2603820Z`
- Audit 前後 hash／size／mtime：一致
- Open mode：read-only
- Raw report：位於 ignored TEMP，未納入 repository

### 3.1 Family totals

| Family | Count unit | Total | Official | Observed-only | Unmatched | Future-blocked | Revision | Eligible | Status／blocker |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 月營收 | database rows | 244,499 | 0 | 1,848 | 242,651 | 244,499 | 0 | 0 | audited；`revision_column_missing` |
| 季度財報 | statement item rows | 1,645,555 | 0 | 0 | 1,645,555 | 1,645,555 | 0 | 0 | audited；`revision_column_missing` |
| Corporate action | event rows | 0 | 0 | 0 | 0 | 0 | 0 | 0 | `coverage_deferred`；table missing／coverage unknown |

判讀限制：

- `official=0` 表示正式表沒有 explicit `quality=official`，不能推論來源不是官方，也不能自行提升為 official。
- 正式表 `quality=observed` 只計為 observed-only；`degraded` 計為 unmatched PIT evidence。
- `future-blocked` 以 `available_date > 2024-12-31` 判定。現有基本面 backfill dates 皆晚於 cutoff，因此 eligible 為 0。
- 季度財報 count unit 是 statement item rows，不是 filing natural keys；需建立 canonical quarterly mapping 後才能稽核 filing coverage。
- `revision=0` 搭配缺欄 blocker，不能解讀為已證明沒有 revision。
- Corporate table 缺失時 0 rows 不是 clean label coverage。

### 3.2 Source-level 摘要

- 月營收：`mops.monthly_revenue_static_snapshot`。2014–2025 rows 均為 degraded／future-blocked；2026 有 1,848 observed-only rows，但對 2024 cutoff 仍 future-blocked。
- 季度財報：`financial_data.balance_sheet_csv`、`financial_data.cash_flows_statement_csv`、`financial_data.income_statement_csv`；全部為 degraded／future-blocked statement items。
- Corporate action：無正式 source table，coverage unknown。

完整逐 source／year counts 由 `scripts/audit_pit_historical_coverage.py` 重跑取得，不在 closeout 複製大量 raw rows。

## 4. Source acceptance 狀態

| Source family | 當前狀態 | 缺少證據／completion rule |
|---|---|---|
| MOPS 月營收 historical publication | deferred | 逐期 publication provenance、source version/hash、revision coverage與 license decision |
| Historical first-observed archive | deferred | 可重跑 archive provenance、coverage threshold與 unmatched review |
| 季度財報 official publication | deferred | filing natural key、個別／合併 scope、revision chain與逐年 coverage |
| Corporate-action／restriction | deferred | 正式 source ingestion、coverage window、release events、license與完整性門檻 |

本任務沒有寫入 accepted／limited／rejected 決策；`source_acceptance_changed=false`。

## 5. Verification

Coverage audit slice：

- TDD RED：3 個缺失 contract／CLI failures，加上 1 個大型 DB fingerprint streaming regression。
- Focused GREEN：`tests/test_pit_historical_coverage_audit.py` 4 passed。
- 正式 DB audit：exit 0，DB hash／size／mtime unchanged。
- E2 focused suite：12 paths，70 passed in 2.36s。

E2 全部 focused availability／corporate／eligibility tests、`py_compile`、targeted mypy與 owned diff check 由本 slice 收尾驗證；repo-wide pytest、完整 mypy、quant guard與全量 suite 交由 Git Coordinator heavy-QA queue。

## 6. 未完成與 blockers

- 歷史 official／observed-only coverage 未達 accepted 門檻。
- 正式基本面 tables 沒有 revision 欄位與 canonical mapping hash。
- 正式 corporate-action／restriction coverage table 不存在。
- `p0-ml-eligibility.v1` tooling 已完成，但目前 formal audit 對 2024 cutoff 的基本面 eligible 為 0。
- Production apply 未執行；`production_apply_performed=false`。
- B frozen dataset 完全未修改；未來新 dataset version 必須顯式選擇是否消費 eligibility artifact。

## 7. Closeout 狀態

- Engineering tooling：完成。
- Actual historical coverage：deferred／incomplete。
- Source acceptance：pending，無 accepted source。
- Production apply：未執行。
- External／formal Gates：未變更。
