# 台股數據收集架構文檔

## 相關文檔
- [系統架構文檔](system_architecture.md) - 系統架構和模組說明
- [技術分析優化文檔](technical_analysis_optimizations.md) - 技術分析模塊優化說明
- [腳本目錄說明](scripts_readme.md) - 腳本使用說明
- [開發進度記錄](note.txt) - 當前開發進度和更新說明
- [測試說明文檔](readme_test.txt) - 測試相關說明
- **[每日數據更新指南](daily_data_update_guide.md)** ⭐ - 每日股票數據更新完整指南（**推薦閱讀**）
- **[數據獲取邏輯說明](../DATA_FETCHING_LOGIC.md)** - 股票數據獲取邏輯詳細說明（**重要：包含使用方式和錯誤排查指南**）
- **[HOW_TO_UPDATE_DAILY_DATA.md](../HOW_TO_UPDATE_DAILY_DATA.md)** - 快速更新指南
- [故障排除指南](../docs/TROUBLESHOOTING_DAILY_UPDATE.md) - 每日股票更新故障排除指南

## 概述
本文檔描述台股技術分析系統的數據收集架構，包括數據來源、更新流程、配置說明和錯誤處理機制。數據收集是系統的基礎，確保了分析和回測功能的可靠性。系統目前已實現完整的數據收集、處理和備份功能，並支持增量更新、自動修復和數據質量監控。

## 數據來源

### 1. 市場指數數據 (TAIEX)
- **API來源**: 台灣證券交易所 FMTQIK API
- **API路徑**: https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK
- **更新頻率**: 每個交易日收盤後更新
- **資料格式**: JSON
- **存儲位置**: `D:/Min/Python/Project/FA_Data/meta_data/market_index.csv`
- **主要欄位**: 日期、成交股數、成交金額、成交筆數、發行量加權股價指數、漲跌點數
- **數據驗證**: 自動檢查數據完整性和一致性
- **數據質量**: 自動監控數據質量指標（新增）
- **異常檢測**: 自動檢測異常數據（新增）

### 2. 產業指數數據
- **API來源**: 台灣證券交易所 BFIAMU API
- **API路徑**: https://www.twse.com.tw/rwd/zh/afterTrading/BFIAMU
- **更新頻率**: 每個交易日收盤後更新
- **資料格式**: JSON
- **存儲位置**: `D:/Min/Python/Project/FA_Data/meta_data/industry_index.csv`
- **主要欄位**: 日期、指數名稱、開盤指數、最高指數、最低指數、收盤指數、漲跌點數、漲跌百分比
- **數據驗證**: 自動檢查數據完整性和一致性
- **數據質量**: 自動監控數據質量指標（新增）
- **異常檢測**: 自動檢測異常數據（新增）

### 3. 個股日成交資料
- **API來源**: 台灣證券交易所 MI_INDEX API (使用 `type=ALL`)
- **API路徑**: https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
- **更新頻率**: 每個交易日收盤後更新
- **資料格式**: JSON
- **存儲位置**: `D:/Min/Python/Project/FA_Data/daily_price/YYYYMMDD.csv`（文件名格式：`20250829.csv`）
- **主要欄位**: 證券代號、證券名稱、開盤價、最高價、最低價、收盤價、成交股數、成交金額、漲跌(+/-)、漲跌價差
- **數據驗證**: 自動檢查數據完整性和一致性
- **數據質量**: 自動監控數據質量指標（新增）
- **異常檢測**: 自動檢測異常數據（新增）
- **更新方式**:
  - **批量更新（推薦）**: `python scripts/batch_update_daily_data.py --start-date YYYY-MM-DD`
  - **單日更新**: `python scripts/update_daily_stock_data.py --date YYYY-MM-DD`
- **重要說明**: 
  - 詳細的數據獲取邏輯、使用方式和錯誤排查請參考 [DATA_FETCHING_LOGIC.md](../DATA_FETCHING_LOGIC.md)
  - 每日數據更新完整指南請參考 [HOW_TO_UPDATE_DAILY_DATA.md](../HOW_TO_UPDATE_DAILY_DATA.md) ⭐

### 4. 技術指標數據
- **數據來源**: 系統計算生成
- **更新頻率**: 每個交易日收盤後更新
- **資料格式**: CSV
- **存儲位置**: `D:/Min/Python/Project/FA_Data/technical_analysis/`
- **主要指標**: 
  * 移動平均線 (MA)
  * 相對強弱指標 (RSI)
  * 布林通道 (Bollinger Bands)
  * MACD指標
  * KDJ指標
  * 成交量指標
  * 動量指標
  * 自定義指標
  * 組合指標

