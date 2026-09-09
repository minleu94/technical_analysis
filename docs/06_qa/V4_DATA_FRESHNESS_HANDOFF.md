# V4 全資料更新稽核、Freshness 修補與每日增量閉環交接

日期：2026-09-08

分支：`dev`

責任範圍：Data Engineering／Data Audit／Execution／Testing QA

交付者：Codex

## 1. 交付結論

本輪已完成更新服務、官方交易日曆、來源完整性 probe、每日 quick runner、TWSE／TPEx／大盤／產業／券商／技術指標增量路徑，以及既有更新狀態投影的修補；沒有新增 branch、worktree、平行更新框架，也沒有修改 Health／Exit／Formal 或個股 UI。

修補後的真實唯讀讀回顯示：

- 2026-09-08 的 TWSE、TPEx、SQLite `daily_prices`、market index、industry index、broker flows、technical indicators 均為 `current`。
- 最近 10 個官方交易 session（2026-08-26 至 2026-09-08）均被納入檢查；每日行情 raw 1,095（TWSE）+ 866（TPEx）= 1,961 筆與 SQLite 當日 1,961 筆對帳一致。技術指標對 1,958 個 eligible stocks 為 10,000 bp 覆蓋率，另 3 筆每日資料不符合至少 30 日歷史資格，沒有用 forward-fill 補值。
- probe 不再因 `MAX(date)` 或單一最新檔案存在而假裝全綠。修補後真實狀態為 `degraded`：月營收正式表停在 `2026-06`（預期 `2026-07`）、季報表停在 `2024-Q1`（預期 `2026-Q2`），`fundamental_statement_availability.csv` 不存在，因此另列 `unknown`。
- MOPS `2026-07` 真實 bounded 抓取取得 1,851 筆；由同批官方 HTML 產生的公告／可得日 candidate 為 1,851 筆、缺漏 0、重複 0、診斷 0。正式 mapping merge preview 為 `existing=1,832 + added=1,851 -> merged=3,683`，月營收 recovery preview 為 `normalized=1,851、unmatched=0、ready_for_apply=true`。
- 上述月營收 candidate 尚未寫入正式 mapping 或 SQLite：Direct heavy-chain lock 仍存在，且正式 apply 必須由 Fundamental Data owner 接受 PIT mapping 後執行。本輪沒有為了「變綠」而改日期、寫 DB 或覆寫 raw。

因此本交付是「每日市場資料閉環已修補且有自然資料證據；月／季資料已取得並完成可套用 preview，但正式 transaction 受既有鎖與跨 owner gate 阻擋」；不宣稱所有正式基本面資料已完成。

## 2. 範圍、分支與保護條款

- 沿用既有 `dev`，未建立 branch／worktree。
- 未使用 `reset`、`stash`、`revert`，未覆寫其他 owner 的未提交變更；未 stage／commit 整個工作區。
- 沒有直接修改中央 `docs/00_core/PROJECT_SNAPSHOT.md` 或 `docs/07_guides/APPLICATION_MANUAL.md`；給 root 的精確補丁在本文件第 11 節。
- 沒有修改 `ui_qt/`、Health、Exit、Formal。既有工作區其他 dirty 檔案不屬本輪交付，root 整併時須依 `docs/agents/git_exclusions.md` 過濾。
- 只在 repo 的 `output/v4_data_freshness_handoff_20260908/` 產生 raw／candidate QA；`output/` 已被 `.gitignore` 忽略，不提交 DB 或 raw。

## 3. 設定、實體來源與更新入口清冊

### 3.1 設定與路徑

`TWStockConfig` 的正式資料根目錄為 `D:\Min\Python\Project\FA_Data`，可由 `DATA_ROOT` 覆蓋；正式輸出根目錄為 `DATA_ROOT/output`，可由 `OUTPUT_ROOT` 覆蓋；正式 SQLite 為 `DATA_ROOT/sqlite/twstock.db`。本輪 probe 明確以這三個絕對路徑執行，沒有讀取 `Date_table.csv` 作為交易日權威。

| 實體位置 | 真實讀回 | 判讀 |
|---|---:|---|
| `daily_price/` | 3,101 CSV，約 260,204,634 bytes，最新 `20260908.csv`，local mtime 04:20:07 | TWSE raw 日行情，保留歷史檔，不以檔案數代替市場 coverage |
| `daily_price_tpex/` | 3,067 CSV，約 205,802,094 bytes，最新 `20260908.csv`，local mtime 04:20:09 | TPEx raw 日行情 |
| `broker_flow/` | 48 active branches；7,275 CSV（7,227 daily + 48 meta），最新 branch 日檔 `20260908.csv`，local mtime 04:22:42 | MoneyDJ 分點來源與 registry 路由 |
| `technical_analysis/` | 2,148 `_indicators.csv`；最早抽查 `0060` mtime 2026-06-30，最新抽查 `9962` mtime 2026-09-08 04:28:04 | 由 SQLite daily 衍生的 per-stock legacy/檢查輸出 |
| `financial_data/` | 6,258 CSV，約 138.7 MB：monthly revenue 1,567、income 1,563、balance 1,565、cash flow 1,562、other 1；最新檔 mtime 2024-07-05 | 舊 raw financial cache；沒有最近發布 receipt，不能冒充 2026 完整來源 |
| `meta_data/` | 84 files，約 16.4 GB；含 companies、broker registry、monthly availability、market／industry index、legacy aggregate | 靜態／治理 metadata 與 legacy snapshot，逐項見來源矩陣 |
| `industry_analysis/` | 206 files，約 21.6 MB，最新 mtime 2025-02-20 | derived/static，沒有註冊的官方發布 cadence |
| `features/` | 21 files，約 1.8 MB，最新 mtime 2025-03-04 | derived/static，沒有註冊的官方發布 cadence |
| `sqlite/` | 9 files，約 8.2 GB；`twstock.db` 約 3.414 GB | 正式 read model；本輪只 query-only 讀取 |
| `output/` | 約 112,589 files，約 350.7 GB | runtime／QA／研究輸出；不是來源完整性證明，raw QA 維持 ignored |

以下目錄存在但不在 production update registry／入口：`_test`、`backup_daily_etf`、`industry_correlation`、`KY__buy_sell`、`models`、`portfolio`、`predictions`、`test_data`、`TS_daily`。本輪沒有把它們誤列為正式來源，也沒有新建假資料。

