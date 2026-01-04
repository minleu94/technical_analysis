# 股票測試模型系統

> 注意：本項目文件和交流使用繁體中文。
> Note: This project documentation and communication uses Traditional Chinese.

## 系統概述

本系統是一個完整的台股技術分析平台，提供數據收集、處理、分析和回測功能。系統採用模組化設計，確保各個組件之間的獨立性和可維護性。

## 當前狀態：Phase 2.5 完成 ✅

**Phase 2.5：參數設計優化** ✅ 已完成並驗證通過
- ✅ 強勢/弱勢分數標準化（z-score、log 壓縮）
- ✅ Pattern ATR-based 參數（threshold_atr_mult、prominence_atr_mult）
- ✅ Scoring Contract 統一（0-100 分制、Regime 權重切換）
- ✅ 回測參數改進（execution_price、ATR 停損停利、部位管理）
- ✅ **功能驗證**：18/18 功能通過（100% 通過率）
  - 驗證報告：`output/qa/phase2_5_validation/VALIDATION_REPORT.md`
  - 驗證腳本：`scripts/qa_validate_phase2_5.py`

**詳細開發進度**：請參考 [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md)

## 快速開始指南

### 1. 環境設置
```
# 克隆項目
git clone [repository_url]
cd technical_analysis

# 安裝依賴
pip install -r requirements.txt
```

### 2. 目錄結構
```
technical_analysis/
├── analysis_module/           # 分析模組
│   ├── __init__.py
│   ├── pattern_analysis/     # 圖形模式分析
│   │   ├── pattern_analyzer.py
│   │   └── pattern_parameter_optimizer.py
│   ├── technical_analysis/   # 技術分析
│   │   ├── __init__.py
│   │   ├── technical_indicators.py
│   │   └── calculate_technical_indicators.py
│   └── ml_analysis/         # 機器學習分析
├── data_module/              # 數據模組
│   ├── __init__.py
│   ├── data_loader.py
│   └── data_processor.py
├── backtest_module/          # 回測模組
│   ├── __init__.py
│   ├── strategy_tester.py
│   └── performance_analyzer.py
├── recommendation_module/    # 推薦模組
│   ├── __init__.py
│   └── recommendation_engine.py
├── scripts/                  # 獨立工具腳本
│   ├── fix_market_index.py  # 市場指數數據修復工具
│   ├── fix_industry_index.py # 產業指數數據修復工具
│   └── merge_daily_data.py  # 每日數據合併工具
├── tests/                    # 測試目錄
│   ├── test_data/           # 測試數據
│   ├── test_backtest/       # 回測測試
│   ├── test_pattern_analysis/ # 圖形模式測試
│   ├── test_recommendation/  # 推薦測試
│   ├── test_technical_analysis/ # 技術分析測試
│   └── test_data_update/    # 數據更新測試
├── data/                     # 數據目錄
│   ├── raw/                 # 原始數據
│   ├── processed/           # 處理後的數據
│   └── backup/             # 數據備份
├── output/                   # 輸出目錄
│   ├── results/             # 分析結果
│   └── reports/             # 報告文件
├── docs/                     # 文檔目錄
│   ├── system_architecture.md # 系統架構文檔
│   └── note.txt            # 開發進度記錄
├── config.py                 # 配置文件
├── main.py                   # 主程序
├── requirements.txt          # 依賴管理
└── README.md                # 項目文檔
```

為了快速了解系統架構和當前開發進度，請先閱讀以下文件：

1. **[system_architecture.md](docs/system_architecture.md)**：包含系統架構的流程圖和詳細說明，幫助您理解各模組之間的關係和數據流程。
   - 包括數據流程圖
   - 模組結構詳解
   - 數據和輸出流程
   - 輸出文件說明

2. **[note.txt](docs/note.txt)**：包含當前開發進度、已完成的功能和待解決的問題。
   - 各模組的開發進度
   - 最新更新內容
   - 輸出文件說明
   - 已知問題和解決方案
   - 下一步開發建議

3. **[readme_test.txt](readme_test.txt)**：包含測試輸出檔案的詳細說明。
   - 測試輸出檔案分類和說明
   - 各檔案的生成腳本和用途
   - 測試腳本與輸出檔案的對應關係
   - 正式模組建議輸出
   - 配置選項建議

閱讀這些文件後，您將能夠快速了解系統的整體架構、當前狀態、測試輸出和未來開發方向，從而更有效地銜接開發進度。

## 數據存儲路徑說明

系統默認使用以下固定路徑存儲數據和計算結果：