### 5. 機器學習模型數據
- **數據來源**: 系統訓練生成
- **更新頻率**: 每週更新
- **資料格式**: PKL/H5
- **存儲位置**: `D:/Min/Python/Project/FA_Data/ml_models/`
- **主要模型**:
  * 預測模型
  * 分類模型
  * 聚類模型
  * 異常檢測模型

## 數據結構設計

### 1. 目錄結構
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

### 2. 數據模型
- **市場指數模型**:
  - 日期 (Date): 交易日期 (YYYY-MM-DD)
  - 收盤價 (Close): 當日收盤指數
  - 開盤價 (Open): 當日開盤指數
  - 最高價 (High): 當日最高指數
  - 最低價 (Low): 當日最低指數
  - 成交量 (Volume): 當日成交量
  - 成交金額 (Amount): 當日成交金額
  - 漲跌點數 (Change): 當日漲跌點數
  - 漲跌百分比 (ChangePercent): 當日漲跌百分比
  - 數據質量分數 (QualityScore): 數據質量評分（新增）
  - 異常標記 (AnomalyFlag): 異常數據標記（新增）

- **產業指數模型**:
  - 日期 (Date): 交易日期 (YYYY-MM-DD)
  - 指數名稱 (IndexName): 產業指數名稱
  - 開盤指數 (Open): 開盤指數
  - 最高指數 (High): 最高指數
  - 最低指數 (Low): 最低指數
  - 收盤指數 (Close): 收盤指數
  - 漲跌點數 (Change): 漲跌點數
  - 漲跌百分比 (ChangePercent): 漲跌百分比
  - 成交量 (Volume): 當日成交量
  - 成交金額 (Amount): 當日成交金額
  - 數據質量分數 (QualityScore): 數據質量評分（新增）
  - 異常標記 (AnomalyFlag): 異常數據標記（新增）

- **個股日成交模型**:
  - 股票代號 (StockID): 股票代號
  - 股票名稱 (StockName): 股票名稱
  - 日期 (Date): 交易日期 (YYYY-MM-DD)
  - 開盤價 (Open): 開盤價
  - 最高價 (High): 最高價
  - 最低價 (Low): 最低價
  - 收盤價 (Close): 收盤價
  - 成交量 (Volume): 成交量
  - 成交金額 (Amount): 成交金額
  - 漲跌 (ChangeType): 漲/跌/平
  - 漲跌點數 (Change): 漲跌點數
  - 漲跌百分比 (ChangePercent): 漲跌百分比
  - 振幅 (Amplitude): 當日振幅
  - 週轉率 (TurnoverRate): 當日週轉率
  - 數據質量分數 (QualityScore): 數據質量評分（新增）
  - 異常標記 (AnomalyFlag): 異常數據標記（新增）

- **技術指標模型**（新增）:
  - 股票代號 (StockID): 股票代號
  - 日期 (Date): 交易日期
  - 指標名稱 (IndicatorName): 技術指標名稱
  - 指標值 (Value): 指標計算值
  - 參數設置 (Parameters): 計算參數
  - 版本號 (Version): 計算版本
  - 更新時間 (UpdateTime): 最後更新時間

- **機器學習模型**（新增）:
  - 模型ID (ModelID): 模型唯一標識
  - 模型類型 (ModelType): 模型類型
  - 模型版本 (Version): 模型版本
  - 訓練數據範圍 (TrainRange): 訓練數據時間範圍
  - 模型參數 (Parameters): 模型參數
  - 性能指標 (Metrics): 模型性能指標
  - 創建時間 (CreateTime): 創建時間
  - 更新時間 (UpdateTime): 最後更新時間

## 數據更新流程

### 1. 更新流程概述

#### 個股日成交資料更新（推薦方式）

**批量更新（推薦）**：
```bash
# 更新從指定日期之後到今天的所有交易日
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 更新後合併數據
python scripts/merge_daily_data.py
```

**單日更新**：
```bash
# 更新單日數據
python scripts/update_daily_stock_data.py --date 2025-08-29

# 更新後合併數據
python scripts/merge_daily_data.py
```

**詳細說明**：請參考 [HOW_TO_UPDATE_DAILY_DATA.md](../HOW_TO_UPDATE_DAILY_DATA.md)

#### 完整數據更新流程
1. 檢查需要更新的日期範圍
2. 對於每個日期：
   a. 更新市場指數
   b. 更新產業指數
   c. 更新個股日成交資料（使用主模組，包含 delay time）
   d. 計算技術指標
   e. 更新機器學習模型（新增）
