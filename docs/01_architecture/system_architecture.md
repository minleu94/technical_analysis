# 台股技術分析系統架構文檔

## 系統概述

**系統定位**：這不是一個「每天吐股票的工具」，而是一個「會隨著你交易理解一起成長的投資決策系統」。

本系統是一個完整的台股技術分析平台，提供數據收集、處理、分析和回測功能。系統採用模組化設計，確保各個組件之間的獨立性和可維護性。

### 當前狀態：Phase 2.5 完成 ✅ → Phase 3 準備

**Phase 1：市場觀察儀 ✅ 已完成**
- 強勢股/產業識別 + 推薦理由
- 市場 Regime 判斷（Trend/Reversion/Breakout）
- 統一打分模型（0-100分制）
- Regime 自動策略切換
- 產業映射系統

**Phase 2：策略資料庫 ✅ 已完成**
- 策略配置界面（已完成）
- 預設策略庫（已完成）
- 策略說明文檔（已完成）
- 單一策略回測（已完成）
- 批次回測、參數最佳化、Walk-forward（已完成）

**Phase 2.5：參數設計優化 ✅ 已完成並驗證通過**
- 強勢/弱勢分數標準化（z-score、log 壓縮）
- Pattern ATR-based 參數（threshold_atr_mult、prominence_atr_mult）
- Scoring Contract 統一（0-100 分制、Regime 權重切換）
- 回測參數改進（execution_price、ATR 停損停利、部位管理）
- **功能驗證**：18/18 功能通過（100% 通過率）

**詳細演進地圖**：請參考 [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)

## 系統架構
```
technical_analysis/
├── data_module/          # 數據處理模組
│   ├── data_loader.py    # 數據加載器（已完成）
│   ├── data_processor.py # 數據處理器（已完成）
│   ├── data_validator.py # 數據驗證器（新增）
│   └── config.py         # 配置管理（已完成）
├── analysis_module/      # 分析模組（已完成）
│   ├── technical_indicators.py  # 技術指標計算
│   ├── market_analysis.py       # 市場分析
│   ├── pattern_analysis/        # 形態分析
│   │   ├── pattern_analyzer.py  # 形態識別器
│   │   ├── pattern_predictor.py # 形態預測器
│   │   └── pattern_visualizer.py # 形態可視化（新增）
│   ├── signal_analysis/         # 信號分析
│   │   └── signal_combiner.py  # 信號組合器
│   └── ml_analysis/            # 機器學習分析 ⚠️ 暫停開發
│       ├── ml_analyzer.py      # ML分析器（未來持續開發）
│       ├── feature_engineering.py # 特徵工程（未來持續開發）
│       └── model_manager.py    # 模型管理器（未來持續開發）
├── backtest_module/      # 回測模組（已完成）
│   ├── strategy_tester.py      # 策略測試器
│   └── performance_analyzer.py # 績效分析器
├── recommendation_module/# 推薦模組（優化中）
│   └── recommendation_engine.py # 推薦引擎
├── app_module/         # 應用服務層（✅ 已完成）
│   ├── __init__.py              # 模組導出
│   ├── dtos.py                  # 數據傳輸對象（RecommendationDTO, RegimeResultDTO, BacktestReportDTO）
│   ├── recommendation_service.py # 推薦服務（✅ 已完成）
│   ├── screening_service.py     # 強勢股/產業篩選服務（✅ 已完成）
│   ├── regime_service.py        # 市場狀態檢測服務（✅ 已完成）
│   ├── update_service.py        # 數據更新服務（✅ 已完成）
│   ├── backtest_service.py      # 回測服務（✅ 已完成）
│   ├── optimizer_service.py     # 參數最佳化服務（✅ 已完成）
│   ├── broker_branch_update_service.py # 券商分點資料更新服務（✅ 已完成）
│   └── README.md                # 架構說明文檔
├── ui_app/              # Tkinter UI 應用程式模組（✅ 已完成）
│   ├── main.py                  # 主應用程式（深色主題，三列布局）
│   ├── stock_screener.py        # 強勢股/產業篩選器
│   ├── strategy_configurator.py # 策略配置器
│   ├── scoring_engine.py        # 統一打分引擎（0-100分制）
│   ├── reason_engine.py         # 推薦理由生成引擎
│   ├── market_regime_detector.py # 市場狀態檢測器（Trend/Reversion/Breakout）
│   ├── industry_mapper.py       # 產業映射系統
│   ├── strategies.py            # 策略定義模組
│   └── README.md                # UI 模組說明文檔
├── ui_qt/               # Qt UI 應用程式模組（✅ 已完成，推薦使用）
│   ├── main.py                  # 主應用程式（PySide6）
│   ├── models/                  # 數據模型
│   │   └── pandas_table_model.py # Pandas DataFrame 表格模型
│   ├── views/                   # 視圖組件
│   │   ├── update_view.py       # 數據更新視圖
│   │   ├── strong_stocks_view.py # 強勢個股視圖
│   │   ├── market_regime_view.py # 大盤指數視圖
│   │   ├── strong_industries_view.py # 強勢產業視圖
│   │   ├── recommendation_view.py # 推薦分析視圖
│   │   └── backtest_view.py    # 策略回測視圖（✅ 已完成）
│   │       - 單一策略回測
│   │       - 參數最佳化（Grid Search）
│   │       - Walk-forward 驗證
│   │       - 日期範圍自動調整提示
│   │       - 參數範圍設定（固定值/範圍模式）
│   └── workers/                 # 後台工作線程
│       └── task_worker.py       # 任務工作器（非阻塞執行）
├── scripts/             # 獨立腳本
│   ├── batch_update_daily_data.py # 批量更新每日數據（已完成）
│   ├── batch_update_market_and_industry_index.py # 批量更新市場/產業指數（已完成）
│   ├── calculate_technical_indicators.py # 計算技術指標（已完成）
│   ├── merge_daily_data.py     # 數據合併腳本（已完成）
│   ├── update_daily_stock_data.py # 單日數據更新（已完成）
│   └── analyze_companies_industry.py # 產業分析腳本（已完成）
├── technical_analysis/ # 技術分析工具
│   └── utils/
│       └── io_utils.py         # 原子寫入工具（新增）
├── tests/              # 測試文件（已完成）
│   ├── test_data_processing/   # 數據處理測試
│   ├── test_pattern_analysis/  # 形態分析測試
│   ├── test_backtest/         # 回測測試
│   ├── test_ml_analysis/      # 機器學習測試（新增）
│   ├── test_recommendation/   # 推薦系統測試
│   └── e2e/                   # 端到端測試（新增）
│       └── test_data_path_isolation.py # 路徑隔離測試（新增）
├── docs/              # 文檔
│   ├── 00_core/              # 核心文檔
│   │   ├── DEVELOPMENT_ROADMAP.md  # 開發路線圖
│   │   ├── PROJECT_SNAPSHOT.md   # 專案快照（開場 30 秒必讀）
│   │   └── DOCUMENTATION_INDEX.md # 文檔索引
│   ├── 01_architecture/     # 架構文檔
│   │   └── system_architecture.md  # 系統架構文檔（本文件）
│   └── ...                    # 其他文檔
└── data/              # 數據存儲（實際路徑：D:/Min/Python/Project/FA_Data/）
    ├── meta_data/      # 元數據
    │   ├── market_index.csv
    │   ├── industry_index.csv
    │   ├── companies.csv       # 公司產業映射
    │   ├── stock_data_whole.csv
    │   └── backup/     # 數據備份
    ├── daily_price/    # 每日價格數據（YYYYMMDD.csv格式）
    ├── technical_analysis/ # 技術指標數據
    │   ├── {股票代號}_indicators.csv  # 個股技術指標
    │   └── ...        # 市場/產業技術指標
    └── logs/          # 日誌文件
        ├── data_loader.log # 數據加載器日誌
        ├── update_all_data.log # 更新腳本日誌
        └── ...        # 其他日誌
```

