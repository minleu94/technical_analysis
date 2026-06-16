# Month 5 Fundamental Source Inventory

> **最後更新**：2026-06-16  
> **範圍**：Month 5 Fundamental Layer preflight 的資料來源盤點。本文只描述資料來源與可用性，不宣告任何基本面因子已可用於推薦、回測或 Daily Decision Desk。

## 1. 結論

目前正式系統尚未建立可直接決策使用的 Fundamental Layer。

正式 SQLite 主庫 `twstock.db` 目前包含原有核心表與 Month 5 fundamental schema：

- `daily_prices`
- `technical_indicators`
- `broker_flows`
- `market_indices`
- `industry_indices`
- `fundamental_monthly_revenues`
- `fundamental_statement_items`
- `fundamental_valuation_metrics`

正式 SQLite 已具備基本面專用 schema；月營收與財報仍未正式回填，P/E 估值 metrics 已在 2026-06-16 依使用者確認受控寫入 `fundamental_valuation_metrics`。同日另建立 TPEX daily price backfill workflow，修正 `3207` 這類上櫃股票存在於公司 registry 但缺 `daily_prices` 的市場日價管線缺口；此 workflow 只寫 `daily_prices`，不寫 fundamental tables。`DATA_ROOT/financial_data/` 內存在舊 CSV 原始資料，但缺少公告日與 `available_date`，因此只能列為 raw candidate source，不得直接用於回測、推薦、策略分數或 Daily Decision Desk。

Month 5 下一步必須先完成 available-date contract 與 no-look-ahead tests，再將 fundamental 資料升級為正式可用來源。2026-06-16 已建立 `data_module/fundamental_data.py` 作為唯讀正規化契約：raw 月營收 row 必須搭配外部 `available_date` mapping 才會產生 normalized record；缺 mapping 時只輸出 diagnostics。同日亦建立 `data_module/fundamental_availability_sources.py` 作為受治理的公告日 / `available_date` mapping 契約，允許人工或後續下載來源提供 `announced_date`、`available_date`、`source` 與 `source_version`，但明確拒絕把 raw 月營收 CSV 自身當成可得日來源。`data_module/fundamental_availability_entrypoint.py` 與 `scripts/validate_monthly_revenue_availability.py` 已建立正式驗證入口，可對使用者提供的 mapping 檔執行 dry-run 驗證、列出 diagnostics、拒絕未治理來源，且不建立、不改寫 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`。`data_module/fundamental_schema.py` 目前尚未接入 `DBManager.init_database()`，不會在一般啟動流程自動修改 SQLite。該模組提供 `generate_fundamental_schema_dry_run_report()` 與 `generate_fundamental_schema_copy_dry_run_report()`，可在暫時 SQLite connection 或正式 DB working copy 上確認既有核心表不被修改。`data_module/fundamental_migration.py` 與 `scripts/migrate_fundamental_schema.py` 已提供顯式 migration workflow：預設 dry-run 只在 working copy 上執行；正式 `--apply` 必須搭配 `--confirm apply-fundamental-schema`，且 apply 前會建立備份、失敗時可用 `restore_fundamental_schema_backup()` 回復。2026-06-16 已依使用者確認對正式 `twstock.db` 套用 fundamental schema migration，備份檔為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_fundamental_schema_20260616_022301.db`。`data_module/company_registry.py` 與 `scripts/update_company_registry.py` 已新增 TWSE/TPEX 官方公司基本資料 registry workflow，正式 `companies.csv` 已更新為 2,326 筆、無重複 stock id，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/companies_company_registry_20260616_031111.csv`。`data_module/valuation_metrics_backfill.py` 與 `scripts/backfill_valuation_metrics.py` 已建立 P/E 估值 metrics 受控回填 workflow，可由 `daily_prices.本益比` 與最新 `companies.csv` 產業 mapping 產生同產業 percentile 的 governed rows；正式 `fundamental_valuation_metrics` 已寫入 831 筆 2026-06-15 P/E records，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_valuation_metrics_backfill_20260616_031146.db`。`data_module/fundamental_availability.py` 則集中公告日 / available_date 策略，避免 parser、adapter 或後續 migration 各自發明時間軸規則。

## 2. 盤點依據

資料根目錄依 `data_module/config.py` 的 `TWStockConfig`：

```text
DATA_ROOT = D:/Min/Python/Project/FA_Data
SQLite = D:/Min/Python/Project/FA_Data/sqlite/twstock.db
financial_data = D:/Min/Python/Project/FA_Data/financial_data
```

本次已完成受控 schema migration，並依使用者確認正式寫入 P/E valuation metrics；另依使用者授權以受控 TPEX daily price backfill 寫入 2026-06-16 上櫃日價 877 筆。未修改 raw financial CSV。月營收與財報仍因缺正式 availability mapping 而未回填。

## 3. 資料來源清單

