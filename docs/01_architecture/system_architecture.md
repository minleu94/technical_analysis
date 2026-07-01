# 系統架構

> **最後更新**：2026-06-17
> **定位**：本文件是目前模組邊界、依賴方向、資料流與高風險技術契約的架構權威。歷史遷移過程不在本文件維護。

## 1. 系統定位

baldr 是一套可驗證、可回溯、可演化的台股研究與投資決策工作台。產品北極星與長期能力圖像見 [system_vision_specification.md](system_vision_specification.md)；本文件只描述目前架構與模組邊界。

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
| 推薦與市場 | `recommendation_service.py`、`screening_service.py`、`regime_service.py`、`recommendation_profile_service.py` |
| 數據更新 | `update_service.py`、`broker_branch_update_service.py`、`sqlite_inspector_service.py` |
| 籌碼 | `broker_flow_service.py`、`portfolio_chip_service.py` |
| 回測 | `backtest_service.py`、`batch_backtest_service.py`、`optimizer_service.py`、`walkforward_service.py`、`research_result_presentation.py` |
| 推薦回放 | `recommendation_replay_service.py`、`recommendation_portfolio_backtest_service.py` |
| 保存與版本 | `backtest_repository.py`、`recommendation_repository.py`、`strategy_version_service.py`、`preset_service.py`、`universe_service.py` |
| Portfolio | `portfolio_service.py`、`portfolio_condition_monitor.py`、`portfolio_source_adapter.py` |
| Strategy lifecycle / feedback | `strategy_lifecycle_service.py`、`strategy_lifecycle_repository.py`、`portfolio_feedback_service.py`、`portfolio_review_service.py`、`promotion_reconciliation_service.py` |
| Post-V1 evidence | `evidence_event_dtos.py`、`evidence_event_repository.py`、`evidence_event_service.py`、`forward_performance_service.py` |
| Runtime | `runtime_services/`、`dtos/runtime_dtos.py` |

`app_module` 不依賴 `ui_app`。Legacy Tkinter UI 不是目前 service 架構的一部分。

Daily Decision Desk 後續應以 application service / DTO 聚合既有市場、推薦、watchlist 與 portfolio 結果，不得在 UI 層重算 scoring、screening、broker flow 或 portfolio logic. Market Breadth v1 由 `app_module.market_breadth_service.MarketBreadthService` 與 `SQLiteDailyPriceMarketBreadthProvider` 自 SQLite `daily_prices` 唯讀推導多方 / 空方 / 持平、成交量擴散與新高新低 metadata，並在指定日無資料時以最近可用交易日降級顯示。Sector Rotation v1 由 `app_module.sector_rotation_service.SectorRotationService` 與 `SQLiteIndustryIndexSectorRotationProvider` 自 SQLite `industry_indices` 唯讀推導領先 / 落後產業、5 / 20 日變化與輪動強度，同樣以 warnings 揭露 fallback 日期。Relative Strength / Liquidity Ranking v1 由 `RelativeStrengthLiquidityService` 與 `SQLiteDailyPriceRelativeStrengthLiquidityProvider` 自 SQLite `daily_prices` 唯讀推導 5 / 20 日相對強度與平均成交金額，輸出強勢、弱勢與低流動性代碼，不在 UI 層重算；歷史不足 21 天時降級為 DEGRADED 並警告。Watchlist Trigger v1 由 `WatchlistServiceWatchlistProvider` 與 `SQLiteRankingProvider` 結合，唯讀查詢 `technical_indicators` 產生個股強度 `score_bp` 與風險 `risk_alert`，並支援日期 fallback 降級警告（quality 改為 `DEGRADED`，在 `warnings` 中標註 `watchlist_trigger_as_of_fallback:<date>`）。Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，可把條件監控與籌碼風險彙總成每日持倉警示；若籌碼資料缺失、估算或不可用，會透過 `quality / warnings` 降級揭露，不補值。Portfolio Alert Attribution v1 屬於 `PortfolioAlertService` 的輸出責任，因為只有該 service 同時看得到 position source、condition monitor 結果與 chip summary。UI 與 Risk Prompt service 只能讀取 `PortfolioAlertSummary.attributions`，不得重新查詢或重算。Why Not / 風險提示 v1 由 `DecisionDeskRiskPromptService` 從既有 section DTO 的 quality、warnings、低流動性、相對弱勢、watchlist risk alert、portfolio alert 與 application service 提供的 fundamental diagnostics 推導，提供可行動風險提示，不重算既有邏輯。Fundamental diagnostics 來源是 `FundamentalDiagnosticsService` 序列化後的 metadata；Risk Prompt service 只轉成 `source="fundamental"` 的提示並清理禁用行動語句，不 import abnormal flag policy 或 raw data。Month 4 收尾新增 `tests/test_decision_desk_ui_contract.py`，以靜態契約阻擋 Daily Decision Desk UI 直接 import scoring、screening、backtest、portfolio core 等計算模組。