## 數據存儲說明

### 1. 數據目錄結構
- **主數據目錄**: `D:/Min/Python/Project/FA_Data/`
  * `meta_data/`: 元數據存儲
    - `market_index.csv`: 市場指數數據
    - `industry_index.csv`: 產業指數數據
    - `stock_data_whole.csv`: 完整股票數據
    - `all_stocks_data.csv`: 所有股票數據
    - `broker_branch_registry.csv`: 券商分點註冊表（✅ 新增）
    - `backup/`: 數據備份目錄
  * `daily_price/`: 每日價格數據
  * `technical_analysis/`: 技術指標數據
    - `market/`: 市場指數技術指標
    - `industry/`: 產業指數技術指標
    - `stocks/`: 個股技術指標
  * `broker_flow/`: 券商分點資料（✅ 新增）
    - `{branch_system_key}/`: 每個分點獨立目錄
      - `daily/{YYYY-MM-DD}.csv`: 每日原始資料
      - `meta/merged.csv`: 合併後的歷史資料
  * `ml_models/`: 機器學習模型 ⚠️ 暫停開發（未來持續進行）
    - `prediction/`: 預測模型（未來功能）
    - `classification/`: 分類模型（未來功能）
    - `clustering/`: 聚類模型（未來功能）
    - `anomaly/`: 異常檢測模型（未來功能）
  * `logs/`: 日誌文件
    - `data_loader.log`: 數據加載器日誌
    - `update_all_data.log`: 更新腳本日誌
    - `data_checker.log`: 數據檢查日誌
    - `data_repair.log`: 數據修復日誌
    - `error_notification.log`: 錯誤通知日誌

### 2. 數據存儲路徑配置

#### 2.1 預設路徑（生產模式）
- 默認路徑: `D:/Min/Python/Project/FA_Data/`
- 輸出路徑: `D:/Min/Python/Project/FA_Data/output/`

#### 2.2 路徑隔離功能（測試模式）
系統支援靈活的路徑覆蓋，確保測試環境不會影響生產數據：

**環境變量覆蓋**:
```bash
export DATA_ROOT=./test_data
export OUTPUT_ROOT=./test_output
export PROFILE=test
```

**命令行參數覆蓋**:
```bash
python scripts/update_all_data.py --profile test --data-root ./sandbox_data --output-root ./sandbox_output --dry-run
```

**配置檔案模式**:
- `--profile prod`: 使用預設D槽路徑（生產模式）
- `--profile test`: 自動添加 `_test` 後綴到路徑
- `--profile staging`: 使用指定的staging路徑

#### 2.3 傳統配置方式（向後兼容）
- 通過 `TWStockConfig` 類配置：
```python
from data_module.config import TWStockConfig
config = TWStockConfig()
config.base_dir = Path("your/custom/path")
```
- 可通過環境變量 `TWSTOCK_DATA_DIR` 修改：
```bash
set TWSTOCK_DATA_DIR=your/custom/path
```

### 3. 數據備份策略
- 自動備份: 每日數據更新後
- 手動備份: 重要操作前
- 備份位置: `D:/Min/Python/Project/FA_Data/meta_data/backup/`
- 備份命名格式: `original_filename_YYYYMMDD_HHMMSS.csv`
- 備份保留策略: 保留最近30天的備份
- 備份完整性檢查: 每次備份後自動驗證