### 3.2 SQLite schema 與真實 row count

唯讀連線讀回 22 張非 SQLite internal tables：

```text
broker_flows
credit_transactions
daily_prices
decision_desk_snapshots
decision_quality_action_items
decision_quality_item_status_history
decision_quality_items
decision_quality_reviews
evidence_events
evidence_operations_weekly_reviews
evidence_outcomes
fundamental_monthly_revenues
fundamental_statement_items
fundamental_valuation_metrics
industry_indices
institutional_flows
live_research_gap_observations
market_indices
schema_version
signal_decay_observations
tdcc_shareholding
technical_indicators
```

核心表的實際讀回如下：

| Table | rows／期間 | schema／key／異常 | 主要 consumer |
|---|---:|---|---|
| `daily_prices` | 5,297,742；20140102--20260908；2,205 codes、3,089 dates | `(證券代號, 日期)` duplicate groups 0；20260908 為 1,961 rows | recommendation、decision desk、SQLite-first market consumers |
| `technical_indicators` | 5,242,035；3,098 dates；target 20260908 為 1,958 rows | `(日期, 證券代號)` duplicate groups 0；eligible 1,958／covered 1,958 | recommendation、decision desk、research |
| `market_indices` | 3,078；20140102--20260908；每日 1 row | date/name duplicate groups 0 | market regime、benchmark |
| `industry_indices` | 211,300；20140102--20260908；每日 75 rows | date/name duplicate groups 0 | industry mapper、sector rotation、benchmark |
| `broker_flows` | 1,022,130；20251024--20260908；220 dates、2,201 codes | natural key `(分點名稱, 證券代號, 日期, trade_type)` duplicate groups 0；同日同 code 的 6,123 個重複觀測是多分點／trade type 的預期粒度 | broker-flow repository、research-only microstructure |
| `fundamental_monthly_revenues` | 246,331；2014-04--2026-06；147 periods、1,849 codes | key `(stock_code, period, source_version)`；正式最新期落後 `2026-07` | fundamental snapshot、valuation consumers |
| `fundamental_statement_items` | 1,645,555；2014-Q2--2024-Q1；40 periods、1,567 codes | key `(stock_code, statement_type, period, item_code, source_version)`；正式最新期落後 `2026-Q2` | fundamental snapshot、PIT research-only |
| `fundamental_valuation_metrics` | 1,671；as-of 2026-06-15--2026-08-06；841 codes | key `(stock_code, as_of, metric)`；沒有註冊到 daily quick 的發布 cadence | recommendation／research valuation；`scripts/backfill_valuation_metrics.py` |
| `institutional_flows` | 0 | schema 存在，P0 candidate-only，production ingestion disabled | 尚無正式 downstream |
| `credit_transactions` | 0 | schema 存在，P0 candidate-only，production ingestion disabled | 尚無正式 downstream |
| `tdcc_shareholding` | 0 | schema 存在，P0 candidate-only，production ingestion disabled | 尚無正式 downstream |

其他 11 張 evidence／decision／schema／observation tables 是下游決策或治理證據，不是本輪行情來源；probe 沒有把它們誤算成 source freshness。`PRAGMA journal_mode=wal`、`PRAGMA query_only=1` 真實讀回成功；本輪沒有 checkpoint、VACUUM 或寫 transaction。

### 3.3 Registry 與 consumer 路由

`build_default_data_source_capability_registry()` 讀回 15 個 capability：8 ready、7 partial。ready 主要是 TWSE／TPEx raw、SQLite daily、recommendation persisted result／screening matrix、decision desk read model；partial 是公司行動、停牌／處置／全額交割／漲跌停／分盤交易等 candidate/event 能力。P0 source IDs 為 13 個，現況全部 `candidate-only`／`production_ingestion=false`；P0 route registry 有 27 條路由，包含 TWSE／TPEx corporate action、T86／margin、TDCC、t187ap05、MOPS statement lanes。

production update 仍沿用 `app_module/update_service.py`：

| 路由 | 更新入口 | 產物／consumer | 排程 |
|---|---|---|---|
| TWSE + TPEx daily | `UpdateService.update_daily`、`update_tpex_daily_price_range`、`scripts/batch_update_daily_data.py` | raw daily CSV → `daily_prices` → indicators | `baldr-data-update-quick-daily` 04:20 |
| market index | `UpdateService.update_market`、`batch_update_market_and_industry_index.py` | `market_index.csv` → `market_indices` | 同上 |
| industry index | `UpdateService.update_industry`、同一 batch | `industry_index.csv` → `industry_indices` | 同上 |
| broker branch | `UpdateService.update_broker_branch`、`BrokerBranchUpdateService` | 48 branch daily CSV → `broker_flows` | 同上 |
| indicators | `UpdateService.calculate_technical_indicators` | `technical_indicators`、per-stock indicator CSV | 同上，daily 之後 |
| monthly revenue | `fetch_mops_monthly_revenue_snapshot_candidate`、`dry_run/apply_mops_monthly_revenue_backfill` | candidate snapshot → governed availability → `fundamental_monthly_revenues` | candidate／人工 gate，非 daily quick |
| quarterly statements | MOPS statement publication／candidate CLI | `fundamental_statement_items` | 目前沒有 production quick schedule |

## 4. 來源矩陣

時間欄位約定：官方來源沒有在 raw CSV 寫入 `published_at` 時，矩陣明確寫「未記錄」，不把 local mtime 當成官方發布時間；`取得／觀察` 才使用檔案 mtime 或 quick receipt；`可得` 只有在 availability contract 或明確 receipt 存在時才填入。日資料的 expected 只由 `OfficialTradingCalendar` 的官方 session 決定，月／季資料由公告 cadence 與 PIT available date 決定。

### 4.1 每日行情、指數、分點與衍生資料

