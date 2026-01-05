# Scripts 目錄說明

## 概述
本目錄包含系統中獨立的腳本，主要用於數據更新、修復、合併以及參數優化等任務。這些腳本在系統架構中扮演重要角色，確保數據的完整性和系統的穩定性。

## 相關文檔
- [系統架構文檔](../01_architecture/system_architecture.md) - 系統架構和模組說明
- [數據收集架構文檔](../01_architecture/data_collection_architecture.md) - 數據收集和處理說明
- [技術分析優化文檔](technical_analysis_optimizations.md) - 技術分析模塊優化說明
- [開發進度記錄](note.txt) - 當前開發進度和更新說明
- [測試說明文檔](readme_test.txt) - 測試相關說明

## 數據存儲路徑

所有腳本默認使用以下數據存儲路徑：

```
D:/Min/Python/Project/FA_Data/
├── meta_data/         # 元數據
│   ├── market_index.csv    # 市場指數數據
│   ├── industry_index.csv  # 產業指數數據
│   ├── stock_data_whole.csv # 股票整合數據
│   ├── all_stocks_data.csv  # 所有股票整合數據
│   └── backup/             # 數據備份
├── daily_price/       # 每日價格數據
├── technical_analysis/ # 技術分析數據
├── ml_models/         # 機器學習模型
└── logs/              # 日誌文件
```

### 配置方式

#### 1. 路徑隔離功能（推薦用於測試）
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

**乾運行模式**:
```bash
# 測試腳本邏輯而不實際寫入檔案
python scripts/update_all_data.py --dry-run
```

#### 2. 傳統配置方式（向後兼容）
可以通過以下方式修改存儲路徑：

1. 使用 `TWStockConfig` 類：
```python
from data_module.config import TWStockConfig
config = TWStockConfig()
config.base_dir = Path("your/custom/path")
```

2. 使用環境變數：
```bash
set TWSTOCK_DATA_DIR=your/custom/path
```

## 腳本列表

### 1. 數據更新腳本

#### `batch_update_daily_data.py` ⭐ **推薦**
- **功能**：批量更新多個交易日的每日股票數據（使用主模組）
- **特點**：
  - 使用主模組 `data_module/data_loader.py` 的 `download_from_api()` 方法
  - 自動更新多個交易日（排除週末）
  - 已包含 delay time（預設 4 秒，可調整）
  - 自動跳過已存在的文件
  - 顯示詳細進度和結果摘要
- **使用範例**：
  ```bash
  # 更新從指定日期之後到今天的所有交易日
  python scripts/batch_update_daily_data.py --start-date 2025-08-28
  
  # 更新指定日期範圍
  python scripts/batch_update_daily_data.py --start-date 2025-08-28 --end-date 2025-09-05
  
  # 自訂延遲時間（更安全，避免 API 限制）
  python scripts/batch_update_daily_data.py --start-date 2025-08-28 --delay-min 4 --delay-max 4
  ```
- **詳細說明**：請參考 [HOW_TO_UPDATE_DAILY_DATA.md](../03_data/HOW_TO_UPDATE_DAILY_DATA.md)

#### `update_daily_stock_data.py` ⭐
- **功能**：使用主模組更新單日股票數據
- **使用範例**：
  ```bash
  # 更新單日數據（只更新 daily_price）
  python scripts/update_daily_stock_data.py --date 2025-08-29
  
  # 更新並自動合併到 meta_data
  python scripts/update_daily_stock_data.py --date 2025-08-29 --merge
  ```
- **詳細說明**：請參考 [HOW_TO_UPDATE_DAILY_DATA.md](../03_data/HOW_TO_UPDATE_DAILY_DATA.md)