### 1. 基礎數據目錄
- **主數據目錄**: `D:/Min/Python/Project/FA_Data/`

### 2. 數據子目錄
- **原始數據目錄**: `D:/Min/Python/Project/FA_Data/meta_data/`
  - 股票整合數據: `stock_data_whole.csv`
  - 所有股票計算後數據: `all_stocks_data.csv`
  - 市場指數數據: `market_index.csv`
  - 產業指數數據: `industry_index.csv`

- **技術指標計算結果目錄**: `D:/Min/Python/Project/FA_Data/technical_analysis/`
  - 個股技術指標文件: `{股票代號}_indicators.csv`

- **每日價格數據目錄**: `D:/Min/Python/Project/FA_Data/daily_price/`
  - 每日價格文件: `{日期}.csv`

- **備份目錄**: `D:/Min/Python/Project/FA_Data/meta_data/backup/`
  - 備份文件格式: `{原檔名}_{備份時間}.csv`
  - 例如: `all_stocks_data_20240402_143000.csv`

- **日誌目錄**: `D:/Min/Python/Project/FA_Data/logs/`
  - 技術指標計算日誌: `technical_calculation.log`
  - 數據更新日誌: `data_update.log`

### 3. 路徑配置說明

#### 3.1 預設路徑（生產模式）
系統預設使用D槽路徑，保持向後兼容性。

#### 3.2 路徑隔離功能（測試模式）
系統支援靈活的路徑覆蓋，確保測試環境不會影響生產數據：

**環境變量覆蓋**:
```bash
# 設置測試環境
export DATA_ROOT=./test_data
export OUTPUT_ROOT=./test_output
export PROFILE=test
```

**命令行參數覆蓋**:
```bash
# 直接指定測試路徑
python scripts/update_all_data.py --profile test --data-root ./sandbox_data --output-root ./sandbox_output --dry-run
```

**配置檔案模式**:
- `--profile prod`: 使用預設D槽路徑（生產模式）
- `--profile test`: 自動添加 `_test` 後綴到路徑
- `--profile staging`: 使用指定的staging路徑

**乾運行模式**:
```bash
# 測試腳本邏輯而不實際寫入檔案
python scripts/update_all_data.py --dry-run
```

#### 3.3 傳統配置方式（向後兼容）
若需修改這些路徑，仍可使用以下方式：

1. **修改配置文件**: 編輯 `data_module/config.py` 中的 `TWStockConfig` 類
   ```python
   @dataclass
   class TWStockConfig:
       # 基礎路徑配置 - 可在此修改基礎目錄
       base_dir: Path = field(default_factory=lambda: Path(
           os.environ.get('TWSTOCK_DATA_DIR', 'D:/Min/Python/Project/FA_Data')
       ))
   ```

2. **環境變數設置**: 設置 `TWSTOCK_DATA_DIR` 環境變數

3. **建立軟連結/符號連結**: 在硬碟上建立軟連結，將固定路徑映射到您偏好的位置

注意：所有路徑都會自動創建，無需手動建立目錄結構。

## 最新更新

1. PatternAnalyzer類擴展
   - 新增圖形模式識別方法：V形反轉、圓頂/圓底、矩形、楔形
   - 優化現有模式識別：三角形、雙頂/雙底、W底等
   - 更新方法返回格式，統一添加pattern、type、direction等字段

2. 添加圖形模式橫向比較功能
   - 計算並比較各種模式的勝率、平均收益率、風險回報比和準確率
   - 生成綜合評分和比較報表
   - 輸出柱狀圖、雷達圖等可視化成果

3. 修復和優化
   - 修復熊市模式的風險回報比計算問題
   - 改進峰值和谷值檢測算法
   - 優化圖形模式識別參數，顯著提高準確率和降低誤報率

4. 圖形模式識別方法優化（2023.11.22）
   - 楔形模式(Wedge)識別優化：
     * 添加R方值檢查確保趨勢線擬合可靠性
     * 增加斜率、高度比例等嚴格檢查
     * 改進收斂點計算和驗證
     * 優化趨勢線接觸點計算
     * 區分上升楔形和下降楔形
   - 三角形模式(Triangle)識別重構：
     * 使用二次函數進行擬合並確保R方值達標
     * 改進趨勢線擬合邏輯
     * 優化三角形類型(對稱、上升、下降)的判定標準
     * 添加成交量確認機制
     * 增加形態完整性驗證
   - 圓底/圓頂模式(Rounding Bottom/Top)識別改進：
     * 使用二次函數擬合代替基於相似度的方法
     * 添加曲率和最高/最低點位置檢查
     * 增加深度/高度比例檢查
     * 增加成交量模式確認
     * 優化重疊形態的合併邏輯