| 類型 | 目前位置 | 狀態 | 格式 | 可用性判定 | Month 5 處置 |
|---|---|---|---|---|---|
| 月營收 | `financial_data/*_monthly_revenue.csv` | 既有 raw CSV，約 1,567 檔 | CSV | 有 `date`、`stock_id`、`revenue`、`revenue_month`、`revenue_year`；缺 `announced_date` / `available_date` | 可作 raw source 候選；接入前必須補公告日契約或降級政策 |
| 損益表 | `financial_data/*_income_statement.csv` | 既有 raw CSV，約 1,563 檔 | CSV | 有報表日、科目、數值與原始中文科目；缺公告日 / 可得日 | 可作 raw source 候選；不得直接算 EPS / margin 因子 |
| 資產負債表 | `financial_data/*_balance_sheet.csv` | 既有 raw CSV，約 1,565 檔 | CSV | 有報表日、科目、數值與原始中文科目；缺公告日 / 可得日 | 可作 raw source 候選；不得直接算 ROE / debt ratio 因子 |
| 現金流量表 | `financial_data/*_cash_flows_statement.csv` | 既有 raw CSV，約 1,562 檔 | CSV | 有報表日、科目、數值與原始中文科目；缺公告日 / 可得日 | 可作 raw source 候選；不得直接算 cash-flow 因子 |
| 日資料本益比 | SQLite `daily_prices.本益比` / `technical_indicators.本益比` | 已在日資料表 | SQLite | 屬日成交資料附帶欄位，不是完整估值 layer；有交易日但無估值來源版本與品質政策 | 可列 valuation preflight 候選；需建立相對分位與 quality policy |
| P/B / P/S / 殖利率 | 未發現正式來源 | unavailable | - | 無正式 CSV 或 SQLite 表 | Month 5 不得假造；需另定來源 |
| 月營收公告日 | TWSE / TPEX OpenAPI 最新月；MOPS 歷史頁待人工可追溯來源 | partial | JSON / HTML | TWSE/TPEX 最新月彙總表有 `出表日期`；目前未取得可穩定自動化的歷史公告日來源 | 可產生候選 mapping；正式寫入前必須人工確認 |
| 財報公告日 | 未發現正式來源 | unavailable | - | 既有 raw CSV 未保存公告日 | 必須補來源或制定 conservative `available_date` 政策 |
| source_version / quality | 未發現正式 fundamental 欄位 | unavailable | - | 既有 raw CSV 沒有資料品質與來源版本欄位 | 必須由 migration / adapter 補齊 |

## 3.1 候選 SQLite Schema

候選 schema 由 `data_module/fundamental_schema.py` 定義，供 dry-run 與後續受控 migration 使用。目前包含：

| 表格 | 用途 | 關鍵防線 |
|---|---|---|
| `fundamental_monthly_revenues` | 月營收 normalized records | `available_date NOT NULL`，主鍵為 `(stock_code, period, source_version)` |
| `fundamental_statement_items` | 損益表 / 資產負債表 / 現金流量表長表項目 | `available_date NOT NULL`，保留 `statement_type`、`item_code`、`item_name` |
| `fundamental_valuation_metrics` | P/E、P/B、P/S 等估值候選 metrics | `available_date NOT NULL`，保留 `industry_percentile_bp` 作相對分位 |

這些表已於 2026-06-16 依使用者確認建立於正式 SQLite。正式 apply 前已在 `twstock.db` working copy 上完成 schema dry-run：既有 `broker_flows`、`daily_prices`、`industry_indices`、`market_indices`、`technical_indicators` preserved，新增候選表為 `fundamental_monthly_revenues`、`fundamental_statement_items`、`fundamental_valuation_metrics`，`modified_existing_tables` 為 none。正式 apply 後再次查詢 `sqlite_master` 與 `pragma table_info`，確認三張 fundamental 表存在且欄位符合 schema；目前 `fundamental_valuation_metrics` 已正式寫入 831 筆 P/E records，月營收與財報表仍未回填。

### 3.2 受控 SQLite Migration Workflow

`scripts/migrate_fundamental_schema.py` 是目前唯一的 fundamental schema migration CLI 入口：

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fundamental_schema.py --dry-run
.\.venv\Scripts\python.exe scripts\migrate_fundamental_schema.py --apply --confirm apply-fundamental-schema
```

- 未指定 `--apply` 時預設執行 dry-run，會複製來源 DB 到 working copy，再於 working copy 套用候選 schema 並輸出 Markdown report。
- `--apply` 未搭配 `--confirm apply-fundamental-schema` 時會拒絕執行並回傳 2。
- 正式 apply 由 `data_module.fundamental_migration.apply_fundamental_schema_migration()` 負責，會先在 `TWStockConfig.backup_dir` 建立備份，再套用 schema；發生例外時會 rollback connection 並以備份檔 restore 來源 DB。
- 本 workflow 不接入 `DBManager.init_database()`，因此不會在一般啟動、資料更新或測試以外流程中自動修改正式 SQLite。
- 截至 2026-06-16，本 repo 已完成 migration tooling、測試與正式 `twstock.db` schema apply；備份檔為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_fundamental_schema_20260616_022301.db`。正式 DB 已有三張 fundamental 表，其中 `fundamental_valuation_metrics` 已寫入 831 筆 P/E records，月營收與財報仍未寫入。

### 3.3 月營收 normalized backfill workflow

`data_module/monthly_revenue_backfill.py` 與 `scripts/backfill_monthly_revenue_fundamentals.py` 提供月營收 raw CSV 到 `fundamental_monthly_revenues` 的受控回填入口。此 workflow 只接受已通過治理契約的 availability mapping；若正式 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 不存在或 mapping loader 回傳 diagnostics，回填計畫會 `ready_for_apply=false`，不讀 raw rows、不產生 normalized records，也不寫 SQLite。