| 來源 | 權威／頻率 | 實際期間；發布／取得／可得 | 覆蓋率、缺日、重複／異常 | 下游／入口／任務／owner | 狀態 |
|---|---|---|---|---|---|
| `twse.daily_prices.raw` | TWSE `MI_INDEX/ALLBUT0999`；官方收盤後每日 | target `20260908`；publish 未記錄；observed 04:20:07 PDT；quick receipt 04:32:45 | 1,095 rows/codes；10/10 official sessions；target duplicate 0 | `UpdateService.update_daily` → `daily_prices`；04:20 quick；Data Engineering | `current` |
| `tpex.daily_prices.raw` | TPEx OpenAPI daily close quotes；官方收盤後每日 | target `20260908`；publish 未記錄；observed 04:20:09；quick receipt 04:32:45 | 866 rows/codes；10/10 sessions；schema/date/code set 通過 | `update_tpex_daily_price_range` → `daily_prices`；04:20 quick；Data Engineering | `current` |
| `sqlite.daily_prices` | TWSE + TPEx raw 的正式 SQLite read model；每日同步 | latest `20260908`；source publish 未記錄；SQLite receipt 04:32:45 | 1,961 target rows，與 raw 合計及 code set 精確對帳；10/10；PK duplicate 0 | `sync_source_to_sqlite('daily_price_files')`；recommendation／decision desk | `current` |
| `meta_data/market_index.csv` | TWSE FMTQIK／market index CSV；官方每日 | latest `20260908`；publish 未記錄；observed 04:20:12；receipt 04:32:45 | historical 3,078 rows；target 1 row；10/10；schema/date 驗證 | `UpdateService.update_market`；04:20 quick；market regime／benchmark | `current` |
| `sqlite.market_indices` | official market CSV；每日 read model | latest `20260908`；available receipt 04:32:45 | 3,078 rows；target 1；10/10；date/name duplicate 0 | `sync_source_to_sqlite('market_index')`；market consumers | `current` |
| `meta_data/industry_index.csv` | TWSE `MI_INDEX` industry index；官方每日 | latest `20260908`；publish 未記錄；observed 04:20:17；receipt 04:32:45 | 約 11.5 MB；target 75 rows；10/10；schema/date 驗證 | `UpdateService.update_industry`；04:20 quick；industry／benchmark | `current` |
| `sqlite.industry_indices` | official industry CSV；每日 read model | latest `20260908`；available receipt 04:32:45 | 211,300 rows；target 75；10/10；date/name duplicate 0 | `sync_source_to_sqlite('industry_index')`；industry mapper／sector rotation | `current` |
| `broker_flow/*/daily` | MoneyDJ branch pages + `broker_branch_registry.csv`；每 branch 每交易日 | latest `20260908`；publisher time 未記錄；observed 04:22:42；receipt 04:32:45 | 48 branches；target 6,943 rows、820 codes；10/10；natural PK duplicate 0 | `BrokerBranchUpdateService`／`UpdateService.update_broker_branch`；04:20 quick；Data Engineering | `current` |
| `sqlite.broker_flows` | MoneyDJ branch raw read model；每日 | latest `20260908`；available receipt 04:32:45 | 1,022,130 rows；target 6,943；10/10；natural key duplicate 0；date+code repeated 6,123 是預期粒度 | `sync_source_to_sqlite('broker_branch_files')`；research-only broker flow | `current` |
| `technical_analysis/*_indicators.csv` | 由 SQLite daily 計算的 derived indicator；daily 後 | latest observed 04:28:04；calculation receipt 04:32:45；非 upstream publish | 2,148 files；DB target eligible 1,958／1,958；3 daily observations outside history eligibility；無 forward-fill | `calculate_technical_indicators`；04:20 quick；legacy／research consumers | `current`（以 SQLite technical 為準） |
| `sqlite.technical_indicators` | `daily_prices` derived read model；daily after price sync | latest `20260908`；available receipt 04:32:45 | 5,242,035 rows；3,098 dates；target 1,958；PK duplicate 0；10/10 | `UpdateService.calculate_technical_indicators`；recommendation／decision desk | `current` |

### 4.2 公司、基本面與可得日

| 來源 | 權威／頻率 | 實際期間；發布／取得／可得 | 覆蓋率、缺日、重複／異常 | 下游／入口／任務／owner | 狀態 |
|---|---|---|---|---|---|
| `meta_data/companies.csv` | official company registry；static/event | 2,343 rows；data date 2026-08-10／08-11；local mtime 2026-08-11；upstream receipt 未記錄 | 有檔可讀；無 validity window，不能作歷史 PIT universe | `scripts/update_company_registry.py`；未接 daily quick；Company Data owner | `not_applicable`（存在但不代表 fresh） |
| `meta_data/broker_branch_registry.csv` | branch registry／MoneyDJ mapping；static/event | 48 rows；local mtime 2026-07-06；upstream receipt 未記錄 | 48 active routes；無 validity window | broker updater；無獨立排程；Data Engineering + source owner | `not_applicable` |
| `financial_data/*.csv` | financial raw cache；monthly／quarterly | latest file mtime 2024-07-05；sample monthly 到 2024-03、statement 到 2023-Q4；receipt 未記錄 | 6,258 files；不能拿 file MAX／mtime 當 2026 completeness | `fundamental_data.py`／statement parser；standalone backfill；Fundamental owner | `not_applicable`／legacy raw |
| `fundamental.monthly_revenues` | TWSE／TPEx／MOPS announcement + governed availability；monthly | latest `2026-06`；expected `2026-07`；DB max available `2026-07-15`；candidate fetch 2026-09-08T21:24:25Z，HTML 出表 2026-09-09 Taipei，保守 available 2026-09-10 | 246,331 rows、147 periods、1,849 codes；expected absent | `UpdateService.dry_run/apply_mops_monthly_revenue_backfill`；candidate route；Fundamental + Data Engineering | `stale` |
| `MOPS 2026-07 snapshot` | MOPS static official report；monthly candidate | 1,851 rows；TWSE 992 + TPEx 859；fetch 2026-09-08T21:24:25Z；出表 2026-09-09 Taipei | duplicate 0、invalid 0；raw/candidate only，未寫 DB | `fetch_mops_monthly_revenue_snapshot_candidate`；非 daily quick；Data Engineering，待 Fundamental owner | `candidate_ready` |
| `fundamental.monthly_availability_map` | TWSE／TPEx／MOPS governed PIT mapping；event/static | existing 1,832 rows，mtime 2026-07-14；candidate available 2026-09-10 | candidate 1,851 rows；missing 0、duplicate 0、diagnostics 0；merge ready，正式檔未改 | `apply_monthly_revenue_availability_candidate.py`／recovery CLI；人工確認後 atomic merge | 現有 `not_applicable`；candidate `ready_for_merge` |
| `fundamental.quarterly_statements` | MOPS statement publication/document lanes；quarterly | latest `2024-Q1`；expected `2026-Q2`；DB max available 2026-06-17；publish receipt 未記錄 | 1,645,555 rows、40 periods、1,567 codes；expected absent | statement candidate／backfill CLI；無 production quick；Fundamental owner | `stale` |
| `fundamental.statement_availability_map` | MOPS statement availability；static PIT | file 不存在；無 successful check／available date | 不用 statement MAX(period) 冒充 mapping | 尚未有可套用正式入口；Fundamental owner | `unknown`／`file_missing` |
| `fundamental.valuation_metrics` | valuation source policy／P/E backfill；cadence 尚未註冊 | as-of 2026-06-15--08-06；publish/fetch receipt 未記錄 | 1,671 rows、841 codes；不能以 MAX(as_of) 判完整 | `scripts/backfill_valuation_metrics.py`；recommendation／research；Valuation owner | `not_applicable`（待定 cadence） |
| `meta_data/stock_data_whole.csv` | legacy aggregate；需 source receipt | 約 486 MB；mtime 2026-07-14 | 非 daily complete proof | legacy consumers；安全更新／手動 merge | `not_applicable` |
| `meta_data/all_stocks_data.csv` | legacy aggregate；非 authoritative | 約 2.22 GB；mtime 2026-06-29 | 不作 daily completeness | legacy consumers | `not_applicable` |
| `industry_analysis/` | derived industry analytics；依 upstream daily／industry data 計算，沒有獨立官方發布頻率 | 206 files；最新 local mtime 2025-02-20；無 calculation receipt | derived cache，未建立 bounded period／coverage contract；不能以 mtime 代替 current | legacy industry consumers；沒有接入 daily quick；Industry Analytics owner | `not_applicable`／legacy derived |
| `features/` | derived feature cache；依策略／研究流程產生，沒有獨立官方發布頻率 | 21 files；最新 local mtime 2025-03-04；無 calculation receipt | derived cache，未建立 PIT／coverage contract；不作行情 freshness 證明 | research／ML consumers；沒有接入 daily quick；Feature owner | `not_applicable`／legacy derived |

