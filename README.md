# 台股技術分析系統

## 系統概述

**這不是一個「每天吐股票的工具」，而是一個「可驗證、可回溯、可演化」的投資決策系統。**

本系統是一個完整的台股技術分析平台，提供數據收集、處理、分析和回測功能。系統採用模組化設計，確保各個組件之間的獨立性和可維護性。

### 當前狀態：Phase 2.5 完成 → Phase 3.1 進行中 🚧

**Phase 1：市場觀察儀 ✅ 已完成**
- 數據更新流程（股票/大盤/產業）
- 強勢股/強勢產業（本日/本週）
- 市場 Regime 判斷（Trend/Reversion/Breakout）
- 統一打分模型（技術/量能/結構）
- 推薦理由生成（Why，不是 Buy/Sell）
- **應用服務層（app_module/）** ✅ 已完成
- **Qt UI（ui_qt/）** ✅ 已完成（數據更新、市場觀察、推薦分析、策略回測）

**Phase 2：策略資料庫 ✅ 已完成**

**目標**：讓策略成為「可被描述、被比較、被淘汰」的研究對象

**已完成項目**：
- ✅ **Phase2-A：跨 Tab 共用 Watchlist**
  - WatchlistService（JSON 持久化）
  - Market Watch → 加入候選池
  - Recommendation → 加入候選池
  - Backtest → 從候選池建立 stock list
  - UI 管理入口（觀察清單 Tab）
- ✅ **Phase2-B：Market Watch 弱勢分析**
  - 弱勢股視圖（與強勢股同架構，反向排名）
  - 弱勢產業視圖（與強勢產業同架構，反向排名）
- ✅ **Phase2-C：Recommendation DTO 統一**
  - RecommendationResultDTO（固定欄位）
  - RecommendationRepository（推薦結果可保存、可追溯）
  - UI 保存功能整合
- ✅ **Phase2-D：Backtest 研究體驗補強**
  - Grid Search 進度回調（顯示完成 x/y）
  - 最佳化結果雙擊套用參數
- ✅ **Phase2-E：預設策略庫（最小可用）**
  - StrategyMeta（適用/不適用 Regime、風險屬性）
  - 實作 2 個最小策略（暴衝/穩健）
  - 每策略一頁策略說明（Why，不是 How）
  - 單一策略回測可跑、可保存
- ✅ **策略回測實驗室**
  - 單檔/批次回測（支援選股清單）
  - 策略預設管理（儲存/載入/刪除）
  - 參數最佳化（Grid Search，含進度回調）
  - Walk-forward 驗證（Train-Test Split / Rolling）
    - ✅ Walk-Forward 暖機期（warmup_days 參數，預設 0，向後兼容）
    - ✅ Baseline 對比（Buy & Hold 策略對比）
    - 🚧 過擬合風險提示（實作中，階段 1-2 已完成）
  - 回測結果保存與載入（SQLite + Parquet/CSV）
  - 回測歷史管理（比較、刪除）
  - 圖表視覺化（權益曲線、回撤曲線、報酬分佈、持有天數）
  - 詳細功能請參考：[策略回測功能清單.md](策略回測功能清單.md)

**Phase 2 已完成，系統已具備完整的策略研究能力。**

**Phase 2.5：參數設計優化 ✅ 已完成並整合到 UI**
- ✅ 強勢/弱勢分數標準化（z-score 標準化）
- ✅ Pattern threshold/prominence ATR-based
- ✅ Scoring Contract 統一（所有子分數 0~100，Regime 用權重切換）
- ✅ 回測 execution_price 明確定義（next_open/close）- **已整合到 UI**
- ✅ 停損停利 ATR 倍數模式 - **已整合到 UI**
- ✅ 部位管理（max_positions、reentry cooldown）- **已整合到 UI**
- ✅ **功能驗證**：18/18 功能通過（100% 通過率）
- ✅ **UI 整合**：所有新參數已整合到回測配置界面

