# 專案導航文件

**版本**：v1.4.2
**最後更新**：2026-06-15
**目標讀者**：專案開發者、新加入工程師

---

## 1️⃣ 專案一句話定位

**這是一個「可驗證、可回溯、可演化」的台股投資決策系統。**

系統提供完整的數據更新、市場觀察、股票推薦、策略回測功能，讓策略成為可被描述、被比較、被淘汰的研究對象。這不是單純的策略腳本，而是一個工具型系統。

產品北極星見 `docs/01_architecture/system_vision_specification.md`。Daily Decision Desk 是 Month 4 目標首頁，目前尚未成為可用頂層工作區；現行開發仍以 `docs/01_architecture/system_architecture.md` 的模組邊界為準。

---

## 2️⃣ 三層架構導航

### UI Layer（`ui_qt/`、`ui_app/`）

**主要入口**：`ui_qt/main.py`（PySide6 Qt UI，推薦使用）

**這一層不該做什麼**：
- 不包含業務邏輯
- 不直接操作數據
- 只負責：收參數、呼叫 Service、顯示 DTO

**Legacy UI**：`ui_app/main.py`（Tkinter UI，僅供參考）

---

### Application Service Layer（`app_module/`）

**這一層負責什麼**：
- Use case 編排（orchestration）
- UI 與 Domain 的解耦橋樑
- 數據轉換（DTO 處理）
- 服務組合（例如：回測服務組合策略執行器、績效分析器）

**與 Domain 的關係**：
- 依賴 `decision_module/`，不依賴 `ui_app/`
- 所有業務邏輯都透過 `decision_module/` 取得

---

### Domain Layer（`decision_module/`）

**這一層放什麼**：
- 策略配置器（StrategyConfigurator）
- 股票篩選器（StockScreener）
- 打分引擎（ScoringEngine）
- 推薦理由引擎（ReasonEngine）
- 市場狀態檢測（MarketRegimeDetector）
- 產業映射（IndustryMapper）
- 回測分數門檻策略（ScoreThresholdPolicy）：fixed / Expanding T-1 quantile、60 個有效觀測暖機
- 推薦橫斷面百分位排名（Recommendation Percentile Ranker）：eligible universe empirical CDF

**為什麼它是核心**：
- 所有業務邏輯的實際實作都在這裡
- `app_module/` 服務層完全依賴它
- UI 層透過服務層間接使用它，或主程式直接初始化它

---

### Planned Market Intelligence Layer（目標 `market_module/`）

**目前狀態**：尚未建立正式 `market_module/`。

**目標責任**：
- Market Breadth
- Sector Rotation
- Relative Strength / Liquidity Ranking
- Watchlist Trigger
- Daily Decision Desk snapshot

**目前替代位置**：
- `decision_module/market_regime_detector.py`
- `decision_module/stock_screener.py`
- `decision_module/industry_mapper.py`
- `decision_module/flow_signal_engine.py`
- `app_module/regime_service.py`
- `app_module/screening_service.py`
- `app_module/broker_flow_service.py`

新增 Daily Decision Desk 前，必須先定義 service / DTO 邊界，不能在 UI 直接複製上述 domain 計算。

---

### AI Runtime Subsystem (`runtime/`)

**這一層負責什麼**：
- Governance-aware AI 執行環境與狀態管理
- FSM Lifecycle (IDLE -> THINKING -> VALIDATING -> APPROVED/ERROR/HALTED)
- DTO-first contracts 與 Append-only Audit Log
- 作為 AI-Native OS 的核心運作層，與 UI/Orchestration 解耦

**為什麼重要**：
- 保證 AI Agent 運作時的 Explainability 與 Governance
- 隔離 LLM Frameworks 與系統核心業務邏輯的污染
- 讓所有狀態流轉變得 Observable

---

## 3️⃣ 專案主要入口

### ✅ 主要啟動方式（推薦）

```bash
python ui_qt/main.py
```

**這是什麼**：PySide6 Qt 圖形界面，包含 7 個頂層 Tab：數據更新、市場觀察（含主力流向 / Smart Money 子 Tab）、策略回測（即 Research Lab 產品語意）、推薦分析、觀察清單、持倉管理、Runtime Observatory

Daily Decision Desk 尚未加入這 7 個頂層 Tab；它是 6M Roadmap Month 4 目標。

---

### ⚠️ Legacy 啟動方式（僅供參考）

`ui_app/main.py` 是舊 Tkinter UI 的歷史入口，不作為目前安裝、操作、驗證或新功能開發依據。需要目前 UI 請使用 `ui_qt/main.py`。