### 4.3 官方日曆、公司行動、P0 與不存在類型

| 來源 | 權威／頻率 | 實際期間；發布／取得／可得 | 覆蓋率、缺日、重複／異常 | 下游／入口／任務／owner | 狀態 |
|---|---|---|---|---|---|
| `OfficialTradingCalendar` | TWSE `holidaySchedule` + temporary closure evidence；年度 + event | 2026 cache capture 2026-09-07T19:20:27Z；HTTP 200、hash-bound；probe 2026-09-08 14:23:27 PDT | 2026 年完整 365 日；最近 10 sessions 精確為 08-26、27、28、31、09-01、02、03、04、07、08 | `official_trading_calendar.py`；daily updater／freshness／TPEX history；Data Engineering | `current` |
| `meta_data/Date_table.csv` | local historical calendar，非官方 | 4,920 rows；mtime 2024-06-20；無近期 official receipt | 僅 legacy inventory；不可作假日推算 | 不再作 production expected-date input | `not_applicable`／non-authoritative |
| `institutional_flows` | TWSE T86／TPEx institutional；daily candidate | table 0 rows；無 production available period | schema 存在但 ingestion disabled | P0 route registry；無 production downstream | `not_applicable`／candidate-only |
| `credit_transactions` | TWSE MI_MARGN／TPEx margin；daily candidate | table 0 rows；無 production available period | schema 存在但 ingestion disabled | P0 route registry；無 production downstream | `not_applicable`／candidate-only |
| `tdcc_shareholding` | TDCC public holdings OpenAPI／legacy id 1--5；weekly/latest candidate | table 0 rows；官方 endpoint 不提供完整歷史輪詢 | 不以執行日改寫資料日 | P0 route registry；無 production downstream | `not_applicable`／candidate-only |
| corporate action event lanes | TWSE／TPEx ex-dividend、減資、停復牌等；event | 無 production SQLite table；event status 對 `TWT49U/6949/2025-12-10` 報 `unlinked_revision_conflict`，last good 2026-09-06 | failed event 未寫正式 DB；revision lineage 待 owner | `baldr-official-market-events-daily` 04:50；Corporate Action owner | production `not_applicable`；event `failed` |
| microstructure restriction lanes | disposition、periodic call auction、full delivery、limit lock；event | 無 production table；只有 route／candidate capability | 不從行情缺檔反推 restriction | capability registry partial；Microstructure owner | `not_applicable`／candidate-only |
| `derivatives.futures_options` | official futures/options source 應為 event/daily | DATA_ROOT、schema、updater registry 均不存在 | 不新建假表／假資料 | 無入口、task、consumer | `not_applicable`／type absent |

## 5. 根因、修補與閉環行為

### 5.1 日曆、週末、假日與盤中 cutoff

- 新增 `OfficialTradingCalendar.require_trading_days_in_range()` 與 `get_recent_official_trading_days()`；所有 production date range 先從 TWSE annual `holidaySchedule`／temporary closure evidence 解決，無法確定時直接 `OfficialTradingCalendarError`，不 fallback 到 weekday。
- `UpdateService._iter_weekday_date_keys` 保留舊名稱以維持 UI／legacy caller contract，但實際已改成官方交易日；TPEX historical plan、daily batch、market／industry batch、broker update、freshness probe、quick runner 均共用同一 resolver 與 immutable repo cache。
- probe 使用 local Pacific `04:30` cutoff：盤前缺檔為 `expected_wait`，盤後仍缺為 `stale`；假日／週末沒有 session 不列為缺行情。合法 holiday-only TPEX range 會回 `success=true, no_op=true`，不呼叫 API；真正的日期反轉或 calendar failure 仍失敗。
- 不使用 `Date_table.csv`、local weekday 或資料庫 `MAX(date)` 當官方日曆；不 forward-fill 行情。

### 5.2 SQLite sync 與重跑安全

- market／industry sync 從整表 `DELETE/replace` 改成只針對驗證過的 date keys 做 scoped replacement；中斷或部分來源不會抹掉歷史表。
- `UpdateService.update_daily` 及 batch runner 會傳入明確 `--data-root`／`--output-root`，避免排程 process 讀錯 working directory 的 DB／raw root。
- market／industry batch 的 `False` 不再被 UpdateService 當成默認成功；未知 return type 也 fail-closed。batch main 以 `fail_count == 0` exit code 回傳，例外／失敗日期不再被吞掉。
- quick runner 保留既有 `running`／terminal receipt、source step summary、retry／delay／checkpoint 邏輯；本輪沒有另造 writer 或平行 scheduler。

