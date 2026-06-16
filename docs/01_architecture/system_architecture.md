# 系統架構

> **最後更新**：2026-06-15
> **定位**：本文件是目前模組邊界、依賴方向、資料流與高風險技術契約的架構權威。歷史遷移過程不在本文件維護。

## 1. 系統定位

本系統是一個可驗證、可回溯、可演化的台股投資決策系統。產品北極星與長期能力圖像見 [system_vision_specification.md](system_vision_specification.md)；本文件只描述目前架構與模組邊界。

目前已落地三個產品閉環：

1. 資料與市場狀態：Update → SQLite → Market Watch / Smart Money → 候選池。
2. 研究驗證：Recommendation → Research Lab / Backtest / Replay / Walk-forward → Promote。
3. 持倉檢查：Recommendation / Backtest → Portfolio → Condition / Chip Monitor → Journal → 回到研究。

目標中的第四閉環是 Daily Decision Desk：Market Intelligence → Daily Decision Desk → Watchlist Trigger / Portfolio Alert / Research Input。v1 已接上主 UI，作為每日決策頂層入口；目前由 service snapshot 聚合，Market Breadth v1 已由 SQLite `daily_prices` provider 接線，Sector Rotation v1 已由 SQLite `industry_indices` provider 接線，Watchlist Trigger v1 已由 `WatchlistService` 與 SQLite `technical_indicators` 共同推導接線，Portfolio Alert v1 已由 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService` 共同推導接線。

未來 6 個月的工程方向見 [ROADMAP_6M_ENGINEERING.md](../00_core/ROADMAP_6M_ENGINEERING.md)，舊 Roadmap 移交狀態見 [LEGACY_ROADMAP_CARRYOVER.md](../00_core/LEGACY_ROADMAP_CARRYOVER.md)。

## 2. 分層架構

```text
PySide6 UI
  ui_qt/
      |
      v
Application Services / DTO / Repository
  app_module/
      |
      +--> Decision Domain
      |      decision_module/
      |
      +--> Backtest Engine
      |      backtest_module/
      |
      +--> Portfolio Domain
      |      portfolio_module/
      |
      +--> Data Infrastructure
      |      data_module/
      |
      +--> Runtime Core
             runtime/