#### `update_all_data.py`
- **功能**：更新所有數據，包括市場指數、產業指數和每日價格數據
- **使用範例**：
  ```bash
  # 生產模式 - 更新最近30天的數據
  python scripts/update_all_data.py --days 30
  
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

#### `update_stock_data.py`
- **功能**：更新股票數據
- **使用範例**：
  ```bash
  # 生產模式
  python scripts/update_stock_data.py
  
  # 測試模式
  python scripts/update_stock_data.py --profile test --data-root ./test_data --output-root ./test_output --dry-run
  ```

### 2. 數據修復腳本

#### `fix_market_index.py`
- **功能**：修復市場指數數據中的問題
- **使用範例**：
  ```bash
  python scripts/fix_market_index.py --report --backup
  ```

#### `fix_industry_index.py`
- **功能**：修復產業指數數據中的問題
- **使用範例**：
  ```bash
  python scripts/fix_industry_index.py --report --backup
  ```

#### `merge_daily_data.py`
- **功能**：合併每日價格數據
- **使用範例**：
  ```bash
  python scripts/merge_daily_data.py --report --compress
  ```

### 3. 技術指標計算腳本

#### `calculate_technical_indicators.py`
- **功能**：計算所有股票的技術指標
- **使用範例**：
  ```bash
  python scripts/calculate_technical_indicators.py
  ```

#### `simple_technical_calc.py`
- **功能**：簡化版技術指標計算（重命名自 simple_indicator_calc.py）
- **使用範例**：
  ```bash
  python scripts/simple_technical_calc.py
  ```

#### `date_specific_indicator_calc.py`
- **功能**：特定日期指標計算
- **使用範例**：
  ```bash
  python scripts/date_specific_indicator_calc.py
  ```

### 4. 工具腳本

#### `market_date_range.py`
- **功能**：市場日期範圍管理
- **使用範例**：
  ```bash
  python scripts/market_date_range.py
  ```

## 腳本分類

### 📊 數據管理腳本
- `batch_update_daily_data.py` ⭐ - **批量更新每日股票數據（推薦）**
- `update_daily_stock_data.py` ⭐ - **更新單日股票數據（推薦）**
- `update_all_data.py` - 全面數據更新
- `update_stock_data.py` - 股票數據更新
- `merge_daily_data.py` - 數據合併

### 🔧 數據修復腳本
- `fix_market_index.py` - 市場指數修復
- `fix_industry_index.py` - 產業指數修復

### 📈 技術分析腳本
- `calculate_technical_indicators.py` - 完整技術指標計算
- `simple_technical_calc.py` - 簡化技術指標計算
- `date_specific_indicator_calc.py` - 特定日期指標計算

### 🛠️ 工具腳本
- `market_date_range.py` - 日期範圍管理

## 腳本執行順序建議

### 日常數據更新流程（推薦）

**方式 1：批量更新（推薦）**
1. **批量更新每日數據**：`batch_update_daily_data.py --start-date YYYY-MM-DD`
2. **合併數據**：`merge_daily_data.py`
3. **計算指標**：`calculate_technical_indicators.py`

**方式 2：單日更新**
1. **更新單日數據**：`update_daily_stock_data.py --date YYYY-MM-DD`
2. **合併數據**：`merge_daily_data.py`
3. **計算指標**：`calculate_technical_indicators.py`

**方式 3：全面更新（舊方式）**
1. **更新數據**：`update_all_data.py`
2. **檢查數據**：`fix_market_index.py` 和 `fix_industry_index.py`（如有問題）
3. **合併數據**：`merge_daily_data.py`
4. **計算指標**：`calculate_technical_indicators.py`

### 數據修復流程
1. **檢查問題**：運行修復腳本檢查數據問題
2. **修復數據**：執行相應的修復腳本
3. **驗證修復**：重新運行數據更新腳本驗證

## 注意事項

### 執行前準備
- 確保已正確設置環境變量和依賴項
- 建議在執行腳本前先備份數據，以防意外情況發生
- 確保數據目錄具有適當的讀寫權限

### 執行時注意
- 定期檢查日誌文件以監控系統運行狀況
- 注意內存使用，特別是在處理大量數據時
- 某些腳本可能需要較長時間執行，請耐心等待

### 錯誤處理
- 如果腳本執行失敗，檢查日誌文件了解詳細錯誤信息
- 某些腳本支持重試機制，可以多次執行
- 如遇到數據問題，使用相應的修復腳本

## 與其他文檔的關聯

- **每日數據更新詳細指南**：請參考 [HOW_TO_UPDATE_DAILY_DATA.md](../03_data/HOW_TO_UPDATE_DAILY_DATA.md) ⭐
- **數據獲取邏輯說明**：請參考 [DATA_FETCHING_LOGIC.md](../03_data/DATA_FETCHING_LOGIC.md)
- 詳細的系統架構和數據流程可參考 `../01_architecture/system_architecture.md`
- 數據收集和處理的詳細說明可參考 `../01_architecture/data_collection_architecture.md`
- 測試相關的說明可參考 `readme_test.txt`
- 技術分析模組的優化說明可參考 `technical_analysis_optimizations.md`

## 版本更新記錄

### v1.2.1 (2024-04-08)
- 重命名 `simple_indicator_calc.py` 為 `simple_technical_calc.py`
- 刪除重複的 `config.py` 檔案
- 更新腳本說明和分類

### v1.2.0 (2024-04-02)
- 新增 `date_specific_indicator_calc.py` 腳本
- 優化 `calculate_technical_indicators.py` 功能
- 改進錯誤處理和日誌記錄 