### 5.3 Raw／DB／衍生資料品質

- freshness probe 以最近 10 個官方 session 檢查每個 source 的 bounded missing periods；raw market source 另與 SQLite row count／exact code set 對帳。
- technical status 必須同時滿足 daily latest、technical latest、10-session history 與 eligible-stock coverage；只有 `MAX(technical.date)` 新而 coverage 不全時會標 `partial`。
- broker 的 date+code 重複觀測是多 branch／trade type 的業務粒度，不再把 `row_count - distinct_code_count` 誤當 natural PK duplicate；natural key readback 為 0 duplicate。
- `source_statuses` 統一輸出 `current`、`expected_wait`、`stale`、`failed`、`partial`、`not_applicable`、`unknown`，包含 authority、frequency、actual／published／available／expected、coverage、missing periods、duplicates、reason、entry、task、owner、downstream、time provenance。

### 5.4 月營收候選與失敗可見性

- MOPS snapshot harvester 只保存 raw HTML／candidate numeric snapshot，不會偽造公告日或直接寫正式表。
- raw snapshot-only dry-run 曾正確拒絕 1,851 筆 `snapshot_mapping_incomplete`；使用同批官方 HTML 產生 governed mapping 後，validator／merge plan／recovery plan 均通過，證明缺口是 availability contract 未接線，不是把數值偷偷視為可得。
- 正式 recovery 仍必須先檢查 target mapping hash、建立 mapping／DB backup、取得既有 lock、`BEGIN IMMEDIATE` 寫入並留下 journal/evidence；本輪 Direct lock 存在，故沒有嘗試 apply。

### 5.5 狀態投影

`UpdateService.check_data_status()`、`check_data_overview()`、`check_source_detail()` 會唯讀載入 `OUTPUT_ROOT/scheduled/data_freshness/latest_status.json`，由 `update_service_status_support.apply_freshness_receipt()` 映射到既有 `daily_data`、market、industry、broker、technical、monthly status keys。`failed/unknown` 映射 legacy error；`stale/partial/expected_wait` 映射 lagging／等待語意，不覆蓋實際日期。季度 status 已在 probe 與 projection contract 保留，但現有 update page 沒有新增 UI key；這是刻意交給 root／UI owner 的跨 owner interface，不在本輪改個股 UI。

## 6. 真實修補前後證據

| 證據 | 修補前 | 修補後／讀回 | 判讀 |
|---|---|---|---|
| 舊 freshness receipt | `D:\Min\Python\Project\FA_Data\output\scheduled\data_freshness\latest_status.json` 在 05:00 回 `passed`，主要檢查 latest date／file exists | 同一資料狀態用新 probe 重查 | 舊綠燈無法證明 bounded market coverage 或 fundamentals cadence，已被更嚴格 probe 取代 |
| 自然 quick run | `run_id=20260908-49768`，04:20:03--04:32:45 PDT，原有 receipt status `passed` | TWSE／TPEx／daily／market／industry／broker／technical 全部完成；48 branches 48 dates 成功；technical 1,958 success、0 failed、6 insufficient | 這是實際資料產物，不是 fixture；probe 以它作 receipt context 但另做 raw／DB／calendar 對帳 |
| 日行情 bounded audit | 舊 probe 只看 target latest | 新 probe 的 10 sessions = 10/10；TWSE 1,095 + TPEx 866 = SQLite 1,961，code set／row count 一致 | `twse.daily_prices.raw`、`tpex.daily_prices.raw`、`sqlite.daily_prices` `current` |
| 衍生 indicators | 舊邏輯可因 latest date 相同而放行部分 coverage | target eligible 1,958、covered 1,958、10,000 bp；3 個 daily observations 被 eligibility 排除，未補值 | `sqlite.technical_indicators` `current`，缺 coverage 會 `partial` |
| 新 freshness probe | 舊 receipt `passed` | 2026-09-08 14:23:27 PDT，`status=degraded`、7 current、14 not_applicable、2 stale、1 unknown、errors 0 | 正確曝光月／季基本面缺口，沒有把 `MAX(date)` 當完整 |
| MOPS numeric candidate | snapshot-only dry-run：1,851 raw rows，0 normalized，1 `snapshot_mapping_incomplete`，unmatched 1,851 | 官方 HTML mapping：TWSE 992 + TPEx 859 = 1,851；mapping missing 0／duplicate 0／diagnostics 0；recovery preview normalized 1,851／unmatched 0／ready true | candidate 已具備下一步 apply 條件，但尚未寫 production |
| 官方事件 | event artifact 仍有 `unlinked_revision_conflict` | 失敗狀態保留，未把 conflict 轉成正式資料；last known good 仍保留 | 跨 owner gap，不能以行情更新成功掩蓋 event source failure |

### 6.1 新 probe 的實際 source counts

```json
{
  "status": "degraded",
  "checked_at": "2026-09-08T14:23:27-07:00",
  "expected_official_session": "20260908",
  "expected_official_session_window": [
    "20260826", "20260827", "20260828", "20260831", "20260901",
    "20260902", "20260903", "20260904", "20260907", "20260908"
  ],
  "source_status_counts": {
    "current": 7,
    "not_applicable": 14,
    "stale": 2,
    "unknown": 1
  },
  "warnings": [
    "monthly_revenue_expected_period_not_available",
    "quarterly_statement_expected_period_not_available"
  ],
  "errors": []
}
```

## 7. 排程與每日增量閉環

### 7.1 已存在且已觀測的 task

唯讀 artifact `output/v4_next_ops/task_registration_after_forward_20260908.json` 於 2026-09-08 04:54:03 PDT 讀回：`task_count=18`、`available_count=18`、`wrapper_missing_count=0`、`action_mismatch_count=0`、`configuration_ready=true`、`query_only=true`、`side_effect_free=true`。本輪沒有註冊新 task，也沒有修改既有 task。

與本交付直接相關的時間線：