```

依賴方向只能由外層指向內層。Domain 與 Runtime core 不得反向依賴 Qt UI。

## 3. UI Layer

### 位置

- `ui_qt/main.py`
- `ui_qt/views/`
- `ui_qt/widgets/`
- `ui_qt/workers/`
- `ui_qt/bridges/`

### 責任

- 收集參數。
- 呼叫 application service。
- 顯示 DTO、DataFrame、圖表與狀態。
- 透過 worker 執行長任務。
- 處理工作區之間的導航與來源傳遞。

### 禁止事項

- 不直接實作策略評分、推薦理由或撮合規則。
- 不直接修改正式資料。
- 不在 UI 內複製 application/domain 計算。
- Runtime UI 不得直接讀寫 Runtime store。

### 目前 8 個頂層工作區

1. 數據更新
2. 市場觀察
3. 策略回測 / Research Lab
4. 推薦分析
5. 觀察清單
6. 持倉管理
7. Runtime Observatory
8. Daily Decision Desk（v1 首頁）

完整操作見 [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md)。

## 4. Application Layer

### 位置

`app_module/`

### 責任

- Use case orchestration。
- DTO 組裝與 UI contract。
- Repository 與保存流程。
- 資料來源選擇、fallback 與服務組合。
- 研究、推薦、回測與 Portfolio 來源追溯。

### 主要服務群

| 領域 | 主要元件 |
|---|---|
| 推薦與市場 | `recommendation_service.py`、`screening_service.py`、`regime_service.py` |
| 數據更新 | `update_service.py`、`broker_branch_update_service.py`、`sqlite_inspector_service.py` |
| 籌碼 | `broker_flow_service.py`、`portfolio_chip_service.py` |
| 回測 | `backtest_service.py`、`batch_backtest_service.py`、`optimizer_service.py`、`walkforward_service.py` |
| 推薦回放 | `recommendation_replay_service.py`、`recommendation_portfolio_backtest_service.py` |
| 保存與版本 | `backtest_repository.py`、`recommendation_repository.py`、`strategy_version_service.py`、`preset_service.py`、`universe_service.py` |
| Portfolio | `portfolio_service.py`、`portfolio_condition_monitor.py`、`portfolio_source_adapter.py` |
| Runtime | `runtime_services/`、`dtos/runtime_dtos.py` |

`app_module` 不依賴 `ui_app`。Legacy Tkinter UI 不是目前 service 架構的一部分。

Daily Decision Desk 後續應以 application service / DTO 聚合既有市場、推薦、watchlist 與 portfolio 結果，不得在 UI 層重算 scoring、screening、broker flow 或 portfolio logic. Market Breadth v1 由 `app_module.market_breadth_service.MarketBreadthService` 與 `SQLiteDailyPriceMarketBreadthProvider` 自 SQLite `daily_prices` 唯讀推導多方 / 空方 / 持平、成交量擴散與新高新低 metadata，並在指定日無資料時以最近可用交易日降級顯示。Sector Rotation v1 由 `app_module.sector_rotation_service.SectorRotationService` 與 `SQLiteIndustryIndexSectorRotationProvider` 自 SQLite `industry_indices` 唯讀推導領先 / 落後產業、5 / 20 日變化與輪動強度，同樣以 warnings 揭露 fallback 日期。Relative Strength / Liquidity Ranking v1 由 `RelativeStrengthLiquidityService` 與 `SQLiteDailyPriceRelativeStrengthLiquidityProvider` 自 SQLite `daily_prices` 唯讀推導 5 / 20 日相對強度與平均成交金額，輸出強勢、弱勢與低流動性代碼，不在 UI 層重算；歷史不足 21 天時降級為 DEGRADED 並警告。Watchlist Trigger v1 由 `WatchlistServiceWatchlistProvider` 與 `SQLiteRankingProvider` 結合，唯讀查詢 `technical_indicators` 產生個股強度 `score_bp` 與風險 `risk_alert`，並支援日期 fallback 降級警告（quality 改為 `DEGRADED`，在 `warnings` 中標註 `watchlist_trigger_as_of_fallback:<date>`）。Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，可把條件監控與籌碼風險彙總成每日持倉警示；若籌碼資料缺失、估算或不可用，會透過 `quality / warnings` 降級揭露，不補值。Portfolio Alert Attribution v1 屬於 `PortfolioAlertService` 的輸出責任，因為只有該 service 同時看得到 position source、condition monitor 結果與 chip summary。UI 與 Risk Prompt service 只能讀取 `PortfolioAlertSummary.attributions`，不得重新查詢或重算。Why Not / 風險提示 v1 由 `DecisionDeskRiskPromptService` 從既有 section DTO 的 quality、warnings、低流動性、相對弱勢、watchlist risk alert、portfolio alert 與 application service 提供的 fundamental diagnostics 推導，提供可行動風險提示，不重算既有邏輯。Fundamental diagnostics 來源是 `FundamentalDiagnosticsService` 序列化後的 metadata；Risk Prompt service 只轉成 `source="fundamental"` 的提示並清理禁用行動語句，不 import abnormal flag policy 或 raw data。Month 4 收尾新增 `tests/test_decision_desk_ui_contract.py`，以靜態契約阻擋 Daily Decision Desk UI 直接 import scoring、screening、backtest、portfolio core 等計算模組。

## 5. Decision Domain

### 位置

`decision_module/`

### 主要元件

- `strategy_configurator.py`
- `scoring_engine.py`
- `indicator_parameter_registry.py`
- `weight_contract.py`
- `score_threshold_policy.py`
- `recommendation_percentile_ranker.py`
- `reason_engine.py`
- `stock_screener.py`
- `market_regime_detector.py`
- `industry_mapper.py`
- `flow_signal_engine.py`

### 核心契約

#### 指標參數與推薦權重

- `IndicatorParameterRegistry` 是技術指標參數 schema、alias、版本與跨欄位限制的權威。
- v1+ 啟用指標缺少必要參數、未知欄位、錯誤型態或非法值時 Fail-Closed；disabled 指標完全跳過。
- `RecommendationWeightContract` 只接受 `pattern`、`technical`、`volume` 三個非 bool 整數 bp，總和固定為 `10000`。
- `ScoringEngine` 使用 Decimal 核心加權，Regime 採最大餘額法重分配，總分以 `ROUND_HALF_UP` 量化至 `0.01` 分。

#### fixed / quantile 回測門檻

- 舊策略沒有 `threshold_mode` 時維持 fixed。
- quantile 使用單股 expanding 歷史分布。
- T 日門檻只能使用 T-1 以前資料。
- 暖機期為 60 個有效觀測值。
- 分位數參數使用整數基點。

#### 推薦橫斷面百分位

- 先固定當日 eligible universe。
- 同分股票取得相同百分位。
- 母體過小時拒絕執行，不靜默退回 fixed。
- 結果保存母體數、門檻模式與百分位 metadata。

#### Factor Layer v1

新資料不得直接硬接 `ScoringEngine`。Month 3 v1 先以 `decision_module/factors/` 建立 factor contract、registry、Look-ahead gate 與既有資料 adapters，並以 `app_module/factor_service.py` 建立 application snapshot serialization。Factor 必須具備：

```text
factor_name
as_of_date
available_date
value
score_bp
quality
missing_policy
source_version
```

Factor `available_date` 晚於決策日時必須拒絕使用。

目前 v1 元件：

- `decision_module/factors/factor_dtos.py`
- `decision_module/factors/factor_registry.py`
- `decision_module/factors/factor_gate.py`
- `decision_module/factors/factor_adapters.py`
- `decision_module/factors/fundamental_adapters.py`（Month 5 preflight 基本面 adapter contract；目前可從已正規化月營收 records 產生 `fundamental.revenue_yoy`、`fundamental.revenue_mom`、`fundamental.revenue_3m_trend`、`fundamental.revenue_new_high`，保留 available_date / diagnostics 邊界，不接 ScoringEngine）
- `decision_module/factors/abnormal_fundamental_flags.py`（Month 5 異常基本面 diagnostics policy；只輸出 `FactorDiagnostic`，不改財報、不改 score）
- `app_module/fundamental_diagnostics_service.py`（Research metadata application boundary；序列化 abnormal diagnostics）
- `data_module/valuation_data.py`（Month 5 valuation data layer；建立 governed `ValuationObservation` 與同產業整數基點分位，不產生估值結論）
- `decision_module/factors/valuation_policy.py` / `valuation_adapters.py`（Month 5 估值 presentation boundary；只輸出相對估值區間與 factor metadata，不接 ScoringEngine）
- `app_module/factor_service.py`

Research Run metadata 可透過 `data_manifest.factor_snapshot` 與 `data_manifest.factor_contributions` 保存 factor 追溯資料。`ResearchRunService.save_run()` 在 metadata 寫入前可合併 explicit factor metadata，或由 `FactorRecord` 與 decision date 透過 `FactorService` 產生 snapshot 與 contribution summary。推薦組合回放結果會從 replay snapshot recommendations 產生初版 factor manifest；單股回測會從 `BacktestService` 已產生的 signal score 序列建立 `technical.total_score` factor records，並由 `BacktestView` 保存 Research Run 時轉交 `ResearchRunService`；批次回測沿用每檔 `BacktestReportDTO` 內的 factor records，在 legacy run 保存成功後以 `batch-backtest:<legacy_run_id>` 寫入 Research Run Registry。固定組合目前共用批次執行路徑，但 UI 會將 Research Lab mode 傳入 service，Registry metadata 以 `fixed_basket_stock` 區分固定組合 per-stock 保存結果。這些保存路徑都不在 UI 重算分數或重新抓取資料。Cross-run Comparison 只能讀已保存 metadata，不得為比較重新抓取當前資料。

長期 factor 權重可擴充到 chip / fundamental / market / risk，但目前正式 `RecommendationWeightContract` 仍只接受 `pattern`、`technical`、`volume` 三項整數 bp。擴充前必須先完成資料可得日、品質狀態與 missing policy 治理。Month 5 preflight 已確認既有 `financial_data/` 缺公告日與 `available_date`，因此 raw CSV 不得直接進回測、推薦、Daily Decision Desk 或 `ScoringEngine`；缺 `available_date` 的基本面 observation 必須只回 diagnostics，不得被補成期間日期。Revenue Factor Pack v1 也只輸出 factor records / diagnostics：缺 YoY 或 MoM baseline 時不產生該 ratio factor，不補中性分數；future `available_date` 由 `FactorGate` 依 `MissingPolicy.SKIP` 跳過。Abnormal Fundamental diagnostics v1 僅標記營收與獲利背離、一次性收益風險與資料品質缺口，並作為 Research metadata / Daily Decision Desk risk prompts；不得自動扣除業外、改寫財報或調整分數。`data_module/valuation_data.py` 只負責建立 governed valuation observations 與同產業 `industry_percentile_bp`，不輸出估值結論。`decision_module/factors/valuation_policy.py` 與 `valuation_adapters.py` 只建立估值 presentation boundary。它們不得 import 或呼叫 `ScoringEngine`，不得產生 target price / fair value / upside / buy-sell recommendation，且缺少 `industry_percentile_bp` 時不得輸出中性估值區。

## 6. Backtest Engine

### 位置

`backtest_module/`

### 主要元件

- `broker_simulator.py`：撮合、成本、部位與台股市場限制。
- `strategy_tester.py`：策略訊號與模擬流程。
- `performance_analyzer.py`：結果分析。
- `performance_metrics.py`：績效與風險指標。

### Application orchestration

- 一般回測：`app_module/backtest_service.py`
- 批次回測：`app_module/batch_backtest_service.py`
- 最佳化：`app_module/optimizer_service.py`
- Walk-forward：`app_module/walkforward_service.py`
- 推薦回放：`app_module/recommendation_portfolio_backtest_service.py`

### 時間軸防線

- `next_open`：T 日訊號，最早以 T+1 開盤成交。
- `close`：同根 K 收盤成交假設，必須在 metadata 與報告揭露。
- benchmark、停損停利、標準化與篩選都只能使用決策當下可取得資料。
- Walk-forward 的 OOS 測試可用該 fold 訓練起點至 T-1 的歷史產生訊號門檻，但交易狀態必須在測試窗起點以空倉重置，撮合、權益曲線與績效也只從測試窗起點計算；`signal_context_start_date` 不得把訓練期持倉或交易混入 OOS 指標。

推薦組合回放目前已有持有天數、配置權重與 equity curve；Month 3 後續需補強現金帳、再平衡、未成交、Liquidity / Gap 標記與結果揭露，才可作為策略生命週期的可靠證據。

### 金融數值防線

核心金額、交易成本、股數、PnL、持倉與風控不得新增裸 `float` 計算。使用：

- `Decimal`
- 整數股數
- 整數基點
- 分為單位的整數金額

只有明確隔離的 analytics / visualization boundary 可轉換為 float。

## 7. Portfolio Domain

### 位置

- `portfolio_module/core.py`
- `app_module/portfolio_service.py`
- `app_module/portfolio_condition_monitor.py`
- `app_module/portfolio_chip_service.py`

### 資料流

```text
manual / recommendation / backtest / strategy_version
  -> source adapter
  -> trade record
  -> portfolio domain projection
  -> position / average cost / realized PnL
  -> condition monitor / chip monitor
  -> journal