5. 測試和評估
   - 創建test_advanced_patterns.py測試腳本
   - 自動計算各種模式的準確率和收益率
   - 生成測試報告和可視化圖表

6. 測試腳本和參數優化（2023.11.25）
   - 開發圖形模式識別優化測試腳本test_optimized_patterns.py：
     * 增強數據加載功能，支持多種數據源的自動檢測和加載
     * 自動適配市場指數數據（如台灣加權指數、上證指數、標普500等）
     * 實現多種圖表可視化，包括柱狀圖、雷達圖、散點圖等
     * 生成詳細的測試報告，包含各模式的識別數量、準確率、勝率等指標
   - 數據加載模塊改進：
     * 添加多數據源優先級加載機制
     * 增加數據框架自動識別和格式化功能
     * 添加數據驗證和缺失處理（如自動生成隨機成交量數據用於測試）
     * 實現日期索引自動檢測和標準化
   - 圖形模式參數優化：
     * 優化各種圖形模式的識別參數，提高識別率並降低誤報率
     * 針對不同市場特性調整參數閾值
     * 添加參數自動調整測試功能
   - 測試評估功能增強：
     * 實現多種績效指標的自動計算和比較
     * 添加圖形模式橫向比較報告生成
     * 創建綜合評分系統，為不同市場數據推薦最適合的模式

7. 測試數據組織結構優化（2023.11.26）
   - 重構測試數據組織結構：
     * 在 test_data 目錄下為每個股票代碼創建專屬資料夾
     * 所有測試結果（圖表、報告、數據）都保存在對應的股票資料夾中
     * 優化文件命名規則，使其更具描述性和一致性
   - 改進參數優化測試功能：
     * 開發 pattern_parameter_tuning 測試腳本
     * 實現網格搜索方法來尋找最佳參數組合
     * 添加參數優化結果的可視化和報告生成
     * 支持多種圖形模式（W底、頭肩頂、三角形等）的參數優化
   - 優化數據加載和處理：
     * 改進市場指數數據的加載機制
     * 添加數據格式驗證和自動轉換功能
     * 優化缺失數據的處理方法
     * 增加數據預處理的日誌記錄
   - 增強測試報告功能：
     * 添加更詳細的測試結果統計
     * 改進圖表生成和保存機制
     * 優化報告格式和內容組織
     * 增加測試結果的版本控制

8. 圖形模式參數優化（2024.03.20）
   - 優化圖形模式識別參數測試腳本：
     * 改進參數組合的測試方法，使用更合理的參數範圍
     * 添加數據預處理步驟，包括標準化處理
     * 優化測試結果的可視化展示
     * 改進結果保存格式，更清晰地展示每個參數組合的效果
   - 測試結果顯示：
     * W底模式：最佳參數組合（window=10）達到50%準確率
     * 頭肩頂模式：最佳參數組合（window=20, threshold=0.08）達到56.25%準確率
     * 三角形模式：最佳參數組合（window=20, threshold=0.08, min_r_squared=0.4, min_height_ratio=0.02）達到75%準確率
   - 改進測試數據處理：
     * 添加數據自動生成功能，確保測試的穩定性
     * 優化數據預處理流程，提高模式識別的準確性
     * 改進測試結果的保存和展示方式

## 模組功能說明
1. 數據模組 (data_module)
DataLoader 類
負責從不同來源讀取股票數據。主要方法:
•  load_from_yahoo(ticker, start_date, end_date): 從Yahoo Finance加載股票數據
•  load_from_csv(file_path): 從CSV文件加載股票數據，支援utf-8-sig編碼
•  save_to_csv(data, ticker, folder): 保存數據到CSV文件，可選擇不保存索引列
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

數據來源:
•  Yahoo Finance API (透過yfinance套件)
•  本地CSV文件

DataProcessor 類
負責數據清洗、標準化和特徵工程。主要方法:
•  clean_data(df): 清洗數據，處理缺失值和異常值
•  normalize_data(df): 標準化數據
•  add_basic_features(df): 添加基本特徵（移動平均線、交易量變化等）
•  split_train_test(df, test_size): 將數據分割為訓練集和測試集
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