---

### ❌ 不建議使用的入口

- `examples/main_example.py`：已棄用的舊版主程式示例

---

## 4️⃣ 「我要做 X，要去哪裡看？」功能導航

### 📌 Data Update（數據更新）

**從哪個 UI 進**：`ui_qt/views/update_view.py`（數據更新 Tab）

**對應的 Service**：`app_module/update_service.py`
- 負責：數據狀態檢查、更新流程編排

**目前 UI 形態**：
- `UpdateView` 已整理為維運工作台式布局：左側導覽、上方狀態摘要、右側資料來源頁、底部共享日誌與進度
- 日常維護建議使用「安全更新所有數據」，保守依序執行狀態檢查、每日股價、大盤指數、產業指數、券商分點、每日合併與技術指標計算
- 單一來源維護仍可從左側導覽切換到每日股價、大盤指數、產業指數、券商分點、技術指標或進階維護

**真正動邏輯的地方**：
- `scripts/batch_update_daily_data.py`：批量更新每日股票數據
- `scripts/merge_daily_data.py`：合併數據到 meta_data
- `scripts/batch_update_market_and_industry_index.py`：更新市場/產業指數
- `scripts/calculate_technical_indicators.py`：計算技術指標
- `app_module/broker_branch_update_service.py`：券商分點資料抓取、標準化與合併

**如果我要改數據更新邏輯**：先看 `app_module/update_service.py`，再看對應的腳本檔案。如果要改 SQLite 資料檢視器分頁或查詢邏輯，看 `app_module/sqlite_inspector_service.py` 與 `ui_qt/widgets/sqlite_inspector_widget.py`。

---

### 📌 Market Watch（市場觀察）

**從哪個 UI 進**：`ui_qt/views/` 目錄下的 5 個視圖
- `market_regime_view.py`：大盤指數
- `strong_stocks_view.py`：強勢個股
- `weak_stocks_view.py`：弱勢個股
- `strong_industries_view.py`：強勢產業
- `weak_industries_view.py`：弱勢產業

**對應的 Service**：
- `app_module/screening_service.py`：強勢/弱勢股篩選
- `app_module/regime_service.py`：市場狀態檢測

**真正動邏輯的地方**：
- `decision_module/stock_screener.py`：股票篩選邏輯（強勢/弱勢判斷）
- `decision_module/market_regime_detector.py`：市場狀態判斷（Trend/Reversion/Breakout）
- `decision_module/industry_mapper.py`：產業映射與產業指數處理

**如果我要改市場觀察邏輯**：先看 `app_module/screening_service.py` 或 `app_module/regime_service.py`，再看 `decision_module/` 對應的檔案。

**如果我要做 Daily Decision Desk / Market Breadth / Watchlist Trigger**：先看 `docs/01_architecture/system_vision_specification.md` 與 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 的 Month 4；實作前先設計 `DecisionDeskSnapshot` / service 邊界，不要直接在 UI 層重算。

---

### 📌 Smart Money Terminal (籌碼分析)

**從哪個 UI 進**：`ui_qt/views/smart_money/smart_money_flow_view.py`（籌碼分析 Tab）

**對應的 Service**：`app_module/broker_flow_service.py`
- 負責：提供籌碼流向資料編排與查詢

**真正動邏輯的地方**：
- `decision_module/flow_signal_engine.py`：籌碼信號判斷邏輯（過濾、強度計算）
- `ui_qt/views/smart_money/terminal_delegate.py`：負責 UI 渲染細節（Row Intensity、Sparklines、Badges），不包含業務邏輯

**如果我要改籌碼邏輯**：
- 改信號或演算法判斷 → `decision_module/flow_signal_engine.py`
- 改畫面長相（顏色、趨勢線渲染） → `ui_qt/views/smart_money/terminal_delegate.py`

---

### 📌 Recommendation（推薦分析）

**從哪個 UI 進**：`ui_qt/views/recommendation_view.py`（推薦分析 Tab）

**對應的 Service**：`app_module/recommendation_service.py`
- 負責：策略配置編排、推薦結果生成、結果保存
- 推薦 Tab 也能把目前 Profile/Config 送到 Backtest Tab 的「推薦組合回測」，由回測頁在歷史日期重播推薦邏輯。