```

### 來源追溯

Portfolio 記錄可保留：

- `source_type`
- `source_id`
- 推薦 Profile / Regime
- 回測 run
- promoted strategy version
- 進場分數與策略參數摘要

UI 警示只提供輔助判讀，不自動下單或平倉。

## 8. Data Infrastructure

### 位置

`data_module/`

### 核心設定

所有資料路徑以 `TWStockConfig` 為準：

```text
DATA_ROOT  -> 預設 D:/Min/Python/Project/FA_Data
OUTPUT_ROOT
db_file    -> <DATA_ROOT>/sqlite/twstock.db
```

不得在新程式中硬編碼正式資料根目錄。

### SQLite-first 與 CSV fallback

目前主要讀取採 SQLite-first，CSV 保留：

- raw 原始資料
- 完整備份
- migration / fallback
- 人工研究匯出

日常快速更新可直接同步 SQLite；安全更新同時維護完整 CSV 與 SQLite。

### 主要資料表

- `daily_prices`
- `market_indices`
- `industry_indices`
- `technical_indicators`
- `broker_flows`

未來資料表：

- 月營收
- 基本面
- 估值
- `institutional_flows`
- Factor registry / values

這些資料表尚未成為正式可用資料源。接入時必須保留 `as_of_date`、`available_date`、資料品質、來源版本與 fallback / migration。

Month 5 preflight 已新增 `data_module/fundamental_availability.py` 集中處理公告日 / available_date 初版政策，並新增 `data_module/fundamental_availability_sources.py` 作為受治理的公告日 / available_date mapping 契約；mapping 可保留 `announced_date`、`available_date`、`source`、`source_version`，但明確拒絕把 raw 月營收 CSV 自身當成可得日來源。正式 mapping 檔案位置由 `TWStockConfig.monthly_revenue_availability_file` 指向 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`；缺檔時只回 diagnostic，不自動補值。`data_module/fundamental_availability_entrypoint.py` 與 `scripts/validate_monthly_revenue_availability.py` 是正式 mapping dry-run 驗證入口，只讀取指定 mapping 檔、驗證允許來源並輸出 diagnostics / Markdown 摘要，不建立、不改寫正式 mapping 檔、raw CSV 或 SQLite。`data_module/fundamental_data.py` 則作為 raw 月營收 CSV 的唯讀正規化契約。`data_module/monthly_revenue_backfill.py` 與 `scripts/backfill_monthly_revenue_fundamentals.py` 是 raw 月營收進入 `fundamental_monthly_revenues` 的受控回填邊界：預設 dry-run，缺 mapping fail-closed，正式 apply 需 `--confirm apply-monthly-revenue-backfill` 並先備份 DB。`data_module/fundamental_sqlite_provider.py` 是正式 fundamental tables 的唯讀 provider，只讀 `available_date <= decision_date` 的月營收與估值 rows，不讀 raw CSV、不寫 DB。`app_module/fundamental_factor_service.py` 串接 provider、revenue/valuation adapters 與 FactorGate，輸出 factor records / diagnostics 供 Research metadata 使用，但不接 `ScoringEngine`。`data_module/valuation_data.py` 則作為估值 metric 的 governed observation layer，保留 raw metric value、available_date、quality、source_version 與同產業整數基點分位，缺分位不補值。這些模組不修改正式 raw 檔，也不把 raw `date` 推定為公告日；呼叫端必須提供 explicit `available_date` mapping，否則只回 diagnostics，不產生 normalized record。`data_module/fundamental_schema.py` 定義 SQLite schema 與 dry-run report API，可在呼叫端提供的暫時 connection 或正式 DB working copy 上驗證 schema；尚未接入 `DBManager.init_database()`，因此不會在一般啟動流程自動改動正式 `twstock.db`。`data_module/fundamental_migration.py` 與 `scripts/migrate_fundamental_schema.py` 是獨立受控 migration 邊界，正式 apply 需顯式 `--confirm apply-fundamental-schema`，會先備份並提供 restore helper；2026-06-16 已依使用者確認對正式 DB 執行 apply，備份為 `D:/Min/Python/Project/FA_Data/meta_data/backup/twstock_fundamental_schema_20260616_022301.db`。正式 DB 目前僅新增 `fundamental_monthly_revenues`、`fundamental_statement_items`、`fundamental_valuation_metrics` 三張空表，尚未回填 fundamental records。