CLI 範例：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --dry-run
.\.venv\Scripts\python.exe scripts\backfill_monthly_revenue_fundamentals.py --apply --confirm apply-monthly-revenue-backfill
```

- 未指定 `--apply` 時只產生 Markdown plan，列出 `ready_for_apply`、raw row count、normalized record count 與 diagnostics。
- `--apply` 必須搭配 `--confirm apply-monthly-revenue-backfill`；缺少 confirm 時回傳 2，不寫入 DB。
- 正式 apply 前會先備份 DB 到 `TWStockConfig.backup_dir`，寫入失敗時 restore 備份。
- 寫入採 `INSERT OR REPLACE`，主鍵仍由 schema 的 `(stock_code, period, source_version)` 控制；不同 source_version 可保留不同回填版本。

2026-06-16 以正式路徑 dry-run 時，因 `D:/Min/Python/Project/FA_Data/meta_data/monthly_revenue_availability.csv` 尚不存在，結果為 `ready_for_apply=false`、`normalized_record_count=0`、diagnostic=`fundamental_availability.mapping_file_missing`。因此尚未對正式 `fundamental_monthly_revenues` 寫入任何 records。

### 3.4 Company registry workflow

`data_module/company_registry.py` 與 `scripts/update_company_registry.py` 提供 `meta_data/companies.csv` 的受控更新入口。資料來源使用官方 OpenAPI：

- TWSE listed company basic data：`https://openapi.twse.com.tw/v1/opendata/t187ap03_L`
- TPEX OTC company basic data：`https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O`
- TPEX emerging company basic data：`https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R`

CLI 範例：

```powershell
.\.venv\Scripts\python.exe scripts\update_company_registry.py --dry-run
.\.venv\Scripts\python.exe scripts\update_company_registry.py --apply --confirm apply-company-registry
```

- 未指定 `--apply` 時只輸出 plan，不覆寫 `companies.csv`。
- `--apply` 必須搭配 `--confirm apply-company-registry`；正式 apply 前會先備份既有檔案。
- 輸出仍維持既有 schema：`industry_category, stock_id, stock_name, type, date, download_time`。
- loader 會把 TWSE/TPEX 產業代碼轉回既有繁中產業名稱；未知產業代碼會回 diagnostics，不靜默寫入。

2026-06-16 正式 dry-run 顯示可產生 2,326 筆、0 diagnostics；依使用者確認正式 apply 後，`companies.csv` 已更新為 2,326 筆，`stock_id` 無重複，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/companies_company_registry_20260616_031111.csv`。抽查 `3207` 為 `電子零組件業 / tpex`，`9935` 為 `居家生活 / twse`。

本次資料排查結論：

- `9935` 慶豐富舊檔同時存在 2023 `其他` 與 2024 `居家生活` 兩列，舊 loader 取第一列，造成產業 mapping 可能落到過時值；已改為依 `date`、`download_time` 選最新列，正式 registry 更新後不再有重複列。
- `3207` 耀勝存在於 TPEX 公司 registry，但原先 `daily_prices` 無資料，是因舊每日股價下載管線只吃 TWSE `MI_INDEX type=ALL`；這是市場日價管線缺口，不是 company registry 缺口。2026-06-16 已以受控 TPEX daily price backfill 對正式 DB 寫入 `3207` 當日價格列；日常管線現已納入 TPEX official daily close quotes，仍不由 company registry 或 fundamental layer 假造價格列。

### 3.4.1 TPEX daily price backfill workflow

`data_module/tpex_daily_price_backfill.py` 與 `scripts/backfill_tpex_daily_prices.py` 提供 TPEX 上櫃日價的受控補寫入口。資料來源使用官方 OpenAPI：

- TPEX mainboard daily close quotes：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`

CLI 範例：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --dry-run
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --apply --confirm apply-tpex-daily-price-backfill
```

- dry-run 只讀官方來源與 SQLite，列出 `insert_count`、`existing_count` 與 diagnostics，不寫 DB。
- 正式 apply 必須搭配 `--confirm apply-tpex-daily-price-backfill`；寫入前會先備份 DB，寫入失敗會以備份還原。
- workflow 只寫入 `daily_prices`；不修改 `companies.csv`、raw financial CSV、`fundamental_monthly_revenues`、`fundamental_statement_items`、`fundamental_valuation_metrics`、技術指標或推薦分數。
- CLI 批次模式只處理指定 `--date` 的四碼上櫃普通股且收盤價為正數的 rows；債券、權證、ETF 或當日無有效收盤價的 rows 會被跳過，避免污染日價表。

2026-06-16 正式 dry-run 顯示 `ready_for_apply=true`、可新增 877 筆、0 diagnostics；依使用者授權正式 apply 後，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_tpex_daily_price_backfill_20260616_034627.db`。read-only 驗證結果：`daily_prices` 在 `20260616` 有 877 筆四碼上櫃日價、0 duplicate `(證券代號, 日期)` keys；`3207` 已有 `20260616` 日價 `67.0`，成交股數 `2,238,197`，成交金額 `153,210,146`；`9935` 既有日價仍保留，最新為 `20260615`。

### 3.5 Valuation metrics backfill workflow

`data_module/valuation_metrics_backfill.py` 與 `scripts/backfill_valuation_metrics.py` 提供 `daily_prices.本益比` 到 `fundamental_valuation_metrics` 的受控回填入口。此 workflow 使用既有 `meta_data/companies.csv` 的 `stock_id` / `industry_category` 作主要產業 mapping，並以同一交易日、同一產業 universe 計算整數基點 percentile。`available_date` 採交易日當日，因 P/E 來自既有日資料欄位；此資料只可進 valuation presentation policy，不得輸出目標價、合理價、上漲空間或交易建議。