**下一步：Phase 3.1 推薦可用化（每天能快速產出可理解名單）**

**Phase 3 計劃（每階段可完整使用）：**
- **Phase 3.1：推薦可用化** 🚧 進行中
  - 目標：每天 1 分鐘內完成「選風格 → 出名單 → 看懂理由 → 丟到候選池」
  - 新手/進階模式切換、Why Not（反向解釋）、結果可保存
- **Phase 3.2：Profiles 正式化** ⏳ 待開始
  - 目標：落地「短線/中線/長線」為真正可用的 Profiles
- **Phase 3.3：研究閉環** 🚧 進行中
  - **Phase 3.3b：回測穩健性驗證** 🚧 進行中
    - ✅ Epic 2 MVP-1：Walk-Forward 暖機期 + Baseline 對比（已完成，2025-12-30）
    - 🚧 Epic 2 MVP-2：過擬合風險提示（實作中，階段 1-2 已完成）
    - ⏸️ Epic 3：視覺驗證（待開始）
    - ⏸️ Epic 1：Promote 機制（待開始）
  - 目標：形成「推薦 → 回測 → 優化 → Promote → 再推薦」閉環

**詳細演進地圖**：請參考 [docs/00_core/DEVELOPMENT_ROADMAP.md](docs/00_core/DEVELOPMENT_ROADMAP.md)

**詳細系統說明請參考 [readme.txt](readme.txt)，其中包含完整的系統功能說明、模組架構和使用方法。**

## 專案結構

```
technical_analysis/
├── 📁 核心模組
│   ├── data_module/           # 數據處理模組
│   ├── analysis_module/       # 分析模組
│   ├── backtest_module/       # 回測模組
│   ├── recommendation_module/ # 推薦模組
│   └── app_module/            # 應用服務層（UI 與業務邏輯解耦）
│
├── 📁 UI 應用
│   ├── ui_app/                # Tkinter UI（原有）
│   └── ui_qt/                 # PySide6 Qt UI（新增，推薦使用）
│
├── 📁 工具腳本 (scripts/)
│   ├── update_all_data.py           # 更新所有數據
│   ├── fix_market_index.py          # 修復市場指數
│   ├── fix_industry_index.py        # 修復產業指數
│   ├── merge_daily_data.py          # 合併每日數據
│   ├── calculate_technical_indicators.py # 計算技術指標
│   ├── date_specific_indicator_calc.py   # 特定日期指標計算
│   ├── simple_technical_calc.py          # 簡化技術指標計算
│   ├── update_stock_data.py              # 更新股票數據
│   └── market_date_range.py              # 市場日期範圍管理
│
├── 📁 測試檔案 (tests/)
│   ├── test_technical_calc.py        # 技術計算測試
│   ├── test_finmind_integration.py   # FinMind整合測試
│   ├── test_market_index.py          # 市場指數測試
│   └── [其他測試檔案...]             # 詳細請見 tests/ 目錄
│
├── 📁 文檔 (docs/)
│   ├── 00_core/                      # 核心文檔（必讀）
│   │   ├── DEVELOPMENT_ROADMAP.md    # 開發路線圖
│   │   ├── PROJECT_SNAPSHOT.md       # 專案快照
│   │   ├── DOCUMENTATION_INDEX.md    # 文檔索引
│   │   └── note.txt                  # 開發進度記錄
│   ├── 01_architecture/              # 架構文檔
│   ├── 02_features/                  # 功能文檔
│   ├── 03_data/                      # 數據相關文檔
│   ├── 07_guides/                    # 指南文檔
│   └── [其他目錄...]                 # 詳細請見 docs/README.md
│
├── 📁 數據存儲 (data/)
│   ├── meta_data/                    # 元數據
│   ├── daily_price/                  # 每日價格數據
│   ├── technical_analysis/           # 技術指標數據
│   ├── processed/                    # 處理後數據
│   └── raw/                          # 原始數據
│
├── 📁 輸出 (output/)
│   ├── results/                      # 分析結果
│   └── reports/                      # 報告文件
│
├── 📁 日誌 (logs/)                   # 系統日誌
│
├── 📄 核心檔案
│   ├── main.py                       # 主程序
│   ├── system_config.py              # 系統配置
│   ├── talib_compatibility.py        # TA-Lib兼容性模組
│   ├── requirements.txt              # Python依賴
│   └── README.md                     # 本文件
│
└── 📄 開發檔案
    ├── 01_stock_data_collector_enhanced.py # 增強版數據收集器
    ├── 02_technical_calculator.ipynb       # 技術指標計算Notebook
    ├── 01_stock_data_collector.ipynb       # 原始數據收集器Notebook
    ├── 01_stock_data_collector.md          # 數據收集器說明
    └── 02_technical_calculator.md          # 技術計算器說明
```