### 4. 數據訪問權限
- 讀取權限: 所有模組
- 寫入權限: 僅數據處理模組
- 備份權限: 僅數據處理模組
- 日誌權限: 所有模組可讀，僅系統可寫
- 模型權限: 僅機器學習模組可寫

## 模組說明

### 1. 數據處理模組 (data_module)
#### 1.1 數據加載器 (data_loader.py)
- 功能：負責從各種數據源加載數據
- 主要類：
  * `DataLoader`: 數據加載核心類
  * `MarketDateRange`: 市場日期範圍管理類
- 主要方法：
  * `load_market_index()`: 加載市場指數數據
  * `load_industry_index()`: 加載產業指數數據
  * `load_daily_price()`: 加載每日價格數據
  * `update_market_index()`: 更新市場指數數據
  * `update_industry_index()`: 更新產業指數數據
  * `update_daily_data()`: 更新每日數據
  * `_make_request()`: 發送API請求並處理重試邏輯
  * `_convert_roc_date()`: 轉換民國日期
  * `get_latest_date()`: 獲取最新數據日期
  * `validate_data_quality()`: 驗證數據質量（新增）
  * `handle_data_gaps()`: 處理數據缺口（新增）

#### 1.2 數據處理器 (data_processor.py)
- 功能：處理和轉換原始數據
- 主要類：
  * `DataProcessor`: 數據處理核心類
- 主要方法：
  * `process_market_index()`: 處理市場指數數據
  * `process_industry_index()`: 處理產業指數數據
  * `process_daily_price()`: 處理每日價格數據
  * `validate_data()`: 數據驗證
  * `clean_data()`: 數據清洗
  * `transform_data()`: 數據轉換
  * `handle_outliers()`: 處理異常值（新增）
  * `normalize_data()`: 數據標準化（新增）
  * `create_features()`: 創建特徵（新增）

#### 1.3 數據驗證器 (data_validator.py)（新增）
- 功能：驗證數據完整性和質量
- 主要類：
  * `DataValidator`: 數據驗證核心類
- 主要方法：
  * `validate_completeness()`: 驗證數據完整性
  * `validate_consistency()`: 驗證數據一致性
  * `validate_quality()`: 驗證數據質量
  * `generate_validation_report()`: 生成驗證報告

#### 1.4 配置管理 (config.py)
- 功能：管理系統配置，支援路徑隔離和環境覆蓋
- 主要類：
  * `TWStockConfig`: 台股配置管理類
- 主要配置：
  * API端點配置
  * 文件路徑配置（支援環境變量和命令行覆蓋）
  * 系統參數配置
  * 日誌配置
  * 數據目錄結構
  * 備份管理
  * 路徑隔離配置（新增）
  * 原子寫入配置（新增）
  * 乾運行模式配置（新增）
  * 性能監控配置（新增）
  * 安全配置（新增）
- 新增功能：
  * 環境變量覆蓋：`DATA_ROOT`、`OUTPUT_ROOT`、`PROFILE`
  * 命令行參數覆蓋：`--data-root`、`--output-root`、`--profile`、`--dry-run`
  * 配置檔案模式：`prod`、`test`、`staging`
  * 路徑解析輔助：`resolve_path()`、`resolve_output_path()`
  * 原子寫入支援：確保檔案寫入安全性

### 2. 分析模組 (analysis_module)
#### 2.1 技術指標計算 (technical_indicators.py)
- 功能：計算各種技術指標
- 主要指標：
  * 移動平均線 (MA)
  * 相對強弱指標 (RSI)
  * 布林通道 (Bollinger Bands)
  * MACD指標
  * KDJ指標
  * 成交量指標
  * 動量指標
  * 自定義指標（新增）
  * 組合指標（新增）

#### 2.2 市場分析 (market_analysis.py)
- 功能：進行市場趨勢分析
- 主要分析：
  * 趨勢分析
  * 支撐阻力位分析
  * 成交量分析
  * 波動性分析
  * 市場情緒分析
  * 板塊輪動分析
  * 市場寬度分析（新增）
  * 資金流向分析（新增）
  * 市場結構分析（新增）

#### 2.3 形態分析 (pattern_analysis/)
- 功能：識別和預測圖形模式
- 主要類：
  * `PatternAnalyzer`: 形態識別器
  * `PatternPredictor`: 形態預測器
  * `PatternVisualizer`: 形態可視化器（新增）
- 支持的形態：
  * 基本形態：W底、頭肩頂、頭肩底
  * 進階形態：V形反轉、圓頂/圓底、矩形、楔形
  * 組合形態：多形態組合分析
  * 新形態：杯柄形態、旗形、三角形（新增）
- 主要功能：
  * 形態識別
  * 形態預測
  * 準確率評估
  * 視覺化分析
  * 形態組合分析（新增）
  * 形態可靠性評估（新增）

#### 2.4 機器學習分析 (ml_analysis/) ⚠️ **暫停開發**
- **狀態**：目前暫停開發，未來持續進行
- **原因**：根據開發路線圖，當前階段（Phase 1-2）專注於規則基礎系統和策略資料庫建設，ML 功能將在後續階段（Phase 3-4）引入
- 功能：基於機器學習的市場分析（未來功能）
- 主要類：
  * `MLAnalyzer`: ML分析器（未來持續開發）
  * `FeatureEngineering`: 特徵工程（未來持續開發）
  * `ModelManager`: 模型管理器（未來持續開發）
