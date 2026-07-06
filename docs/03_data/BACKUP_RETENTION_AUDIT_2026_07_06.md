# Backup Retention Audit 2026-07-06

> 本文件記錄 2026-07-06 對 repo 與 `D:/Min/Python/Project/FA_Data` 備份檔的盤點結果。初次盤點沒有刪除任何正式資料或既有備份；同日後續依使用者明確指示，已清理 repo / Temp 內可重建的 working-copy 與 QA raw output，正式 `FA_Data/sqlite/twstock.db` 未被修改。

## 結論

- 真正造成硬碟快速膨脹的來源，是部分 migration / backfill / repair workflow 直接用 `shutil.copy2()` 複製大型 SQLite DB 或大型 CSV，未套用既有 `TWStockConfig.create_backup()` 的保留策略。
- 既有 `TWStockConfig.create_backup()` 已有 retention：同一來源同一天只保留最新一份，最多保留最新 5 個日期版本。
- 2026-07-06 已新增 `data_module.backup_retention.create_retained_backup()`，並把正式 backfill / migration / registry / 大型 merge / 手動修復入口接到相同 retention 規則。
- `TWStockConfig.create_backup()` 的 cleanup prefix 已收窄：一般 `twstock_YYYYMMDD_HHMMSS.db` 不會清掉 `twstock_fundamental_schema_YYYYMMDD_HHMMSS.db` 或其他帶 label 的 DB 備份。
- 既有歷史備份不會被本次程式變更自動刪除；只有下一次產生同 prefix 新備份時，才會清理該 prefix 的舊版本。
- `_reference_fix` historical replay 仍有 V2.0 evidence quality 參考價值，已移到 `D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/`；Workbench 只應讀取其中 JSON summary，不直接讀 replay DB。
- 已完成 closeout 且可重建的 repo `tmp/pre_v2_source_gap_smoke/`、`tmp/evidence_ops_continue_20260703/`、`output/qa/statement_items_backfill/` 與 6/30 Temp clone 已刪除。

## Retention 規則

受控備份目錄主要是 `DATA_ROOT/meta_data/backup/`。

| 規則 | 行為 |
|---|---|
| 同一天多份同 prefix 備份 | 只保留該日期最新一份 |
| 同 prefix 跨日期備份 | 只保留最新 5 個日期 |
| 不同 prefix 備份 | 不互相清理 |
| 正式資料檔 | 不會被 retention 刪除 |
| 既有歷史大備份 | 不會自動清掉，需人工確認清理 |

Prefix 例子：

- `stock_data_whole_20260706_150000.csv` 屬於 `stock_data_whole`
- `twstock_statement_items_backfill_20260706_150000.db` 屬於 `twstock_statement_items_backfill`
- `twstock_fundamental_schema_20260706_150000.db` 屬於 `twstock_fundamental_schema`

## 已納入 retention 的來源

| 來源 | 典型備份檔 | 產生情境 |
|---|---|---|
| `data_module/config.py::TWStockConfig.create_backup()` | `market_index_*.csv`、`industry_index_*.csv`、`all_stocks_data_*.csv`、`twstock_*.db` | 日常資料更新、技術指標、broker flow schema migration |
| `data_module/fundamental_migration.py` | `twstock_fundamental_schema_*.db` | Fundamental schema 正式 migration |
| `data_module/monthly_revenue_backfill.py` | `twstock_monthly_revenue_backfill_*.db`、`twstock_mops_monthly_revenue_backfill_*.db` | 月營收正式回填 |
| `data_module/fundamental_statement_backfill.py` | `twstock_statement_items_backfill_*.db` | 季度財報 item 正式回填 |
| `data_module/valuation_metrics_backfill.py` | `twstock_valuation_metrics_backfill_*.db` | 估值 metrics 正式回填 |
| `data_module/tpex_daily_price_backfill.py` | `twstock_tpex_daily_price_backfill_*.db` | TPEX daily price 正式補回 |
| `data_module/evidence_event_migration.py` | `twstock_evidence_event_schema_*.db` | Evidence event schema 正式 migration |
| `scripts/update_company_registry.py` | `companies_company_registry_*.csv` | 官方公司 registry 正式更新 |
| `scripts/merge_daily_data.py` | `stock_data_whole_*.csv` | 大型 daily price 合併 |
| `scripts/fix_industry_index.py` | `industry_index_*.csv` | 手動修復產業指數 |
| `scripts/fix_market_index.py` | `market_index_*.csv`、`market_index_before_save_*.csv` | 手動修復大盤指數 |

## 不屬於自動 retention 的複製產物

以下不是一般備份輪替，而是工作副本、QA 產物或固定覆蓋型備份；應透過 output / QA 清理政策或個別人工確認處理。

| 來源 | 行為 | 清理判斷 |
|---|---|---|
| `generate_*_copy_dry_run_report()` | 把 source DB 複製到使用者指定 working copy | 屬於顯式 working copy；確認不再需要後可清理 |
| `app_module/historical_evidence_replay.py` | 建立 replay DB | 屬研究產物；不應放在正式資料根目錄長期堆積 |
| `scripts/smoke_evidence_pipeline_working_copy.py` | 建立 working-copy DB smoke | 屬 QA 產物；應放 ignored output / QA 位置 |
| `app_module/watchlist_service.py` | 損壞 watchlist 改名成固定 `.json.bak` | 固定覆蓋，通常不會爆量 |

## 2026-07-06 掃描摘要