## 快速開始

### 環境設置
```bash
# A. 克隆代碼庫
git clone [repository_url]

# B. 安裝依賴
pip install -r requirements.txt
```

### 數據更新

#### 每日股票數據更新（推薦 ⭐）

```bash
# 批量更新從指定日期之後到今天的所有交易日（推薦）
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 更新單日數據
python scripts/update_daily_stock_data.py --date 2025-08-29

# 合併數據到 meta_data
python scripts/merge_daily_data.py
```

**詳細說明**：請參考 [docs/03_data/HOW_TO_UPDATE_DAILY_DATA.md](docs/03_data/HOW_TO_UPDATE_DAILY_DATA.md)

#### 全面數據更新

```bash
# 更新最近30天的數據（生產模式）
python scripts/update_all_data.py

# 更新指定日期範圍的數據
python scripts/update_all_data.py --start 2023-01-01 --end 2023-01-31

# 更新所有數據（從2014年起）
python scripts/update_all_data.py --all

# 測試模式 - 使用隔離路徑
python scripts/update_all_data.py --profile test --data-root ./test_data --output-root ./test_output --dry-run

# 環境變量覆蓋模式
export DATA_ROOT=./sandbox_data
export OUTPUT_ROOT=./sandbox_output
export PROFILE=test
python scripts/update_all_data.py --dry-run
```

### 技術指標計算
```bash
# 計算所有股票的技術指標
python scripts/calculate_technical_indicators.py

# 簡化版技術指標計算
python scripts/simple_technical_calc.py

# 特定日期指標計算
python scripts/date_specific_indicator_calc.py
```

### 數據修復
```bash
# 修復市場指數數據
python scripts/fix_market_index.py

# 修復產業指數數據
python scripts/fix_industry_index.py

# 合併每日數據
python scripts/merge_daily_data.py
```

## 文檔導航

### 📖 快速開始
1. **[docs/07_guides/QUICK_START.md](docs/07_guides/QUICK_START.md)** - 快速開始指南
2. **[docs/07_guides/QUICK_REFERENCE.md](docs/07_guides/QUICK_REFERENCE.md)** - 常用命令快速參考
3. **[docs/07_guides/INSTALL_GUIDE.md](docs/07_guides/INSTALL_GUIDE.md)** - 安裝指南

### 📖 核心文檔
4. **[PROJECT_NAVIGATION.md](PROJECT_NAVIGATION.md)** - 專案導航文件（⭐ 快速查找必讀）
5. **[PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)** - 專案盤點報告（完整的專案結構盤點）
6. **[docs/00_core/DOCUMENTATION_INDEX.md](docs/00_core/DOCUMENTATION_INDEX.md)** - 完整文檔索引（⭐ 推薦先看）
7. **[docs/00_core/DEVELOPMENT_ROADMAP.md](docs/00_core/DEVELOPMENT_ROADMAP.md)** - 開發演進地圖（⭐ 最重要）
8. **[docs/00_core/PROJECT_SNAPSHOT.md](docs/00_core/PROJECT_SNAPSHOT.md)** - 專案快照（開場 30 秒必讀）
9. **[docs/01_architecture/system_architecture.md](docs/01_architecture/system_architecture.md)** - 系統架構詳細說明
10. **[readme.txt](readme.txt)** - 完整的系統功能說明、模組架構和使用方法