2. 分析模組 (analysis_module)
TechnicalAnalyzer 類
實現各種技術指標分析。主要方法:
•  add_momentum_indicators(df): 添加動量指標（RSI、MACD、隨機震盪指標等）
•  add_volatility_indicators(df): 添加波動性指標（布林帶、ATR等）
•  add_trend_indicators(df): 添加趨勢指標（ADX、拋物線轉向指標等）
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

依賴套件:
•  talib: 用於計算技術指標

MLAnalyzer 類
實現機器學習模型分析。主要方法:
•  prepare_features(df, feature_cols): 準備特徵數據，處理特徵名稱不匹配問題
•  prepare_features_targets(df, target_col, feature_cols, prediction_horizon): 準備特徵和目標變量
•  train_classifier(X_train, y_train, model_type, **kwargs): 訓練分類模型
•  train_regressor(X_train, y_train, model_type, **kwargs): 訓練回歸模型
•  predict(X_test, model_name): 使用訓練好的模型進行預測
•  evaluate_classifier(X_test, y_test, model_name): 評估分類模型
•  evaluate_regressor(X_test, y_test, model_name): 評估回歸模型
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

支持的模型:
•  分類模型: 隨機森林、邏輯回歸
•  回歸模型: 梯度提升回歸

依賴套件:
•  scikit-learn: 用於機器學習模型

MathAnalyzer 類
實現數學模型分析。主要方法:
•  check_stationarity(time_series): 檢查時間序列的平穩性
•  fit_arima(time_series, order): 擬合ARIMA模型
•  forecast_arima(steps): 使用ARIMA模型進行預測
•  calculate_volatility(returns, window): 計算波動率
•  calculate_sharpe_ratio(returns, risk_free_rate): 計算夏普比率
•  calculate_correlation_matrix(df): 計算相關性矩陣
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

依賴套件:
•  statsmodels: 用於時間序列分析和ARIMA模型

PatternAnalyzer 類
實現價格圖形模式分析。主要方法:
•  find_peaks_and_troughs(df, price_col): 找出價格序列中的峰和谷
•  identify_w_bottom(df, price_col): 識別W底形態
•  identify_head_and_shoulders(df, price_col): 識別頭肩頂形態
•  identify_double_top(df, price_col): 識別雙頂形態
•  identify_double_bottom(df, price_col): 識別雙底形態
•  identify_triangle(df, price_col): 識別三角形形態（上升、下降、對稱）
•  identify_flag(df, price_col): 識別旗形形態（看漲、看跌）
•  identify_pattern(df, pattern_type, price_col): 識別指定類型的圖形模式
•  plot_pattern(df, pattern_positions, pattern_type): 繪製識別出的圖形模式
•  predict_from_pattern(df, pattern_positions, pattern_type): 根據識別出的圖形模式進行預測
•  evaluate_pattern_accuracy(df, pattern_type): 評估圖形模式預測的準確性
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

支持的圖形模式:
•  W底: 兩個相近的低點，中間有一個高點，形成W形狀
•  頭肩頂: 三個高點，中間的高點（頭）高於兩側的高點（肩），形成頭肩頂形態
•  頭肩底: 三個低點，中間的低點（頭）低於兩側的低點（肩），形成頭肩底形態

依賴套件:
•  scipy: 用於信號處理和峰值檢測
•  fastdtw: 用於動態時間規整

3. 回測模組 (backtest_module)
StrategyTester 類
實現策略回測功能。主要方法:
•  run_backtest(df, strategy_func, **strategy_params): 運行回測
•  plot_results(): 繪製回測結果圖表
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

回測數據:
•  交易記錄: 包含買入/賣出時間、價格、數量和價值
•  組合價值: 包含現金、持倉和總價值的時間序列

PerformanceAnalyzer 類
計算各種績效指標並生成視覺化報告。主要方法:
•  calculate_returns(portfolio_values): 計算收益率
•  calculate_cumulative_returns(returns): 計算累積收益率
•  calculate_annualized_return(returns): 計算年化收益率
•  calculate_volatility(returns, annualized): 計算波動率
•  calculate_sharpe_ratio(returns): 計算夏普比率
•  calculate_sortino_ratio(returns): 計算索提諾比率
•  calculate_max_drawdown(returns): 計算最大回撤
•  calculate_alpha_beta(): 計算阿爾法和貝塔係數
•  generate_performance_report(): 生成績效報告
•  plot_performance(): 繪製績效圖表

績效指標:
•  累積收益率、年化收益率、年化波動率
•  夏普比率、索提諾比率、最大回撤
•  阿爾法、貝塔（相對於基準）