CLI 範例：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --dry-run
.\.venv\Scripts\python.exe scripts\backfill_valuation_metrics.py --apply --confirm apply-valuation-metrics-backfill
```

- 未指定 `--as-of-date` 時，dry-run 會選擇 `daily_prices` 中最新有 P/E 的交易日。
- `--apply` 必須搭配 `--confirm apply-valuation-metrics-backfill`；缺少 confirm 時回傳 2，不寫入 DB。
- 正式 apply 前會先備份 DB 到 `TWStockConfig.backup_dir`，寫入失敗會以備份還原。
- P/E 非正數、無法解析或缺 `companies.csv` 產業 mapping 的 rows 會被跳過並輸出 diagnostics；可用 records 仍可形成可 apply plan。
- 同產業只有單一樣本時，`industry_percentile_bp=None` 並標記 `quality=degraded`，後續 valuation adapter 只會輸出 missing-percentile diagnostics。

2026-06-16 先以舊 `companies.csv` 對正式路徑 dry-run，最新 P/E 交易日為 `2026-06-15`，來源 rows 為 1,090，產生 812 筆可正規化 valuation records，另有 278 筆 diagnostics（主要是 P/E 非正數，少數缺產業 mapping）。更新官方 company registry 後再次 dry-run，產生 831 筆可正規化 valuation records、259 筆 diagnostics；依使用者確認正式 apply 後，`fundamental_valuation_metrics` 共有 831 筆 records、0 duplicate primary keys，quality 全為 `observed`，`industry_percentile_bp` 無 NULL。抽查 `9935` 為 P/E `11.83`、產業 `居家生活`、percentile `3333`；`2330` 可由 `FundamentalFactorService` 讀出 `valuation.pe.relative_band:mid_relative:observed`，且 `available_date > decision_date` 時不會提前讀取。正式 DB 備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_valuation_metrics_backfill_20260616_031146.db`。

### 3.6 Fundamental SQLite read provider

`data_module/fundamental_sqlite_provider.py` 提供正式 fundamental SQLite 表的唯讀 provider：

- `load_monthly_revenues(stock_code, decision_date)` 只讀 `fundamental_monthly_revenues.available_date <= decision_date` 的 rows，並轉為 `MonthlyRevenueRecord`。
- `load_valuation_observations(stock_code, decision_date)` 只讀 `fundamental_valuation_metrics.available_date <= decision_date` 的 rows，並轉為 governed `ValuationObservation`。

此 provider 不讀 raw CSV、不補 availability mapping、不寫 SQLite；它只負責讓後續 factor adapters 或服務層能從已治理 SQLite records 讀資料，並在 SQL 層保留 no-look-ahead gate。正式 DB 目前 `fundamental_monthly_revenues` 與 `fundamental_statement_items` 仍未回填；`fundamental_valuation_metrics` 已有 831 筆 P/E records。月營收或財報缺資料時只回 missing diagnostics，不應被解讀為無基本面風險或中性。

### 3.6 Fundamental factor application service

`app_module/fundamental_factor_service.py` 將 SQLite provider 與既有 factor adapters 串接為服務層 snapshot：

- 從 `FundamentalSQLiteProvider` 讀取 `available_date <= decision_date` 的月營收與估值 observations。
- 對月營收使用 `build_revenue_factor_pack()` 產生 YoY / MoM / 3M trend / new high factor records。
- 對估值使用 `build_relative_valuation_factor()` 產生 presentation-only relative valuation band。
- 所有 records 再經 `FactorGate.validate_for_decision()`；服務本身不接 `ScoringEngine`，不輸出 score，不寫 DB。
- 月營收或估值缺資料時回 missing diagnostic，不產生中性訊號。

2026-06-16 對正式 DB 執行 service snapshot dry-run 時，`2330` 在 `decision_date=2026-06-16` 可讀取 1 筆 valuation factor，並同時回 `fundamental_sqlite.monthly_revenue_missing` diagnostic；在 `decision_date=2026-06-14` 不會提前讀取 2026-06-15 才 available 的 valuation row。

## 4. Raw CSV 欄位觀察

月營收 CSV 範例欄位：

```text
date,stock_id,country,revenue,revenue_month,revenue_year
```

財報 CSV 範例欄位：

```text
date,stock_id,type,value,origin_name
```

這些欄位可以支援 `period` 與 raw value，但不能單獨支援 no-look-ahead。`date` 是報表期間或月份，不等於市場可得日。

## 5. 決策可用性規則

任何 fundamental observation 進入 factor layer 前，至少必須具備：

| 欄位 | 要求 |
|---|---|
| `stock_code` | 股票代號，字串 |
| `period` | 資料所屬月份或財報期間 |
| `as_of_date` | 資料代表的期間截止日 |
| `announced_date` | 原始公告日；來源沒有時必須為 `None` 並降級 |
| `available_date` | 系統最早可安全使用日期；不得晚於決策後才被使用 |
| `source` | 原始來源名稱或路徑類型 |
| `source_version` | 來源版本或 migration 版本 |
| `quality` | `OBSERVED` / `ESTIMATED` / `DEGRADED` / `MISSING` |

回測、推薦、Daily Decision Desk 與 Research Run 保存只能使用：

```text
available_date <= decision_date
```

若缺少 `available_date`，預設不得升級為 `OBSERVED`。可接受政策只有：

- `FAIL_CLOSED`：拒絕使用該筆資料。
- `NEUTRAL`：轉為中性 factor，並留下 diagnostics。
- `SKIP`：跳過該 factor，並留下 diagnostics。

### 5.1 公告日 / available_date 初版政策