### 🎯 UI 功能與使用指南
9. **[docs/02_features/UI_FEATURES_DOCUMENTATION.md](docs/02_features/UI_FEATURES_DOCUMENTATION.md)** - UI 功能完整文檔（⭐ 推薦）
   - 每個 Tab 的詳細功能說明
   - 技術指標參數設定
   - 圖形模式參數設定
   - 策略回測完整功能
10. **[docs/02_features/USER_GUIDE.md](docs/02_features/USER_GUIDE.md)** - 使用者指南（⭐ 推薦）
    - 推薦分析 - 產業篩選使用說明
    - 策略回測 - 參數最佳化完整教程
    - 策略回測 - Walk-forward 驗證詳細說明
    - 常見問題解答

### 🏗️ 架構改進計劃
11. **[docs/08_technical/PARAMETER_DESIGN_IMPROVEMENTS.md](docs/08_technical/PARAMETER_DESIGN_IMPROVEMENTS.md)** - 參數設計改進計劃（⭐ 重要）
    - 參數單位一致性問題分析
    - 強勢/弱勢分數公式改進
    - 圖形模式參數 ATR-based 改進
    - Scoring Contract 統一規範
    - 回測參數改進計劃
    - 實施優先級與時間表

### 🔧 使用指南
11. **[docs/03_data/HOW_TO_UPDATE_DAILY_DATA.md](docs/03_data/HOW_TO_UPDATE_DAILY_DATA.md)** - 每日數據更新指南
12. **[docs/03_data/daily_data_update_guide.md](docs/03_data/daily_data_update_guide.md)** - 數據更新詳細指南
13. **[docs/07_guides/scripts_readme.md](docs/07_guides/scripts_readme.md)** - 腳本使用說明
14. **[docs/07_guides/EXECUTION_GUIDE.md](docs/07_guides/EXECUTION_GUIDE.md)** - 執行指南

### 🏗️ 架構文檔
15. **[docs/01_architecture/data_collection_architecture.md](docs/01_architecture/data_collection_architecture.md)** - 數據收集架構
16. **[docs/03_data/DATA_FETCHING_LOGIC.md](docs/03_data/DATA_FETCHING_LOGIC.md)** - 數據獲取邏輯
17. **[docs/08_technical/technical_analysis_optimizations.md](docs/08_technical/technical_analysis_optimizations.md)** - 技術分析優化

### 📊 數據文檔
18. **[docs/03_data/INDUSTRY_INDEX_UPDATE_SUMMARY.md](docs/03_data/INDUSTRY_INDEX_UPDATE_SUMMARY.md)** - 產業指數更新說明
19. **[docs/03_data/MERGE_AND_MARKET_INDEX_SUMMARY.md](docs/03_data/MERGE_AND_MARKET_INDEX_SUMMARY.md)** - 市場指數更新說明

### 🧪 測試文檔
20. **[docs/09_archive/readme_test.txt](docs/09_archive/readme_test.txt)** - 完整測試指南（歷史文檔）
21. **[docs/07_guides/tests_readme.md](docs/07_guides/tests_readme.md)** - tests/ 目錄結構說明

### 📚 開發文檔
22. **[docs/05_phases/PHASE2_STRATEGY_LIBRARY.md](docs/05_phases/PHASE2_STRATEGY_LIBRARY.md)** - Phase 2 策略資料庫設計
23. **[docs/00_core/note.txt](docs/00_core/note.txt)** - 開發進度記錄
24. **[01_stock_data_collector.md](01_stock_data_collector.md)** - 數據收集器開發說明
25. **[02_technical_calculator.md](02_technical_calculator.md)** - 技術計算器開發說明