| Task | 時間 | 最近自然讀回 | 下次／判讀 |
|---|---|---|---|
| `baldr-data-update-quick-daily` | daily 04:20 | 2026-09-08 04:20，LastResult 0；quick receipt passed | 2026-09-09 04:20；先以 official calendar 解決 session，再依 raw→SQLite→technical sequence 執行 |
| `baldr-data-freshness-check-daily` | daily 05:00 | 2026-09-07 05:00，LastResult 0；新 probe 可由 wrapper 產生 degraded receipt | 每日 05:00；只讀，對 current／expected_wait／stale／failed／N/A 分類 |
| `baldr-official-market-events-daily` | daily 04:50 | 2026-09-08 LastResult 2；`unlinked_revision_conflict` | 保留 failed artifact，待 Corporate Action owner 修 revision lineage |

其餘 15 個 task（PIT、recommendation、Evidence、ML、Paper、weekly collection）已在 artifact 內列出，但不是本輪資料更新 writer；不可把其 LastResult 當成行情 source 成功。此刻重新執行 `inspect_scheduled_task_registration.py --repo-root .` 曾因 host 的 Task Scheduler API 回傳 `The system cannot find the path specified`；不以這次 API unavailable 推導 task missing，沿用上面的既有 18/18 query-only artifact，待 host 權限恢復再更新觀測。

### 7.2 每日 sequence

```text
OfficialTradingCalendar
        ↓  (official sessions + cutoff, fail-closed)
TWSE raw + TPEx raw  --bounded retry/rate control/checkpoint--
        ↓
scoped SQLite daily sync (no whole-table delete)
        ↓
market / industry / broker scoped sync
        ↓
technical indicators recompute + eligible coverage check
        ↓
quick terminal receipt + append-only history
        ↓
05:00 read-only freshness probe
        ↓
existing UpdateService status projection
```

月營收／季報不會因 daily quick 的交易日成功而被標成 current；它們按 announcement／available cadence 另行檢查。未發布時回 expected wait，已發布但未匯入回 stale，解析／mapping／API 錯誤回 failed 或 unknown。

## 8. 測試與語法驗證

執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_update_service_status.py tests/test_official_trading_calendar.py tests/test_scheduled_data_freshness_probe.py tests/test_scheduled_data_update_runner.py tests/test_update_service_status_support.py tests/test_broker_branch_decode.py tests/test_tpex_daily_price_history_plan.py tests/test_scheduled_cmd_scripts_exist.py tests/test_scheduled_scripts_exist.py -q -o addopts=
```

結果：`115 passed, 1 warning in 3.51s`。唯一 warning 是 pytest 無法寫入 `.pytest_cache` 的環境 ACL，不是測試失敗。

另以 `py_compile` 對本輪修改的 update service、calendar、batch、probe、runner 與測試檔執行，exit code 0。

測試覆蓋的真實風險邊界：

- official holiday／weekend、unresolved calendar fail-closed、盤前 expected wait。
- raw／SQLite 部分股票缺漏與 exact code-set reconciliation；API／calendar failure。
- TWSE／TPEx、market／industry rerun idempotency；market／industry scoped sync 不刪歷史。
- broker branch parsing／route coverage；trade_type natural key 與重跑。
- indicator eligible coverage、TPEX source retry／date mismatch、holiday-only no-op。
- freshness receipt status projection；missing／stale／partial／failed 與 candidate/N/A 區分。

本輪沒有把 fixture 測試結果寫成自然資料成果；自然成果只採用 D 槽既有 quick receipt、正式 SQLite 有限讀回、實際 MOPS bounded candidate 與現存 scheduler artifact。

## 9. DB、磁碟、WAL 與 Direct 協調

- probe 以 `file:...twstock.db?mode=ro`、`PRAGMA query_only=ON` 執行；WAL mode 讀回，當時 `-wal` 0 bytes、`-shm` 存在；沒有 checkpoint／VACUUM／全庫覆寫。
- 現有 `twstock.db.bak` 約 1.486 GB、最後修改 2026-06-11；不是本輪 2026-09-08 的新 backup。因 Direct heavy-chain lock，本輪沒有冒險建立新的正式 DB backup 或寫入。
- Direct status `D:\Min\Python\Project\FA_Data\output\scheduled\ml_direct_chain_maintenance\latest_status.json` 仍為 `running`；database mode `ro`、`writes_source_database=false`，heavy lock `D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock` 存在且被另一程序鎖住。不能與它爭用 `BEGIN IMMEDIATE`，因此沒有執行月營收 SQLite apply 或任何 quick writer 重跑。
- Direct status 內的 storage preflight 為 free `333,590,917,120` bytes、minimum reserve `214,748,364,800` bytes；本輪即時 `Get-PSDrive` 讀回 D free `299,237,740,544` bytes（約 278.7 GiB），仍高於 200 GiB reserve。C free `176,637,206,528` bytes（約 164.5 GiB）；TEMP 為 `C:\Users\archi\AppData\Local\Temp`，沒有把 C/TEMP 當可無限擴張空間。
- Direct frozen raw manifest／shards／依賴檔及其 hashes 未修改；本輪 candidate 寫在 repo ignored output，不觸碰 frozen raw。

## 10. 跨 owner 介面需求與後續 apply 契約

### 10.1 Fundamental Data owner：月營收

已提供可驗證 candidate；正式 owner handoff 必須接受下列 contract，不得只給一個數值 snapshot：

```text
stock_code
period
as_of_date
announced_date
available_date
source
source_version
availability_contract_version
evidence_class
source_hash
revision
parent_revision
```

本次 1,851 rows 的來源為 MOPS official HTML：TWSE 992、TPEx 859；mapping `available_date=2026-09-10` 是以官方出表日 2026-09-09 加保守 1 calendar day，不能改成 fetch day 來讓 UI current。owner 確認後使用既有 `scripts/apply_monthly_revenue_recovery.py`，先 preview／target hash，再在 Direct lock 解除且 backup／journal 可用時執行：

```powershell
.\.venv\Scripts\python.exe scripts\apply_monthly_revenue_recovery.py `
  --candidate-mapping <MOPS_AVAILABILITY_CANDIDATE> `
  --snapshot-file <MOPS_SNAPSHOT> `
  --target-mapping D:\Min\Python\Project\FA_Data\meta_data\monthly_revenue_availability.csv `
  --db-file D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --backup-dir <TASK_SPECIFIC_BACKUP_DIR> `
  --evidence-file <TASK_SPECIFIC_EVIDENCE_JSON> `
  --source-version mops-static-snapshot-2026-09-08 `
  --apply --confirm apply-monthly-revenue-recovery --format json
```