| 條件 | 處置 |
|---|---|
| 有 `announced_date` 且 explicit `available_date >= announced_date` 且不早於 `as_of_date` | quality = `OBSERVED` |
| 缺 `announced_date` 但有 explicit `available_date` 且不早於 `as_of_date` | quality = `DEGRADED`，輸出 `fundamental_availability.missing_announced_date` |
| 缺 explicit `available_date` | quality = `MISSING`，不產生 normalized record |
| `available_date < announced_date` | quality = `MISSING`，不產生 normalized record |
| `available_date < as_of_date` | quality = `MISSING`，不產生 normalized record |

此政策不允許把 raw CSV 的 `date` 推定為公告日或可得日。

### 5.2 受治理 Mapping 契約

`data_module/fundamental_availability_sources.py` 定義月營收 availability mapping loader。每筆 mapping 至少必須提供：

| 欄位 | 要求 |
|---|---|
| `stock_code` | 股票代號 |
| `period` | `YYYY-MM` 月營收期別 |
| `as_of_date` | 該期別月底日期 |
| `announced_date` | 公告日；可缺，但缺失時只能降級為 `DEGRADED` |
| `available_date` | 系統可安全使用日；缺失時不產生 override |
| `source` | mapping 來源；不得為 `financial_data.monthly_revenue_csv` |
| `source_version` | mapping 版本 |

此契約目前解決「資料如何被標記為可得」的工程邊界；它不是公告日資料本身。正式接入前仍需建立可追溯的公告日資料來源或人工維護流程。

預設正式 mapping 檔案位置由 `TWStockConfig.monthly_revenue_availability_file` 定義：

```text
DATA_ROOT/meta_data/monthly_revenue_availability.csv
```

repo 內只提供欄位範本：`docs/03_data/templates/monthly_revenue_availability.csv`。正式檔案不存在時，loader 只回傳 `fundamental_availability.mapping_file_missing` diagnostic，不會建立檔案、不會改寫 raw CSV，也不會用 raw 月營收 `date` 自動補值。

### 5.2.1 驗證入口

`data_module/fundamental_availability_entrypoint.py` 提供 `validate_monthly_revenue_availability_file(path)`，用來驗證受治理 mapping 檔是否只使用允許的公告日 / available_date 來源。允許來源目前包含：

- `manual.twse_monthly_revenue_announcement_log`
- `manual.available_date_mapping`
- `twse.monthly_revenue_announcement`
- `tpex.monthly_revenue_announcement`
- `mops.monthly_revenue_announcement`
- `tej.monthly_revenue_announcement_pit`

若 mapping 檔不存在，驗證結果會回傳 `fundamental_availability.mapping_file_missing`；若使用 `financial_data.monthly_revenue_csv` 或其他未治理來源，驗證結果會保留 diagnostics 並判定 invalid。CLI 入口為：

```powershell
.\.venv\Scripts\python.exe scripts\validate_monthly_revenue_availability.py --path <mapping-csv>
```

未提供 `--path` 時，CLI 只讀取 `TWStockConfig.monthly_revenue_availability_file` 指向的位置並輸出 Markdown 摘要；它不會建立正式 mapping 檔、不會改寫 raw CSV，也不會寫入 SQLite。

### 5.2.2 TWSE / TPEX OpenAPI 與 historical dry-run 候選產生器

`data_module/monthly_revenue_availability_builder.py` 與 `scripts/build_monthly_revenue_availability.py` 提供月營收 availability mapping 候選產生器，可從 TWSE OpenAPI `https://openapi.twse.com.tw/v1/opendata/t187ap05_P` 讀取公開發行公司每月營業收入彙總表，使用官方欄位 `出表日期`、`資料年月`、`公司代號` 產生受治理 mapping row。產生器會：

- 將民國 `資料年月` 轉為 `YYYY-MM`，並以該月月底作 `as_of_date`。
- 將民國 `出表日期` 轉為 `announced_date`。
- 以 `announced_date + 1 calendar day` 作為保守 `available_date`，避免同日盤中可得性假設。
- 僅輸出本機 `financial_data/*_monthly_revenue.csv` 已存在的 `(stock_code, period)`，避免產生無 raw record 可對應的 mapping。
- 使用 `source=twse.monthly_revenue_announcement` 與 `source_version=twse-openapi-t187ap05-p-<fetch_date>`。

CLI 範例：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability.py --fetch-date 2026-06-16
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability.py --source-json <twse-json> --output <candidate-csv> --fetch-date 2026-06-16
```

未提供 `--output` 時只輸出 Markdown 摘要，不建立檔案。即使提供 `--output`，也只會寫入使用者指定的候選 CSV；不得直接覆寫 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`，正式寫入前仍需人工確認、備份與驗證入口通過。

2026-06-16 對真實 TWSE OpenAPI 執行 dry-run 時，官方端點回傳 299 筆最新月資料，本機 raw monthly revenue 期間為 175,234 組，兩者交集為 0，因此未產生候選 row、未寫入正式 mapping。MOPS 個股 ajax 歷史查詢在一般自動化請求下回傳安全性阻擋頁，尚不能列為穩定自動下載來源；若要補歷史 mapping，需另取得可追溯的官方批次檔、人工公告日 log，或使用受控手動 mapping 後再經 validator 驗證。

`data_module/monthly_revenue_availability_history.py` 與 `scripts/build_monthly_revenue_availability_history.py` 是下一版 historical dry-run builder。它支援：