### 📊 回測文檔
26. **[策略回測功能清單.md](策略回測功能清單.md)** - 策略回測實驗室完整功能清單（⭐ 推薦）
27. **[策略回測常見問題解答.md](策略回測常見問題解答.md)** - 回測功能常見問題與解答
28. **[docs/02_features/BACKTEST_LAB_COMPLETE.md](docs/02_features/BACKTEST_LAB_COMPLETE.md)** - 策略回測實驗室完整功能總結

## 目錄詳細說明

### 📁 scripts/ - 工具腳本目錄
包含所有實用的工具腳本，用於數據更新、修復和計算。詳細說明請見 [docs/07_guides/scripts_readme.md](docs/07_guides/scripts_readme.md)。

### 📁 tests/ - 測試檔案目錄
包含所有測試檔案，用於驗證系統功能。
- **目錄結構說明**：請見 [docs/07_guides/tests_readme.md](docs/07_guides/tests_readme.md)
- **完整測試指南**：請見 [docs/09_archive/readme_test.txt](docs/09_archive/readme_test.txt)（歷史文檔，包含環境設置、執行方法、報告生成等）

### 📁 docs/ - 文檔目錄
包含所有系統文檔，包括架構說明、開發記錄等。

### 📁 data/ - 數據存儲目錄
系統的數據存儲位置，包含原始數據、處理後數據和技術指標數據。

## 數據存儲路徑說明

### 預設路徑（生產模式）
系統默認使用以下路徑存儲數據和計算結果：

1. **原始數據目錄**: `D:/Min/Python/Project/FA_Data/meta_data/`
   - 股票數據: `stock_data_whole.csv`
   - 所有股票整合數據: `all_stocks_data.csv`

2. **技術指標計算結果目錄**: `D:/Min/Python/Project/FA_Data/technical_analysis/`
   - 個股技術指標文件: `{股票代號}_indicators.csv`

3. **備份目錄**: `D:/Min/Python/Project/FA_Data/meta_data/backup/`
   - 備份文件格式: `all_stocks_data_{YYYYMMDD}.csv`

### 路徑隔離功能（測試模式）

系統支援靈活的路徑覆蓋，確保測試環境不會影響生產數據：

#### 1. 環境變量覆蓋
```bash
# 設置測試環境
export DATA_ROOT=./test_data
export OUTPUT_ROOT=./test_output
export PROFILE=test

# 運行腳本（自動使用隔離路徑）
python scripts/update_all_data.py --dry-run
```

#### 2. 命令行參數覆蓋
```bash
# 直接指定測試路徑
python scripts/update_all_data.py --profile test --data-root ./sandbox_data --output-root ./sandbox_output --dry-run
```

#### 3. 配置檔案模式
- `--profile prod`: 使用預設D槽路徑（生產模式）
- `--profile test`: 自動添加 `_test` 後綴到路徑
- `--profile staging`: 使用指定的staging路徑

#### 4. 乾運行模式
```bash
# 測試腳本邏輯而不實際寫入檔案
python scripts/update_all_data.py --dry-run
```

### 路徑配置詳情
若需修改這些路徑，請參考 `data_module/config.py` 中的 `TWStockConfig` 類，或使用上述的環境變量/命令行參數。

## UI 應用程式

### Tkinter UI（原有）
```bash
python ui_app/main.py
```
- 完整的市場觀察和推薦分析功能
- 策略配置界面
- 數據更新功能

### Qt UI（新增，推薦使用）⭐
```bash
python ui_qt/main.py
```
- 現代化的 PySide6 界面
- 標籤頁設計：數據更新、市場觀察、推薦分析、**策略回測**、**觀察清單**
- 市場觀察分為五個子標籤：大盤指數、強勢個股、弱勢個股、強勢產業、弱勢產業（大盤指數在最前面，方便先查看整體市場狀況）
- **觀察清單功能**：
  - 跨 Tab 共用候選池（Market Watch、Recommendation、Backtest）
  - 股票來源追蹤（market_watch、recommendation、manual）
  - 備註與標籤管理