- 主要功能（未來規劃）：
  * 特徵提取
  * 模型訓練
  * 預測分析
  * 模型評估
  * 模型版本控制
  * 自動化模型選擇
  * 模型性能監控
  * 預測結果可視化

### 3. 回測模組 (backtest_module)
- 功能：進行策略回測
- 主要類：
  * `StrategyTester`: 策略測試器
  * `PerformanceAnalyzer`: 績效分析器
  * `BrokerSimulator`: 交易模擬器（✅ 已完成）
    - 支援多種執行價格模式（next_open、close）
    - 支援 ATR-based 停損停利
    - 支援部位管理（max_positions、position_sizing、allow_pyramid、allow_reentry）
  * `RiskManager`: 風險管理器（新增）
- 主要功能：
  * 策略回測（✅ 已完成）
  * 績效評估（✅ 已完成）
  * 風險分析（✅ 已完成）
  * 資金管理（✅ 已完成）
  * 交易模擬（✅ 已完成）
  * 報告生成（✅ 已完成）
  * 參數優化（✅ 已完成，Grid Search + 多線程）
  * 日期範圍自動調整（✅ 已完成）
  * 數據預載入優化（✅ 已完成）
  * 多策略組合（新增）
  * 風險控制（新增）

### 4. 推薦模組 (recommendation_module)
- 功能：生成交易建議
- 主要類：
  * `RecommendationEngine`: 推薦引擎
- 主要功能：
  * 交易信號生成
  * 信號可靠性評估
  * 綜合分析報告

### 5. 應用服務層 (app_module/) ✅ **已完成**
- **功能**：提供統一的業務邏輯接口，供各種 UI（Tkinter/Qt/Web/CLI）調用
- **設計原則**：採用方案 A（最小重工），不搬動檔案，service 層內部 import `ui_app` 模組
- **主要類**：
  * `RecommendationService`: 推薦服務（✅ 已完成）
  * `ScreeningService`: 強勢股/產業篩選服務（✅ 已完成）
  * `RegimeService`: 市場狀態檢測服務（✅ 已完成）
  * `UpdateService`: 數據更新服務（✅ 骨架完成）
  * `BacktestService`: 回測服務（✅ 骨架完成）
- **數據傳輸對象 (DTOs)**：
  * `RecommendationDTO`: 股票推薦結果
  * `RegimeResultDTO`: 市場狀態檢測結果
  * `BacktestReportDTO`: 回測報告
- **主要功能**：
  * **推薦服務**：
    - `run_recommendation()`: 執行策略分析，返回推薦股票列表
    - `detect_regime()`: 檢測市場狀態（Trend/Reversion/Breakout）
    - `get_strategy_config_for_regime()`: 獲取指定市場狀態的策略配置
  * **篩選服務**：
    - `get_strong_stocks()`: 獲取強勢股（本日/本周）
    - `get_strong_industries()`: 獲取強勢產業（本日/本周）
  * **市場狀態服務**：
    - `detect_regime()`: 檢測市場狀態
    - `get_strategy_config()`: 獲取策略配置
  * **數據更新服務**（✅ 完整實現）：
    - `update_daily(start_date, end_date, delay_seconds=4.0)`: 更新每日數據，調用 `batch_update_daily_data.py`
    - `update_market(start_date, end_date)`: 更新市場指數（待實現）
    - `update_industry(start_date, end_date)`: 更新產業指數（待實現）
    - `merge_daily_data(force_all=False)`: 合併每日數據
      - `force_all=True`: 強制重新合併所有數據（完全重建）
      - `force_all=False`: 增量合併，只處理新文件
    - `check_data_status()`: 檢查數據狀態（每日股票數據、大盤指數、產業指數、券商分點資料的最新日期）
    - `update_broker_branch(start_date, end_date, delay_seconds=4.0, force_all=False)`: 更新券商分點資料
    - `merge_broker_branch_data(force_all=False)`: 合併券商分點資料
    - `check_broker_branch_data_status()`: 檢查券商分點資料狀態
  * **券商分點資料更新服務**（✅ 已完成）：
    - `BrokerBranchUpdateService`: 券商分點資料更新服務類
    - `update_broker_branch_data()`: 更新券商分點每日買賣資料（從 MoneyDJ 抓取）
    - `merge_broker_branch_data()`: 合併券商分點資料（每個分點獨立合併）
    - `check_broker_branch_data_status()`: 檢查券商分點資料狀態
    - `_load_branch_registry()`: 載入分點註冊表（含 mojibake 自動修復）
    - `_build_branch_url()`: 構建分點 URL
    - `_parse_counterparty_broker_name()`: 解析對手券商名稱
    - ChromeDriver 自動恢復機制（檢測崩潰並自動重建）
    - 重試機制（每個日期最多重試 3 次）
  * **回測服務**（✅ 已完成）：
    - `run_backtest()`: 執行單一股票回測
      - 支援日期範圍自動調整（當請求日期超出實際數據範圍時）
      - 支援預載入數據（參數最佳化時共用數據，提升性能）
      - 支援多種執行價格模式（next_open、close）
      - 支援 ATR-based 停損停利
      - 支援部位管理（max_positions、position_sizing、allow_pyramid、allow_reentry）
    - `_load_stock_data()`: 載入股票數據和技術指標（自動調整日期範圍）
    - `_load_indicator_data()`: 載入技術指標數據（支援 YYYYMMDD 格式日期解析）
  * **參數最佳化服務**（✅ 已完成）：
    - `grid_search()`: Grid Search 參數掃描
      - 預載入數據一次，所有參數組合共用（性能優化）
      - 多線程並行執行（預設最多 8 個線程）
      - 支援多種目標指標（sharpe_ratio、cagr、cagr_mdd）
      - 進度回調支援