套用後必須重新以 query-only probe 讀回：`fundamental_monthly_revenues` latest `2026-07`、新增 1,851 rows、PK／source_version 無 duplicate、mapping／DB backup／journal 完整；若 DB transaction 失敗，沿用既有 recovery rollback，不手動刪 raw。

### 10.2 Fundamental Data owner：季報

提供 `fundamental_statement_availability.csv`，至少包含 stock、period、as_of、announced、available、source、source_version、source_hash、revision lineage；先以 MOPS official publication rows 產生 candidate，再讓既有 statement backfill CLI preview。沒有此檔時維持 `unknown`，不把 `fundamental_statement_items` 的舊 MAX period 改名成「最新」。

### 10.3 Corporate Action owner

針對 `TWT49U / 6949 / 2025-12-10` 提供可核對的 source revision identity、parent revision、effective date、available date、source hash，解決 `unlinked_revision_conflict` 後才可重跑 04:50 task；保留 last-known-good，不覆蓋 frozen manifest，也不把事件型資料塞進 daily market table。

### 10.4 Update page／root interface

現有 update page 的 status DTO 沒有 quarterly card key；本輪只把 probe／status projection 做成可讀 contract，未改 UI。root 若要在既有頁面顯示季報，應新增明確 `quarterly_statements` source key 與上述七狀態映射，並同步 Manual；不能把 monthly card 改名兼用季度資料。

### 10.5 Scheduler owner

host 的 Task Scheduler API 可讀時，重跑既有 inspector，更新 `task_registration_after_forward_20260908.json`；不要新增第二個 quick／freshness task。月營收若要自動抓 candidate，應更新既有 daily freshness wrapper 的明確 bounded candidate route，並維持 raw-only／PIT approval，不在 task 內偷偷 apply 正式 DB。

## 11. 給 root 的中央文件精確補丁（本分支未直接修改）

以下內容是可直接套用的文字補丁；anchor 使用目前文件已有的 exact headings，避免 root 需要猜插入位置。

### 11.1 `docs/07_guides/APPLICATION_MANUAL.md`

Anchor：`## 4. 數據更新` → `### 4.2 快速更新與安全更新`，放在該節兩個模式表格之後、現有「TWSE 補檔遇到平日休市」段落之前：

```markdown
#### V4 freshness 與官方交易日閉環（2026-09-08）

每日更新與 freshness probe 共用 `OfficialTradingCalendar` 的 TWSE `holidaySchedule`／temporary closure evidence；不再以 weekday、`Date_table.csv` 或 `MAX(date)` 猜交易日。盤前 04:30 前缺少下一個官方 session 是「等待公告／等待來源」，盤後仍缺少才是「過期」；官方日曆無法解析時 fail-closed，不修改日期、不 forward-fill 行情。

唯讀 probe 會檢查最近 10 個官方交易 session、TWSE／TPEx raw 與 SQLite 的 row count／code set、market／industry／broker 覆蓋、以及 technical eligible coverage。狀態 token 為 `current`、`expected_wait`、`stale`、`failed`、`partial`、`not_applicable`、`unknown`；`candidate` 只代表已取得候選，不代表正式 mapping／SQLite 已套用。probe 的 `latest_status.json` 由既有 `UpdateService.check_data_status` 唯讀投影到更新頁，不會因檔案存在而把缺月／缺季資料標為正常。

合法假日區間沒有官方交易日會回報成功 no-op，不呼叫 API；HTTP、timeout、schema、parser、mapping 或 SQLite transaction 失敗會保留 failed／diagnostic。market／industry 同步只替換驗證過的 date keys，不會以整表 DELETE 取代增量交易。

月營收 MOPS snapshot 與公告／可得日 mapping 是兩個不同 gate。snapshot 可用時仍須先跑 availability validator／merge preview，再由 owner 確認後執行 `scripts/apply_monthly_revenue_recovery.py`；正式 apply 前要有 task-specific DB／mapping backup、journal、WAL transaction 與 Direct heavy-chain lock 狀態讀回。季報沒有 availability map 時顯示 `unknown`，不能用月營收或 legacy aggregate 代替。
```

### 11.2 `docs/00_core/PROJECT_SNAPSHOT.md`

Anchor：`## 2026-09-08 V4 持續目標啟動（尚未完成）` 之下，放在該節第一個 bullet 前：

```markdown
- **資料更新 freshness 閉環交付（2026-09-08）**：Data Engineering 已將 daily update、TWSE／TPEx／market／industry／broker／technical sync 與 `data_freshness_probe.py` 接到共用 TWSE official calendar，修補 weekday／MAX(date) false-green、market／industry 整表刪除、錯 root、batch failure swallowed 與 holiday-only TPEX 失敗語意。真實 2026-09-08 讀回為 7 個 production daily sources `current`，最近 10 個 official sessions 完整；probe 正確標出月營收 `2026-06 → expected 2026-07`、季報 `2024-Q1 → expected 2026-Q2` 與缺少 statement availability map，整體維持 `degraded`，沒有為了變綠而改日期或補行情。MOPS 2026-07 snapshot 的 1,851 rows 及 official HTML availability candidate 已完成 read-only recovery preview（normalized 1,851、unmatched 0、ready_for_apply=true），但尚未寫正式 mapping／SQLite，等待 Fundamental owner PIT 接受與 Direct heavy-chain lock 解除。完整來源矩陣、測試與 root 精確 Manual 補丁見 `docs/06_qa/V4_DATA_FRESHNESS_HANDOFF.md`。
```

## 12. 剩餘限制與完成判定

目前不能宣稱以下項目已完成：

- 月營收正式 mapping／SQLite 尚未 apply；原因是治理接受與 Direct heavy-chain lock，不是把來源判成未發布。
- 季報 production data 與 availability map 落後／缺檔；沒有合法新 rows 就不造資料。
- 官方公司行動 event 有 revision conflict；candidate route 不等於 production table。
- institutional／credit／TDCC 仍是 schema-only candidate；derivatives futures/options 在本專案正式設定中不存在。
- companies、broker registry、legacy aggregate、valuation metrics、industry_analysis、features 缺少統一 upstream validity／publish receipt；狀態刻意為 N/A 或需另定 cadence，不是綠燈。
- Task Scheduler inspector 的即時 API 在本次 host 讀取失敗；已有 18/18、action／wrapper 對齊的 query-only artifact，需權限恢復後再刷新。