4. 推薦模組 (recommendation_module)
RecommendationEngine 類
綜合各種分析結果，生成交易建議和詳細分析報告。主要方法:
•  set_weights(technical, ml, math): 設置各分析方法的權重
•  get_technical_signals(df): 獲取技術分析信號
•  get_ml_signals(df, model_name): 獲取機器學習模型信號
•  get_math_signals(df): 獲取數學模型信號
•  generate_recommendation(df): 生成綜合建議
•  get_latest_recommendation(df, days): 獲取最近幾天的建議
•  generate_report(ticker, df): 生成詳細分析報告
•  _signal_to_text(signal): 將信號轉換為文本
•  _generate_advice(signal, rsi, macd, macd_signal): 生成詳細建議
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

建議類型:
•  買入、賣出、持有
•  每種建議都包含詳細的分析依據和置信度

5. 信號組合模組 (新增)
SignalCombiner 類
組合不同分析模組的信號並評估綜合信號的可靠性。主要方法:
•  analyze_combined_signals(df, pattern_types, technical_indicators, volume_conditions): 分析組合信號
•  _analyze_volume(df, volume_conditions): 分析交易量
•  _combine_signals(df, patterns): 組合不同來源的信號
•  _evaluate_signal_reliability(df): 評估信號的可靠性
•  backtest_strategy(df, strategy_params, initial_capital, commission): 回測組合策略
•  visualize_signals(df, ticker, save_path): 視覺化信號
•  _get_column_name(df, eng_name): 獲取對應的列名，支援中英文列名映射

信號類型:
•  形態信號: 基於圖形模式的信號
•  技術指標信號: 基於技術指標的信號
•  交易量信號: 基於交易量的信號
•  組合信號: 綜合以上信號的強度和可靠性

## 數據流程
•  數據獲取:
•  從Yahoo Finance或本地CSV文件加載原始股票數據
•  數據包含開盤價、最高價、最低價、收盤價和交易量
•  數據預處理:
•  清洗數據（處理缺失值和異常值）
•  添加基本特徵（移動平均線、交易量變化等）
•  特徵工程:
•  添加技術指標（RSI、MACD、布林帶等）
•  準備機器學習特徵和目標
•  識別圖形模式（W底、頭肩頂、頭肩底等）
•  模型訓練:
•  訓練機器學習模型（分類和回歸）
•  擬合ARIMA時間序列模型
•  策略回測:
•  根據交易信號模擬交易
•  計算組合價值和收益率
•  績效評估:
•  計算各種績效指標
•  生成視覺化報告
•  信號組合:
•  組合不同來源的信號
•  評估信號的可靠性
•  回測組合策略
•  建議生成:
•  綜合各種分析結果
•  生成交易建議和詳細分析報告

## 系統依賴
主要套件:
•  pandas: 數據處理和分析
•  numpy: 數值計算
•  matplotlib: 數據可視化
•  yfinance: 從Yahoo Finance獲取股票數據
•  scikit-learn: 機器學習模型
•  talib: 技術指標計算
•  statsmodels: 時間序列分析和ARIMA模型
•  scipy: 信號處理和峰值檢測
•  fastdtw: 動態時間規整

安裝方法:
```
pip install pandas numpy matplotlib yfinance scikit-learn ta-lib statsmodels scipy fastdtw
```

## 使用示例
### 使用模組化方式
```
# 初始化各模組
data_loader = DataLoader()
data_processor = DataProcessor()
tech_analyzer = TechnicalAnalyzer()
ml_analyzer = MLAnalyzer()
math_analyzer = MathAnalyzer()
pattern_analyzer = PatternAnalyzer()
signal_combiner = SignalCombiner()
strategy_tester = StrategyTester(initial_capital=100000.0)

# 加載數據
ticker = '2330.TW'  # 台積電
df = data_loader.load_from_yahoo(ticker, '2020-01-01', '2022-01-01')

# 數據預處理和特徵工程
df_cleaned = data_processor.clean_data(df)
df_features = data_processor.add_basic_features(df_cleaned)
df_tech = tech_analyzer.add_momentum_indicators(df_features)
df_tech = tech_analyzer.add_volatility_indicators(df_tech)
df_tech = tech_analyzer.add_trend_indicators(df_tech)

# 識別圖形模式
pattern_types = ['W底', '頭肩頂', '頭肩底']
patterns = {}
for pattern_type in pattern_types:
    patterns[pattern_type] = pattern_analyzer.identify_pattern(df_tech, pattern_type)

# 分析組合信號
df_signals = signal_combiner.analyze_combined_signals(
    df_tech, 
    pattern_types=pattern_types,
    technical_indicators=['momentum', 'volatility', 'trend'],
    volume_conditions=['increasing', 'decreasing', 'spike']
)

# 回測組合策略
strategy_params = {
    'buy_threshold': 1,  # 買入信號閾值
    'sell_threshold': -1,  # 賣出信號閾值
    'reliability_threshold': 0.5,  # 可靠性閾值
    'use_stop_loss': True,  # 是否使用止損
    'stop_loss_pct': 0.05  # 止損百分比
}
backtest_results = signal_combiner.backtest_strategy(df_signals, strategy_params)

# 視覺化信號
signal_combiner.visualize_signals(df_signals, ticker=ticker, save_path=f"{ticker}_signals.png")

# 生成交易建議
recommendation_engine = RecommendationEngine(
    technical_analyzer=tech_analyzer,
    ml_analyzer=ml_analyzer,
    math_analyzer=math_analyzer
)

recommendation = recommendation_engine.generate_recommendation(df_tech)
latest_recommendation = recommendation_engine.get_latest_recommendation(df_tech, days=5)

# 生成詳細分析報告
report = recommendation_engine.generate_report(ticker, df_tech)
print(report)
```