Healthcheck Batch 2 新增 `DecisionDeskDashboardComposer` 與 `SmartMoneySemanticService`。`DecisionDeskDashboardComposer` 只組合既有 section DTO 與可選 Smart Money summary，產生 action summary、sector focus 與 stock focus；它不重新計算 ranking、scoring 或 portfolio logic。`SmartMoneySemanticService` 位於 app layer，從 `BrokerFlowService.get_events()` 的唯讀事件快照與可選 `SQLiteSmartMoneyPriceProvider` 產生 5 / 20 / 60 日語意診斷、quantity-based 集中度、價格位置風險與資料品質 counts；Qt UI 只讀 DTO 欄位與 tooltip，不直接查 SQLite 或重算籌碼語意。

Healthcheck Batch 3 新增 `RecommendationProfileService`。該 service 是推薦分析 Profile lifecycle 邊界，負責把內建 Profile、自訂 Profile 與 Strategy Registry 中通過 gate 的策略版本 Profile 組成 UI 可選清單；自訂 Profile 保存於 output root 下的 `recommendation/profiles/custom_profiles.json`，標示「自訂，未經回測驗證」，並以 Decimal 字串與整數 bp 保存數值權威。策略版本 Profile 只讀 `StrategyVersionService.list_versions()`，僅顯示通過 gate 且未停用的版本，不刪除歷史策略版本 JSON。Qt UI 只呈現來源 label、保存自訂設定與 Profile-Regime match / mismatch 說明，不在 UI 層重算 scoring，也不把 mismatch 當成自動排除或交易建議。

Healthcheck Batch 4 新增 `research_result_presentation.py` 作為 Research Lab 結果頁呈現邊界。它只把已產生的推薦回放 summary、Train-Test report、Walk-forward fold summary 轉成 UI 文案與可靠度提示，不重跑回測、不重新抓取目前資料、不改變交易或績效計算。Train-Test / Walk-forward 樣本可靠度提示只讀交易數、Fold 數、OOS 與 consistency 等已存在結果 metadata；Registry 比較仍只讀已保存 metadata、equity curve 與 benchmark_results。Qt UI 可使用這些 helper 顯示「樣本不足，不宜作正式策略判斷」、資金使用與 Monte Carlo 語意，但不得把提示升級成交易建議、自動下單或持倉調整。