3. 檢查數據完整性
4. 執行數據合併（如需要）
5. 生成更新報告
6. 執行數據質量檢查（新增）
7. 執行異常檢測（新增）

### 2. 增量更新機制
- 檢查已有數據的最新日期
- 只更新缺失的日期數據
- 避免重複請求和處理
- 智能日期範圍選擇
- 自動跳過非交易日
- 智能重試策略（新增）
- 並行處理優化（新增）

### 3. 錯誤處理和重試機制
- 網絡錯誤自動重試（最多5次）
- 請求間隔延遲（批量更新：4秒，單日更新：1.5-2.5秒）
- 使用 Session 和 cookie 處理（避免 307 重定向）
- 404錯誤（當日無數據）處理
- 超時和連接錯誤處理
- 數據驗證和修復
- 自動錯誤通知
- 請求限流控制（新增）
- 代理切換機制（新增）
- 錯誤恢復策略（新增）
- **批量更新自動跳過已存在的文件**（新增）

### 4. 數據備份策略
- 每次更新前自動備份現有數據
- 備份文件命名格式：`original_filename_YYYYMMDD_HHMMSS.csv`
- 更新失敗時自動恢復備份
- 定期清理舊備份
- 備份完整性檢查
- 增量備份支持（新增）
- 異地備份支持（新增）
- 備份加密（新增）

## 數據檢查和修復

### 1. 數據檢查功能
- 檢查數據文件是否存在
- 檢查數據格式是否正確
- 檢查數據日期排序是否一致
- 檢查數據是否有缺失值
- 檢查數據異常值
- 檢查數據一致性
- 生成檢查報告
- 數據質量評分（新增）
- 異常數據檢測（新增）
- 數據完整性驗證（新增）

### 2. 數據修復功能
- 修復日期排序問題
- 修復數據格式不一致問題
- 修復數據缺失問題（如可能）
- 從備份恢復錯誤數據
- 自動數據補全
- 異常值處理
- 生成修復報告
- 智能數據修復（新增）
- 數據平滑處理（新增）
- 數據標準化（新增）

### 3. 數據合併功能
- 合併每日數據到整合性文件
- 檢查和處理重複記錄
- 優化數據存儲格式
- 生成統計摘要
- 數據壓縮和優化
- 索引優化
- 生成合併報告
- 增量合併支持（新增）
- 並行合併處理（新增）
- 合併衝突解決（新增）

## 配置說明

### 1. TWStockConfig 類
```python
class TWStockConfig:
    """台股數據配置類"""
    def __init__(self, base_dir=None):
        # 基礎目錄設置
        self.base_dir = base_dir or Path.cwd()
        
        # 數據目錄設置
        self.data_dir = self.base_dir / "data"
        self.market_index_dir = self.data_dir / "market_index"
        self.industry_index_dir = self.data_dir / "industry_index"
        self.daily_price_dir = self.data_dir / "daily_price"
        self.meta_data_dir = self.data_dir / "metadata"
        self.backup_dir = self.data_dir / "backup"
        self.log_dir = self.data_dir / "logs"
        self.technical_indicators_dir = self.data_dir / "technical_indicators"
        self.ml_models_dir = self.data_dir / "ml_models"  # 新增
        
        # 確保目錄存在
        self._ensure_directories()
        
        # 文件路徑設置
        self.market_index_file = self.market_index_dir / "market_index.csv"
        self.industry_index_file = self.industry_index_dir / "industry_index.csv"
        self.stock_data_file = self.meta_data_dir / "stock_data.csv"
        self.all_stocks_data_file = self.data_dir / "all_stocks_data.csv"
        
        # API請求配置
        self.max_retries = 5
        self.retry_delay = 2
        self.request_timeout = 30
        self.backup_retention_days = 30
        self.request_rate_limit = 3  # 新增：每秒請求數限制
        self.proxy_list = []  # 新增：代理服務器列表
        
        # 數據處理配置
        self.batch_size = 100
        self.max_workers = 4
        self.chunk_size = 1000
        self.parallel_processing = True  # 新增：並行處理開關
        self.data_compression = True  # 新增：數據壓縮開關
        
        # 數據質量配置（新增）
        self.quality_threshold = 0.95  # 數據質量閾值
        self.anomaly_detection = True  # 異常檢測開關
        self.data_validation = True  # 數據驗證開關
        
        # 通知配置
        self.enable_email_notification = False
        self.email_recipients = []
        self.enable_slack_notification = False  # 新增：Slack通知
        self.slack_webhook_url = ""  # 新增：Slack Webhook URL
        
        # 日誌配置
        self.log_level = "INFO"
        self.log_rotation = "1 day"
        self.log_retention = "30 days"
        self.enable_performance_logging = True  # 新增：性能日誌
        self.enable_audit_logging = True  # 新增：審計日誌
```