嚴格掃描條件：只統計 backup / backups 目錄、`.bak` / `.backup` / `.orig`、或檔名含 `backup` / `before` / `restore` / `old` / `copy` / `snapshot` / `checkpoint` 的檔案；排除 `.git`、`.venv`、cache、`__pycache__`、`node_modules`。

| 位置 | 檔案數 | 約略大小 | 判斷 |
|---|---:|---:|---|
| `D:/Min/Python/Project/FA_Data/meta_data/backup` | 3351 | 24.25 GB | 主要堆積來源，含大型 DB 與大型 CSV 歷史備份 |
| `D:/Min/Python/Project/FA_Data/backup` | 7 | 4.16 GB | 多為一次性修復 / cleanup 備份目錄 |
| `D:/Min/Python/Project/FA_Data/sqlite/backups` | 1 | 3.16 GB | SQLite 一次性 branch / schema 前備份 |
| repo `output/qa/statement_items_backfill/backup` | 1 | 1.42 GB | QA raw output，不應提交；確認不需要後可清理 |

最大型檔案範例：

- `D:/Min/Python/Project/FA_Data/sqlite/twstock_before_drop_mojibake_col_20260617_235005.db`，約 3.23 GB；健康檢查文件曾記錄為 mojibake 欄位清理前備份。
- `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_20260520_daily_price_repair_20260624_152726.db`，約 3.16 GB；一次性 daily price repair 備份。
- `D:/Min/Python/Project/FA_Data/backup/industry_index_cleanup_20260624_015508/twstock.db.bak`，約 3.16 GB；一次性 industry index cleanup 備份。
- `D:/Min/Python/Project/FA_Data/sqlite/backups/twstock_before_8_branch_add_20260706_150817.db`，約 3.16 GB；branch / schema 前備份。

## 既有大檔清理與處置

初次盤點沒有刪除檔案；2026-07-06 後續依使用者明確授權完成以下清理與移動：

| 原位置 | 處置 | 理由 / 回滾方式 |
|---|---|---|
| `tmp/historical_replay/evidence_replay_2026-01-06_2026-07-06_reference_fix.db*` | 移到 `D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/` | 可保留作研究層 event / outcome 深入分析；如需回滾，可搬回原 `tmp/historical_replay/` |
| `output/evidence_pipeline/historical_replay_2026-01-06_2026-07-06_reference_fix.{json,md,log}` | 移到同一個 D 槽 archive | V2.0 Workbench 只讀 JSON summary；文件與 CLI 範例已改指向 archive |
| `tmp/pre_v2_source_gap_smoke/` | 刪除 | 已完成 Pre-V2 closeout；正式 DB 未寫入。需要時可依 QA 文件命令從 formal DB 重建 working copy |
| `tmp/evidence_ops_continue_20260703/` | 刪除 | 已被後續 Pre-V2 all-source closeout 取代；需要時可依 2026-07-03 QA 文件重跑 |
| `output/qa/statement_items_backfill/` | 刪除 | 正式 `fundamental_statement_items` 已在 `D:/Min/Python/Project/FA_Data/sqlite/twstock.db`；repo 內只是 QA raw DB / backup |
| `C:/Users/archi/AppData/Local/Temp/technical_analysis_v1_main_20260630_164819`、`...164434` | 刪除 | 6/30 clean-clone / inspect 暫存 clone；需要時重新跑 clean-clone 驗證 |

尚未處理的既有大型備份仍需個別確認，不得因本次 cleanup 而自動刪除：

| 候選 | 建議 |
|---|---|
| `D:/Min/Python/Project/FA_Data/meta_data/backup/technical_restore_*` | 若對應修復已驗證且不再需要 rollback，可移到外部冷 archive 或刪除 |
| `D:/Min/Python/Project/FA_Data/backup/industry_index_cleanup_*` | 若 cleanup 已驗證完成，可移到外部冷 archive 或刪除 |
| `D:/Min/Python/Project/FA_Data/sqlite/backups/twstock_before_8_branch_add_*.db` | 若 branch/schema 已合併且當前 DB healthcheck 通過，可刪或移出資料根 |
| repo `output/qa/**/backup` | 屬 raw QA output，確認不需重跑證據後可清理；不應 stage。本次已清理 `output/qa/statement_items_backfill/` |
| `meta_data/backup/*_backfill_*.db` | 至少保留最近一次可 rollback 版本；較舊版本需依對應 migration/backfill closeout 確認 |

## 後續原則

- 新增任何正式 DB / CSV 備份入口時，優先使用 `TWStockConfig.create_backup()` 或 `create_retained_backup()`。
- 直接 `shutil.copy2()` 只能用於 restore、working copy、使用者顯式指定的 QA/replay DB，不應用來產生無限累積的正式備份。
- 大型 replay / smoke / QA DB 應放在 ignored output 位置或 `OUTPUT_ROOT/evidence_pipeline/<research_archive>/`，不要放在 `DATA_ROOT/meta_data/backup/` 或 repo C 槽長期堆積。
- 清理歷史備份前必須先列出來源、大小、風險、回滾方式與目標路徑，並取得明確確認。

## 更新記錄

- 2026-07-06：建立備份盤點與 retention 規則文件，記錄既有大檔來源、已納入 retention 的程式入口與需人工確認的清理候選。
- 2026-07-06：依使用者明確指示執行 C 槽 cleanup；移動 `_reference_fix` replay artifact 至 `D:/Min/Python/Project/FA_Data/output/evidence_pipeline/historical_replay_reference_fix_20260706/`，並刪除已文件化且可重建的 repo working-copy / QA raw output 與 6/30 Temp clone。