- **架構優勢**：
  * ✅ UI 與邏輯解耦：未來可支持 Qt/Web/CLI 等多種 UI
  * ✅ 向後兼容：現有 Tkinter UI 繼續正常工作
  * ✅ 逐步遷移：風險可控，每一步都可測試
  * ✅ 最小改動：只新增 `app_module/`，不破壞現有代碼

### 6. UI 應用程式模組 (ui_app/) ✅ **已完成**
- **功能**：提供圖形化界面進行數據更新、策略配置和股票推薦
- **架構變化**：
  * **之前**：`ui_app/main.py` → 直接調用 `ui_app/stock_screener.py`, `strategy_configurator.py` 等
  * **現在**：`ui_app/main.py` → `app_module/recommendation_service.py` → `ui_app/stock_screener.py` 等
  * **向後兼容**：保留原有實例（`self.strategy_configurator` 等），確保現有代碼不中斷
- **主要類**：
  * `TradingAnalysisApp`: 主應用程式類（深色主題，三列布局）
    - 已整合 `RecommendationService`，通過服務層調用業務邏輯
  * `StockScreener`: 強勢股/產業篩選器（業務邏輯層，由 `ScreeningService` 調用）
    - **最新改進**：
      - 修正 off-by-one 錯誤（week 週期）
      - 成交量計算優化（不含最新日）
      - 20日新高容忍度修正（0.999）
      - 日期解析改進（支持多種格式）
      - 錯誤處理改進（不再靜默吞掉異常）
  * `StrategyConfigurator`: 策略配置器（業務邏輯層，由 `RecommendationService` 調用）
  * `ScoringEngine`: 統一打分引擎（0-100分制）
  * `ReasonEngine`: 推薦理由生成引擎
  * `MarketRegimeDetector`: 市場狀態檢測器（業務邏輯層，由 `RegimeService` 調用）
  * `IndustryMapper`: 產業映射系統
    - **優化**：在 `main.py` 創建共享實例，避免重複載入數據
- 主要功能：
  * **數據更新**：
    - 每日股票數據更新（批量/單日）
    - 大盤指數數據更新
    - 產業指數數據更新
    - 數據狀態檢查
  * **策略配置**（6個配置標籤頁）：
    - 強勢股/產業：查詢本日/本周強勢股和產業（三列布局）
    - 技術指標：配置動量、波動率、趨勢指標（RSI、MACD、KD、布林通道、ATR、ADX、均線）
    - 圖形模式：選擇11種圖形模式（W底、頭肩頂、雙頂等）
    - 信號組合：配置技術指標信號、成交量條件、權重設置
    - 篩選條件：設置漲幅、成交量、RSI、市值、產業等篩選條件
    - 推薦結果：顯示策略推薦股票，包含總分、指標分、圖形分、成交量分、推薦理由
  * **市場觀察**：
    - 市場 Regime 判斷（Trend/Reversion/Breakout）
    - 強勢股/產業識別
    - 推薦理由生成（價格動能、成交量動能、趨勢結構、產業一致性）
  * **統一打分模型**：
    - `TotalScore = W_pattern * PatternScore + W_indicator * IndicatorScore + W_volume * VolumeScore`
    - Regime Match Factor：匹配市場狀態 ×1.1，不匹配 ×0.85
    - 所有分數範圍：0-100 分
  * **產業映射**：
    - 股票到產業的映射（companies.csv）
    - 產業指數表現查詢（industry_index.csv）
    - 產業篩選功能
- 界面特點：
  * 深色主題（專業金融界面風格）
  * 三列布局（個股強勢、大盤指數、產業指數）
  * 搜索功能
  * 多線程處理（避免UI卡頓）
  * 數據表格（Treeview）顯示
  * 配置保存/載入功能

## 數據流程

### 1. 數據收集流程
1. 初始化配置
2. 檢查數據更新需求
3. 發送API請求
4. 接收和驗證數據
5. 處理和轉換數據
6. 保存數據
7. 創建備份
8. 數據質量檢查（新增）
9. 異常處理和恢復（新增）

### 2. 數據處理流程
1. 加載原始數據
2. 數據清洗
3. 數據轉換
4. 數據驗證
5. 生成處理後的數據
6. 特徵工程（新增）
7. 數據標準化（新增）
8. 異常值處理（新增）

### 3. 分析流程
1. 加載處理後的數據
2. 計算技術指標
3. 進行市場分析
4. 識別圖形模式
5. 執行機器學習分析
6. 生成分析結果
7. 模型評估和優化（新增）
8. 結果可視化（新增）

### 4. 回測流程
1. 加載歷史數據
2. 執行回測策略
3. 計算績效指標
4. 生成回測報告
5. 參數優化（新增）
6. 風險評估（新增）
7. 策略組合（新增）

### 5. 推薦流程（已重構為服務層架構）
1. **UI 層調用**：`ui_app/main.py` 調用 `RecommendationService.run_recommendation()`
2. **服務層處理**：`app_module/recommendation_service.py` 協調業務邏輯
3. **業務邏輯層**：
   - 調用 `StrategyConfigurator` 執行策略配置
   - 調用 `MarketRegimeDetector` 檢測市場狀態
   - 調用 `ScoringEngine` 計算分數
   - 調用 `ReasonEngine` 生成推薦理由
   - 調用 `IndustryMapper` 映射產業信息
