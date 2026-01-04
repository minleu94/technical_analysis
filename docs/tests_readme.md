# Tests 目錄結構說明

## 概述
本文檔專門說明 `tests/` 目錄的檔案結構和組織方式。本目錄包含系統的所有測試檔案，用於驗證系統功能的正確性和穩定性。測試檔案採用 pytest 框架，提供完整的單元測試、集成測試和性能測試覆蓋。

**📖 完整的測試指南、環境設置、執行方法等詳細說明請參考 [docs/readme_test.txt](docs/readme_test.txt)**

## 文檔分工說明

- **`docs/readme_test.txt`**：完整的測試指南，包含環境設置、執行方法、報告生成、持續集成等
- **`docs/tests_readme.md`**：本文檔，專門說明 tests/ 目錄的檔案結構和組織方式

## 相關文檔
- **[測試完整指南](readme_test.txt)** - 測試環境設置、執行方法、報告生成等完整說明 ⭐
- [系統架構文檔](system_architecture.md) - 系統架構和模組說明
- [腳本使用說明](scripts_readme.md) - 腳本使用說明
- [開發進度記錄](note.txt) - 當前開發進度和更新說明

## 測試檔案結構

```
tests/
├── 📁 測試配置檔案
│   ├── conftest.py                    # pytest 配置文件
│   ├── pytest.ini                     # pytest 配置
│   └── run_tests.py                   # 測試執行腳本
│
├── 📁 核心功能測試
│   ├── test_data_module.py            # 數據模組測試
│   ├── test_config.py                 # 配置測試
│   └── test_data_loader.py            # 數據加載測試
│
├── 📁 API 測試
│   └── test_twse_api.py               # 台灣證券交易所 API 測試
│
├── 📁 分析模組測試
│   ├── test_technical_analysis.py     # 技術分析測試
│   └── test_technical_analyzer.py     # 技術分析器測試
│
├── 📁 模式分析測試
│   ├── test_pattern_analyzer.py       # 模式分析器測試
│   ├── test_advanced_patterns.py      # 高級模式測試
│   ├── test_extended_patterns.py      # 擴展模式測試
│   ├── test_optimized_patterns.py     # 優化模式測試
│   ├── test_pattern_parameter_tuning.py # 參數調優測試
│   ├── test_signal_combiner.py        # 信號組合測試
│   └── test_math_analyzer.py          # 數學分析器測試
│
├── 📁 機器學習測試
│   └── test_ml_analyzer.py            # 機器學習分析器測試
│
├── 📁 回測測試
│   └── test_backtest_recommendation.py # 回測推薦測試
│
├── 📁 推薦系統測試
│   └── test_recommendation_report.py  # 推薦報告測試
│
├── 📁 數據測試
│   ├── test_daily_data.py             # 每日數據測試
│   ├── test_data_loading.py           # 數據加載測試
│   ├── check_signals_file.py          # 信號文件檢查
│   ├── check_processed_file.py        # 處理文件檢查
│   ├── check_saved_file.py            # 保存文件檢查
│   └── check_columns.py               # 列檢查
│
├── 📁 工具測試
│   └── test_utils.py                  # 工具函數測試
│
├── 📁 獨立測試檔案
│   ├── test_technical_calc.py         # 技術計算測試（從 scripts/ 移動）
│   ├── test_finmind_integration.py    # FinMind 整合測試（從根目錄移動）
│   └── test_market_index.py           # 市場指數測試（從根目錄移動）
│
├── 📁 端到端測試
│   └── test_data_path_isolation.py    # 數據路徑隔離測試
│
└── 📁 測試數據
    └── test_data/                     # 測試數據目錄
```

## 測試檔案詳細說明

### 📁 測試配置檔案

#### `conftest.py`
- **功能**：pytest 配置文件，定義測試夾具和共享設置
- **內容**：測試環境設置、數據夾具、配置管理

#### `pytest.ini`
- **功能**：pytest 運行配置
- **內容**：測試路徑、標記定義、覆蓋率設置

#### `run_tests.py`
- **功能**：測試執行腳本
- **內容**：自動化測試執行、報告生成