Healthcheck Batch 5 將 `OptimizerService` 的參數掃描邊界明確化：單股最佳化仍只使用 `BacktestService._load_stock_data()` 預載一次資料，並沿用 SQLite-first、缺資料 fallback CSV 的資料來源策略；並行模型仍是 ThreadPoolExecutor，UI 允許 1 到 8 workers，但不宣稱 ProcessPool 或多進程。`grid_search()` 採 bounded in-flight futures，只提交少量已啟動子任務，取消時停止提交新組合並將 `CancelledError` 視為正常取消狀態。這個變更只影響任務排程、可預期性與 UI 回饋，不改策略訊號、撮合、績效、資金或推薦計算。

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
- `decision_module/factors/fundamental_adapters.py`（Month 5 基本面 adapter contract；目前可從已正規化月營收與季度財報 records 產生 Revenue YoY / MoM / 3M trend / new high、EPS、gross margin、operating margin、ROE 與 non-operating income ratio factor records，保留 available_date / diagnostics 邊界，不接 ScoringEngine）
- `decision_module/factors/abnormal_fundamental_flags.py`（Month 5 異常基本面 diagnostics policy；只輸出 `FactorDiagnostic`，不改財報、不改 score）
- `app_module/fundamental_diagnostics_service.py`（Research metadata application boundary；序列化 abnormal diagnostics）
- `data_module/valuation_data.py`（Month 5 valuation data layer；建立 governed `ValuationObservation` 與同產業整數基點分位，不產生估值結論）
- `data_module/company_registry.py` / `scripts/update_company_registry.py`（Month 5 official company registry workflow；以 TWSE/TPEX 官方基本資料更新 `companies.csv`，維持既有 schema 並先 dry-run / backup / confirm）
- `data_module/monthly_revenue_availability_history.py` / `scripts/build_monthly_revenue_availability_history.py`（Month 5 月營收公告日 historical dry-run builder；讀 TWSE/TPEX 官方 `出表日期`、人工提供 JSON、人工保存的 MOPS 官方 HTML、新版 MOPS redirectToOld / mopsov static report，或授權 PIT 月營收公告日 CSV，輸出候選 mapping / diagnostics，不寫正式 mapping 或 SQLite）
- `data_module/monthly_revenue_snapshot_harvester.py` / `scripts/fetch_mops_monthly_revenue_snapshot.py`（Month 5 MOPS 月營收完整市場 snapshot 候選抓取器；保存 raw HTML 與營收值 candidate CSV，不產生 availability mapping、不推定 available_date、不寫 SQLite）
- `data_module/finmind_monthly_revenue_create_time.py` / `scripts/fetch_finmind_monthly_revenue_create_time.py`（Month 5 FinMind 月營收 create_time 候選抓取器；逐檔抓取 `TaiwanStockMonthRevenue`、支援 resume / rate limit / DPAPI token，輸出觀測日分組候選，不寫正式 mapping 或 SQLite）
- `data_module/tpex_daily_price_source.py`（TPEX daily close quotes 日常 / 區間 adapter；以官方 afterTrading historical endpoint 補缺少日期，輸出 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`，交由既有 SQLite sync upsert `daily_prices`，不接 company registry 或 fundamental layer）
- `data_module/tpex_daily_price_history_plan.py` / `scripts/plan_tpex_daily_price_history_backfill.py`（TPEX 歷史日價 dry-run planner；估算來源筆數、既有筆數、新增候選筆數與失敗日期，不寫正式 DB）
- `data_module/tpex_daily_price_backfill.py` / `scripts/backfill_tpex_daily_prices.py`（TPEX 市場日價受控補寫 workflow；以官方 daily close quotes 補寫 `daily_prices`，預設 dry-run，正式 apply 需 confirm 與備份，不寫 company registry 或 fundamental tables）
- `data_module/valuation_metrics_backfill.py` / `scripts/backfill_valuation_metrics.py`（Month 5 P/E valuation metrics 受控回填邊界；預設 dry-run，正式 apply 需 confirm 與備份）
- `decision_module/factors/valuation_policy.py` / `valuation_adapters.py`（Month 5 估值 presentation boundary；只輸出相對估值區間與 factor metadata，不接 ScoringEngine）
- `app_module/factor_service.py`

Research Run metadata 可透過 `data_manifest.factor_snapshot` 與 `data_manifest.factor_contributions` 保存 factor 追溯資料。`ResearchRunService.save_run()` 在 metadata 寫入前可合併 explicit factor metadata，或由 `FactorRecord` 與 decision date 透過 `FactorService` 產生 snapshot 與 contribution summary。推薦組合回放結果會從 replay snapshot recommendations 產生初版 factor manifest；單股回測會從 `BacktestService` 已產生的 signal score 序列建立 `technical.total_score` factor records，並由 `BacktestView` 保存 Research Run 時轉交 `ResearchRunService`；批次回測沿用每檔 `BacktestReportDTO` 內的 factor records，在 legacy run 保存成功後以 `batch-backtest:<legacy_run_id>` 寫入 Research Run Registry。固定組合目前共用批次執行路徑，但 UI 會將 Research Lab mode 傳入 service，Registry metadata 以 `fixed_basket_stock` 區分固定組合 per-stock 保存結果。這些保存路徑都不在 UI 重算分數或重新抓取資料。Cross-run Comparison 只能讀已保存 metadata，不得為比較重新抓取當前資料。

長期 factor 權重可擴充到 chip / fundamental / market / risk，但目前正式 `RecommendationWeightContract` 仍只接受 `pattern`、`technical`、`volume` 三項整數 bp。擴充前必須先完成資料可得日、品質狀態與 missing policy 治理。Month 5 v1 已完成 fundamental tables、provider、adapter 與 diagnostics 的保守接入；raw fundamental CSV 仍不得直接進回測、推薦、Daily Decision Desk 或 `ScoringEngine`。缺 `available_date` 的基本面 observation 必須只回 diagnostics，不得被補成期間日期。Revenue / statement factor pack v1 只輸出 factor records / diagnostics，不補中性分數；future `available_date` 由 `FactorGate` 依 `MissingPolicy.SKIP` 跳過。Abnormal Fundamental diagnostics v1 僅標記營收與獲利背離、一次性收益風險與資料品質缺口，並作為 Research metadata / Daily Decision Desk risk prompts；不得自動扣除業外、改寫財報或調整分數。`data_module/valuation_data.py` 只負責建立 governed valuation observations 與同產業 `industry_percentile_bp`，不輸出估值結論。`decision_module/factors/valuation_policy.py` 與 `valuation_adapters.py` 只建立估值 presentation boundary。它們不得 import 或呼叫 `ScoringEngine`，不得產生 target price / fair value / upside / buy-sell recommendation，且缺少 `industry_percentile_bp` 時不得輸出中性估值區。P/B 與 P/S policy 已採 guarded ready：只接受 governed external observations 或後續明確 backfill records，不在系統內用不完整財報推導 book value、share count、market cap 或 TTM sales。

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

日常快速更新可直接同步 SQLite；安全更新同時維護完整 CSV 與 SQLite。每日股價資料源包含 TWSE `DATA_ROOT/daily_price/` 與 TPEX `DATA_ROOT/daily_price_tpex/`，SQLite sync 會讀取兩個目錄並依 `(證券代號, 日期)` upsert 到 `daily_prices`。

### 主要資料表

- `daily_prices`
- `market_indices`
- `industry_indices`
- `technical_indicators`
- `broker_flows`

正式資料表（Month 5 起）：

- `fundamental_monthly_revenues`
- `fundamental_statement_items`
- `fundamental_valuation_metrics`

未來資料表：

- `institutional_flows`
- Factor registry / values

任何新資料表接入時必須保留 `as_of_date`、`available_date`、資料品質、來源版本與 fallback / migration。既有 fundamental tables 只能透過受治理 provider / factor service 使用，不得由 UI 或策略核心直接讀 raw CSV。

Month 5 v1 已新增 `data_module/fundamental_availability.py` 集中處理公告日 / available_date 初版政策，並新增 `data_module/fundamental_availability_sources.py` 作為受治理的公告日 / available_date mapping 契約；mapping 可保留 `announced_date`、`available_date`、`source`、`source_version`，但明確拒絕把 raw 月營收 CSV 自身當成可得日來源。正式 mapping 檔案位置由 `TWStockConfig.monthly_revenue_availability_file` 指向 `DATA_ROOT/meta_data/monthly_revenue_availability.csv`；缺檔時只回 diagnostic，不自動補值。`data_module/fundamental_availability_entrypoint.py` 與 `scripts/validate_monthly_revenue_availability.py` 是正式 mapping dry-run 驗證入口，只讀取指定 mapping 檔、驗證允許來源並輸出 diagnostics / Markdown 摘要，不建立、不改寫正式 mapping 檔、raw CSV 或 SQLite。允許來源包含 manual、TWSE、TPEX 與 MOPS mapping source，但 raw CSV 永遠不是 allowed source；validator 另以 `as_of_date + 45 days` 作月營收合理揭露窗口，拒絕重新出表日或其他過晚 available_date。`data_module/monthly_revenue_availability_history.py` 與 `scripts/build_monthly_revenue_availability_history.py` 是候選 mapping 產生邊界：可讀 TWSE `/opendata/t187ap05_L`、TPEX `/openapi/v1/mopsfin_t187ap05_O`、人工提供的官方 JSON、以 `--mops-html-dir` 讀人工保存且含 `出表日期` 的 MOPS 官方 HTML，或以 `--mops-static` 透過新版 MOPS `/mops/api/redirectToOld` 取得 `mopsov.twse.com.tw/nas/t21/...` historical static report；支援期間、market、stock_code 與 output 參數。未指定 output 時只輸出 dry-run summary，指定 output 時也只寫候選 CSV，不得直接覆寫正式 mapping；MOPS HTML 缺 `出表日期` 或 `公司代號` 表格時只產生 diagnostics。2026-06-17 驗證 MOPS historical static report 的 `出表日期` 是查詢當日重新出表日，對歷史 period 會被 45 天窗口擋下，不產生候選 row。`data_module/fundamental_data.py` 則作為 raw 月營收 CSV 的唯讀正規化契約。`data_module/monthly_revenue_backfill.py` 與 `scripts/backfill_monthly_revenue_fundamentals.py` 是 raw 月營收進入 `fundamental_monthly_revenues` 的受控回填邊界：預設 dry-run，正式 apply 需 `--confirm apply-monthly-revenue-backfill` 並先備份 DB。`data_module/company_registry.py` 與 `scripts/update_company_registry.py` 是 `companies.csv` 的官方 registry 更新邊界：預設 dry-run，正式 apply 需 `--confirm apply-company-registry` 並先備份；它不寫 SQLite，也不補 daily price。`data_module/tpex_daily_price_source.py` 是 TPEX 日常 / 區間市場日價 adapter：抓 official afterTrading historical daily close quotes、保留四碼普通股有效日價、補齊缺少的 `daily_price_tpex/YYYYMMDD.csv`，再由日常 SQLite sync 寫入 `daily_prices`；它不修改 `companies.csv`、raw financial CSV、fundamental tables、technical indicators 或 scoring。背景補齊入口由 `scripts/run_tpex_full_refresh_and_technical.py` 串接 TPEX 補齊、SQLite sync 與技術指標增量，狀態寫入 `DATA_ROOT/meta_data/tpex_full_refresh_status.json`，預設不先強制跑 TWSE 全量。`data_module/tpex_daily_price_history_plan.py` 與 `scripts/plan_tpex_daily_price_history_backfill.py` 保留為歷史缺口 dry-run / 估算工具，不直接寫正式 DB。`data_module/tpex_daily_price_backfill.py` 與 `scripts/backfill_tpex_daily_prices.py` 是 TPEX 上櫃日價單日受控補寫工具，預設 dry-run，正式 apply 需 `--confirm apply-tpex-daily-price-backfill` 並先備份 DB；日常 UI 流程則優先走區間 adapter 與 SQLite sync。`broker_flows` 的資料身份鍵是 `(分點名稱, 證券代號, 日期, trade_type)`；同步前若偵測到舊 DB 仍使用三欄主鍵，`DBManager.ensure_broker_flows_trade_type_primary_key()` 會先備份再遷移，使同日同分點同股票的買超 / 賣超榜單可以共存。`data_module/valuation_metrics_backfill.py` 與 `scripts/backfill_valuation_metrics.py` 是 `daily_prices.本益比` 進入 `fundamental_valuation_metrics` 的受控回填邊界：預設 dry-run，以 `companies.csv` 產業 mapping 計算同產業 percentile，正式 apply 需 `--confirm apply-valuation-metrics-backfill` 並先備份 DB；P/E 非正數或缺產業 mapping 的 rows 只輸出 diagnostics 並跳過。`data_module/fundamental_sqlite_provider.py` 是正式 fundamental tables 的唯讀 provider，只讀 `available_date <= decision_date` 的月營收、季度財報與估值 rows，不讀 raw CSV、不寫 DB。`app_module/fundamental_factor_service.py` 串接 provider、revenue / statement / valuation adapters 與 FactorGate，輸出 factor records / diagnostics 供 Research metadata 使用，但不接 `ScoringEngine`。`data_module/valuation_data.py` 則作為估值 metric 的 governed observation layer，保留 raw metric value、available_date、quality、source_version 與同產業整數基點分位，缺分位不補值。這些模組不修改正式 raw 檔，也不把 raw `date` 推定為公告日；呼叫端必須提供 explicit `available_date` mapping，否則只回 diagnostics，不產生 normalized record。`data_module/fundamental_schema.py` 定義 SQLite schema 與 dry-run report API；`data_module/fundamental_migration.py` 與 `scripts/migrate_fundamental_schema.py` 是獨立受控 migration 邊界，正式 apply 需顯式 confirm、先備份並提供 restore helper。正式 DB 目前已有 `fundamental_monthly_revenues`、`fundamental_statement_items`、`fundamental_valuation_metrics` 三張表；月營收已回填 244,499 筆、季度財報 items 已回填 1,645,555 筆、valuation metrics 已正式 apply `2026-06-15` P/E 共 831 筆 records。TPEX 歷史日價已可由區間 adapter 補入正式 SQLite；2026-06-17 排查確認 `daily_prices` 中 `3207` 已有 `20140102` 至 `20260617`、共 2,907 筆。

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
- 進入 MoneyDJ 前先以每日股價日檔或 SQLite `daily_prices` 作交易日預檢；沒有行情證據的日期視為不需抓取的 broker-flow 日期，整天跳過。
- 更新流程優先以 HTTP fast path 直接抓取 MoneyDJ Big5 HTML；只有 HTTP 失敗或解析不到資料時才使用 Selenium fallback。流程仍採序列更新，不以多 worker 併發打 MoneyDJ。

品質三態：

| 狀態 | 意義 |
|---|---|
| observed | 原始榜單直接觀測。 |
| estimated | 由金額與有效價格估算，降低信心。 |
| unavailable | 無法可靠取得，不參與該事件數值聚合。 |

單筆 unavailable 不得污染同股票其他有效事件。

Smart Money 語意層沿用上述資料品質契約：observed / estimated 可進入 quantity 聚合，unavailable 必須排除於 concentration 分子與分母並揭露筆數。5 / 20 / 60 日視窗只取 decision date 當下以前的 distinct event dates；高檔出貨疑慮的價格位置只使用 `daily_prices` 中 decision date 前最近 60 筆收盤價。千元金額只可作為 estimated quantity 的來源，不可直接作為集中度 metric。

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

Post-V1 evidence layer 由 `EvidenceEventService` / `EvidenceEventRepository` 保存 append-only `evidence_events`，並由 `ForwardPerformanceService` 計算 `evidence_outcomes`。v1 outcome 使用 SQLite `daily_prices` 的 close-to-close forward return，並嘗試從 `market_indices` / `industry_indices` 產生 benchmark / industry excess；缺資料時保留 NULL 與 warnings，不中斷整批。此層只輸出 research evidence，不改 `ScoringEngine`、推薦權重、策略版本或 portfolio position。

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

Month 2 M2-C 已新增 Cross-run Comparison service / UI 與 Registry-based Promote Gate。Month 6 v1 後，Promotion 以 Registry run 為單一來源，前置檢查要求 committed / valid、未 archive、未 promoted、可還原 parameter contract version，且通過最低 validation gate 與 `StrategyLifecycleService` 的 promote gate。Lifecycle gate 只讀已保存 metadata：交易次數、總報酬、Sharpe、回撤、勝率、benchmark excess return、factor snapshot quality 與 regime breakdown，不重新抓取當前資料、不重跑回測。`LifecycleEvidenceRepository` 以 append-only SQLite table 保存 decision snapshot、gate reasons、version id 與 status，並提供 latest state projection；`LifecycleEvidenceGovernanceService` 可把 demote / retire 判斷保存為 proposed evidence，不刪除或覆寫策略版本。策略版本 JSON 採 temporary file + atomic replace 寫入；若 Registry 回填 `promoted_version_id` 失敗，系統會刪除已寫入 JSON，刪除失敗時標記 `promotion_reconciliation_status='reconciliation_required'`，不宣稱為 SQLite transaction rollback。Promotion 成功且 evidence repository 已注入時，會在 Registry sync 後保存 applied lifecycle evidence。Reconciliation service 會掃描 JSON 與 Registry 的 source_run_id / promoted_version_id 不一致狀態，提供受控修復依據。

## 12. 報告匯出與分頁資料流

### 12.1 SQLite 檢視器穩定分頁

- **分頁機制**：透過 `SqliteInspectorService` 的 count 與 page 查詢共用 filter builder。預覽查詢藉由 `LIMIT ? OFFSET ?` 完成。
- **排序穩定契約**：預設依 `日期 DESC, 證券代號 ASC` 加上其他關鍵欄位作為 tie-breaker，最後補上唯一 `rowid ASC`，確保跨頁無重複與遺漏；使用者點擊表頭排序時，只能使用 PRAGMA schema 驗證後的白名單欄位或安全顯示 alias，並由 SQLite 端 `ORDER BY` 搭配既有分頁執行。
- **欄位呈現契約**：SQLite Inspector 可在唯讀查詢層套用使用者可見 alias，例如舊 daily_prices schema 的簡體 `涨跌` 會顯示為繁體 `漲跌`；`漲跌價差` 的預覽值可依 `漲跌(+/-)` / `漲跌` 方向轉為帶正負號的展示值，但不改寫原始資料表。UI table model 以欄位位置取值，可容忍顯示 alias 造成的重複欄名，不應再出現 Series ambiguity。
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

- 2026-06-23：完成 Healthcheck Batch 2 架構同步，新增 `DecisionDeskDashboardComposer` 與 `SmartMoneySemanticService` 邊界；Daily Decision Desk answer-first dashboard 與 Smart Money 5 / 20 / 60 日語意診斷皆由 app service / DTO 提供，Qt UI 不重算籌碼或市場邏輯。
- 2026-07-01：新增 Post-V1 evidence layer 架構邊界，確認 Evidence Event Store / Forward Outcome Calculator 只保存事件與 close-to-close research outcomes，不改 scoring、推薦權重、portfolio 或 UI。
- 2026-07-11：新增 Evidence Review Dashboards read-only UI pack 架構邊界，Research Lab `Evidence Review` 只透過 dashboard service 讀取 Forward Evidence、Live vs Research Gap、Signal Decay 與 Decision Quality；UI 不直接讀 SQLite / repository，不改 scoring、portfolio、Research Run 或 Strategy Lifecycle，也不建立 scheduler。
- 2026-06-23：完成 Healthcheck Batch 3 架構同步，新增 `RecommendationProfileService` 作為推薦分析 Profile lifecycle 邊界，支援內建 / 自訂 / gate-passed 策略版本 Profile，並明確規範 Profile-Regime mismatch 只作解釋與分數揭露。
- 2026-06-23：完成 Healthcheck Batch 4 架構同步，新增 `research_result_presentation.py` 作為 Research Lab 結果頁呈現邊界；推薦回放段落、Train-Test / Walk-forward 樣本可靠度提示與 Registry 比較中文判讀只讀既有結果，不重跑回測、不抓新資料、不產生交易建議。
- 2026-06-17：完成 Month 5 Fundamental Layer v1 closeout 架構同步，確認 fundamental tables / provider / adapters / diagnostics 為保守接入邊界；P/B、P/S 已補 guarded presentation policy，官方歷史 PIT 公告日保留為後續治理 residual；Month 6 Strategy Lifecycle 不得直接污染 ScoringEngine。
- 2026-06-17：補上 P/B / P/S valuation policy 架構同步，確認 P/B / P/S 僅接受 governed external observations 或 future backfill records，不在系統內推導估值分子 / 分母。
- 2026-06-17：完成 Month 6 Strategy Lifecycle / Portfolio Feedback v1 架構同步，新增 lifecycle rule engine、drift detector、portfolio feedback attribution、Portfolio Review snapshot 與 Registry-based Promote lifecycle gate；持倉管理 UI 只讀 service attribution，不重算策略或改寫持倉。
- 2026-06-17：補上 lifecycle evidence 架構同步，新增 append-only `strategy_lifecycle_repository.py`、latest state projection 與 demote / retire proposed evidence 保存邊界；Promotion 成功後可記錄 applied evidence。
- 2026-06-15：完成 Daily Decision Desk Portfolio Alert Attribution v1，將持倉警示拆為來源標籤、condition status、chip risk level、reason tokens 與 data quality flags，並整合至主 UI 與風險提示，明確定義由 PortfolioAlertService 進行歸因產生的架構職責。
- 2026-06-15：完成 Daily Decision Desk Why Not / 風險提示 v1 對接，由既有 section DTO 欄位與警告推導，輸出對應之低流動性、相對弱勢、Watchlist 觸發與持倉警示提示，不重複計算。
- 2026-06-15：補入 baldr 願景與架構權威邊界，更新 Daily Decision Desk v1 已接上主 UI；Market Breadth v1已接 SQLite `daily_prices` provider，Sector Rotation v1 已接 SQLite `industry_indices` provider，Relative Strength / Liquidity Ranking v1 已接 SQLite `daily_prices` provider，Watchlist Trigger v1 已接 `WatchlistService` 與 SQLite `technical_indicators`，Portfolio Alert v1 已接 `PortfolioService`、`PortfolioConditionMonitor` 與 `PortfolioChipService`，其餘 Strategy Drift 與 Post-trade Attribution 仍屬後續工作；同步 Month 3 Portfolio Replay 可信度、固定組合 per-stock factor metadata保存與後續資料因子接入防線。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾架構註記，確認 v1 以 service snapshot 聚合並新增 UI boundary contract test；Month 5 可從 Fundamental Layer preflight 開始，Strategy Drift 與 Post-trade Attribution 仍屬後續工作。
- 2026-06-16：啟動 Month 5 Fundamental Layer preflight 架構落點，新增公告日 / available_date 初版政策、raw 月營收正規化契約、候選 SQLite schema dry-run / report API 與 fundamental adapter contract，確認 raw fundamental CSV 缺 `available_date` 時不得產生 normalized record / factor record，未來資料仍須經 FactorGate 驗證。
- 2026-06-16：新增月營收 availability mapping dry-run 驗證入口與 CLI 架構邊界，確認它們只讀 mapping、輸出 diagnostics，不建立或改寫正式 mapping、raw CSV 或 SQLite。
- 2026-06-16：新增月營收 availability historical dry-run builder 架構邊界，確認 TWSE/TPEX 最新月 OpenAPI 或人工官方 JSON 只能產生候選 mapping / diagnostics，正式 mapping 寫入與 monthly revenue backfill 仍需人工 gate。
- 2026-06-16：補上 MOPS 官方 HTML source-dir 架構邊界；`--mops-html-dir` 只讀人工保存且含 `出表日期` 的官方 HTML，缺欄位時 fail-closed，不由 raw CSV 補日期。
- 2026-06-17：補上 MOPS `--mops-static` 架構邊界與 45 天合理揭露窗口；historical static report 的重新出表日會被視為過晚 available_date，不得形成 candidate row。
- 2026-06-16：補上授權 PIT 月營收公告日 CSV 架構邊界；`--pit-csv` 只接受具 source_version 的 point-in-time 匯出檔並產生候選 mapping，不寫正式 mapping、不回填 SQLite、不接 ScoringEngine。
- 2026-06-16：補上 GitHub public archive source audit 架構邊界；commit first-seen 可作未來 PIT 候選方法，但目前已檢查 public repos 皆未提供可追溯 daily snapshot，因此不新增 `github.*` allowed source。
- 2026-06-16：新增 MOPS snapshot / FinMind create_time 候選抓取器架構邊界；兩者只輸出 candidate/raw evidence 到 output 目錄，不推定正式 available_date，不寫 `monthly_revenue_availability.csv` 或 SQLite。
- 2026-06-16：新增估值呈現政策 / adapter 架構邊界，確認只輸出相對估值區間與 diagnostics，不接 ScoringEngine，不產生目標價、合理價、上漲空間或買賣建議。
- 2026-06-16：新增 valuation data layer 架構邊界，確認資料層只建立受治理 observation 與同產業分位，估值輸出仍由 presentation policy 控制。
- 2026-06-16：新增 valuation metrics backfill 架構邊界，確認 `daily_prices.本益比` 需經 dry-run / confirm / backup workflow 才能寫入 `fundamental_valuation_metrics`，且不接 ScoringEngine。
- 2026-06-16：新增 Abnormal Fundamental diagnostics 架構邊界，確認異常基本面只進 Research metadata 與 Daily Decision Desk risk prompts，不改財報、不改 score。
- 2026-06-16：新增 TPEX daily price backfill 架構邊界，確認官方 TPEX daily close quotes 只能經 dry-run / confirm / backup workflow 補寫 `daily_prices`，不修改 `companies.csv`、fundamental tables 或 scoring。
- 2026-06-18：更新 TPEX daily price 架構邊界，確認日常 / 手動 / 背景流程以官方 afterTrading historical endpoint 補缺少日期，SQLite sync 同時讀取 TWSE `daily_price/` 與 TPEX `daily_price_tpex/`，並 upsert `daily_prices`；背景補齊狀態寫入 `DATA_ROOT/meta_data/tpex_full_refresh_status.json`。
- 2026-06-16：更新 SQLite / broker flow 邊界，確認 `broker_flows` 唯一鍵需包含 `trade_type`，且 SQLite Inspector 顯示 alias 不得影響表格 model 取值。