**真正動邏輯的地方**：
- `decision_module/strategy_configurator.py`：策略配置（技術指標、圖形模式設定）
- `decision_module/scoring_engine.py`：打分引擎（統一打分模型，0-100 分）
- `decision_module/indicator_parameter_registry.py`：指標參數 schema、版本、alias 與 Fail-Closed 驗證
- `decision_module/weight_contract.py`：推薦權重整數 bp 契約與 legacy migration
- `decision_module/recommendation_percentile_ranker.py`：推薦 eligible universe 橫斷面百分位

**門檻模式**：
- `fixed`：維持既有總分排序與 `top_n`
- `quantile`：先建立 eligible universe，再依 empirical CDF 百分位篩選；母體不足時拒絕降級
- `decision_module/reason_engine.py`：推薦理由生成（Why / Why Not）

**如果我要改推薦邏輯**：
- 改策略配置 → `decision_module/strategy_configurator.py`
- 改打分邏輯 → `decision_module/scoring_engine.py`
- 改推薦理由 → `decision_module/reason_engine.py`
- 改推薦結果 Excel 匯出 → `app_module/report_export_service.py` / `app_module/report_export_dtos.py`

---

### 📌 Backtest / Research Lab（策略回測 / 研究實驗室）

> 「策略回測」是頂層 Tab 名稱，「Research Lab」是其產品語意，支援單股回測、批次股票回測、固定組合回測、推薦系統回放與策略研究。

**從哪個 UI 進**：`ui_qt/views/backtest_view.py`（策略回測 Tab）

**對應的 Service**：
- `app_module/backtest_service.py`：單次回測
- `app_module/batch_backtest_service.py`：批次回測；負責 ProcessPool 工作分派、bounded in-flight queue、合作式取消與主行程集中保存
- `app_module/recommendation_replay_service.py`：歷史日期重播推薦邏輯
- `app_module/recommendation_portfolio_backtest_service.py`：推薦組合資金配置、持有期與績效彙整
- `app_module/recommendation_dataframe_provider.py`：推薦 replay 用資料提供與候選集 prefilter
- `app_module/recommendation_portfolio_dates.py`：台股資料日期解析工具，避免數字型 `YYYYMMDD` 誤判
- `app_module/walkforward_service.py`：Walk-forward 驗證
- `app_module/optimizer_service.py`：參數最佳化；使用 ThreadPool 與合作式取消
- `app_module/research_run_service.py`：Research Run Registry 保存 owner，協調 SQLite metadata、Parquet 明細、hash 與 crash reconciliation
- `app_module/research_run_repository.py`：Research Run SQLite schema、查詢、archive / promoted guard
- `app_module/research_run_legacy_adapter.py`：legacy Backtest / Recommendation Portfolio run 匯入 registry 的轉接層
- `app_module/research_run_comparison_service.py`：Registry run comparability、正規化 equity 交集與 benchmark attribution 比較
- `app_module/promotion_reconciliation_service.py`：Registry-based promote gate、JSON Strategy Version 補償交易與 reconciliation 掃描
- `app_module/exceptions.py`：跨服務共用的取消例外

**真正動邏輯的地方**：
- `backtest_module/strategy_tester.py`：策略測試器（執行策略邏輯）
- `backtest_module/performance_analyzer.py`：績效分析器（計算績效指標）
- `backtest_module/performance_metrics.py`：績效指標計算（包含 Walk-Forward 退化、一致性、過擬合風險）
- `backtest_module/broker_simulator.py`：券商模擬器（模擬交易執行）
- `app_module/strategies/`：策略執行器（實際策略邏輯）

**如果我要改回測邏輯**：
- 改回測流程 → `app_module/backtest_service.py`
- 改推薦組合歷史重播 → `app_module/recommendation_replay_service.py` / `app_module/recommendation_portfolio_backtest_service.py`
- 改績效計算 → `backtest_module/performance_metrics.py`
- 改策略執行 → `app_module/strategies/` 對應的執行器
- 改 Walk-Forward → `app_module/walkforward_service.py`
- 改報告匯出或 Excel 結構 → `app_module/report_export_service.py` / `app_module/report_export_dtos.py`
- 改研究結果保存、hash、archive 或 legacy backfill → `app_module/research_run_service.py` / `app_module/research_run_repository.py` / `scripts/backfill_legacy_runs.py`
- 改跨 run 比較、comparability 或 benchmark attribution → `app_module/research_run_comparison_service.py` / `ui_qt/views/research_lab/run_registry_compare_widget.py`
- 改 registry-based promotion、補償交易或 reconciliation → `app_module/promotion_reconciliation_service.py` / `app_module/strategy_version_service.py`