4. **數據返回**：返回 `List[RecommendationDTO]` 數據傳輸對象
5. **UI 顯示**：`ui_app/main.py` 接收 DTO 並顯示結果
6. **風險控制**（新增）
7. **動態調整**（新增）

**架構優勢**：
- ✅ UI 與業務邏輯解耦，未來可支持多種 UI（Qt/Web/CLI）
- ✅ 統一的服務接口，便於測試和維護
- ✅ 向後兼容，現有 Tkinter UI 繼續正常工作

## 錯誤處理

### 1. API請求錯誤
- 重試機制
- 錯誤日誌記錄
- 備份還原
- 錯誤代碼處理
- 請求限流（新增）
- 代理切換（新增）

### 2. 數據處理錯誤
- 數據驗證
- 錯誤日誌記錄
- 數據修復
- 異常處理
- 數據備份
- 數據恢復
- 數據一致性檢查（新增）
- 數據完整性檢查（新增）

### 3. 系統錯誤
- 錯誤日誌記錄
- 系統重啟
- 錯誤通知
- 系統監控
- 性能監控（新增）
- 安全監控（新增）

## 配置管理

### 1. 系統配置
- 環境變量（支援路徑覆蓋）
- 配置文件（支援多環境配置）
- 日誌配置
- 數據目錄結構（支援路徑隔離）
- 備份管理
- 路徑隔離配置（新增）
- 原子寫入配置（新增）
- 乾運行模式配置（新增）
- 性能監控配置（新增）
- 安全配置（新增）

### 2. 數據配置
- 數據源配置
- 數據格式配置
- 數據處理配置
- 數據驗證配置
- 數據備份配置
- 數據恢復配置
- 路徑隔離配置（新增）
- 原子寫入配置（新增）
- 數據質量配置（新增）
- 數據安全配置（新增）

### 3. 分析配置
- 技術指標配置
- 市場分析配置
- 形態分析配置
- 機器學習配置
- 回測配置
- 推薦配置
- 路徑隔離配置（新增）
- 參數優化配置（新增）
- 模型管理配置（新增）

### 4. 路徑隔離配置（新增）
- 環境變量覆蓋：`DATA_ROOT`、`OUTPUT_ROOT`、`PROFILE`
- 命令行參數覆蓋：`--data-root`、`--output-root`、`--profile`、`--dry-run`
- 配置檔案模式：`prod`、`test`、`staging`
- 路徑解析輔助：`resolve_path()`、`resolve_output_path()`
- 原子寫入支援：確保檔案寫入安全性
- 乾運行模式：測試腳本邏輯而不實際寫入檔案

## 路徑隔離架構設計

### 1. 設計原則
- **向後兼容性**：預設行為完全保持不變
- **環境隔離**：測試環境與生產環境完全分離
- **靈活配置**：支援多種配置方式
- **安全寫入**：使用原子操作確保數據安全

### 2. 架構層次
```
應用層
├── UI 層
│   ├── ui_app/（Tkinter UI）✅ 已完成
│   │   └── 原有 Tkinter 界面，功能完整
│   ├── ui_qt/（PySide6 Qt UI）✅ 已完成（推薦使用）
│   │   ├── 數據更新視圖（數據狀態、更新、合併、強制重新合併）
│   │   │   └── 查找範圍設置，用於檢查缺失日期
│   │   ├── 市場觀察視圖（強勢個股、大盤指數、強勢產業）
│   │   │   └── 緩存機制：切換「本日/本周」時使用緩存，避免重複計算
│   │   └── 推薦分析視圖（策略配置、執行、結果顯示）
│   └── 未來：Web/CLI UI
├── 應用服務層 (app_module/) ✅ 已完成
│   ├── RecommendationService（推薦服務）
│   ├── ScreeningService（強勢股/產業篩選服務）
│   ├── RegimeService（市場狀態檢測服務）
│   ├── UpdateService（數據更新服務）
│   └── BacktestService（回測服務）
├── 業務邏輯層 (ui_app/ 中的業務模組)
│   ├── StockScreener（強勢股/產業篩選）
│   ├── StrategyConfigurator（策略配置）
│   ├── MarketRegimeDetector（市場狀態檢測）
│   ├── ScoringEngine（統一打分引擎）
│   ├── ReasonEngine（推薦理由生成）
│   └── IndustryMapper（產業映射）
├── 核心模組層
│   ├── data_module/（數據處理）
│   ├── analysis_module/（技術分析）
│   ├── backtest_module/（回測）
│   └── recommendation_module/（推薦）
├── 腳本層 (scripts/)
│   ├── 命令行參數解析
│   ├── 環境變量讀取
│   └── 配置實例化
├── 配置層 (data_module/config.py)
│   ├── TWStockConfig 類
│   ├── 路徑解析邏輯
│   └── 環境覆蓋處理
├── 工具層 (technical_analysis/utils/)
│   ├── 原子寫入工具
│   ├── 乾運行支援
│   └── 安全寫入機制
└── 測試層 (tests/e2e/)
    ├── 路徑隔離測試
    ├── 端到端驗證
    └── 隔離性確認
```

### 3. 配置優先級
1. **命令行參數**（最高優先級）
2. **環境變量**
3. **預設值**（最低優先級）

### 4. 安全機制
- **原子寫入**：使用臨時檔案確保寫入完整性
- **路徑驗證**：確保測試路徑不與生產路徑衝突
- **乾運行模式**：允許測試邏輯而不實際寫入檔案
- **隔離驗證**：端到端測試確保完全隔離

## 開發進度