### 2. 命令行參數
```
--days N        : 更新最近N天的數據
--start DATE    : 更新開始日期 (YYYY-MM-DD)
--end DATE      : 更新結束日期 (YYYY-MM-DD)
--all           : 更新全部數據（從2014年起）
--check         : 只檢查數據狀態，不更新
--repair        : 修復數據問題
--backup        : 創建數據備份
--notify        : 啟用郵件通知
--workers N     : 設置並行處理的工作進程數
--batch N       : 設置批處理大小
--quality       : 執行數據質量檢查（新增）
--anomaly       : 執行異常檢測（新增）
--compress      : 啟用數據壓縮（新增）
--proxy         : 使用代理服務器（新增）
--slack         : 啟用Slack通知（新增）
--audit         : 啟用審計日誌（新增）
```

## 使用示例

### 1. 更新最近30天數據
```python
from scripts.update_all_data import main

# 執行更新
main(["--days", "30", "--notify", "--quality", "--anomaly"])
```

### 2. 檢查數據狀態
```python
from scripts.update_all_data import check_data_status

# 檢查數據
check_data_status(repair=True, notify=True, quality=True, anomaly=True)
```

### 3. 手動更新特定日期
```python
from data_module.data_loader import DataLoader
from data_module.config import TWStockConfig

# 初始化
config = TWStockConfig()
loader = DataLoader(config)

# 更新數據
loader.update_market_index("2023-03-01")
loader.update_industry_index("2023-03-01")
loader.update_daily_data("2023-03-01")
loader.update_technical_indicators("2023-03-01")  # 新增
loader.update_ml_models()  # 新增
```

### 4. 數據質量檢查（新增）
```python
from data_module.data_validator import DataValidator

# 初始化驗證器
validator = DataValidator(config)

# 執行數據質量檢查
quality_report = validator.check_data_quality()
anomaly_report = validator.detect_anomalies()
```

### 5. 數據修復（新增）
```python
from data_module.data_repair import DataRepair

# 初始化修復器
repairer = DataRepair(config)

# 執行數據修復
repair_report = repairer.repair_data()
```

### 6. 模型更新（新增）
```python
from data_module.model_manager import ModelManager

# 初始化模型管理器
manager = ModelManager(config)

# 更新模型
manager.update_models()
manager.evaluate_models()
```

## 錯誤處理

### 1. 常見錯誤及解決方案
- **連接錯誤**: 網絡不穩定，使用重試機制並增加延遲
- **超時錯誤**: 請求超時，增加超時時間並重試
- **數據格式錯誤**: API返回格式變更，需更新解析邏輯
- **數據缺失**: 該日期無交易或數據尚未發布，略過該日期
- **請求頻率限制**: 添加隨機延遲，避免頻繁請求
- **數據不一致**: 自動檢測和修復數據不一致問題
- **磁盤空間不足**: 自動清理舊備份和日誌文件

### 2. 日誌記錄
所有錯誤和警告都記錄在 `data/logs/` 目錄下的日誌文件中，包括：
- `data_loader.log`: 數據加載器日誌
- `update_all_data.log`: 更新腳本日誌
- `data_checker.log`: 數據檢查日誌
- `data_repair.log`: 數據修復日誌
- `error_notification.log`: 錯誤通知日誌

## 最佳實踐

1. 定期執行更新（建議每個交易日收盤後執行）
2. 監控日誌文件，及時發現和解決問題
3. 定期檢查數據狀態，確保數據完整性
4. 適當設置重試參數，避免過於頻繁的請求
5. 定期清理舊備份，節省磁盤空間
6. 啟用郵件通知，及時獲取錯誤信息
7. 定期驗證數據質量
8. 使用並行處理提高效率
9. 保持配置文件的版本控制
10. 定期更新API接口適配

## 開發計劃

### 1. 短期計劃
- 改進日期範圍選擇的靈活性
- 添加電子郵件通知功能
- 優化數據合併邏輯
- 改進並行處理效率
- 優化內存使用
- 添加更多數據驗證規則

### 2. 長期計劃
- 添加更多數據來源（財報數據、籌碼數據等）
- 實現分佈式數據收集
- 添加實時數據更新功能
- 實現數據分析預警
- 開發Web管理界面
- 支持更多數據格式
- 實現自動化測試
- 添加數據可視化功能 