- `--start-period YYYY-MM` / `--end-period YYYY-MM`
- `--markets twse,tpex`
- `--stock-code 2330` 單股篩選
- `--output <candidate-csv>`；未指定時只輸出 summary，不寫檔
- `--source-json-dir <dir>` 供測試或人工下載的官方 JSON 檔使用（檔名為 `twse.json` / `tpex.json`）
- `--mops-html-dir <dir>` 供人工保存的 MOPS 官方歷史 HTML 使用（檔名規則為 `twse_YYYY-MM.html` / `tpex_YYYY-MM.html`）
- `--mops-static` 透過新版 MOPS `/mops/api/redirectToOld` 取得 `mopsov.twse.com.tw/nas/t21/...` historical static report，僅作 dry-run source validation
- `--pit-csv <csv>` 讀取授權取得的 point-in-time 月營收公告日匯出檔；必須搭配非空 `--pit-source-version`，只產生候選 mapping，不寫正式檔

目前官方 OpenAPI 驗證結果：

| 來源 | endpoint | 歷史支援判定 | 欄位 / 樣本 |
|---|---|---|---|
| TWSE 上市公司每月營業收入彙總表 | `https://openapi.twse.com.tw/v1/opendata/t187ap05_L` | swagger 未提供 period query；目前回最新月 | 2026-06-16 查得 1,076 rows；`2330` 與 `9935` 均為 `資料年月=11505`、`出表日期=1150615` |
| TPEX 上櫃公司每月營業收入彙總表 | `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O` | swagger 未提供 period query；目前回最新月 | 2026-06-16 查得 889 rows；`3207` 為 `資料年月=11505`、`出表日期=1150616` |
| data.gov 上市公司每月營業收入彙總表 | `https://data.gov.tw/dataset/18420` | 資料集欄位確認有 `出表日期`；資源指向 TWSE / MOPS 最新資料 | 欄位包含 `出表日期`、`資料年月`、`公司代號`、營收與累計營收欄位 |
| MOPS 採用 IFRSs 後月營收頁 | `https://mops.twse.com.tw/mops/#/web/t21sc04_ifrs` | 新版 SPA 可用 `/mops/api/redirectToOld` 產生 `mopsov.twse.com.tw/nas/t21/...` historical static report URL；但 HTML 的 `出表日期` 是查詢當日重新出表日，不是原始公告日 | 可作歷史資料內容佐證；不得直接作 historical availability mapping |
| TEJ Point-in-Time 月營收公告日 | `https://medium.com/tej-can-help/tej-dictionary-use-tej-point-in-time-data-to-explore-the-connotation-of-monthly-revenue-beabe2b51eba` / `https://www.tejwin.com/en/news/monthly-sales/` | TEJ 文件明確描述以 TEJ API 取得月營收公告日 point-in-time data；屬授權 / 商業來源，repo 不內建憑證或下載器 | 可由授權匯出 CSV 經 `--pit-csv` 匯入候選 mapping；source 固定治理為 `tej.monthly_revenue_announcement_pit`，source_version 必須由匯出批次提供 |

2026-06-16 追加 `parse_mops_monthly_revenue_html()`：若人工保存的官方 MOPS HTML 內含頁面層級 `出表日期` 與含 `公司代號` 的表格，builder 會將 `announced_date=出表日期`、`available_date=announced_date+1 calendar day`，source 設為 `mops.monthly_revenue_announcement`，source_version 設為 `mops-t05st10-ifrs-<fetch-date>`。若 HTML 缺 `出表日期`、無可解析公司列，或指定期間檔案不存在，只輸出 diagnostics，不用 raw CSV 日期補值。2026-06-17 驗證新版 MOPS historical static report 時，`113/04` 上市與上櫃彙總表可抓到 `2330`、`9935`、`3207` rows，但 `出表日期` 為查詢當日 `115/06/17`；builder 與 validator 均新增 `as_of_date + 45 days` 合理揭露窗口，這類重新出表日期會回 `monthly_revenue_availability.available_date_unreasonably_late` / `fundamental_availability.available_date_unreasonably_late`，不產生候選 row。

2026-06-16 追加 PIT CSV importer：`load_pit_announcement_rows()` 接受授權匯出的月營收公告日 CSV，欄位可為 `stock_code` / `公司代號`、`period` / `資料年月`、`announced_date` / `公告日` / `出表日期`。匯入時會正規化民國年、`YYYY-MM` period 與 `YYYY-MM-DD` 公告日；只有可解析公告日才產生 mapping。`source_version` 必須非空且原樣保留為 mapping 版本，不以 raw CSV 日期或查詢日期補值。PIT 匯入後的 `available_date` 仍採保守政策 `announced_date + 1 calendar day`，正式寫入 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 前必須先產生 candidate、跑 validator，並由使用者人工確認。

2026-06-16 對正式 raw 路徑執行：

```powershell
.\.venv\Scripts\python.exe scripts\build_monthly_revenue_availability_history.py --start-period 2020-01 --end-period 2026-05 --markets twse,tpex --fetch-date 2026-06-16
```

結果為 `requested_periods=77`、`fetched_periods=1`、`matched_raw_monthly_revenue_rows=0`、`missing_availability_rows=76902`、`duplicate_mapping_rows=0`、`diagnostics=0`。原因是正式 raw 月營收目前涵蓋 `2014-04` 至 `2024-04`，而 TWSE/TPEX OpenAPI 最新月為 `2026-05`，沒有 period overlap。此結果不產生候選 CSV，也不得用 raw CSV 期間日期補值。

### 5.3 估值呈現政策 v1