### 1. 已完成功能
- 數據收集與處理
  * 市場指數數據收集（使用 FMTQIK API）
  * 產業指數數據收集（使用 BFIAMU API）
  * 每日價格數據收集（使用 MI_INDEX API）
  * 數據清洗和驗證
  * 自動備份機制
  * 增量更新功能
  * 錯誤重試機制
  * 詳細的日誌記錄
- 基礎架構
  * 模組化設計
  * 配置管理系統（支援路徑隔離）
  * 數據備份機制
  * 錯誤處理系統
- 應用服務層（✅ 已完成）
  * `app_module/` 目錄結構建立
  * `RecommendationService`：推薦服務（✅ 完整實現）
  * `ScreeningService`：強勢股/產業篩選服務（✅ 完整實現）
    - 支持共享 `IndustryMapper` 實例，避免重複載入數據
  * `RegimeService`：市場狀態檢測服務（✅ 完整實現）
  * `UpdateService`：數據更新服務（✅ 完整實現）
    - `update_daily()`: 更新每日數據
    - `merge_daily_data(force_all=False)`: 合併每日數據（支持強制重新合併）
    - `check_data_status()`: 檢查數據狀態
    - `update_broker_branch()`: 更新券商分點資料
    - `merge_broker_branch_data()`: 合併券商分點資料
    - `check_broker_branch_data_status()`: 檢查券商分點資料狀態
  * `BrokerBranchUpdateService`：券商分點資料更新服務（✅ 已完成）
    - 從 MoneyDJ 抓取 6 個追蹤分點的每日買賣資料
    - 資料存儲在 `data/broker_flow/{branch_system_key}/daily/{YYYY-MM-DD}.csv`
    - 合併資料到 `data/broker_flow/{branch_system_key}/meta/merged.csv`
    - ChromeDriver 自動恢復機制
    - 重試機制（每個日期最多重試 3 次）
  * `BacktestService`：回測服務（✅ 已完成）
    - 日期範圍自動調整
    - 技術指標數據載入優化（YYYYMMDD 格式支援）
    - 預載入數據支援（參數最佳化性能優化）
  * `OptimizerService`：參數最佳化服務（✅ 已完成）
    - Grid Search 參數掃描
    - 多線程並行執行
    - 數據預載入優化
  * DTOs：數據傳輸對象定義（RecommendationDTO, RegimeResultDTO, BacktestReportDTO）
  * UI 與邏輯解耦：`ui_app/main.py` 已使用 `RecommendationService`
  * 向後兼容：保留原有實例，確保現有功能不受影響
- Qt UI 性能優化（✅ 已完成）
  * 市場觀察緩存機制：`StrongStocksView` 和 `StrongIndustriesView` 實現數據緩存
  * 切換「本日/本周」時使用緩存，避免重複計算
  * 點擊「刷新」按鈕時強制重新計算
- 強勢股篩選邏輯修正（✅ 已完成）
  * 修正 off-by-one 錯誤（week 週期）
  * 成交量計算優化（不含最新日）
  * 20日新高容忍度修正（0.999）
  * 日期解析改進（支持多種格式）
  * 錯誤處理改進（不再靜默吞掉異常）
- 路徑隔離功能（新增）
  * 環境變量覆蓋支援
  * 命令行參數覆蓋支援
  * 配置檔案模式支援
  * 路徑解析輔助功能
  * 原子寫入功能
  * 乾運行模式
  * 端到端測試隔離驗證

### 2. 開發中功能
- 數據處理
  * 技術指標計算
  * 數據整合和優化
  * 數據質量檢查
- 分析功能
  * 移動平均線分析
  * RSI 指標計算
  * 布林通道分析
  * 市場趨勢分析

### 3. 計劃中功能
- 回測系統
  * 策略回測
  * 績效評估
  * 風險分析
- 推薦系統
  * 基於技術指標的交易信號
  * 客製化推薦策略

## 測試說明

### 1. 單元測試
- 使用 pytest 框架
- 測試覆蓋率要求 > 80%
- 每個模組都需要對應的測試文件

### 2. 集成測試
- 測試模組間的交互
- 測試數據流程
- 測試錯誤處理

### 3. 性能測試
- 測試系統性能
- 測試數據處理效率
- 測試分析效率

### 4. 安全測試
- 測試系統安全性
- 測試數據安全性
- 測試訪問控制

## 文檔管理

### 1. 技術文檔
- API文檔
- 架構文檔
- 部署文檔

### 2. 用戶文檔
- 使用手冊
- 常見問題
- 故障排除

### 3. 開發文檔
- 開發指南
- 代碼規範
- 測試規範

## 維護指南

### 1. 日常維護
- 系統監控
- 日誌監控
- 數據監控

### 2. 定期維護
- 數據備份
- 系統更新
- 性能優化

### 3. 緊急維護
- 錯誤處理
- 數據恢復
- 系統重啟

## 版本控制

### 1. 分支管理
- 主分支
- 功能分支
- 發布分支

### 2. 版本號規則
- 主版本號
- 次版本號
- 修訂號

## 文檔更新

### 1. 自動更新
- API文檔
- 代碼註釋
- 版本日誌

### 2. 手動更新
- 使用手冊
- 架構文檔
- 部署文檔

### 3. 審核流程
- 技術審核
- 用戶審核
- 發布審核

## 版本歷史

### v1.0.0 (2024-03-20)
- 初始版本發布
- 實現基礎功能
- 完成核心模塊

### v1.1.0 (2024-03-21)
- 添加形態識別優化
- 改進數據處理
- 優化性能

### v1.2.0 (2024-03-22)
- 添加機器學習分析
- 改進回測系統
- 優化推薦系統

### v1.3.0 (2024-03-23)
- 添加新形態支持
- 改進模型管理
- 優化風險控制