**如果我要改回測圖表 / 視覺化**：
- 改圖表資料轉換 → `ui_qt/widgets/chart_payloads.py`
- 改 fast Canvas 渲染 → `ui_qt/widgets/fast_chart_widget.py`
- 改 Backtest Tab 圖表掛載 → `ui_qt/views/backtest_view.py`
- 查架構說明 → `docs/08_technical/UI_QT_CHART_RENDERING.md`
- 注意：fast widgets 透過 factory 建立；QtWebEngine 不可用時會 fallback 到 `ui_qt/widgets/chart_widget.py` 的 Matplotlib widgets。

**特殊功能**：
- **Walk-Forward 暖機期**：`app_module/walkforward_service.py` 的 `warmup_days` 參數
- **Baseline 對比**：`backtest_module/performance_metrics.py` 的 `calculate_baseline_comparison()`
- **過擬合風險提示**：`backtest_module/performance_metrics.py` 的 `calculate_overfitting_risk()`
- **Research Run Registry**：保存入口由 `ResearchRunService.save_run()` 負責；Cross-run Comparison 與 Registry-based Promote 已完成 Month 2 M2-C 第一版。Registry save 仍不等同策略升級，promotion 必須通過 registry gate、Strategy Version JSON 補償交易與 reconciliation 防線。

---

### 📌 Agent / Codex / Antigravity 指引

**Codex 自動讀取入口**：`AGENTS.md`

**Antigravity 自動讀取入口**：`GEMINI.md`

**Antigravity 輔助規則**：`.agent/rules/`

**完整 Agent 架構**：`docs/agents/`

**使用規則**：
- Codex 會讀取 repo 根目錄 `AGENTS.md`。
- Antigravity 會讀取 repo 根目錄 `GEMINI.md`，並可搭配 `.agent/rules/` 的任務規則。
- `docs/agents/` 保存完整 Agent 職責、Prompt 與共用上下文，但不會單靠檔名自動成為 Codex 指令入口。
- 資料路徑請以 `data_module/config.py` 的 `TWStockConfig` 與 `DATA_ROOT` 為準，不要假設 repo 內一定存在正式 `data/` 目錄。

---

### 📌 Portfolio（持倉管理）

**目前狀態**：Portfolio 閉環已建立且完成主要深化：Portfolio Tab、domain/service/test、Recommendation/Backtest 來源追溯 metadata、策略與價格監控、目前價格對照、未實現損益、停損停利警示、籌碼監控與 Smart Money 下鑽皆已完成。

**從哪個 UI 進**：`ui_qt/views/portfolio_view.py`（持倉管理 Tab）

**對應的 Service**：
- `app_module/portfolio_service.py`：Portfolio use case 編排
- `app_module/portfolio_condition_monitor.py`：條件監控（來源快照 vs 目前快照 Regime/TotalScore 對照）
- `app_module/portfolio_chip_service.py`：持倉層籌碼監控與分點資料彙整
- `app_module/journal_service.py`：交易/決策紀錄服務

**真正動邏輯的地方**：
- `portfolio_module/`：Portfolio MVP domain layer

**如果我要改持倉管理邏輯**：
- 改 domain 規則 → `portfolio_module/`
- 改服務編排 → `app_module/portfolio_service.py`
- 改條件監控 → `app_module/portfolio_condition_monitor.py`
- 改 UI → `ui_qt/views/portfolio_view.py`

---

### 📌 Watchlist（觀察清單）

**從哪個 UI 進**：`ui_qt/views/watchlist_view.py`（觀察清單 Tab）

**對應的 Service**：`app_module/watchlist_service.py`
- 負責：跨 Tab 共用候選池管理、JSON 持久化

**真正動邏輯的地方**：
- `app_module/watchlist_service.py`：觀察清單的完整邏輯都在這裡（沒有 Domain 層依賴）

**如果我要改觀察清單邏輯**：直接看 `app_module/watchlist_service.py`。

---

### 📌 AI Runtime Observatory (狀態機監控站)

**從哪個 UI 進**：`ui_qt/views/runtime_view.py`（Runtime Observatory Tab）

**對應的 Service**：
- `app_module/runtime_services/runtime_controller.py`
- `app_module/runtime_services/snapshot_service.py`
- `app_module/runtime_services/health_service.py`
- `app_module/runtime_services/event_bus.py`

**真正動邏輯的地方**：
- `runtime/store/local_file_store.py`：所有事件與狀態的實際 I/O 儲存。
- `ui_qt/bridges/runtime_event_bridge.py`：唯一的 Qt Signal 轉譯點。