### 使用主程序
系統提供了 main.py 主程序，可以直接運行完整的分析流程：

```
python main.py
```

main.py 主程序功能：
1. 加載指定股票的歷史數據（默認為台積電 2330）
2. 進行數據預處理和特徵工程
3. 訓練機器學習模型（分類和回歸）
4. 進行時間序列分析（ARIMA模型）
5. 使用簡單移動平均線交叉策略進行回測
6. 計算績效指標並生成視覺化報告
7. 生成交易建議和詳細分析報告
8. 保存處理後的數據

您可以修改 main.py 中的以下參數來自定義分析：
- ticker：股票代碼
- data_path：數據路徑
- 策略參數：simple_ma_strategy 函數中的 short_window 和 long_window

## 測試腳本
系統提供了多個測試腳本，用於測試各個模組的功能：

1. test_data_loading.py: 測試數據加載和處理功能
   - 測試從CSV文件加載數據
   - 測試數據清洗和基本特徵添加
   - 測試數據保存功能

2. test_technical_analyzer.py: 測試技術指標計算功能
   - 測試動量指標計算（RSI、MACD等）
   - 測試波動性指標計算（布林帶等）
   - 測試趨勢指標計算（ADX等）
   - 生成技術指標視覺化圖表

3. test_math_analyzer.py: 測試數學分析功能
   - 測試時間序列平穩性檢驗
   - 測試ARIMA模型擬合和預測
   - 測試波動率和夏普比率計算
   - 測試相關性矩陣計算

4. test_pattern_analyzer.py: 測試圖形模式識別功能
   - 測試峰谷檢測
   - 測試W底形態識別
   - 測試頭肩頂/底形態識別
   - 測試圖形模式視覺化和預測

5. test_signal_combiner.py: 測試信號組合功能
   - 測試組合不同來源的信號
   - 測試信號可靠性評估
   - 測試組合策略回測
   - 測試信號視覺化

6. test_backtest_recommendation.py: 測試回測模組和推薦模組功能
   - 測試策略回測功能
   - 測試績效分析功能
   - 測試推薦引擎功能
   - 生成完整回測結果和績效分析圖表

7. test_recommendation_report.py: 測試推薦報告生成和編碼問題
   - 測試推薦報告生成功能
   - 測試報告文件編碼（utf-8-sig）
   - 檢查中文顯示是否正常

8. check_signals_file.py: 檢查信號數據文件
   - 檢查信號數據CSV文件是否存在
   - 檢查文件內容和格式是否正確

9. check_processed_file.py: 檢查處理後的數據文件
   - 檢查處理後的數據文件是否存在
   - 檢查文件內容和格式是否正確

10. check_saved_file.py: 檢查保存的文件
    - 檢查保存的數據文件是否存在
    - 檢查文件內容和格式是否正確

11. check_columns.py: 檢查數據欄位
    - 檢查數據欄位是否完整
    - 顯示所有可用的數據欄位
    - 檢查中英文列名映射是否正確

12. test_extended_patterns.py: 測試擴展的圖形模式識別功能
    - 識別雙頂、雙底、三角形和旗形等圖形模式
    - 評估各種圖形模式的預測準確性
    - 分析三角形和旗形的類型分布
    - 生成綜合分析報告
    - 輸出圖形模式識別結果、預測圖表和分析報告到 test_data 目錄

