# 專案盤點報告 (Project Inventory)

**生成日期**：2025-01-XX  
**專案名稱**：台股技術分析系統 (Taiwan Stock Technical Analysis System)  
**盤點目的**：完整盤點專案目前狀態，協助後續結構化重整

---

## 📋 目錄

1. [專案結構總覽](#1-專案結構總覽)
2. [核心進入點 (Entry Points)](#2-核心進入點-entry-points)
3. [主要功能模組盤點](#3-主要功能模組盤點)
4. [可疑或高風險區域](#4-可疑或高風險區域)
5. [專案狀態總結](#5-專案狀態總結)

---

## 1. 專案結構總覽

### 1.1 完整資料夾樹狀結構

```
technical_analysis/
├── 📁 核心模組（Core Modules）
│   ├── data_module/              # ✅ 核心 - 數據處理模組
│   │   ├── config.py             # 配置管理（路徑、環境變數）
│   │   ├── data_loader.py        # 數據載入器
│   │   └── data_processor.py    # 數據處理器
│   │
│   ├── analysis_module/          # ✅ 核心 - 分析模組
│   │   ├── technical_analysis/  # 技術指標計算
│   │   ├── pattern_analysis/     # 圖形模式識別
│   │   ├── signal_analysis/      # 信號分析
│   │   └── ml_analysis/          # 機器學習分析
│   │
│   ├── backtest_module/          # ✅ 核心 - 回測模組
│   │   ├── strategy_tester.py   # 策略測試器
│   │   ├── performance_analyzer.py # 績效分析器
│   │   ├── performance_metrics.py  # 績效指標
│   │   └── broker_simulator.py    # 券商模擬器
│   │
│   ├── decision_module/          # ✅ 核心 - 決策邏輯模組（Domain Layer）
│   │   ├── strategy_configurator.py # 策略配置器
│   │   ├── reason_engine.py      # 推薦理由引擎
│   │   ├── scoring_engine.py    # 打分引擎
│   │   ├── stock_screener.py    # 股票篩選器
│   │   ├── market_regime_detector.py # 市場狀態檢測
│   │   └── industry_mapper.py   # 產業映射
│   │
│   ├── recommendation_module_legacy/ # ⚠️ 舊版 - 推薦模組（已棄用）
│   │   └── recommendation_engine.py # 推薦引擎（舊版，已棄用）
│   │
│   └── app_module/               # ✅ 核心 - 應用服務層（Application Service Layer）
│       ├── recommendation_service.py  # 推薦服務
│       ├── screening_service.py       # 強勢股/產業篩選服務
│       ├── regime_service.py           # 市場狀態檢測服務
│       ├── update_service.py          # 數據更新服務
│       ├── backtest_service.py        # 回測服務
│       ├── batch_backtest_service.py   # 批次回測服務
│       ├── watchlist_service.py        # 觀察清單服務
│       ├── strategies/                 # 策略執行器
│       │   ├── baseline_score_executor.py
│       │   ├── momentum_aggressive_executor.py
│       │   └── stable_conservative_executor.py
│       ├── backtest_repository.py      # 回測結果儲存
│       ├── recommendation_repository.py # 推薦結果儲存
│       ├── broker_flow_service.py      # 籌碼流向服務 (Smart Money)
│       └── dtos.py                     # 數據傳輸對象
│
├── 📁 AI 運行層（Runtime Subsystem）
│   └── runtime/                  # ✅ 核心 - Governance-aware AI Runtime
│       ├── store/                # 狀態與事件儲存 (Local File Store)
│       ├── events/               # EventBus 與事件定義
│       ├── state/                # FSM 狀態機管理
│       └── registry/             # 代理與技能註冊表
│
├── 📁 UI 應用（User Interfaces）
│   ├── ui_qt/                    # ✅ 核心 - PySide6 Qt UI（推薦使用）
│   │   ├── main.py              # 主入口（QApplication）
│   │   ├── views/               # 視圖層
│   │   │   ├── update_view.py
│   │   │   ├── market_regime_view.py
│   │   │   ├── strong_stocks_view.py
│   │   │   ├── weak_stocks_view.py
│   │   │   ├── strong_industries_view.py
│   │   │   ├── weak_industries_view.py
│   │   │   ├── recommendation_view.py
│   │   │   ├── backtest_view.py
│   │   │   ├── watchlist_view.py
│   │   │   ├── runtime_view.py       # Runtime Observatory UI
│   │   │   └── smart_money/          # Smart Money Terminal
│   │   │       ├── smart_money_flow_view.py
│   │   │       ├── summary_strip.py
│   │   │       ├── terminal_delegate.py
│   │   │       └── terminal_table_model.py
│   │   ├── models/              # 數據模型
│   │   │   └── pandas_table_model.py
│   │   ├── workers/             # 背景任務
│   │   │   └── task_worker.py
│   │   └── widgets/             # UI 組件
│   │       ├── chart_widget.py
│   │       └── info_button.py
│   │
│   └── ui_app/                   # ⚠️ 舊版 - Tkinter UI（僅保留 UI 代碼）
│       ├── main.py               # 主入口（Tkinter）
│       └── strategies.py         # 策略定義（UI 相關）
│
├── 📁 工具腳本（Scripts）
│   └── scripts/                  # ✅ 核心 - 數據更新與維護腳本
│       ├── update_all_data.py           # 全面數據更新
│       ├── batch_update_daily_data.py   # 批量更新每日數據
│       ├── update_daily_stock_data.py   # 更新單日股票數據
│       ├── merge_daily_data.py          # 合併每日數據
│       ├── calculate_technical_indicators.py # 計算技術指標
│       ├── simple_technical_calc.py     # 簡化技術指標計算
│       ├── date_specific_indicator_calc.py # 特定日期指標計算
│       ├── fix_market_index.py          # 修復市場指數
│       ├── fix_industry_index.py        # 修復產業指數
│       ├── batch_update_market_and_industry_index.py # 批量更新市場/產業指數
│       ├── qa_validate_phase2_5.py      # QA 驗證腳本
│       ├── qa_validate_recommendation_tab.py # QA 驗證腳本
│       ├── qa_validate_update_tab.py    # QA 驗證腳本
│       ├── test_*.py                    # ⚠️ 測試腳本（應移到 tests/）
│       └── verify_*.py                  # 驗證腳本
│
├── 📁 測試（Tests）
│   └── tests/                     # ✅ 核心 - 單元測試與整合測試
│       ├── test_technical_calc.py
│       ├── test_finmind_integration.py
│       ├── test_market_index.py
│       ├── test_analysis/
│       ├── test_api/
│       ├── test_backtest/
│       ├── test_core/
│       ├── test_data/
│       ├── test_ml_analysis/
│       ├── test_pattern_analysis/
│       ├── test_recommendation/
│       ├── test_technical_analysis/
│       └── test_utils/
│
├── 📁 文檔（Documentation）
│   └── docs/                      # ✅ 核心 - 完整文檔系統（55個文件）
│       ├── DEVELOPMENT_ROADMAP.md      # 開發演進地圖（最重要）
│       ├── DOCUMENTATION_INDEX.md     # 文檔索引
│       ├── UI_FEATURES_DOCUMENTATION.md # UI 功能文檔
│       ├── USER_GUIDE.md              # 使用者指南
│       ├── system_architecture.md     # 系統架構
│       └── [其他 50+ 個文檔...]
│
├── 📁 數據存儲（Data Storage）
│   └── data/                      # ✅ 核心 - 數據目錄
│       ├── meta_data/             # 元數據（股票數據整合）
│       ├── daily_price/           # 每日價格數據
│       ├── technical_analysis/    # 技術指標數據
│       ├── processed/             # 處理後數據
│       ├── raw/                   # 原始數據
│       └── logs/                  # 日誌文件
│
├── 📁 輸出（Output）
│   └── output/                    # ✅ 核心 - 輸出目錄
│       ├── results/               # 分析結果
│       ├── reports/               # 報告文件
│       └── qa/                    # QA 驗證報告
│
├── 📁 範例（Examples）
│   └── examples/                  # ⚠️ 實驗/參考 - 範例代碼
│       ├── main_example.py        # 舊版主程式示例（已棄用）
│       ├── system_config.py       # 舊版系統配置（已棄用）
│       └── README.md
│
├── 📁 實驗/測試目錄（Experimental）
│   ├── demo_atomic_data/          # ⚠️ 實驗 - Demo 測試數據
│   ├── demo_atomic_output/        # ⚠️ 實驗 - Demo 測試輸出
│   ├── demo_dry_run_data/         # ⚠️ 實驗 - Demo 乾運行數據
│   ├── demo_dry_run_output/       # ⚠️ 實驗 - Demo 乾運行輸出
│   ├── demo_helpers_data/         # ⚠️ 實驗 - Demo 輔助數據
│   ├── demo_helpers_output/       # ⚠️ 實驗 - Demo 輔助輸出
│   ├── demo_test_data/            # ⚠️ 實驗 - Demo 測試數據
│   └── test_data/                 # ⚠️ 實驗 - 測試數據
│
├── 📁 根目錄檔案（Root Files）
│   ├── README.md                  # ✅ 核心 - 專案說明
│   ├── readme.txt                 # ⚠️ 重複 - 完整系統說明（可能與 README.md 重複）
│   ├── requirements.txt            # ✅ 核心 - Python 依賴
│   ├── CLEANUP_PLAN.md            # ⚠️ 計劃 - 清理計劃（未執行）
│   ├── 策略回測功能清單.md        # ✅ 核心 - 功能清單
│   ├── 策略回測常見問題解答.md    # ✅ 核心 - 常見問題
│   ├── 01_stock_data_collector_enhanced.py # ⚠️ 實驗 - 增強版數據收集器
│   ├── 01_stock_data_collector.ipynb      # ⚠️ 實驗 - 數據收集器 Notebook
│   ├── 01_stock_data_collector.md         # ⚠️ 實驗 - 數據收集器說明
│   ├── 02_technical_calculator.ipynb      # ⚠️ 實驗 - 技術計算器 Notebook
│   ├── 02_technical_calculator.md         # ⚠️ 實驗 - 技術計算器說明
│   ├── Crawler.ipynb              # ⚠️ 實驗 - 爬蟲 Notebook
│   ├── install_dependencies.ipynb # ⚠️ 實驗 - 依賴安裝 Notebook
│   ├── moneydj_branches.csv       # ⚠️ 數據 - 券商分支數據
│   ├── test.parquet               # ⚠️ 測試 - 測試 Parquet 文件
│   └── technical_calculation.log  # ⚠️ 日誌 - 技術計算日誌
│
└── 📁 其他
    └── technical_analysis/        # ⚠️ 不明 - 技術分析目錄（可能重複或未使用）
        └── utils/
```

### 1.2 核心模組標註

#### ✅ 核心模組（Core Modules）
- **data_module/** - 數據處理核心，負責數據載入、處理、配置管理
- **analysis_module/** - 分析核心，包含技術分析、圖形識別、信號分析、ML 分析
- **backtest_module/** - 回測核心，策略測試、績效分析、券商模擬
- **app_module/** - 應用服務層核心，UI 與業務邏輯解耦的關鍵層
- **recommendation_module/** - 推薦模組（舊版，可能被 app_module 取代）
- **runtime/** - Governance-aware AI Runtime 運行層，負責系統的可觀測性與狀態管理

#### ✅ UI 核心
- **ui_qt/** - PySide6 Qt UI（推薦使用，現代化界面）
- **ui_app/** - Tkinter UI（舊版，仍在使用但非主要）

#### ✅ 工具腳本核心
- **scripts/** - 數據更新、維護、驗證腳本

#### ✅ 測試核心
- **tests/** - 完整的測試套件

#### ✅ 文檔核心
- **docs/** - 完整的文檔系統（55個文件）

#### ⚠️ 實驗/測試/暫時用途
- **examples/** - 範例代碼（部分已棄用）
- **demo_*** - 多個 Demo 測試目錄
- **test_data/** - 測試數據目錄
- **根目錄的 .ipynb 和 .md 文件** - 實驗性 Notebook 和說明文件
- **scripts/test_*.py** - 測試腳本（應移到 tests/）

---

## 2. 核心進入點 (Entry Points)

### 2.1 程式主要執行入口

#### ✅ 主要入口（目前使用中）

1. **ui_qt/main.py** - **推薦使用的主要入口**
   - **功能**：PySide6 Qt 圖形界面應用程式
   - **狀態**：✅ 目前使用中（Phase 2.5 完成，Phase 3.1 進行中）
   - **啟動方式**：`python ui_qt/main.py`
   - **主要功能**：
     - 數據更新 Tab
     - 市場觀察 Tab（大盤指數、強勢/弱勢個股、強勢/弱勢產業）
     - 籌碼分析 Tab（Smart Money Terminal）
     - 推薦分析 Tab
     - 策略回測 Tab（完整回測實驗室）
     - 觀察清單 Tab
     - 運行監控 Tab（Runtime Observatory）
   - **架構**：使用 app_module 服務層，UI 與業務邏輯解耦

2. **ui_app/main.py** - **舊版入口（仍在使用）**
   - **功能**：Tkinter 圖形界面應用程式
   - **狀態**：⚠️ 仍在使用，但非主要入口
   - **啟動方式**：`python ui_app/main.py`
   - **主要功能**：
     - 數據更新
     - 策略配置
     - 市場觀察
     - 策略推薦
   - **架構**：業務邏輯與 UI 耦合（stock_screener.py, strategy_configurator.py 等）

#### ⚠️ 實驗/參考入口（已棄用或僅供參考）

3. **examples/main_example.py** - **已棄用**
   - **功能**：舊版主程式示例
   - **狀態**：❌ 已棄用，僅供參考
   - **註釋**：文件開頭標註「舊版主程式示例（已棄用）」

### 2.2 UI 主畫面進入點

#### Qt UI（推薦）
- **入口**：`ui_qt/main.py` → `MainWindow` 類
- **Tab 結構**：
  1. 數據更新（UpdateView）
  2. 市場觀察（MarketWatch，包含 5 個子 Tab）
  3. 推薦分析（RecommendationView）
  4. 策略回測（BacktestView）
  5. 觀察清單（WatchlistView）

#### Tkinter UI（舊版）
- **入口**：`ui_app/main.py` → `TradingAnalysisApp` 類
- **Tab 結構**：數據更新、策略選擇、回測、市場觀察、推薦分析

### 2.3 回測或分析的主要呼叫流程

#### 回測流程（Qt UI）
```
ui_qt/main.py (MainWindow)
  → ui_qt/views/backtest_view.py (BacktestView)
    → app_module/backtest_service.py (BacktestService)
      → backtest_module/strategy_tester.py (StrategyTester)
        → backtest_module/performance_analyzer.py (PerformanceAnalyzer)
```

#### 推薦分析流程（Qt UI）
```
ui_qt/main.py (MainWindow)
  → ui_qt/views/recommendation_view.py (RecommendationView)
    → app_module/recommendation_service.py (RecommendationService)
      → ui_app/strategy_configurator.py (業務邏輯，未來會遷移)
      → ui_app/reason_engine.py (業務邏輯，未來會遷移)
      → ui_app/industry_mapper.py (業務邏輯，未來會遷移)
```

#### 市場觀察流程（Qt UI）
```
ui_qt/main.py (MainWindow)
  → ui_qt/views/strong_stocks_view.py (StrongStocksView)
    → app_module/screening_service.py (ScreeningService)
      → ui_app/stock_screener.py (業務邏輯，未來會遷移)
```

### 2.4 數據更新流程

#### 數據更新（Qt UI）
```
ui_qt/main.py (MainWindow)
  → ui_qt/views/update_view.py (UpdateView)
    → app_module/update_service.py (UpdateService)
      → scripts/batch_update_daily_data.py (腳本執行)
      → scripts/merge_daily_data.py (腳本執行)
```

### 2.5 命令行腳本入口

#### 數據更新腳本
- `scripts/update_all_data.py` - 全面數據更新
- `scripts/batch_update_daily_data.py` - 批量更新每日數據
- `scripts/update_daily_stock_data.py` - 更新單日股票數據
- `scripts/merge_daily_data.py` - 合併每日數據
- `scripts/calculate_technical_indicators.py` - 計算技術指標

#### 數據修復腳本
- `scripts/fix_market_index.py` - 修復市場指數
- `scripts/fix_industry_index.py` - 修復產業指數

#### QA 驗證腳本
- `scripts/qa_validate_phase2_5.py` - Phase 2.5 驗證
- `scripts/qa_validate_recommendation_tab.py` - 推薦分析 Tab 驗證
- `scripts/qa_validate_update_tab.py` - 數據更新 Tab 驗證

---

## 3. 主要功能模組盤點

### 3.1 市場觀察（Market Watch）

**功能目的**：觀察市場強勢/弱勢個股與產業，判斷市場狀態

**對應檔案**：
- `app_module/screening_service.py` - 強勢股/產業篩選服務
- `app_module/regime_service.py` - 市場狀態檢測服務
- `ui_qt/views/market_regime_view.py` - 大盤指數視圖
- `ui_qt/views/strong_stocks_view.py` - 強勢個股視圖
- `ui_qt/views/weak_stocks_view.py` - 弱勢個股視圖
- `ui_qt/views/strong_industries_view.py` - 強勢產業視圖
- `ui_qt/views/weak_industries_view.py` - 弱勢產業視圖
- `ui_app/stock_screener.py` - 股票篩選器（業務邏輯，未來會遷移）
- `ui_app/market_regime_detector.py` - 市場狀態檢測（業務邏輯，未來會遷移）

**狀態**：✅ **完整** - Phase 1 已完成，Phase 2-B 弱勢分析已完成

**功能**：
- 強勢/弱勢個股篩選（本日/本周）
- 強勢/弱勢產業篩選（本日/本周）
- 市場 Regime 判斷（Trend/Reversion/Breakout）
- 緩存機制（避免重複計算）
- 整合觀察清單（可加入候選池）

### 3.2 推薦分析（Recommendation）

**功能目的**：基於統一打分模型生成股票推薦，提供推薦理由

**對應檔案**：
- `app_module/recommendation_service.py` - 推薦服務
- `app_module/recommendation_repository.py` - 推薦結果儲存
- `ui_qt/views/recommendation_view.py` - 推薦分析視圖
- `ui_app/strategy_configurator.py` - 策略配置器（業務邏輯，未來會遷移）
- `ui_app/reason_engine.py` - 推薦理由引擎（業務邏輯，未來會遷移）
- `ui_app/scoring_engine.py` - 打分引擎（業務邏輯，未來會遷移）

**狀態**：✅ **完整** - Phase 1 已完成，Phase 3.1 進行中（新手/進階模式、Why Not）

**功能**：
- 策略配置（技術指標、圖形模式、篩選條件）
- 新手/進階模式切換
- Profiles v1（暴衝/穩健/長期）
- 推薦結果顯示（Why + Why Not）
- 結果保存功能
- 整合觀察清單

### 3.3 策略回測（Backtest）

**功能目的**：完整的策略回測實驗室，從策略開發到結果分析

**對應檔案**：
- `app_module/backtest_service.py` - 回測服務
- `app_module/batch_backtest_service.py` - 批次回測服務
- `app_module/backtest_repository.py` - 回測結果儲存
- `app_module/optimizer_service.py` - 參數最佳化服務
- `app_module/walkforward_service.py` - Walk-forward 驗證服務
- `app_module/preset_service.py` - 策略預設服務
- `app_module/strategies/` - 策略執行器
- `backtest_module/strategy_tester.py` - 策略測試器
- `backtest_module/performance_analyzer.py` - 績效分析器
- `backtest_module/broker_simulator.py` - 券商模擬器
- `ui_qt/views/backtest_view.py` - 策略回測視圖

**狀態**：✅ **完整** - Phase 2 已完成，Phase 3.3b 進行中

**功能**：
- 策略管理（預設保存/載入/刪除）
- 選股清單管理
- 單檔/批次回測
- 參數最佳化（Grid Search）
- Walk-forward 驗證
  - ✅ Walk-Forward 暖機期（warmup_days 參數，預設 0，向後兼容）
  - ✅ Baseline 對比（Buy & Hold 策略對比）
  - 🚧 過擬合風險提示（實作中，階段 1-2 已完成）
- 結果保存與載入（SQLite + Parquet/CSV）
- 回測歷史管理
- 圖表視覺化（權益曲線、回撤曲線、報酬分佈、持有天數）
- 整合觀察清單

### 3.4 Watchlist（觀察清單）

**功能目的**：跨 Tab 共用候選池管理

**對應檔案**：
- `app_module/watchlist_service.py` - 觀察清單服務
- `ui_qt/views/watchlist_view.py` - 觀察清單視圖

**狀態**：✅ **完整** - Phase 2-A 已完成

**功能**：
- 跨 Tab 共用候選池（Market Watch、Recommendation、Backtest）
- 股票來源追蹤（market_watch、recommendation、manual）
- 備註與標籤管理
- 選股清單管理（用於回測）
- JSON 持久化

### 3.5 資料更新（Data Update）

**功能目的**：更新每日股票數據、大盤指數、產業指數

**對應檔案**：
- `app_module/update_service.py` - 數據更新服務
- `ui_qt/views/update_view.py` - 數據更新視圖
- `scripts/batch_update_daily_data.py` - 批量更新每日數據
- `scripts/update_daily_stock_data.py` - 更新單日股票數據
- `scripts/merge_daily_data.py` - 合併每日數據
- `scripts/batch_update_market_and_industry_index.py` - 批量更新市場/產業指數

**狀態**：✅ **完整** - Phase 1 已完成，並引入 skip_backup 提升批次更新效能

**功能**：
- 數據狀態檢查
- 每日股票數據更新（支持查找範圍設置，具備 skip_backup 最佳化）
- 大盤指數更新
- 產業指數更新
- 合併每日數據（增量合併）
- 強制重新合併（完全重建）

### 3.6 籌碼分析（Smart Money Terminal）

**功能目的**：高密度、低延遲的專業級籌碼流向觀察終端

**對應檔案**：
- `app_module/broker_flow_service.py` - 籌碼流向服務
- `decision_module/flow_signal_engine.py` - 籌碼信號引擎
- `ui_qt/views/smart_money/smart_money_flow_view.py` - 籌碼終端視圖
- `ui_qt/views/smart_money/terminal_table_model.py` - 高效能表格模型
- `ui_qt/views/smart_money/terminal_delegate.py` - 自定義繪圖委派

**狀態**：✅ **完整** - 具備專業 Terminal 風格渲染

**功能**：
- Row Intensity Shading (強度著色)
- Inline Signal Badges (內聯信號徽章)
- Lightweight Sparklines (輕量級趨勢線)
- 響應式、高效能的資料渲染 (完全交給 Qt native 渲染)

### 3.7 AI 運行監控（Runtime Observatory）

**功能目的**：提供 Governance-aware AI Runtime 的完全可觀測性

**對應檔案**：
- `runtime/` 模組中的 Store, EventBus, State 機制
- `ui_qt/views/runtime_view.py` - 監控站視圖

**狀態**：✅ **完整** - Explainability-first 架構落實

**功能**：
- 狀態機生命週期監控 (IDLE, THINKING, VALIDATING, APPROVED/ERROR/HALTED)
- DTO-first 的不可變審計日誌展示 (Append-only)
- 確保所有 AI 決策流程的可視化和可追溯性

### 3.6 技術指標計算（Technical Indicators）

**功能目的**：計算技術指標數據

**對應檔案**：
- `analysis_module/technical_analysis/technical_analyzer.py` - 技術分析器
- `analysis_module/technical_analysis/technical_indicators.py` - 技術指標
- `scripts/calculate_technical_indicators.py` - 計算技術指標腳本
- `scripts/simple_technical_calc.py` - 簡化技術指標計算
- `scripts/date_specific_indicator_calc.py` - 特定日期指標計算

**狀態**：✅ **完整** - 功能完整

**功能**：
- 多種技術指標計算（RSI、MACD、KD、移動平均線、ADX、布林通道、ATR 等）
- 批量計算所有股票
- 增量更新支持

### 3.9 圖形模式識別（Pattern Analysis）

**功能目的**：識別圖形模式（W底、頭肩底、雙底等）

**對應檔案**：
- `analysis_module/pattern_analysis/pattern_analyzer.py` - 圖形分析器
- `analysis_module/pattern_analysis/pattern_parameter_optimizer.py` - 參數最佳化器
- `analysis_module/pattern_analysis/signal_combiner.py` - 信號組合器

**狀態**：✅ **完整** - 功能完整

**功能**：
- 12 種圖形模式識別
- ATR-based 參數設計
- 模式評分

### 3.10 機器學習分析（ML Analysis）

**功能目的**：機器學習分析（未來擴展）

**對應檔案**：
- `analysis_module/ml_analysis/ml_analyzer.py` - ML 分析器

**狀態**：⚠️ **半成品** - 存在但可能未完全整合

### 3.11 信號分析（Signal Analysis）

**功能目的**：信號組合與分析

**對應檔案**：
- `analysis_module/signal_analysis/signal_combiner.py` - 信號組合器

**狀態**：✅ **完整** - 功能完整

---

## 4. 可疑或高風險區域

### 4.1 檔名或資料夾命名混亂

#### ⚠️ 重複命名
1. **recommendation_module/** vs **app_module/recommendation_service.py**
   - `recommendation_module/recommendation_engine.py` - 舊版推薦引擎
   - `app_module/recommendation_service.py` - 新版推薦服務
   - **問題**：兩者功能可能重複，需要確認是否仍在使用舊版

2. **technical_analysis/** 目錄（根目錄下）
   - 根目錄下有 `technical_analysis/utils/` 目錄
   - 同時存在 `analysis_module/technical_analysis/` 目錄
   - **問題**：命名重複，可能造成混淆

3. **readme.txt** vs **README.md**
   - 兩個文件可能內容重複
   - **問題**：需要確認是否都需要保留

#### ⚠️ 命名不一致
1. **scripts/** 目錄中的測試腳本
   - `test_*.py` - 測試腳本（應移到 tests/）
   - `verify_*.py` - 驗證腳本
   - **問題**：測試腳本不應放在 scripts/ 目錄

### 4.2 明顯重複功能

#### ⚠️ UI 重複
1. **ui_qt/** vs **ui_app/**
   - 兩個 UI 系統並存
   - `ui_qt/` 是推薦使用的新版（PySide6）
   - `ui_app/` 是舊版（Tkinter），但仍在使用
   - **問題**：需要確認是否可以完全遷移到 ui_qt

2. **業務邏輯位置混亂**
   - `ui_app/` 中包含業務邏輯（stock_screener.py, strategy_configurator.py 等）
   - `app_module/` 服務層內部 import `ui_app` 模組
   - **問題**：業務邏輯應從 ui_app 遷移到 app_module 或新建 decision_module

#### ⚠️ 配置重複
1. **examples/system_config.py** vs **data_module/config.py**
   - `examples/system_config.py` - 舊版系統配置（已棄用）
   - `data_module/config.py` - 新版配置系統
   - **問題**：舊版配置應移除或明確標註為參考

### 4.3 看起來像「以前試過但現在沒清掉」的區塊

#### ⚠️ 實驗性 Notebook
1. **根目錄的 .ipynb 文件**
   - `01_stock_data_collector.ipynb` - 數據收集器 Notebook
   - `02_technical_calculator.ipynb` - 技術計算器 Notebook
   - `Crawler.ipynb` - 爬蟲 Notebook
   - `install_dependencies.ipynb` - 依賴安裝 Notebook
   - **問題**：這些可能是開發過程中的實驗性文件，需要確認是否仍在使用

2. **根目錄的 .md 文件**
   - `01_stock_data_collector.md` - 數據收集器說明
   - `02_technical_calculator.md` - 技術計算器說明
   - **問題**：這些可能是開發過程中的說明文件，需要確認是否應移到 docs/

#### ⚠️ Demo 目錄
1. **多個 demo_* 目錄**
   - `demo_atomic_data/`, `demo_atomic_output/`
   - `demo_dry_run_data/`, `demo_dry_run_output/`
   - `demo_helpers_data/`, `demo_helpers_output/`
   - `demo_test_data/`
   - **問題**：這些可能是測試過程中的臨時目錄，需要確認是否可以清理

#### ⚠️ 測試文件位置混亂
1. **scripts/test_*.py**
   - `scripts/test_all_branches_one_day.py`
   - `scripts/test_broker_branch_10days.py`
   - `scripts/test_broker_branch_single.py`
   - `scripts/test_moneydj_requests.py`
   - `scripts/test_moneydj_requests_tables.py`
   - **問題**：測試腳本應移到 tests/ 目錄

#### ⚠️ 根目錄的臨時文件
1. **test.parquet** - 測試 Parquet 文件
2. **technical_calculation.log** - 技術計算日誌
3. **moneydj_branches.csv** - 券商分支數據（應移到 data/）

### 4.4 未使用的模組或功能

#### ⚠️ 可能未使用的模組
1. **recommendation_module/recommendation_engine.py**
   - 可能已被 `app_module/recommendation_service.py` 取代
   - **需要確認**：是否仍在使用

2. **examples/main_example.py**
   - 已明確標註「已棄用」
   - **建議**：移除或移到 docs/ 作為參考

3. **examples/system_config.py**
   - 已明確標註「已棄用」
   - **建議**：移除或移到 docs/ 作為參考

### 4.5 清理計劃未執行

#### ⚠️ CLEANUP_PLAN.md
- 存在 `CLEANUP_PLAN.md` 文件，列出需要清理的文件
- **問題**：清理計劃似乎未執行，許多列出的文件仍存在

---

## 5. 專案狀態總結

### 5.1 專案目前「實際在做什麼」

**專案定位**：台股技術分析系統 - 「可驗證、可回溯、可演化」的投資決策系統

**核心功能**：
1. **數據更新**：每日股票數據、大盤指數、產業指數的更新與合併
2. **市場觀察**：強勢/弱勢個股與產業篩選，市場狀態判斷
3. **推薦分析**：基於統一打分模型的股票推薦，提供推薦理由
4. **策略回測**：完整的策略回測實驗室，從策略開發到結果分析
5. **觀察清單**：跨 Tab 共用候選池管理

**當前狀態**：
- **Phase 1：市場觀察儀** ✅ 已完成
- **Phase 2：策略資料庫** ✅ 已完成
- **Phase 2.5：參數設計優化** ✅ 已完成
- **Phase 3.1：推薦可用化** 🚧 進行中
- **Phase 3.3b：回測穩健性驗證** 🚧 進行中
  - ✅ Epic 2 MVP-1：Walk-Forward 暖機期 + Baseline 對比（已完成，2025-12-30）
  - 🚧 Epic 2 MVP-2：過擬合風險提示（實作中，階段 1-2 已完成）

### 5.2 哪些是核心

#### ✅ 核心模組（必須保留）
1. **data_module/** - 數據處理核心
2. **analysis_module/** - 分析核心
3. **backtest_module/** - 回測核心
4. **app_module/** - 應用服務層核心
5. **ui_qt/** - 主要 UI（PySide6）
6. **scripts/** - 數據更新與維護腳本
7. **tests/** - 測試套件
8. **docs/** - 文檔系統

#### ✅ 核心功能（必須保留）
1. 數據更新流程
2. 市場觀察（強勢/弱勢個股與產業）
3. 推薦分析（統一打分模型）
4. 策略回測（完整回測實驗室）
5. 觀察清單（跨 Tab 共用）

### 5.3 哪些可能是實驗或歷史遺物

#### ⚠️ 實驗性文件（需要確認）
1. **根目錄的 .ipynb 文件** - 開發過程中的 Notebook
2. **根目錄的 .md 文件** - 開發過程中的說明文件
3. **demo_* 目錄** - 測試過程中的臨時目錄
4. **test_data/** - 測試數據目錄
5. **scripts/test_*.py** - 測試腳本（應移到 tests/）

#### ⚠️ 歷史遺物（可能可以移除）
1. **examples/main_example.py** - 已棄用的舊版主程式
2. **examples/system_config.py** - 已棄用的舊版配置
3. **recommendation_module/recommendation_engine.py** - 可能已被取代的舊版推薦引擎
4. **ui_app/** - 舊版 Tkinter UI（如果已完全遷移到 ui_qt）

#### ⚠️ 重複文件（需要整合）
1. **readme.txt** vs **README.md** - 可能內容重複
2. **technical_analysis/** 目錄（根目錄下）vs **analysis_module/technical_analysis/** - 命名重複

### 5.4 哪些地方目前「難以理解或維護」

#### ✅ 架構問題（已解決）
1. **業務邏輯位置混亂** ✅ 已解決
   - ✅ 已建立 `decision_module/` 作為核心領域層（Domain Layer）
   - ✅ 所有業務邏輯已從 `ui_app/` 遷移到 `decision_module/`
   - ✅ `app_module/` 服務層已改為依賴 `decision_module/`，不再依賴 `ui_app/`
   - ✅ UI 與業務邏輯已完全解耦

2. **UI 系統並存** ✅ 已解決
   - ✅ `ui_qt/` 為主要 UI 系統（PySide6）
   - ✅ `ui_app/` 已清理，僅保留 Tkinter UI 代碼（舊版，僅供參考）
   - ✅ 業務邏輯已完全分離，不再混雜在 UI 層

3. **推薦模組重複** ✅ 已解決
   - ✅ `recommendation_module/` 已重命名為 `recommendation_module_legacy/` 並添加棄用警告
   - ✅ 所有引用已更新，功能正常運作
   - ✅ 新專案應使用 `app_module/recommendation_service.py`

#### ✅ 文件組織問題（已解決）
1. **測試文件位置混亂** ✅ 已解決
   - ✅ 所有 `scripts/test_*.py` 已遷移到 `tests/scripts/`
   - ✅ 測試腳本統一管理，易於查找

2. **實驗性文件散落** ✅ 已解決
   - ✅ 所有 `.ipynb` 檔案已整理到 `notebooks/` 目錄
   - ✅ 相關 `.md` 檔案已整理到 `notebooks/` 或 `docs/experimental/`
   - ✅ 專案根目錄整潔，結構清晰

3. **Demo 目錄過多** ✅ 已處理
   - ✅ 已添加 `.gitignore` 規則處理 `demo_*/` 目錄
   - ✅ 專案結構清晰，不再混亂

#### ✅ 命名問題（已解決）
1. **目錄命名重複** ✅ 已解決
   - ✅ `technical_analysis/utils/` 已移動到 `utils/`（根目錄）
   - ✅ `technical_analysis/` 目錄已刪除（如果為空）
   - ✅ 命名不再重複，結構清晰

2. **配置文件重複** ⚠️ 仍存在（低優先級）
   - `examples/system_config.py`（已棄用）vs `data_module/config.py`
   - **狀態**：舊版配置已標註為棄用，不影響功能
   - **建議**：未來可考慮移除或移到 docs/ 作為參考

#### ✅ 清理計劃（已執行）
1. **結構化遷移計畫** ✅ 已完成
   - ✅ 所有 5 個遷移步驟已成功完成
   - ✅ 架構債務已解決，專案結構清晰
   - ✅ 詳細記錄見 `docs/REFACTORING_MIGRATION_PLAN.md`
   - **問題**：許多列出的文件仍存在
   - **影響**：專案結構未優化

### 5.5 建議的優先處理事項

#### 🔴 高優先級（影響維護性）
1. **業務邏輯遷移**：將 `ui_app/` 中的業務邏輯遷移到 `app_module/` 或新建 `decision_module/`
2. **測試文件整理**：將 `scripts/test_*.py` 移到 `tests/` 目錄
3. **推薦模組確認**：確認 `recommendation_module/` 是否仍在使用，如不使用則移除

#### 🟡 中優先級（影響可讀性）
1. **實驗性文件整理**：將根目錄的 .ipynb 和 .md 文件移到適當目錄
2. **Demo 目錄清理**：確認 demo_* 目錄是否可以清理
3. **命名重複解決**：解決 `technical_analysis/` 目錄命名重複問題

#### 🟢 低優先級（影響整潔度）
1. **已棄用文件移除**：移除 `examples/main_example.py` 和 `examples/system_config.py`（或移到 docs/）
2. **重複文件整合**：整合 `readme.txt` 和 `README.md`
3. **臨時文件清理**：清理根目錄的臨時文件（test.parquet, technical_calculation.log 等）

---

## 📝 附註

### 盤點方法
- 本報告基於實際程式碼與檔案結構分析
- 所有資訊皆來自專案實際內容
- 未進行任何程式碼變更

### 盤點範圍
- ✅ 已盤點：專案結構、核心進入點、功能模組、可疑區域
- ⚠️ 未深入：程式碼內部邏輯細節、性能分析、依賴關係圖

### 後續建議
1. **執行清理計劃**：參考 `CLEANUP_PLAN.md` 執行清理
2. **業務邏輯遷移**：優先處理業務邏輯位置混亂問題
3. **測試文件整理**：整理測試文件位置
4. **文檔更新**：根據本報告更新專案文檔

---

**報告結束**