### 資料完整性

- 不刪除或破壞 raw 原始資料。
- schema 變更必須提供 migration 與 fallback。
- 狀態檢查必須唯讀。
- 全量重建前必須建立備份並明確確認。

## 9. Broker Flow 與資料品質

MoneyDJ 張數榜 `c=E` 與金額榜 `c=B` 是各自獨立的 Top 50：

- 資料層使用 union 保存。
- 榜外欄位使用 NULL，不可當成 0。
- 保存方向、rank 與品質狀態。

品質三態：

| 狀態 | 意義 |
|---|---|
| observed | 原始榜單直接觀測。 |
| estimated | 由金額與有效價格估算，降低信心。 |
| unavailable | 無法可靠取得，不參與該事件數值聚合。 |

單筆 unavailable 不得污染同股票其他有效事件。

## 10. Runtime Subsystem

### 分層

```text
runtime/ core
  -> app_module/runtime_services
      -> app_module DTO
          -> ui_qt/bridges/runtime_event_bridge.py
              -> ui_qt/views/runtime_view.py
```

### 禁止依賴

- `runtime/` 不依賴 `app_module` 或 `ui_qt`。
- `app_module` Runtime service 不依賴 PySide6。
- Runtime UI 只接受 DTO 與 Qt signal。
- Runtime View 不直接讀寫檔案或 store。