## 數據和圖表存儲位置
1. 原始數據:
•  從Yahoo Finance獲取的數據不會自動保存
•  可以使用data_loader.save_to_csv()方法保存到本地

2. 處理後的數據:
•  默認保存在./data目錄下
•  文件名格式為{ticker}.csv或{ticker}_processed.csv

3. 測試結果和圖表:
•  測試結果默認保存在 D:\Min\Python\Project\FA_Data\test_data 目錄下
•  完整回測結果圖表 (兩格圖表): {ticker}_backtest_result_complete.png
   - 上半部分：顯示資產價值曲線，包括組合總價值、現金和股票價值，以及買入/賣出點
   - 下半部分：顯示累積收益率曲線
•  舊版回測結果圖表: {ticker}_backtest_result.png
   - 由舊版測試腳本生成，僅供參考
•  績效分析圖表 (四格圖表): {ticker}_performance_analysis.png
   - 左上：累積收益率比較（策略 vs 基準）
   - 右上：月度收益率熱圖
   - 左下：滾動夏普比率
   - 右下：最大回撤分析
•  技術指標圖表: {ticker}_technical_indicators.png
   - 上部：價格和均線（30日簡單移動平均線和30日指數移動平均線）
   - 中部：RSI指標，並標記70和30的超買超賣線
   - 下部：MACD指標和MACD信號線
•  推薦信號圖表: {ticker}_recommendation_signals.png
•  信號組合圖表: {ticker}_signals.png
•  推薦報告: {ticker}_recommendation_report.txt
•  圖形模式圖表: {ticker}_pattern_{pattern_type}.png

4. 自定義存儲位置:
•  可以在測試腳本中修改 test_data_path 變量來自定義存儲位置
•  可以在函數調用時指定 save_path 參數來自定義圖表保存路徑

## 已知問題和解決方案
1. 數學模型分析中的警告：
   - 關於日期索引沒有頻率信息的警告
   - 關於 'M' 已棄用的警告，應使用 'ME' 代替
   - 解決方案：在使用 ARIMA 模型前，為日期索引添加頻率信息，並使用 'ME' 代替 'M'

2. 機器學習模型中的警告：
   - 關於 DataFrame 切片的 SettingWithCopyWarning
   - 解決方案：使用 df.loc[] 或 df.copy() 方法避免警告

3. 數學模型分析中的錯誤：
   - 數學模型分析出錯: -1
   - 解決方案：調整 ARIMA 模型的參數，或使用其他時間序列模型

## 下一步開發計劃
1. 優化數學模型分析
   - [ ] 改進時間序列分析方法
   - [ ] 優化ARIMA模型參數
   - [ ] 添加更多統計指標
2. 優化機器學習模型
   - [ ] 添加深度學習模型
   - [ ] 優化特徵工程
   - [ ] 改進模型評估方法
3. 添加更多的圖形模式
   - [x] 優化W底、頭肩頂和三角形模式的參數
   - [ ] 添加更多技術形態識別
   - [ ] 改進形態預測準確率
4. 添加更多的技術指標
   - [ ] 添加更多動量指標
   - [ ] 添加更多趨勢指標
   - [ ] 優化指標參數
5. 添加更多的回測功能
   - [ ] 添加更多回測策略
   - [ ] 優化回測效率
   - [ ] 改進回測報告
6. 添加更多的推薦功能
   - [ ] 優化推薦算法
   - [ ] 添加風險評估
   - [ ] 改進推薦報告
7. 添加圖形用戶界面
   - [ ] 設計主界面
   - [ ] 添加圖表展示
   - [ ] 添加參數設置界面
8. 添加多資產組合分析
   - [ ] 添加組合優化
   - [ ] 添加風險分析
   - [ ] 改進回測功能
9. 添加更多的數據源
   - [ ] 添加即時數據源
   - [ ] 添加基本面數據
   - [ ] 添加新聞數據
10. 添加更多的測試和文檔
    - [x] 優化參數測試腳本
    - [ ] 添加單元測試
    - [ ] 完善開發文檔

## 配置文件說明
配置文件 `config.py` 包含以下主要設置：

1. 路徑配置
```
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RAW_DATA_DIR = os.path.join(DATA_DIR, 'raw')
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, 'processed')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
RESULTS_DIR = os.path.join(OUTPUT_DIR, 'results')
REPORTS_DIR = os.path.join(OUTPUT_DIR, 'reports')
TEST_DATA_DIR = os.path.join(BASE_DIR, 'tests', 'test_data')
```