解除 Direct lock 後的唯一安全順序是：確認 lock／DB backup／WAL → 重跑 candidate validator 與 recovery preview → owner 明確接受 → 使用既有 recovery apply／journal → query-only DB／mapping／freshness readback → 重新確認 technical derived coverage。任何一步失敗都保留 receipt／diagnostic，不刪 raw、不把 partial 改成 current。

## 13. Ignored QA 證據位置

本輪 raw QA 與 candidate 均在 ignored output，供 root／owner 讀回：

- [probe_after_patch.json](C:/Projects/PythonProjects/technical_analysis/output/v4_data_freshness_handoff_20260908/probe_after_patch.json)
- [probe_after_patch.log](C:/Projects/PythonProjects/technical_analysis/output/v4_data_freshness_handoff_20260908/probe_after_patch.log)
- [MOPS snapshot](C:/Projects/PythonProjects/technical_analysis/output/v4_data_freshness_handoff_20260908/monthly_revenue_mops_snapshots/mops_monthly_revenue_snapshot_2026-07_2026-07_2026-09-08.csv)
- [availability candidate](C:/Projects/PythonProjects/technical_analysis/output/v4_data_freshness_handoff_20260908/monthly_revenue_mops_snapshots/monthly_revenue_availability_candidate_2026-07.csv)
- raw MOPS HTML：`C:\Projects\PythonProjects\technical_analysis\output\v4_data_freshness_handoff_20260908\monthly_revenue_mops_snapshots\raw_html\{twse,tpex}_2026-07.html`
- scheduler registration readback：`C:\Projects\PythonProjects\technical_analysis\output\v4_next_ops\task_registration_after_forward_20260908.json`
- natural quick receipt：`D:\Min\Python\Project\FA_Data\output\scheduled\data_update_quick\latest_status.json`
- Direct status／lock：`D:\Min\Python\Project\FA_Data\output\scheduled\ml_direct_chain_maintenance\latest_status.json`、`D:\Min\Python\Project\FA_Data\output\release_v4\.ml_heavy_chain.lock`

本文件本身是唯一應進 Git 的交接文件；D 槽 raw、candidate、SQLite 與 runtime outputs 不在提交範圍。

## 14. Root 整合複核（2026-09-08）

本輪 Data／ML owner 的獨立 readback 確認 2026-09-08 TWSE／TPEx raw、SQLite daily／market／industry／broker／technical 的 bounded current 證據，並保留月營收、季報 availability 缺件為 `degraded`／`unknown`。freshness／calendar／scheduled 定向 suite 為 `115 passed`，bounded update suite 為 `100 passed`；Direct／scheduler／capacity 定向 suite 為 `50 passed, 1 skipped`，10 個變更 source 的 mypy 與變更 Python `py_compile` 均成功。Paper isolated scheduler 的 fixture 修補後，root 獨立重驗該檔 `9 passed`；Direct 目標 build／resume 測試與 assembler progress 隔離測試也已分別通過。上述是本輪工程／來源狀態證據，不能把 candidate 或測試 fixture 當正式基本面 apply、Direct terminal、OOC fit 或自然成效。

Root 另保存整合前的 canonical freshness receipt 至 `output/v4_next_root/freshness_canonical_before_integration.json`，再以實際 `2026-09-08T20:12:26-07:00` 的新 probe 重新產生 canonical status readback；該次命令 exit 0、整體為 `degraded`，source 分布為 `7 current / 2 stale / 14 not_applicable / 1 unknown`，`errors=[]`。`read_report('2330')` 於 Taipei `2026-09-09` 的 canonical readback（`output/v4_next_root/stock_report_canonical_freshness_readback.json`）顯示 price／technical／broker fresh，月／季基本面仍 stale；這是新的 canonical receipt 與 readback，不把舊 receipt 備份誤寫成已取代的來源資料。

Root 整合複核確認 Direct 實際 checkpoint 正確完成 2014–2020 七個年度，2021 因兩次 capacity hold 暫停，2022–2026 尚無 finalized manifest；live builder／maintainer PID 已不存在，heartbeat 停在 `running`，所以狀態維持未完成。15 個 Direct dependency 的 frozen bytes／SHA-256 readback 全部匹配；raw manifest canonical content hash 與實體 file SHA 分開保存。這些 Direct 結果與本文件的 daily freshness current 狀態分開判讀，不把 Direct 等待誤寫成資料更新失敗，也不把 daily current 誤寫成模型訓練完成。

容量仍使用 current guard 固定門檻：`40 GiB temporary + 35 GiB new persistent + 200 GiB reserve = 275 GiB`（`295,279,001,600` bytes）。清理後 D: free `318,606,434,304` bytes（`296.725364685 GiB`），margin `23,327,432,704` bytes（`21.725364685 GiB`）；2021 已保存 temporary peak `23,169,343,755` bytes（`21.578132878 GiB`），兩次 hold 短缺為 `49,659,904` 與 `20,914,176` bytes，最大值是前者。只越過歷史 hold 點至少需 `49,659,904` bytes（`47.359 MiB`）觀測下限；1 GiB 只是操作緩衝。按 Direct root 已有 `2,525,374,802` bytes、plan persistent 上限 `15,333,023,892` bytes 推得 remaining persistent `12,807,649,090` bytes（`11.928052725 GiB`），以已觀測 temporary peak 代表後續單年並加最大 hold 短缺，從目前 margin 推得全 run continuation lower bound 為 `12,699,220,045` bytes（`11.827070308 GiB`）。這是待量測的保守下限，不是 2021 剩餘或 2022–2026 的完成保證；本輪不 resume、不降低 reserve、不改 D 原始資料。

本節的 daily freshness／update 測試與 bounded source readback 是本輪 owner 的獨立驗收；Direct 七年 checkpoint、live 停止、15/15 freeze 與容量 hold 的整合結論由 root 複核。尚未完成項維持原狀：月營收 candidate 尚未正式 apply、季報 availability map 缺件、scheduler host 即時 inspector 待權限恢復，以及 Direct 後續年度／root manifest／teacher／OOC／release gate。自然與外部等待不以本輪測試數或目前容量 margin 取代。