詳細規則見 [runtime_observatory_rules.md](runtime_observatory_rules.md)。

## 11. 保存與研究治理

目前保存能力包括：

- 推薦結果
- Research Run Registry（單股回測與推薦回放的新保存入口）
- legacy 一般回測 run 與推薦回放 run（僅保留相容、歷史載入與 backfill）
- Preset
- Strategy Version
- Universe
- Portfolio trade / journal

Research Run Registry 由 `ResearchRunService` 統一負責保存 owner，metadata 寫入 SQLite，equity curve 與 trades 寫入 Parquet。保存流程採 staging → files_ready → committed 狀態轉移，並以 payload / file hash 做完整性檢查；失敗或中斷時可透過 reconciliation 標記不完整 run，不把部分資料冒充為成功結果。

目前 registry 已保存：

- 資料截止日與 hash
- 策略版本
- 完整參數與權重版本
- 成本與成交假設
- Universe
- OOS 與 benchmark 結果
- equity curve 與 trades parquet hash
- storage / integrity 狀態

既有 `BacktestRunRepository` 與 `RecommendationPortfolioRunRepository` 仍作為 legacy repository 存在；新「保存結果」入口已改由 UI 呼叫 `ResearchRunService.save_run()`。歷史 run 可由 `scripts/backfill_legacy_runs.py --apply` 明確匯入 registry，dry-run 為預設行為，且不刪除舊資料。