`data_module/valuation_data.py` 建立 valuation data layer v1，可由已治理 row 建立 `ValuationObservation`，保留 `as_of_date`、`available_date`、raw `metric_value`、`quality`、`source_version` 與選擇性的 `industry_percentile_bp`。`calculate_industry_percentiles_bp()` 只在同產業 universe 內計算整數基點分位；單一樣本或缺少同業比較時回 `None`，交由後續 policy 輸出 diagnostics。此資料層不產生 fair value、target price、upside 或 recommendation。

`decision_module/factors/valuation_policy.py` 定義 `valuation_presentation_policy_v1`，仍是估值輸出的唯一邊界。本政策只允許把 P/E、P/B、P/S 或殖利率等估值 metric 呈現為相對估值區間：

- `LOW_RELATIVE`：相對低估值區
- `MID_RELATIVE`：中性估值區
- `HIGH_RELATIVE`：相對高估值區
- `UNAVAILABLE`：資料不足

本政策禁止產生 `fair_value`、`target_price`、`upside_pct`、`buy_signal`、`sell_signal` 或 `recommendation`。缺少 `industry_percentile_bp` 時只能回 `UNAVAILABLE` 或 diagnostics，不得假設為中性估值區。此政策目前不代表 P/B、P/S 或殖利率來源已正式可用，也不寫入正式 SQLite。

## 6. Factor Adapter 邊界

允許：

- raw fundamental CSV 先進 migration / loader 邊界。
- migration 產生具 `available_date`、`quality`、`source_version` 的 normalized records。
- adapter 只輸出 `FactorRecord` 或等價 DTO。
- `decision_module/factors/fundamental_adapters.py` 可由已正規化月營收 records 產生 `fundamental.revenue_yoy`、`fundamental.revenue_mom`、`fundamental.revenue_3m_trend`、`fundamental.revenue_new_high`，但只保留 factor metadata / diagnostics，不產生 score。
- `decision_module/factors/abnormal_fundamental_flags.py` 可由受治理營收 / 獲利 / 一次性收益與資料品質 warning 產生 abnormal fundamental diagnostics；`app_module/fundamental_diagnostics_service.py` 可將其序列化為 Research Run metadata。
- `FactorGate` 集中執行 `available_date <= decision_date`。

禁止：

- `ScoringEngine` 直接讀 `financial_data/*.csv`。
- UI 直接計算營收 YoY / MoM、估值分位或異常基本面旗標。
- Backtest / Recommendation 直接讀 raw financial CSV 繞過 factor gate。
- 在公告日缺失時把報表期間 `date` 當成 `available_date`。

## 7. Month 5 下一步

1. 填入或下載真實月營收公告日資料到候選 CSV，先以 historical dry-run builder 與 validator 驗證；目前 repo 只提供欄位範本、TWSE/TPEX 最新月 builder 與 dry-run 驗證入口，不提供正式 mapping。正式寫入 `DATA_ROOT/meta_data/monthly_revenue_availability.csv` 前必須人工確認。
2. 正式 SQLite schema migration 已完成；後續不得繞過 loader / validator 直接寫入三張 fundamental 表。
3. 補足 no-look-ahead tests：`available_date > decision_date` 必須拒絕、轉中性或跳過。
4. Revenue factor pack 已有 adapter 與 no-look-ahead gate regression；後續仍需接上正式 normalized 資料來源與 Research Run diagnostics，不接入 `ScoringEngine`。
5. 月營收 normalized backfill workflow 已具備 dry-run、confirm、備份與 fail-closed diagnostics；valuation metrics backfill workflow 已具備 dry-run、confirm、備份、產業 mapping 與同產業 percentile，且 2026-06-16 已依使用者確認正式寫入 831 筆 P/E records；SQLite read provider 與 fundamental factor service 已具備 no-look-ahead 讀取 / adapter / gate 邊界。月營收待正式 availability mapping 通過驗證後仍需人工確認才可 apply。
6. TPEX 公司 registry 已納入 `companies.csv`，且已新增受控 TPEX daily price backfill 補齊 `3207` 這類上櫃股票的 `daily_prices` 當日缺口；TPEX quotes 已納入日常市場日價更新管線，歷史缺漏仍需 dry-run plan 與人工確認，不得在 fundamental layer 假造價格列。
7. Abnormal fundamental diagnostics 已能進入 Research metadata 與 Daily Decision Desk risk prompts；後續接正式資料時仍只能作提示，不得改寫財報或自動扣分。

## 8. 更新記錄

