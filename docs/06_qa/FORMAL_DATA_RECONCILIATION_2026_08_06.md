# Formal Data Reconciliation — 2026-08-06

## 結論

正式 SQLite `D:/Min/Python/Project/FA_Data/sqlite/twstock.db` 已完成本輪安全對帳；`PRAGMA quick_check=ok`。在不偽造 PIT、來源驗收或 provenance 的前提下，可直接寫入正式 DB 的剩餘資料為 **0 records**。

這不是「沒有檔案」，而是可接受資料已對齊，剩餘候選缺少正式層必需的 available date／來源驗收／identity 保障，或屬 research／derived artifact。

## 已安全完成的補齊

本輪先前已建立 backup 並寫入可驗證、可回滾的差異：

| 資料集 | 已補入 records | Backup |
|---|---:|---|
| `daily_prices` | 1,310 | `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_existing_data_sync_20260806_170452.db` |
| `broker_flows` | 19,416 | `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_existing_data_sync_20260806_170452.db` |
| `fundamental_valuation_metrics` | 840 | `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_valuation_metrics_backfill_20260806_170559.db` |

寫入後 DB quick check、key duplicate 檢查與 source equivalence 皆通過。

## 逐來源安全對帳

| 資料面 | 對帳結果 | 正式寫入決策 | 原因／後續 |
|---|---|---|---|
| 日價 `daily_prices` | 所有有效交易日 raw 與 DB 對齊。 | 0 | 9 份週六 raw（8,222 rows）無官方交易證據；10 份 2024 malformed test CSV 均保留但不可導入。 |
| 技術指標 | 2,143 份 source 檔與 DB exact aligned。 | 0 | 已同步；不做重算／覆寫。 |
| Market Index | `market_index.csv=3,055`，DB `3,055`，values exact。 | 0 | 已同步。 |
| Industry Index | `209,575` rows exact aligned。 | 0 | 已同步。 |
| Broker Flows | normalized source unique `862,476`；DB `862,859`；logical source-only `0`、DB-only `383`。 | 0 | 差異含 display name／leading-zero ETF identity；既有 sync 是 date delete-and-reinsert，可能刪掉 DB-only rows。須先改為 provenance-preserving only-upsert。 |
| 估值 | 2026-08-06 source 1,094；policy 接受 840，且 840 與 DB exact。 | 0 | 其餘為 nonpositive P/E 或缺 industry mapping 的 diagnostics，不能強塞。 |
| 月營收 | 2026-06 的 1,832 rows 已在 DB，且 mapping 唯讀驗證 `accepted_count=1,832`；historical raw 175,234 缺可信 `available_date`。 | 0 | 新 mapping 必須是 `formal-availability.v2`；現存 2026-05 的 1,848 first-seen rows 不刪除，但 live gate 已隔離，不能進正式推薦／因子。 |
| 財報 | 正式表現有 1,645,555 rows，但沒有 formal availability mapping。 | 0 | 新 mapping 必須有 official announcement、SHA-256 source hash 與 revision lineage；現況只能 degraded／retroactive baseline，不能升為 PIT-safe historical feature。 |
| 三大法人／信用／TDCC | 正式 acceptance 仍為 0。 | 0 | 各候選要完成 source acceptance、license、coverage、PIT mapping。 |
| ML／release／backup／mirror artifacts | 不屬 raw formal source。 | 0 | 永久保持隔離，不得反向導入市場 DB。 |

## 禁止的捷徑

- 不可執行會清空表的 `migrate_csv_to_sqlite.py` 作為補值方式。
- 不可對 broker 執行未改造的 full `sync_source_to_sqlite("broker_branch_files")`，因其 replace-by-date 語意可能刪除 DB-only records。
- 不可將 weekend raw、test CSV、release output、model artifact、derived research 或 backup 當正式市場來源。
- 不可由 current `companies.csv`、raw report date 或回填日推定歷史 `available_date`。

## 下一個可導向正式資料的工作

1. 為月營收、財報與 P0 候選建立可驗證的 `formal-availability.v2` announcement／available-date／SHA-256／revision mapping。
2. 為 broker 建立 normalized identity + provenance 的 only-upsert sync，再對 383 DB-only records 作證據比對。
3. 對每個外部來源完成 license、publication time、coverage、outage/retry 與 acceptance registry。
4. 只有在上述條件與 dry-run／backup／apply evidence 齊備後，才做下一次正式 DB 寫入。

資料狀態 manifest 本身已有 stale 風險，不能取代本文件的 source-level 對帳；下次更新時必須依已驗證方法重建或修正它。