Month 2 M2-C 已新增 Cross-run Comparison service / UI 與 Registry-based Promote Gate。Promotion 以 Registry run 為單一來源，前置檢查要求 committed / valid、未 archive、未 promoted、可還原 parameter contract version，且通過最低 validation gate。策略版本 JSON 採 temporary file + atomic replace 寫入；若 Registry 回填 `promoted_version_id` 失敗，系統會刪除已寫入 JSON，刪除失敗時標記 `promotion_reconciliation_status='reconciliation_required'`，不宣稱為 SQLite transaction rollback。Reconciliation service 會掃描 JSON 與 Registry 的 source_run_id / promoted_version_id 不一致狀態，提供受控修復依據。

## 12. 報告匯出與分頁資料流

### 12.1 SQLite 檢視器穩定分頁

- **分頁機制**：透過 `SqliteInspectorService` 的 count 與 page 查詢共用 filter builder。預覽查詢藉由 `LIMIT ? OFFSET ?` 完成。
- **排序穩定契約**：預設依 `日期 DESC, 證券代號 ASC` 加上其他關鍵欄位作為 tie-breaker，最後補上唯一 `rowid ASC`，確保跨頁無重複與遺漏；使用者點擊表頭排序時，只能使用 PRAGMA schema 驗證後的白名單欄位或安全顯示 alias，並由 SQLite 端 `ORDER BY` 搭配既有分頁執行。
- **欄位呈現契約**：SQLite Inspector 可在唯讀查詢層套用使用者可見 alias，例如舊 daily_prices schema 的簡體 `涨跌` 會顯示為繁體 `漲跌`；`漲跌價差` 的預覽值可依 `漲跌(+/-)` / `漲跌` 方向轉為帶正負號的展示值，但不改寫原始資料表。
- **防禦與 stale 處理**：當重新查詢或變更篩選時，頁碼重設為 1。背景 `TaskWorker` 攜帶單調遞增的 `request_id`，UI 在讀取完畢時會校驗 `request_id` 與當前最新請求是否相符，丟棄過期 (stale) 結果。執行中的 worker 會保留強參考直到執行緒自然結束，不對舊查詢呼叫無參數 `disconnect()` 或提前釋放 `QThread`。

### 12.2 規格化 Excel 報告匯出

```text
Current Result DTO / Run Metadata
  -> UI Payload Builder
  -> Defensive-copy Export Payload DTO (app_module/report_export_dtos.py)
  -> TaskWorker (Background Thread)
  -> ReportExportService (app_module/report_export_service.py)
  -> temporary .xlsx (Atomic temp file)
  -> os.replace (Atomic file replacement)
```

- **防禦性快照 (DTO-first)**：UI 將當前成功回測或推薦的結果 DTO、執行參數與元數據，透過 payload builder 建立防禦性複製。批次回測由正式 `stock_results` 建構排行榜，推薦回放使用執行前保存的參數快照，不在匯出當下重讀已可能變動的 UI 控制項。
- **原子性安全寫入**：匯出服務在寫入目標路徑時，會先建立 `.tmp` 暫存檔，寫入成功後再進行原子性檔案替換 (`os.replace`)，確保匯出失敗或被 Excel 鎖定時不損壞原有報告。
- **資料形狀正規化**：equity curve 可接受 `日期`、`date` 欄位或日期 index；匯出邊界會統一成 `日期` 欄位，並可由已提供的 equity 序列衍生展示用 drawdown。
- **無策略重算防線**：`ReportExportService` 屬於 presentation serialization layer，不重跑策略，也不重新計算總報酬、Sharpe、Monte Carlo 等摘要績效。缺失的追溯欄位統一輸出 `N/A`，不得以預設版本、benchmark 或成交假設代填。