### 📁 核心功能測試

#### `test_data_module.py`
- **功能**：測試數據模組的核心功能
- **測試內容**：
  - 數據加載功能
  - 數據處理功能
  - 數據驗證功能
  - 錯誤處理機制

#### `test_config.py`
- **功能**：測試配置管理功能
- **測試內容**：
  - 配置初始化
  - 路徑設置
  - 參數驗證

#### `test_data_loader.py`
- **功能**：測試數據加載器
- **測試內容**：
  - 數據源連接
  - 數據格式轉換
  - 錯誤重試機制

### 📁 API 測試

#### `test_twse_api.py`
- **功能**：測試台灣證券交易所 API 整合
- **測試內容**：
  - API 請求功能
  - 數據格式驗證
  - 錯誤處理

### 📁 分析模組測試

#### `test_technical_analysis.py`
- **功能**：測試技術分析功能
- **測試內容**：
  - 技術指標計算
  - 數據驗證
  - 結果格式檢查

#### `test_technical_analyzer.py`
- **功能**：測試技術分析器
- **測試內容**：
  - 分析器初始化
  - 指標計算方法
  - 結果輸出格式

### 📁 模式分析測試

#### `test_pattern_analyzer.py`
- **功能**：測試模式分析器核心功能
- **測試內容**：
  - 模式識別算法
  - 參數設置
  - 結果驗證

#### `test_advanced_patterns.py`
- **功能**：測試高級圖形模式識別
- **測試內容**：
  - 複雜模式識別
  - 準確率評估
  - 性能測試

#### `test_extended_patterns.py`
- **功能**：測試擴展模式識別功能
- **測試內容**：
  - 新增模式類型
  - 組合模式分析
  - 邊界條件測試

#### `test_optimized_patterns.py`
- **功能**：測試優化後的模式識別
- **測試內容**：
  - 優化算法驗證
  - 性能提升測試
  - 準確率比較

#### `test_pattern_parameter_tuning.py`
- **功能**：測試模式參數調優
- **測試內容**：
  - 參數優化算法
  - 最佳參數搜索
  - 結果評估

#### `test_signal_combiner.py`
- **功能**：測試信號組合功能
- **測試內容**：
  - 信號組合邏輯
  - 權重計算
  - 結果驗證

#### `test_math_analyzer.py`
- **功能**：測試數學分析功能
- **測試內容**：
  - 統計計算
  - 數學模型
  - 預測算法

### 📁 機器學習測試

#### `test_ml_analyzer.py`
- **功能**：測試機器學習分析器
- **測試內容**：
  - 模型訓練
  - 預測功能
  - 模型評估

### 📁 回測測試

#### `test_backtest_recommendation.py`
- **功能**：測試回測和推薦功能
- **測試內容**：
  - 策略回測
  - 績效分析
  - 推薦生成

### 📁 推薦系統測試

#### `test_recommendation_report.py`
- **功能**：測試推薦報告生成
- **測試內容**：
  - 報告格式
  - 內容驗證
  - 編碼處理

### 📁 數據測試

#### `test_daily_data.py`
- **功能**：測試每日數據處理
- **測試內容**：
  - 數據格式
  - 數據完整性
  - 處理流程

#### `test_data_loading.py`
- **功能**：測試數據加載功能
- **測試內容**：
  - 加載速度
  - 錯誤處理
  - 數據驗證

#### `check_signals_file.py`
- **功能**：檢查信號文件
- **測試內容**：
  - 文件存在性
  - 格式正確性
  - 數據完整性

#### `check_processed_file.py`
- **功能**：檢查處理後的文件
- **測試內容**：
  - 處理結果
  - 格式驗證
  - 數據質量

#### `check_saved_file.py`
- **功能**：檢查保存的文件
- **測試內容**：
  - 保存功能
  - 文件完整性
  - 格式正確性

#### `check_columns.py`
- **功能**：檢查數據列
- **測試內容**：
  - 列名正確性
  - 數據類型
  - 缺失值處理

### 📁 工具測試