- **數據更新功能**：
  - 查找範圍設置：用於檢查指定天數內缺失的日期
  - 普通合併：增量合併新數據
  - 強制重新合併：完全重建所有數據
- **性能優化**：
  - 市場觀察數據緩存：切換「本日/本周」時使用緩存，避免重複計算
  - 點擊「刷新」按鈕時強制重新計算
- **策略回測實驗室** ✅：
  - 單檔/批次回測（支援選股清單）
  - 策略預設管理（儲存/載入/刪除）
  - 參數最佳化（Grid Search）
  - Walk-forward 驗證（Train-Test Split / Rolling）
    - ✅ Walk-Forward 暖機期（warmup_days 參數）
    - ✅ Baseline 對比（Buy & Hold）
    - 🚧 過擬合風險提示（實作中）
  - 回測結果保存與載入（SQLite + Parquet/CSV）
  - 回測歷史管理（比較、刪除）
  - 圖表視覺化（4 種圖表：權益曲線、回撤曲線、報酬分佈、持有天數）
  - 詳細功能請參考：[策略回測功能清單.md](策略回測功能清單.md)
- 推薦理由顯示更清晰

## 版本歷史

- v1.7.3 (2025-12-30)
  - ✅ Phase 3.3b Epic 2 MVP-1：回測穩健性驗證功能
    - ✅ Walk-Forward 暖機期（warmup_days 參數，預設 0，向後兼容）
    - ✅ Baseline 對比（Buy & Hold 策略對比，包含超額報酬率、相對 Sharpe 比率等指標）
    - ✅ 驗證狀態：29/29 測試案例通過（100% 通過率）
    - ✅ 驗證報告：`output/qa/epic2_mvp1_validation/VALIDATION_REPORT.md`
  - 🚧 Phase 3.3b Epic 2 MVP-2：過擬合風險提示（實作中）
    - ✅ 階段 1：核心計算方法實作（已完成）
      - `calculate_walkforward_degradation()` 方法
      - `calculate_consistency()` 方法
      - `calculate_overfitting_risk()` 整合方法
    - ✅ 階段 2：DTO 與服務整合（已完成）
      - `BacktestReportDTO` 新增 `overfitting_risk` 欄位
      - `BacktestService.run_backtest()` 整合過擬合風險計算
    - ⏸️ 階段 3：測試與驗證（待實作）

- v1.7.2 (2025-12-22)
  - ✅ 策略回測功能優化：
    - ✅ 日期範圍自動調整：當選擇的日期範圍超過實際數據時，自動調整為可用範圍並顯示提示
    - ✅ 參數最佳化性能優化：預載入數據、多線程並行執行（提升 6-8 倍速度）
    - ✅ 技術指標數據載入修復：修復 YYYYMMDD 格式日期解析問題
    - ✅ 技術指標計算腳本修復：修復增量更新時覆蓋舊數據的問題
  - ✅ 市場觀察標籤順序調整：大盤指數移至最前面，方便先查看整體市場狀況
  - ✅ Roadmap 重構：Phase 3 拆分為 3.1/3.2/3.3，Phase 4 拆分為 4.1/4.2，強調「每階段可完整使用」
  - ✅ 市場狀態顯示區塊 UI 重新設計：
    - ✅ 三層資訊架構：市場結論層（唯一視覺錨點）、判斷摘要層（並排顯示）、技術細節層（可折疊）
    - ✅ 深色主題可讀性優化：統一深色背景、淺色文字、顏色語意分離
    - ✅ 視覺錨點鎖定：市場狀態名稱成為唯一主角，其他資訊視覺降級
    - ✅ 留白優化：縮小上方留白，標題不貼邊但整體緊湊
    - ✅ 技術細節優化：checkbox 深綠底（已展開）、標題動態顯示狀態、並排顯示多個分類區塊