**如果我要改 Runtime 邏輯**：
- 改 DTO 或 FSM 狀態 → `app_module/dtos/runtime_dtos.py`
- 改指標計算 → `app_module/runtime_services/health_service.py`
- 改架構規範 → 查閱 `docs/architecture/runtime_observatory_rules.md`

---

## 5️⃣ ⚠️ 高風險核心檔案（Do Not Touch Blindly）

### `decision_module/scoring_engine.py`
**為什麼風險高**：統一打分模型的核心，所有推薦分數都從這裡計算，改動會影響所有策略。

### `decision_module/strategy_configurator.py`
**為什麼風險高**：策略配置的核心，定義所有技術指標和圖形模式的參數，改動會影響所有推薦結果。

### `backtest_module/performance_metrics.py`
**為什麼風險高**：所有回測績效指標的計算邏輯，包含 Walk-Forward 退化、一致性、過擬合風險等核心計算。

### `app_module/backtest_service.py`
**為什麼風險高**：回測流程的編排核心，整合策略執行器、績效分析器、券商模擬器，改動會影響所有回測結果。

### `app_module/walkforward_service.py`
**為什麼風險高**：Walk-Forward 驗證的核心邏輯，包含暖機期處理、訓練/測試期分割，改動會影響驗證結果。

### `backtest_module/broker_simulator.py`
**為什麼風險高**：模擬交易執行的核心，包含手續費、滑價、停損停利等邏輯，改動會影響所有回測的實際交易模擬。

### `decision_module/stock_screener.py`
**為什麼風險高**：強勢/弱勢股篩選的核心邏輯，改動會影響市場觀察的所有結果。

### `decision_module/market_regime_detector.py`
**為什麼風險高**：市場狀態判斷的核心，改動會影響所有依賴 Regime 的策略和推薦。

### `data_module/config.py`
**為什麼風險高**：所有數據路徑和配置的核心，改動會影響整個系統的數據存取。

### `app_module/recommendation_service.py`
**為什麼風險高**：推薦分析的編排核心，整合策略配置、打分、理由生成，改動會影響所有推薦結果。

---

## 6️⃣ Legacy / Historical 區塊

### `ui_app/` 目錄

**角色**：Legacy Tkinter UI

**狀態**：
- 業務邏輯已遷移到 `decision_module/`
- 僅保留 Tkinter UI 相關代碼
- 不保證 Legacy UI 與目前 7 個工作區、資料契約或使用手冊同步

**使用建議**：新功能不應再引用 `ui_app/` 中的業務邏輯檔案（如 `strategy_configurator.py`、`stock_screener.py` 等），這些檔案已不存在或已遷移。

---

### `recommendation_module_legacy/` 目錄

**角色**：舊版推薦引擎（已棄用）

**狀態**：
- 僅被 `tests/` 和 `examples/` 使用
- 不屬於核心架構
- 已添加棄用警告

**使用建議**：新功能應使用 `app_module/recommendation_service.py`，不應再引用 `recommendation_module_legacy/`。

---

### 不應再被新功能引用的模組

- `ui_app/` 中的業務邏輯檔案（已遷移到 `decision_module/`）
- `recommendation_module_legacy/`（應使用 `app_module/recommendation_service.py`）
- `examples/main_example.py`（已棄用）

---

## 📚 相關文檔

- **目前狀態快照**：`docs/00_core/PROJECT_SNAPSHOT.md`
- **6 個月工程路線**：`docs/00_core/ROADMAP_6M_ENGINEERING.md`
- **IDS 產品北極星**：`docs/01_architecture/system_vision_specification.md`
- **Roadmap Hub**：`docs/00_core/DEVELOPMENT_ROADMAP.md`
- **舊 Roadmap 移交矩陣**：`docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- **完整操作手冊**：`docs/07_guides/APPLICATION_MANUAL.md`
- **專案盤點報告**：`PROJECT_INVENTORY.md`（完整的專案結構盤點，與本文檔同層）
- **文檔索引**：`docs/00_core/DOCUMENTATION_INDEX.md`（所有文檔的索引）

---

**文件結束**

## 券商分點雙指標資料流

- 抓取與合併：`app_module/broker_branch_update_service.py`
- CSV 到 SQLite：`app_module/update_service.py`
- SQLite schema：`data_module/db_manager.py`
- Smart Money 張數讀取：`app_module/broker_flow_service.py`
- Portfolio Phase 4.2：`app_module/portfolio_chip_service.py`

資料契約：`c=E` 寫入張數，`c=B` 寫入仟元金額；legacy `buy_qty` 不得當張數。