#### `test_utils.py`
- **功能**：測試工具函數
- **測試內容**：
  - 通用工具函數
  - 輔助方法
  - 格式轉換

### 📁 獨立測試檔案

#### `test_technical_calc.py`
- **功能**：測試技術指標計算（從 scripts/ 移動）
- **測試內容**：
  - 計算器功能
  - 指標準確性
  - 性能測試

#### `test_finmind_integration.py`
- **功能**：測試 FinMind API 整合（從根目錄移動）
- **測試內容**：
  - API 連接
  - 數據獲取
  - 錯誤處理

#### `test_market_index.py`
- **功能**：測試市場指數功能（從根目錄移動）
- **測試內容**：
  - 指數數據獲取
  - 數據格式
  - 更新機制

### 📁 端到端測試

#### `test_data_path_isolation.py`
- **功能**：測試數據路徑隔離功能
- **測試內容**：
  - 環境變量覆蓋測試
  - 命令行參數覆蓋測試
  - 乾運行模式測試
  - 原子寫入安全性測試
  - 生產路徑隔離測試
  - 配置檔案自動後綴測試
  - 端到端隔離測試
- **重要性**：確保測試環境不會意外寫入生產數據目錄

## 測試執行

### 執行所有測試
```bash
# 執行所有測試
pytest

# 執行特定目錄的測試
pytest tests/test_pattern_analysis/

# 執行特定測試文件
pytest tests/test_technical_calc.py
```

### 路徑覆寫測試 (Path Isolation)
- **預設行為**：系統預設會寫入 `D:/Min/Python/Project/FA_Data`
- **測試隔離**：測試時可指定隔離路徑避免影響生產數據
- **環境變量覆蓋**：
  ```bash
  export DATA_ROOT=./sandbox_data
  export OUTPUT_ROOT=./sandbox_out
  export PROFILE=test
  pytest
  ```
- **命令行覆蓋**：
  ```bash
  pytest --data-root=./sandbox_data --output-root=./sandbox_out
  ```
- **配置檔案**：使用 `--profile test` 可自動切換至 `./_test` 子資料夾
- **乾運行模式**：使用 `--dry-run` 模式不會實際寫入任何檔案
- **原子寫入**：所有檔案寫入都使用原子操作，確保數據安全

### 執行特定類型的測試
```bash
# 執行單元測試
pytest -m "unit"

# 執行集成測試
pytest -m "integration"

# 執行性能測試
pytest -m "performance"
```

### 生成測試報告
```bash
# 生成覆蓋率報告
pytest --cov=technical_analysis --cov-report=html

# 生成詳細報告
pytest --html=report.html --self-contained-html
```

## 測試數據管理

### 測試數據目錄
- **位置**：`tests/test_data/`
- **內容**：測試用的數據文件、模擬數據、預期結果
- **管理**：定期更新測試數據以反映最新的數據格式

### 測試環境設置
- **隔離性**：每個測試使用獨立的測試環境
- **清理機制**：測試完成後自動清理臨時文件
- **數據備份**：重要測試數據自動備份

## 測試覆蓋率

### 目標覆蓋率
- **總體覆蓋率**：> 80%
- **核心模組覆蓋率**：> 90%
- **新增代碼覆蓋率**：> 85%

### 覆蓋率報告
- **HTML 報告**：`htmlcov/index.html`
- **XML 報告**：`coverage.xml`
- **終端報告**：執行時顯示

## 注意事項

### 測試執行前
- 確保測試環境正確設置
- 檢查測試數據是否完整
- 確認依賴項已安裝

### 測試執行時
- 注意測試執行時間
- 監控內存使用情況
- 檢查錯誤日誌

### 測試執行後
- 檢查測試結果
- 分析失敗的測試
- 更新測試文檔

## 版本更新記錄

### v1.2.1 (2024-04-08)
- 移動測試檔案到 tests/ 目錄
- 重新組織測試檔案結構
- 更新測試文檔說明

### v1.2.0 (2024-04-02)
- 新增模式分析測試
- 改進測試覆蓋率
- 優化測試執行效率