- v1.7.1 (2025-12-20)
  - ✅ 數據合併功能修復：改進日期格式處理，確保所有數據正確合併（2014-04-07 到 2025-12-19）
  - ✅ PandasTableModel 錯誤修復：修復列表/數組類型處理的布爾判斷錯誤
  - ✅ 觀察清單管理器功能增強：整合選股清單管理（保存、載入、CRUD）
  - ✅ 觀察清單管理器布局重新設計：上下分割（主要工作區 70%，管理操作區 30%）
  - ✅ 修復 datetime 導入錯誤（UnboundLocalError）

- v1.7.0 (2025-12-XX)
  - ✅ Phase2-A：跨 Tab 共用 Watchlist 功能實現
  - ✅ WatchlistService（JSON 持久化）
  - ✅ Market Watch 整合：強勢股可加入觀察清單
  - ✅ Recommendation 整合：推薦結果可加入觀察清單
  - ✅ Backtest 整合：可從觀察清單載入股票進行回測
  - ✅ 觀察清單獨立 Tab（管理、新增、移除、清空）

- v1.6.0 (2025-12-16)
  - ✅ 策略回測實驗室完整功能實現
  - ✅ 回測歷史刪除功能（支援單選和多選）
  - ✅ 圖表顯示問題修復（回撤曲線、報酬分佈、持有天數）
  - ✅ 保存結果按鈕啟用邏輯修復
  - ✅ Matplotlib 中文字體配置修復
  - ✅ Parquet 依賴問題修復（自動降級到 CSV）
  - 詳細功能請參考：[策略回測功能清單.md](策略回測功能清單.md)

- v1.5.1 (2025-12-15)
  - ✅ 數據更新邏輯優化：移除「開始日期」，改為「查找範圍（天）」，用於檢查缺失日期
  - ✅ 新增「強制重新合併」功能：支持完全重建數據
  - ✅ 市場觀察性能優化：實現緩存機制，切換「本日/本周」時使用緩存，避免重複計算
  - ✅ 強勢股篩選邏輯修正：修正 off-by-one 錯誤、成交量計算、20日新高容忍度
  - ✅ IndustryMapper 共享實例優化：避免重複載入數據
  - ✅ 日期解析改進：支持多種日期格式，改進錯誤處理

- v1.5.0 (2025-12-15)
  - ✅ 新增應用服務層（app_module/），實現 UI 與業務邏輯解耦
  - ✅ 新增 Qt UI（ui_qt/），使用 PySide6 構建現代化界面
  - ✅ 數據更新功能：數據狀態檢查、合併功能
  - ✅ 市場觀察：強勢個股、大盤指數、強勢產業分離顯示
  - ✅ 推薦分析：策略配置和結果顯示
  - 為未來支持多種 UI（Web、CLI）打下基礎

- v1.3.0 (2024-10-16)
  - 新增路徑隔離功能，支援測試環境與生產環境分離
  - 新增環境變量覆蓋和命令行參數覆蓋功能
  - 新增乾運行模式，支援測試腳本邏輯而不實際寫入檔案
  - 新增原子寫入功能，確保檔案寫入的安全性
  - 新增端到端測試，驗證路徑隔離功能
  - 保持向後兼容性，預設仍使用D槽路徑

- v1.2.1 (2024-04-08)
  - 整理專案結構，移動測試檔案到 tests/ 目錄
  - 重命名和清理重複檔案
  - 更新文檔結構和說明

- v1.2.0 (2024-04-02)
  - 重構數據加載模塊，提高穩定性和可靠性
  - 優化更新流程，支援增量更新和批量更新
  - 添加技術分析模塊優化

- v1.1.0 (2024-03-23)
  - 改進API請求機制
  - 優化錯誤處理
  - 完善數據驗證

- v1.0.0 (2024-03-20)
  - 完善數據備份機制
  - 添加增量更新功能
  - 改進數據驗證邏輯
  - 優化錯誤處理和日誌記錄