2. 數據配置
```python
DEFAULT_ENCODING = 'utf-8-sig'
DATE_FORMAT = '%Y-%m-%d'
DEFAULT_TICKER = '2330.TW'
```

3. 技術分析參數
```python
TECHNICAL_PARAMS = {
    'ma_short': 5,
    'ma_long': 20,
    'rsi_period': 14,
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,
    'bb_period': 20,
    'bb_std': 2
}
```

4. 圖形模式參數
```python
PATTERN_PARAMS = {
    'W底': {'window': 10},
    '頭肩頂': {'window': 20, 'threshold': 0.08},
    '三角形': {
        'window': 20,
        'threshold': 0.08,
        'min_r_squared': 0.4,
        'min_height_ratio': 0.02
    }
}
```

台股技術分析系統 v1.1.0

系統概述：
本系統是一個完整的台股技術分析平台，提供數據收集、處理、分析和回測功能。系統採用模組化設計，確保各個組件之間的獨立性和可維護性。目前系統已實現數據收集和基礎分析功能，正在開發回測和推薦功能。

系統架構：
technical_analysis/
├── data_module/          # 數據處理模組
│   ├── data_loader.py    # 數據加載器（已完成）
│   ├── data_processor.py # 數據處理器（開發中）
│   └── config.py         # 配置管理（已完成）
├── analysis_module/      # 分析模組（開發中）
│   ├── technical_indicators.py  # 技術指標計算
│   └── market_analysis.py       # 市場分析
├── backtest_module/      # 回測模組（計劃中）
├── recommendation_module/# 推薦模組（計劃中）
├── scripts/             # 獨立腳本
│   ├── update_all_data.py      # 數據更新腳本
│   ├── fix_market_index.py     # 市場指數修復腳本
│   ├── fix_industry_index.py   # 產業指數修復腳本
│   └── merge_daily_data.py     # 數據合併腳本
├── tests/              # 測試文件（開發中）
├── docs/              # 文檔
└── data/              # 數據存儲
    ├── market_index/   # 市場指數數據
    ├── industry_index/ # 產業指數數據
    ├── daily_price/    # 每日價格數據
    └── backup/         # 數據備份

開發進度：
1. 已完成功能：
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
     * 配置管理系統
     * 數據備份機制
     * 錯誤處理系統

2. 開發中功能：
   - 數據處理
     * 技術指標計算
     * 數據整合和優化
     * 數據質量檢查
   - 分析功能
     * 移動平均線分析
     * RSI 指標計算
     * 布林通道分析
     * 市場趨勢分析

3. 計劃中功能：
   - 回測系統
     * 策略回測
     * 績效評估
     * 風險分析
   - 推薦系統
     * 基於技術指標的交易信號
     * 客製化推薦策略

安裝說明：
1. 克隆代碼庫：
   git clone [repository_url]

2. 安裝依賴：
   pip install -r requirements.txt

快速開始：
from data_module.data_loader import DataLoader
from data_module.config import Config

# 初始化配置
config = Config()

# 初始化數據加載器
loader = DataLoader(config)

# 加載數據
market_data = loader.load_market_index()
industry_data = loader.load_industry_index()

# 更新數據
loader.update_daily_data()

配置說明：
系統配置位於 system_config.py，主要包含：
- 數據源配置（API端點、請求參數）
- 文件路徑設置（數據存儲、備份位置）
- 系統參數配置（超時設置、重試次數）
- 日誌配置

數據備份：
系統自動在以下情況創建備份：
1. 數據更新前
2. 重要處理操作前
3. 定期備份（每日）
4. 錯誤發生時

開發指南：
1. 代碼風格遵循 PEP 8
2. 所有新功能需要添加單元測試
3. 提交前確保通過所有測試
4. 更新文檔以反映代碼變更
5. 使用類型提示（Type Hints）
6. 添加詳細的函數文檔字符串

注意事項：
1. 首次運行前確保配置正確
2. 定期檢查日誌文件
3. 重要操作前備份數據
4. 遵循最佳實踐指南
5. 注意API請求頻率限制
6. 定期檢查數據完整性

版本歷史：
v1.1.0 (2024-03-23)
- 改進API請求機制
- 優化錯誤處理
- 完善數據驗證
- 更新文檔

v1.0.0 (2024-03-20)
- 完善數據備份機制
- 添加增量更新功能
- 改進數據驗證邏輯
- 優化錯誤處理和日誌記錄

貢獻指南：
1. Fork 代碼庫
2. 創建功能分支
3. 提交變更
4. 發起 Pull Request

授權：
本項目採用 MIT 授權協議