### v1.4.0 (2024-03-24)
- 添加實時分析
- 改進性能監控
- 優化用戶體驗

### v1.5.3 (2025-12-27) ✅ **券商分點資料更新功能**
- **BrokerBranchUpdateService 模組**：
  - 實現券商分點資料抓取、標準化、合併功能
  - 從 MoneyDJ 抓取 6 個追蹤分點的每日買賣資料
  - 資料存儲：每個分點獨立目錄 `data/broker_flow/{branch_system_key}/daily/{YYYY-MM-DD}.csv`
  - 合併功能：每個分點獨立合併檔案 `data/broker_flow/{branch_system_key}/meta/merged.csv`
- **Registry 管理**：
  - 建立分點註冊表 `{meta_data_dir}/broker_branch_registry.csv`
  - 包含 6 個追蹤分點的完整資訊
  - 支援 UTF-8 with BOM 編碼，自動修復 mojibake 問題
- **UI 整合**：
  - 整合到數據更新頁面
  - 新增「券商分點資料」更新類型選項
  - 新增「券商分點數據」狀態顯示區塊
  - 新增「合併券商分點資料」按鈕
- **穩定性改進**：
  - ChromeDriver 自動恢復機制（檢測崩潰並自動重建）
  - 重試機制（每個日期最多重試 3 次）
  - 改進的錯誤處理和日誌記錄
  - 增強 Chrome 選項以提高穩定性

### v1.5.2 (2025-12-22) ✅ **策略回測功能優化**
- **日期範圍自動調整**：
  - 當選擇的日期範圍超過實際數據範圍時，自動調整為可用範圍
  - 顯示提示訊息告知用戶實際使用的日期範圍
  - 在回測報告中記錄請求日期和實際日期
- **參數最佳化性能優化**：
  - 預載入數據一次，所有參數組合共用（從 N 次減少到 1 次）
  - 多線程並行執行（預設最多 8 個線程，提升 6-8 倍速度）
  - 減少重複的日期調整訊息
- **技術指標數據載入修復**：
  - 修復 YYYYMMDD 格式日期解析問題
  - 改進日期欄位類型檢測和轉換邏輯
- **技術指標計算腳本修復**：
  - 修復增量更新時覆蓋舊數據的問題
  - 實現數據合併邏輯（讀取現有數據、合併、去重、排序）

### v1.5.1 (2025-12-15) ✅ **Qt UI 優化與數據更新邏輯改進**
- **數據更新邏輯優化**：
  - 移除「開始日期」欄位，改為「查找範圍（天）」
  - 查找範圍用於檢查指定天數內缺失的日期
  - 合併操作始終處理所有數據，不受查找範圍限制
  - 新增「強制重新合併」功能：完全重建 `stock_data_whole.csv`
- **市場觀察性能優化**：
  - `StrongStocksView` 和 `StrongIndustriesView` 實現數據緩存
  - 切換「本日/本周」時使用緩存，避免重複計算
  - 點擊「刷新」按鈕時強制重新計算
- **強勢股篩選邏輯修正**：
  - 修正 off-by-one 錯誤（week 週期：`df.iloc[-6]`）
  - 成交量計算優化（不含最新日：`iloc[-6:-1]`）
  - 20日新高容忍度修正（`0.999` 而非 `0.99`）
  - 日期解析改進（支持多種格式：`YYYYMMDD`、`YYYY/MM/DD`、`YYYY-MM-DD`）
  - 錯誤處理改進（不再靜默吞掉異常）
- **IndustryMapper 共享實例優化**：
  - 在 `main.py` 創建單一實例，傳遞給 `ScreeningService` 和 `RecommendationService`
  - 避免重複載入 `companies.csv` 和 `industry_index.csv`
- **UpdateService 完整實現**：
  - `update_daily()`: 更新每日數據
  - `merge_daily_data(force_all=False)`: 合併每日數據（支持強制重新合併）
  - `check_data_status()`: 檢查數據狀態

### v1.5.0 (2025-12-15) ✅ **應用服務層重構 + Qt UI**
- **新增 `app_module/` 應用服務層**：
  - `RecommendationService`：推薦服務（✅ 完整實現）
  - `ScreeningService`：強勢股/產業篩選服務（✅ 完整實現）
  - `RegimeService`：市場狀態檢測服務（✅ 完整實現）
  - `UpdateService`：數據更新服務（✅ 骨架完成，v1.5.1 完整實現）
  - `BacktestService`：回測服務（✅ 已完成，v1.5.2 優化）
- **數據傳輸對象 (DTOs)**：
  - `RecommendationDTO`：股票推薦結果
  - `RegimeResultDTO`：市場狀態檢測結果
  - `BacktestReportDTO`：回測報告
- **新增 `ui_qt/` Qt UI（PySide6）**：
  - 數據更新視圖：數據狀態檢查、更新、合併功能
  - 市場觀察視圖：強勢個股、大盤指數、強勢產業（分離顯示）
  - 推薦分析視圖：策略配置、執行、結果顯示
  - 非阻塞任務執行：使用 TaskWorker 和 ProgressTaskWorker
  - 表格數據模型：PandasTableModel 用於顯示 DataFrame
- **架構改進**：
  - UI 與業務邏輯完全解耦，為未來支持多種 UI（Web、CLI）打下基礎
  - 採用方案 A（最小重工），不搬動檔案，service 層內部 import `ui_app` 模組
  - 向後兼容：保留原有實例，確保現有 Tkinter UI 繼續正常工作
  - `ui_app/main.py` 已整合 `RecommendationService` 