## 13. 文件架構

本專案採 Scoped SSOT：

| 主題 | 權威文件 |
|---|---|
| 目前狀態 | `docs/00_core/PROJECT_SNAPSHOT.md` |
| 未來 6 個月 | `docs/00_core/ROADMAP_6M_ENGINEERING.md` |
| 舊 Roadmap 移交 | `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` |
| 架構 | 本文件 |
| 使用方式 | `docs/07_guides/APPLICATION_MANUAL.md` |
| 文件導航 | `docs/00_core/DOCUMENTATION_INDEX.md` |

Roadmap Hub 只負責入口與短版 Next，不保存完整歷史或架構細節。

## 14. 高風險修改清單

修改以下區域必須提高驗證強度：

- `backtest_module/`
- `app_module/backtest_service.py`
- `app_module/recommendation_service.py`
- `decision_module/scoring_engine.py`
- `decision_module/score_threshold_policy.py`
- `decision_module/strategy_configurator.py`
- `app_module/strategies/`
- `portfolio_module/core.py`
- `app_module/portfolio_condition_monitor.py`
- `data_module/config.py`
- `app_module/update_service.py`
- `runtime/`
- UI ↔ DTO contract

策略、回測、推薦、Factor 與 Portfolio 改動前必須做 Look-ahead 自查與金融數值邊界檢查。

## 15. 驗證

UI 修改：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

金融核心：

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

文件修改：

- 檢查 Active docs 不再把 Legacy Roadmap 或 `ui_app/main.py` 當目前入口。
- 驗證 Markdown relative 連結。
- 更新 `DOCUMENTATION_INDEX.md` 與 Manual coverage。

## 16. 更新記錄

- 2026-06-15：完成 Daily Decision Desk Portfolio Alert Attribution v1，將持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags，並整合至主 UI 與風險提示，明確定義由 PortfolioAlertService 進行歸因產生的架構職責。
- 2026-06-15：完成 Daily Decision Desk Why Not / 風險提示 v1 對接，由既有 section DTO 欄位與警告推導，輸出對應之低流動性、相對弱勢、Watchlist 觸發與持倉警示提示，不重複計算。
- 2026-06-15：補入 IDS 願景與架構權威邊界，更新 Daily Decision Desk v1 已接上主 UI；Market Breadth v1已接 SQLite `daily_prices` provider，Sector Rotation v1 已接 SQLite `industry_indices` provider，Relative Strength / Liquidity Ranking v1 已接 SQLite `daily_prices` provider，Watchlist Trigger v1 已接 `WatchlistService` 與 SQLite `technical_indicators`，Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，其餘 Strategy Drift 與 Post-trade Attribution 仍屬後續工作；同步 Month 3 Portfolio Replay 可信度、固定組合 per-stock factor metadata保存與後續資料因子接入防線。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾架構註記，確認 v1 以 service snapshot 聚合並新增 UI boundary contract test；Month 5 可從 Fundamental Layer preflight 開始，Strategy Drift 與 Post-trade Attribution 仍屬後續工作。
- 2026-06-16：啟動 Month 5 Fundamental Layer preflight 架構落點，新增公告日 / available_date 初版政策、raw 月營收正規化契約、候選 SQLite schema dry-run / report API 與 fundamental adapter contract，確認 raw fundamental CSV 缺 `available_date` 時不得產生 normalized record / factor record，未來資料仍須經 FactorGate 驗證。
- 2026-06-16：新增月營收 availability mapping dry-run 驗證入口與 CLI 架構邊界，確認它們只讀 mapping、輸出 diagnostics，不建立或改寫正式 mapping、raw CSV 或 SQLite。
- 2026-06-16：新增估值呈現政策 / adapter 架構邊界，確認只輸出相對估值區間與 diagnostics，不接 ScoringEngine，不產生目標價、合理價、上漲空間或買賣建議。
- 2026-06-16：新增 valuation data layer 架構邊界，確認資料層只建立受治理 observation 與同產業分位，估值輸出仍由 presentation policy 控制。
- 2026-06-16：新增 Abnormal Fundamental diagnostics 架構邊界，確認異常基本面只進 Research metadata 與 Daily Decision Desk risk prompts，不改財報、不改 score。