- 2026-06-16：建立 Month 5 Fundamental Layer preflight 資料來源盤點，確認既有 `financial_data/` 只可作 raw candidate source；初始盤點時正式 SQLite 尚無 fundamental tables，後續同日已完成受控 schema apply。
- 2026-06-16：新增 raw 月營收唯讀正規化契約，缺 explicit `available_date` mapping 時不產生 normalized record。
- 2026-06-16：新增 fundamental 候選 SQLite schema dry-run 模組，定義月營收、財報長表與估值 metrics 表，但尚未接入正式 `DBManager` migration。
- 2026-06-16：新增公告日 / available_date 初版政策，集中處理 observed / degraded / missing 判定與不合法時間軸 diagnostics。
- 2026-06-16：新增 schema dry-run report API，可在暫時 SQLite connection 驗證候選 fundamental schema 不修改既有核心表。
- 2026-06-16：新增正式 DB working copy dry-run API，並以正式 `twstock.db` 複本驗證候選 schema 只新增三張 fundamental 表、不修改既有五張核心表；暫存複本已清理，正式 DB 未寫入。
- 2026-06-16：新增受治理月營收 availability mapping 契約，支援保留 `announced_date` / `available_date` / `source_version`，並拒絕把 raw 月營收 CSV 日期當成可得日來源。
- 2026-06-16：新增估值呈現政策 v1 文件化，確認估值只可呈現相對區間與 diagnostics，不輸出目標價、合理價、上漲空間或交易建議。
- 2026-06-16：新增 valuation data layer v1，建立受治理 `ValuationObservation` 與同產業整數基點分位計算；缺分位仍只經既有 presentation policy 輸出 diagnostics，不產生目標價或建議。
- 2026-06-16：新增月營收公告日 mapping CSV loader、`TWStockConfig.monthly_revenue_availability_file` 預設路徑與 docs 範本；缺檔只輸出 diagnostic，不自動補值或寫正式資料。
- 2026-06-16：新增月營收 availability mapping 正式驗證入口與 CLI dry-run validator，允許治理來源、拒絕 raw CSV available-date 來源，並保持不建立、不改寫正式 mapping 檔或 SQLite。
- 2026-06-16：新增 TWSE OpenAPI 月營收 availability 候選產生器與 CLI，可用官方 `出表日期` / `資料年月` / `公司代號` 產生候選 mapping；真實 dry-run 顯示最新月端點與本機歷史 raw 期間暫無交集，因此未寫入正式 mapping。
- 2026-06-16：新增 Fundamental SQLite 受控 migration service 與 CLI，支援 working-copy dry-run、apply 前備份、失敗 restore 與 `--confirm apply-fundamental-schema` 人工確認。
- 2026-06-16：依使用者確認對正式 `twstock.db` 套用 Fundamental SQLite schema migration，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_fundamental_schema_20260616_022301.db`；正式 DB 新增三張 fundamental 表，後續同日已回填 P/E valuation metrics。
- 2026-06-16：新增月營收 normalized backfill workflow 與 CLI，預設 dry-run，正式 apply 需 `--confirm apply-monthly-revenue-backfill` 並先備份；正式路徑因缺 availability mapping fail-closed，未寫入 records。
- 2026-06-16：新增 official company registry workflow 與 CLI，使用 TWSE/TPEX 官方公司基本資料更新 `companies.csv`；正式 apply 後共 2,326 筆、無重複 stock id，修正 `9935` 舊產業列覆蓋問題，並確認 `3207` 缺 daily price 是市場日價層缺口，不是 company registry 或 fundamental layer 問題；日常 TPEX 日價管線已於後續更新接上。
- 2026-06-16：新增 valuation metrics backfill workflow 與 CLI，可由 `daily_prices.本益比` 與最新 `companies.csv` 產業 mapping 產生 P/E valuation records 與同產業 percentile；正式 apply 後 `fundamental_valuation_metrics` 共 831 筆、0 duplicate primary keys，quality 全為 `observed`。
- 2026-06-16：新增 Fundamental SQLite read provider，可從正式 fundamental tables 讀取 `available_date <= decision_date` 的月營收與估值 observations；缺資料時回 missing diagnostics，不代表中性訊號。
- 2026-06-16：新增 Fundamental factor application service，串接 SQLite provider、revenue/valuation adapters 與 FactorGate；正式 DB 月營收缺資料時只輸出 missing diagnostics，不接 `ScoringEngine`。
- 2026-06-16：新增 Revenue Factor Pack v1 adapters，從已正規化月營收 records 產生 YoY、MoM、3M trend 與 new high factor records；缺 baseline 只輸出 diagnostics，未來 available_date 由 `FactorGate` skip，不接 `ScoringEngine`。
- 2026-06-16：新增 Abnormal Fundamental diagnostics policy / application service / Daily Decision Desk prompt bridge；異常基本面只作 Research metadata 與風險提示，不改寫財報、不自動調整分數。
- 2026-06-16：新增 TPEX daily price backfill workflow 與 CLI，對正式 `daily_prices` 補入 `20260616` 上櫃四碼普通股日價 877 筆；正式 apply 前備份 DB，驗證 0 duplicate primary keys，`3207` 日價缺口已補齊。
- 2026-06-16：TPEX official daily close quotes 已接入日常每日股價更新管線；歷史 TPEX 缺漏仍需 dry-run plan 與人工確認，不由 fundamental layer 補值。
- 2026-06-16：新增 TWSE/TPEX 月營收 historical dry-run builder 與 CLI，支援 `2020-01..2026-05` 期間 summary、單股篩選、候選 CSV 輸出與 diagnostics；真實來源驗證確認 TWSE/TPEX OpenAPI 目前只提供最新月、MOPS historical 自動化查詢仍不可穩定使用，正式 raw 月營收 `2014-04..2024-04` 與最新月來源無交集，因此未產生正式 mapping。
- 2026-06-16：補上 MOPS 官方 HTML parser 與 `--mops-html-dir` 候選流程；只接受人工保存且含 `出表日期` 的官方 HTML，缺欄位時 fail-closed diagnostics，不由 raw CSV 補 available_date。
- 2026-06-17：補上新版 MOPS `redirectToOld` / `mopsov` static report fetcher 與 `--mops-static` dry-run；確認 historical static report 的 `出表日期` 是查詢當日重新出表日，已由 45 天合理揭露窗口 gate 擋下，不能直接作 historical available_date mapping。
- 2026-06-16：新增授權 PIT 月營收公告日 CSV importer 與 `--pit-csv` CLI；目前免費官方來源仍未找到可批次追溯原始歷史公告日的路徑，TEJ PIT 匯出列為治理來源候選，必須附 `source_version` 並通過 validator 後才可人工確認寫入正式 mapping。
