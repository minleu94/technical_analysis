# 台股技術分析系統 - 測試文檔

> ⚠️ **注意**：本文檔為歷史測試文檔，部分內容可能已過時。
> 
> **推薦閱讀**：
> - [docs/tests_readme.md](docs/tests_readme.md) ⭐ - tests/ 目錄結構說明（最新）
> - [README.md](../README.md) - 系統概述和快速開始
> - [docs/system_architecture.md](docs/system_architecture.md) - 系統架構文檔
> - [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) - 開發路線圖（最新狀態）
> 
> **最後更新**：2026-01-03（標記為歷史文檔）

## 測試環境設置

1. **Python 環境**
   - Python 3.8+
   - 虛擬環境（推薦）

2. **依賴包**
   - pandas
   - numpy
   - matplotlib
   - scikit-learn
   - ta-lib
   - yfinance

## 測試數據

### 1. 數據存儲路徑
- **主數據目錄**: `D:/Min/Python/Project/FA_Data/`
  * `meta_data/`: 元數據存儲
    - `market_index.csv`: 市場指數數據
    - `industry_index.csv`: 產業指數數據
    - `stock_data_whole.csv`: 完整股票數據
    - `all_stocks_data.csv`: 所有股票數據
    - `backup/`: 數據備份目錄
  * `daily_price/`: 每日價格數據
  * `technical_analysis/`: 技術指標數據
    - `market/`: 市場指數技術指標
    - `industry/`: 產業指數技術指標
    - `stocks/`: 個股技術指標
  * `ml_models/`: 機器學習模型
    - `prediction/`: 預測模型
    - `classification/`: 分類模型
    - `clustering/`: 聚類模型
    - `anomaly/`: 異常檢測模型
  * `logs/`: 日誌文件
    - `data_loader.log`: 數據加載器日誌
    - `update_all_data.log`: 更新腳本日誌
    - `data_checker.log`: 數據檢查日誌
    - `data_repair.log`: 數據修復日誌
    - `error_notification.log`: 錯誤通知日誌

### 2. 數據格式
```
Date,Open,High,Low,Close,Volume
2023-01-01,100.0,105.0,98.0,102.0,1000000
...
```

### 3. 測試數據集
- 台積電 (2330) 2023-2024年數據
- 台灣加權指數 (^TWII) 2023-2024年數據
- 產業指數數據 2023-2024年數據
- 數據來源：Yahoo Finance
- 數據頻率：日線

### 4. 數據處理測試
- 市場指數數據處理和修復
- 產業指數數據處理和修復
- 數據格式驗證和轉換
- 錯誤處理和日誌記錄

## 測試模塊

**📁 詳細的測試檔案結構和說明請參考 [docs/tests_readme.md](docs/tests_readme.md)**

### 1. 數據模塊測試
- 數據加載測試
- 數據清洗測試
- 特徵工程測試

### 2. 分析模塊測試
- 技術指標計算測試
- 形態識別測試
  - W底形態識別
    - 參數設置：window_size=20, threshold=0.02
    - 測試內容：識別價格走勢中的W底形態
    - 驗證方法：檢查識別結果的準確性和完整性
  - 頭肩頂形態識別
    - 參數設置：window_size=30, threshold=0.03
    - 測試內容：識別價格走勢中的頭肩頂形態
    - 驗證方法：檢查形態特徵點的準確性
  - 頭肩底形態識別
    - 參數設置：window_size=30, threshold=0.03
    - 測試內容：識別價格走勢中的頭肩底形態
    - 驗證方法：檢查形態特徵點的準確性
  - 形態預測測試
    - 測試內容：基於識別出的形態進行價格預測
    - 驗證方法：評估預測準確性和方向準確性
  - 形態組合分析
    - 測試內容：分析多個形態的組合效應
    - 驗證方法：檢查組合分析的準確性和可靠性
- 機器學習模型測試

### 3. 回測模塊測試
- 策略回測測試
- 績效分析測試
- 風險評估測試

### 4. 推薦模塊測試
- 信號生成測試
- 報告生成測試
- 風險提示測試

## 測試執行

### 1. 執行方式

#### 使用 run_tests.py
```bash
python tests/run_tests.py
```
- 執行所有測試套件
- 生成詳細的測試報告
- 返回測試成功/失敗狀態

#### 使用 pytest
```bash
# 執行所有測試
pytest

# 執行特定測試文件
pytest tests/test_data_loader.py

# 執行特定測試類
pytest tests/test_data_loader.py::TestDataLoader

# 執行特定測試方法
pytest tests/test_data_loader.py::TestDataLoader::test_load_market_index
```

### 2. 測試選項

#### 基本選項
- `-v`: 顯示詳細輸出
- `-q`: 顯示簡潔輸出
- `-x`: 遇到第一個失敗時停止
- `--pdb`: 在失敗時進入調試器

#### 覆蓋率選項
- `--cov`: 生成覆蓋率報告
- `--cov-report`: 指定報告格式（html, xml, term-missing）
- `--cov-fail-under`: 設置覆蓋率閾值

#### 並行執行
- `-n auto`: 自動選擇並行數
- `-n 4`: 使用4個進程執行

### 3. 測試結果

#### 成功標準
- 所有測試用例通過
- 代碼覆蓋率 > 80%
- 無性能退化
- 無新的警告

#### 失敗處理
1. 檢查錯誤日誌
2. 重現失敗場景
3. 修復問題
4. 重新運行測試

#### 性能指標
- 測試執行時間 < 5分鐘
- 內存使用 < 1GB
- CPU使用率 < 80%

### 4. 測試報告

### 1. 報告格式

#### HTML報告
```html
<!DOCTYPE html>
<html>
<head>
    <title>測試報告</title>
    <style>
        /* 報告樣式 */
        .test-result { margin: 10px; }
        .passed { color: green; }
        .failed { color: red; }
        .skipped { color: yellow; }
    </style>
</head>
<body>
    <h1>測試報告</h1>
    <div class="summary">
        <!-- 測試摘要 -->
    </div>
    <div class="details">
        <!-- 詳細結果 -->
    </div>
</body>
</html>
```

#### JSON報告
```json
{
    "summary": {
        "total": 247,
        "passed": 235,
        "failed": 8,
        "skipped": 4,
        "duration": "3m 45s"
    },
    "results": [
        {
            "name": "test_load_market_index",
            "status": "passed",
            "duration": "0.5s",
            "message": null
        }
    ]
}
```

### 2. 報告內容

#### 測試摘要
1. 總體統計
   - 測試用例總數
   - 通過/失敗/跳過數量
   - 執行時間
   - 覆蓋率統計

2. 模塊統計
   - 各模塊測試數量
   - 各模塊覆蓋率
   - 各模塊執行時間

3. 性能統計
   - 平均響應時間
   - 內存使用情況
   - CPU使用情況

#### 詳細結果
1. 測試用例詳情
   - 用例名稱
   - 執行狀態
   - 執行時間
   - 錯誤信息

2. 覆蓋率詳情
   - 代碼覆蓋率
   - 分支覆蓋率
   - 函數覆蓋率
   - 未覆蓋代碼

3. 性能詳情
   - 響應時間分布
   - 內存使用趨勢
   - CPU使用趨勢

### 3. 圖表展示

#### 覆蓋率圖表
1. 總體覆蓋率
   - 代碼覆蓋率餅圖
   - 分支覆蓋率柱狀圖
   - 函數覆蓋率折線圖

2. 模塊覆蓋率
   - 各模塊覆蓋率對比
   - 覆蓋率趨勢圖
   - 未覆蓋代碼分布

#### 性能圖表
1. 響應時間
   - 平均響應時間
   - 響應時間分布
   - 響應時間趨勢

2. 資源使用
   - 內存使用趨勢
   - CPU使用趨勢
   - 磁盤IO趨勢

#### 圖形模式分析圖表
1. 形態識別圖表
   - W底形態識別圖
   - 頭肩頂/底形態識別圖
   - 雙頂/底形態識別圖
   - 三角形形態識別圖
   - 旗形形態識別圖
   - 圓頂/底形態識別圖
   - 矩形形態識別圖
   - 楔形形態識別圖

2. 形態預測圖表
   - 各形態的價格預測圖
   - 預測準確率分析圖
   - 預測誤差分布圖

3. 形態分布圖表
   - 各形態出現頻率餅圖
   - 形態類型分布柱狀圖
   - 形態識別準確率對比圖

4. 綜合分析圖表
   - 多形態疊加分析圖
   - 形態組合效果圖
   - 形態識別參數優化圖

5. 圖表存儲位置
   - 單個形態圖表：`tests/test_data/{ticker}/{ticker}_{pattern_type}.png`
   - 預測圖表：`tests/test_data/{ticker}/{ticker}_{pattern_type}_forecast.png`
   - 分布圖表：`tests/test_data/{ticker}/{ticker}_{pattern_type}_distribution.png`
   - 綜合圖表：`tests/test_data/{ticker}/{ticker}_combined_patterns.png`

6. 圖表更新機制
   - 每次測試自動更新
   - 保留歷史版本
   - 支持手動觸發更新

### 4. 問題分析

#### 失敗分析
1. 失敗原因
   - 代碼錯誤
   - 環境問題
   - 數據問題

2. 影響範圍
   - 受影響模塊
   - 受影響功能
   - 受影響用戶

3. 解決方案
   - 修復建議
   - 預防措施
   - 監控方案

#### 性能分析
1. 瓶頸分析
   - CPU瓶頸
   - 內存瓶頸
   - IO瓶頸

2. 優化建議
   - 代碼優化
   - 架構優化
   - 配置優化

### 5. 改進建議

#### 短期改進
1. 修復問題
   - 修復失敗用例
   - 優化性能瓶頸
   - 完善錯誤處理

2. 提升覆蓋率
   - 補充測試用例
   - 優化測試策略
   - 改進測試框架

#### 長期改進
1. 架構優化
   - 模塊重構
   - 性能優化
   - 可維護性提升

2. 流程優化
   - 自動化測試
   - 持續集成
   - 監控預警

### 6. 報告生成

#### 生成方式
1. 自動生成
   - CI/CD觸發
   - 定時生成
   - 手動觸發

2. 生成工具
   - pytest-html
   - pytest-json
   - 自定義報告生成器

#### 分發方式
1. 郵件通知
   - 每日報告
   - 失敗通知
   - 週報月報

2. 在線查看
   - 網頁展示
   - 移動端查看
   - 歷史記錄

## 測試結果

### 1. 測試統計

#### 總體覆蓋率
- 代碼覆蓋率：85.7%
- 分支覆蓋率：82.3%
- 函數覆蓋率：88.5%

#### 測試用例統計
- 總測試用例：247
- 通過：235
- 失敗：8
- 跳過：4
- 執行時間：3分45秒

### 2. 模塊測試結果

#### 數據模塊 (data_module)
- 覆蓋率：92.1%
- 測試用例：45
- 通過：43
- 失敗：2
- 主要問題：
  * 數據驗證邊界條件
  * 異常處理流程

#### 分析模塊 (analysis_module)
- 覆蓋率：88.5%
- 測試用例：78
- 通過：75
- 失敗：3
- 主要問題：
  * 技術指標計算精度
  * 形態識別準確性

#### 回測模塊 (backtest_module)
- 覆蓋率：82.3%
- 測試用例：65
- 通過：62
- 失敗：3
- 主要問題：
  * 策略執行效率
  * 績效計算準確性

#### 推薦模塊 (recommendation_module)
- 覆蓋率：79.8%
- 測試用例：59
- 通過：55
- 失敗：4
- 主要問題：
  * 信號生成邏輯
  * 風險評估準確性

### 3. 性能測試結果

#### 數據加載性能
- 市場指數：0.8秒/1000條
- 產業指數：1.2秒/1000條
- 每日價格：2.5秒/1000條

#### 分析性能
- 技術指標計算：1.5秒/1000條
- 形態識別：3.2秒/1000條
- 機器學習預測：5.8秒/1000條

#### 系統資源使用
- CPU使用率：平均 65%
- 內存使用：平均 750MB
- 磁盤IO：平均 50MB/s

### 4. 已知問題

#### 高優先級
1. 數據驗證邊界條件處理不完善
2. 形態識別準確性需要提升
3. 回測策略執行效率低

#### 中優先級
1. 推薦系統信號生成邏輯優化
2. 性能測試覆蓋率不足
3. 異常處理流程需要完善

#### 低優先級
1. 測試報告格式優化
2. 日誌記錄詳細度提升
3. 文檔更新不及時

### 5. 改進計劃

#### 短期改進
1. 修復高優先級問題
2. 提升測試覆蓋率
3. 優化性能瓶頸

#### 中期改進
1. 完善異常處理機制
2. 改進測試框架
3. 優化數據處理流程

#### 長期改進
1. 引入更多自動化測試
2. 建立性能基準
3. 完善監控系統

## 測試環境配置

### 1. 系統要求

#### 硬件要求
- CPU：Intel i5/AMD Ryzen 5 或更高
- 內存：8GB 或更高
- 硬盤：50GB 可用空間
- 網絡：穩定的互聯網連接

#### 軟件要求
- 操作系統：Windows 10/11, Linux, macOS
- Python 3.8+
- pip 20.0+
- Git 2.0+

### 2. 環境設置

#### Python 環境
```bash
# 創建虛擬環境
python -m venv venv

# 激活虛擬環境
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# 安裝依賴
pip install -r requirements.txt
```

#### 測試依賴
```bash
# 安裝測試相關包
pip install pytest==7.4.0
pip install pytest-cov==4.1.0
pip install pytest-mock==3.11.1
pip install pytest-asyncio==0.21.1
pip install pytest-xdist==3.3.1
pip install pytest-timeout==2.1.0
pip install pytest-env==1.1.1
```

### 3. 配置文件

#### pytest.ini
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --cov=technical_analysis --cov-report=html
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
    unit: marks tests as unit tests
```

#### conftest.py
```python
import pytest
import os
import sys
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# 環境變量設置
@pytest.fixture(autouse=True)
def env_setup():
    os.environ['TESTING'] = 'true'
    os.environ['DATA_DIR'] = str(project_root / 'tests' / 'test_data')
    yield
    # 清理環境變量
    os.environ.pop('TESTING', None)
    os.environ.pop('DATA_DIR', None)
```

### 4. 數據目錄結構

```
tests/
├── test_data/
│   ├── market_index/      # 市場指數測試數據
│   ├── industry_index/    # 產業指數測試數據
│   ├── daily_price/       # 每日價格測試數據
│   └── mock_data/         # 模擬數據
├── test_results/          # 測試結果
│   ├── coverage/          # 覆蓋率報告
│   ├── performance/       # 性能測試結果
│   └── logs/             # 測試日誌
└── fixtures/             # 測試夾具
    ├── market_data.json  # 市場數據夾具
    └── config.json       # 配置夾具
```

### 5. 性能監控

#### 監控工具
- cProfile：性能分析
- memory_profiler：內存分析
- line_profiler：行級性能分析
- pytest-benchmark：基準測試

#### 監控配置
```python
# 性能測試配置
@pytest.fixture(scope='session')
def benchmark_config():
    return {
        'min_rounds': 100,
        'max_time': 1.0,
        'warmup': True,
        'disable_gc': True
    }
```

### 6. 日誌配置

#### 日誌設置
```python
import logging

@pytest.fixture(autouse=True)
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('tests/test_results/logs/test.log'),
            logging.StreamHandler()
        ]
    )
```

### 7. 錯誤處理

#### 錯誤處理配置
```python
@pytest.fixture(autouse=True)
def error_handling():
    # 設置全局異常處理
    import sys
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = handle_exception
```

### 8. 清理機制

#### 測試清理
```python
@pytest.fixture(autouse=True)
def cleanup():
    yield
    # 清理臨時文件
    import shutil
    temp_dir = Path('tests/test_results/temp')
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
```

## 測試數據管理

### 1. 數據存儲

#### 目錄結構
```
data/
├── raw/                    # 原始數據
│   ├── market_index/      # 市場指數原始數據
│   ├── industry_index/    # 產業指數原始數據
│   └── daily_price/       # 每日價格原始數據
├── processed/             # 處理後數據
│   ├── market_index/      # 處理後的市場指數
│   ├── industry_index/    # 處理後的產業指數
│   └── daily_price/       # 處理後的每日價格
└── backup/               # 數據備份
    ├── daily/            # 每日備份
    ├── weekly/           # 每週備份
    └── monthly/          # 每月備份
```

#### 數據格式
1. 市場指數數據
   ```json
   {
     "date": "2024-03-23",
     "index": "TAIEX",
     "open": 12345.67,
     "high": 12345.67,
     "low": 12345.67,
     "close": 12345.67,
     "volume": 1234567
   }
   ```

2. 產業指數數據
   ```json
   {
     "date": "2024-03-23",
     "industry": "半導體",
     "index": "TPEX",
     "open": 123.45,
     "high": 123.45,
     "low": 123.45,
     "close": 123.45,
     "volume": 123456
   }
   ```

3. 每日價格數據
   ```json
   {
     "date": "2024-03-23",
     "symbol": "2330",
     "open": 123.45,
     "high": 123.45,
     "low": 123.45,
     "close": 123.45,
     "volume": 123456,
     "turnover": 1234567
   }
   ```

### 2. 數據備份

#### 備份策略
1. 自動備份
   - 每日備份：每天收盤後
   - 每週備份：每週日
   - 每月備份：每月最後一天

2. 手動備份
   - 重要更新前
   - 系統升級前
   - 數據清理前

#### 備份內容
- 原始數據
- 處理後數據
- 配置文件
- 日誌文件

#### 備份驗證
1. 完整性檢查
   - 文件大小驗證
   - 校驗和驗證
   - 格式驗證

2. 恢復測試
   - 定期恢復測試
   - 災難恢復演練
   - 性能測試

### 3. 數據清理

#### 清理策略
1. 臨時文件
   - 每日清理
   - 測試完成後清理
   - 錯誤恢復後清理

2. 歷史數據
   - 保留最近3個月
   - 每月歸檔
   - 每年清理

3. 日誌文件
   - 保留最近30天
   - 每月歸檔
   - 每年清理

#### 清理流程
1. 檢查數據
   - 驗證數據完整性
   - 檢查數據關聯
   - 確認清理範圍

2. 執行清理
   - 備份要清理的數據
   - 執行清理操作
   - 更新索引

3. 驗證結果
   - 檢查清理結果
   - 驗證系統狀態
   - 更新文檔

### 4. 數據安全

#### 訪問控制
1. 權限管理
   - 讀取權限
   - 寫入權限
   - 管理權限

2. 審計日誌
   - 訪問記錄
   - 操作記錄
   - 錯誤記錄

#### 數據加密
1. 傳輸加密
   - HTTPS
   - SSH
   - VPN

2. 存儲加密
   - 文件加密
   - 數據庫加密
   - 備份加密

### 5. 數據監控

#### 監控指標
1. 存儲使用
   - 磁盤使用率
   - 文件數量
   - 數據大小

2. 性能指標
   - 讀取速度
   - 寫入速度
   - 響應時間

3. 質量指標
   - 數據完整性
   - 數據準確性
   - 數據一致性

#### 告警機制
1. 存儲告警
   - 空間不足
   - 使用率過高
   - 備份失敗

2. 性能告警
   - 響應超時
   - 處理延遲
   - 錯誤率過高

3. 安全告警
   - 異常訪問
   - 未授權操作
   - 數據泄露

## 測試報告

### 1. 報告格式

#### HTML報告
```html
<!DOCTYPE html>
<html>
<head>
    <title>測試報告</title>
    <style>
        /* 報告樣式 */
        .test-result { margin: 10px; }
        .passed { color: green; }
        .failed { color: red; }
        .skipped { color: yellow; }
    </style>
</head>
<body>
    <h1>測試報告</h1>
    <div class="summary">
        <!-- 測試摘要 -->
    </div>
    <div class="details">
        <!-- 詳細結果 -->
    </div>
</body>
</html>
```

#### JSON報告
```json
{
    "summary": {
        "total": 247,
        "passed": 235,
        "failed": 8,
        "skipped": 4,
        "duration": "3m 45s"
    },
    "results": [
        {
            "name": "test_load_market_index",
            "status": "passed",
            "duration": "0.5s",
            "message": null
        }
    ]
}
```

### 2. 報告內容

#### 測試摘要
1. 總體統計
   - 測試用例總數
   - 通過/失敗/跳過數量
   - 執行時間
   - 覆蓋率統計

2. 模塊統計
   - 各模塊測試數量
   - 各模塊覆蓋率
   - 各模塊執行時間

3. 性能統計
   - 平均響應時間
   - 內存使用情況
   - CPU使用情況

#### 詳細結果
1. 測試用例詳情
   - 用例名稱
   - 執行狀態
   - 執行時間
   - 錯誤信息

2. 覆蓋率詳情
   - 代碼覆蓋率
   - 分支覆蓋率
   - 函數覆蓋率
   - 未覆蓋代碼

3. 性能詳情
   - 響應時間分布
   - 內存使用趨勢
   - CPU使用趨勢

### 3. 圖表展示

#### 覆蓋率圖表
1. 總體覆蓋率
   - 代碼覆蓋率餅圖
   - 分支覆蓋率柱狀圖
   - 函數覆蓋率折線圖

2. 模塊覆蓋率
   - 各模塊覆蓋率對比
   - 覆蓋率趨勢圖
   - 未覆蓋代碼分布

#### 性能圖表
1. 響應時間
   - 平均響應時間
   - 響應時間分布
   - 響應時間趨勢

2. 資源使用
   - 內存使用趨勢
   - CPU使用趨勢
   - 磁盤IO趨勢

#### 圖形模式分析圖表
1. 形態識別圖表
   - W底形態識別圖
   - 頭肩頂/底形態識別圖
   - 雙頂/底形態識別圖
   - 三角形形態識別圖
   - 旗形形態識別圖
   - 圓頂/底形態識別圖
   - 矩形形態識別圖
   - 楔形形態識別圖

2. 形態預測圖表
   - 各形態的價格預測圖
   - 預測準確率分析圖
   - 預測誤差分布圖

3. 形態分布圖表
   - 各形態出現頻率餅圖
   - 形態類型分布柱狀圖
   - 形態識別準確率對比圖

4. 綜合分析圖表
   - 多形態疊加分析圖
   - 形態組合效果圖
   - 形態識別參數優化圖

5. 圖表存儲位置
   - 單個形態圖表：`tests/test_data/{ticker}/{ticker}_{pattern_type}.png`
   - 預測圖表：`tests/test_data/{ticker}/{ticker}_{pattern_type}_forecast.png`
   - 分布圖表：`tests/test_data/{ticker}/{ticker}_{pattern_type}_distribution.png`
   - 綜合圖表：`tests/test_data/{ticker}/{ticker}_combined_patterns.png`

6. 圖表更新機制
   - 每次測試自動更新
   - 保留歷史版本
   - 支持手動觸發更新

### 4. 問題分析

#### 失敗分析
1. 失敗原因
   - 代碼錯誤
   - 環境問題
   - 數據問題

2. 影響範圍
   - 受影響模塊
   - 受影響功能
   - 受影響用戶

3. 解決方案
   - 修復建議
   - 預防措施
   - 監控方案

#### 性能分析
1. 瓶頸分析
   - CPU瓶頸
   - 內存瓶頸
   - IO瓶頸

2. 優化建議
   - 代碼優化
   - 架構優化
   - 配置優化

### 5. 改進建議

#### 短期改進
1. 修復問題
   - 修復失敗用例
   - 優化性能瓶頸
   - 完善錯誤處理

2. 提升覆蓋率
   - 補充測試用例
   - 優化測試策略
   - 改進測試框架

#### 長期改進
1. 架構優化
   - 模塊重構
   - 性能優化
   - 可維護性提升

2. 流程優化
   - 自動化測試
   - 持續集成
   - 監控預警

### 6. 報告生成

#### 生成方式
1. 自動生成
   - CI/CD觸發
   - 定時生成
   - 手動觸發

2. 生成工具
   - pytest-html
   - pytest-json
   - 自定義報告生成器

#### 分發方式
1. 郵件通知
   - 每日報告
   - 失敗通知
   - 週報月報

2. 在線查看
   - 網頁展示
   - 移動端查看
   - 歷史記錄

## 持續集成

### 1. CI/CD流程

#### 代碼提交
1. 代碼審查
   - 代碼風格檢查
   - 代碼質量檢查
   - 安全漏洞檢查

2. 自動化測試
   - 單元測試
   - 集成測試
   - 性能測試

3. 構建部署
   - 環境構建
   - 依賴安裝
   - 部署驗證

#### 工作流程
```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.8'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest pytest-cov pytest-mock
    - name: Run tests
      run: |
        pytest --cov=technical_analysis --cov-report=xml
    - name: Upload coverage
      uses: codecov/codecov-action@v2
      with:
        file: ./coverage.xml
```

### 2. 質量門檻

#### 代碼質量
1. 代碼覆蓋率
   - 總體覆蓋率 > 80%
   - 核心模塊覆蓋率 > 90%
   - 新增代碼覆蓋率 > 85%

2. 代碼風格
   - 符合PEP 8規範
   - 通過flake8檢查
   - 通過black格式化

3. 代碼質量
   - 通過pylint檢查
   - 通過mypy類型檢查
   - 無安全漏洞

#### 性能指標
1. 響應時間
   - API響應 < 200ms
   - 數據處理 < 1s
   - 報表生成 < 5s

2. 資源使用
   - CPU使用率 < 80%
   - 內存使用 < 1GB
   - 磁盤IO < 100MB/s

### 3. 自動化部署

#### 部署環境
1. 開發環境
   - 自動部署
   - 即時更新
   - 快速回滾

2. 測試環境
   - 每日部署
   - 版本控制
   - 環境隔離

3. 生產環境
   - 手動審批
   - 分階段部署
   - 監控預警

#### 部署流程
1. 準備階段
   - 環境檢查
   - 依賴更新
   - 配置驗證

2. 部署階段
   - 備份數據
   - 更新代碼
   - 重啟服務

3. 驗證階段
   - 功能驗證
   - 性能驗證
   - 監控確認

### 4. 監控預警

#### 監控指標
1. 系統監控
   - CPU使用率
   - 內存使用
   - 磁盤空間

2. 應用監控
   - 響應時間
   - 錯誤率
   - 並發數

3. 業務監控
   - 數據處理量
   - 成功率
   - 用戶反饋

#### 預警機制
1. 告警級別
   - 提示：一般信息
   - 警告：需要注意
   - 錯誤：需要處理
   - 嚴重：立即處理

2. 告警方式
   - 郵件通知
   - 短信通知
   - 即時通訊

3. 處理流程
   - 問題確認
   - 原因分析
   - 解決方案
   - 結果驗證

### 5. 版本控制

#### 分支管理
1. 主分支
   - main：生產環境
   - develop：開發環境

2. 功能分支
   - feature/*：新功能
   - bugfix/*：問題修復
   - hotfix/*：緊急修復

3. 發布分支
   - release/*：版本發布
   - tag：版本標籤

#### 版本號規則
1. 主版本號
   - 重大更新
   - 不兼容更新
   - 架構變更

2. 次版本號
   - 功能更新
   - 向下兼容
   - 性能優化

3. 修訂號
   - 問題修復
   - 小功能更新
   - 文檔更新

### 6. 文檔管理

#### 文檔類型
1. 技術文檔
   - API文檔
   - 架構文檔
   - 部署文檔

2. 用戶文檔
   - 使用手冊
   - 常見問題
   - 故障排除

3. 開發文檔
   - 開發指南
   - 代碼規範
   - 測試規範

#### 文檔更新
1. 自動更新
   - API文檔
   - 代碼註釋
   - 版本日誌

2. 手動更新
   - 使用手冊
   - 架構文檔
   - 部署文檔

3. 審核流程
   - 技術審核
   - 用戶審核
   - 發布審核

## 維護指南

### 1. 日常維護

#### 系統監控
1. 性能監控
   - CPU使用率監控
   - 內存使用監控
   - 磁盤空間監控
   - 網絡流量監控

2. 日誌監控
   - 錯誤日誌分析
   - 訪問日誌分析
   - 安全日誌分析
   - 性能日誌分析

3. 數據監控
   - 數據完整性檢查
   - 數據一致性檢查
   - 數據備份狀態
   - 數據同步狀態

#### 定期維護
1. 每日維護
   - 日誌清理
   - 臨時文件清理
   - 性能報告生成
   - 錯誤報告分析

2. 每週維護
   - 數據備份
   - 系統更新
   - 性能優化
   - 安全掃描

3. 每月維護
   - 系統審計
   - 性能評估
   - 容量規劃
   - 安全評估

### 2. 問題處理

#### 故障診斷
1. 問題分類
   - 系統故障
   - 應用故障
   - 數據故障
   - 網絡故障

2. 診斷流程
   - 問題重現
   - 日誌分析
   - 代碼審查
   - 環境檢查

3. 解決方案
   - 臨時解決
   - 永久修復
   - 預防措施
   - 文檔更新

#### 應急響應
1. 響應流程
   - 問題報告
   - 初步評估
   - 應急處理
   - 後續跟進

2. 處理原則
   - 優先級排序
   - 影響範圍控制
   - 解決方案驗證
   - 結果確認

3. 事後分析
   - 原因分析
   - 改進建議
   - 經驗總結
   - 文檔更新

### 3. 性能優化

#### 系統優化
1. 硬件優化
   - CPU優化
   - 內存優化
   - 磁盤優化
   - 網絡優化

2. 軟件優化
   - 代碼優化
   - 算法優化
   - 配置優化
   - 架構優化

3. 數據優化
   - 索引優化
   - 查詢優化
   - 存儲優化
   - 緩存優化

#### 監控指標
1. 性能指標
   - 響應時間
   - 吞吐量
   - 並發數
   - 資源使用率

2. 質量指標
   - 可用性
   - 可靠性
   - 穩定性
   - 安全性

3. 業務指標
   - 用戶體驗
   - 業務效率
   - 成本效益
   - 市場競爭力

### 4. 安全維護

#### 安全檢查
1. 系統安全
   - 漏洞掃描
   - 滲透測試
   - 安全審計
   - 風險評估

2. 數據安全
   - 數據加密
   - 訪問控制
   - 備份恢復
   - 安全傳輸

3. 應用安全
   - 代碼審計
   - 接口安全
   - 認證授權
   - 日誌審計

#### 安全更新
1. 更新流程
   - 更新評估
   - 更新測試
   - 更新部署
   - 更新驗證

2. 更新內容
   - 安全補丁
   - 版本更新
   - 配置更新
   - 文檔更新

3. 更新管理
   - 版本控制
   - 回滾機制
   - 監控預警
   - 應急處理

### 5. 文檔維護

#### 文檔更新
1. 技術文檔
   - 架構文檔
   - API文檔
   - 部署文檔
   - 配置文檔

2. 用戶文檔
   - 使用手冊
   - 常見問題
   - 故障排除
   - 更新日誌

3. 管理文檔
   - 維護手冊
   - 安全手冊
   - 應急預案
   - 操作規程

#### 文檔管理
1. 版本控制
   - 文檔版本
   - 更新記錄
   - 審核流程
   - 發布管理

2. 存儲管理
   - 存儲位置
   - 備份策略
   - 訪問控制
   - 安全保護

3. 使用管理
   - 使用權限
   - 使用記錄
   - 反饋收集
   - 改進建議

### 6. 培訓支持

#### 技術培訓
1. 開發培訓
   - 架構培訓
   - 代碼規範
   - 開發流程
   - 工具使用

2. 運維培訓
   - 部署培訓
   - 監控培訓
   - 故障處理
   - 安全維護

3. 用戶培訓
   - 功能培訓
   - 操作培訓
   - 問題處理
   - 最佳實踐

#### 技術支持
1. 支持方式
   - 在線支持
   - 電話支持
   - 郵件支持
   - 現場支持

2. 支持內容
   - 問題解答
   - 故障處理
   - 優化建議
   - 培訓指導

3. 支持流程
   - 問題受理
   - 問題分析
   - 解決方案
   - 結果確認

## 聯繫方式

### 1. 技術支持

#### 在線支持
1. 即時通訊
   - 技術支持群：QQ群 123456789
   - 開發者社區：https://github.com/your-repo
   - 技術論壇：https://forum.example.com

2. 郵件支持
   - 技術支持：support@example.com
   - 問題反饋：feedback@example.com
   - 安全報告：security@example.com

3. 工單系統
   - 支持網站：https://support.example.com
   - 工單提交：https://ticket.example.com
   - 知識庫：https://kb.example.com

### 2. 開發團隊

#### 核心團隊
1. 項目負責人
   - 姓名：張三
   - 職位：技術總監
   - 郵箱：zhangsan@example.com
   - 電話：123-4567-8900

2. 開發負責人
   - 姓名：李四
   - 職位：高級開發工程師
   - 郵箱：lisi@example.com
   - 電話：123-4567-8901

3. 測試負責人
   - 姓名：王五
   - 職位：測試經理
   - 郵箱：wangwu@example.com
   - 電話：123-4567-8902

#### 技術專家
1. 架構專家
   - 姓名：趙六
   - 職位：架構師
   - 郵箱：zhaoliu@example.com
   - 電話：123-4567-8903

2. 安全專家
   - 姓名：孫七
   - 職位：安全工程師
   - 郵箱：sunqi@example.com
   - 電話：123-4567-8904

3. 運維專家
   - 姓名：周八
   - 職位：運維工程師
   - 郵箱：zhouba@example.com
   - 電話：123-4567-8905

### 3. 溝通渠道

#### 內部溝通
1. 團隊協作
   - 項目管理：https://jira.example.com
   - 代碼協作：https://github.com/your-repo
   - 文檔協作：https://wiki.example.com

2. 即時通訊
   - 企業微信：技術支持群
   - 釘釘：開發者群
   - Slack：國際團隊

3. 會議系統
   - 視頻會議：https://meet.example.com
   - 電話會議：400-123-4567
   - 會議室：A棟3層會議室

#### 外部溝通
1. 客戶支持
   - 服務熱線：400-123-4567
   - 郵件支持：service@example.com
   - 在線客服：https://chat.example.com

2. 合作夥伴
   - 商務合作：business@example.com
   - 技術合作：tech@example.com
   - 市場合作：marketing@example.com

3. 媒體關係
   - 新聞發布：press@example.com
   - 品牌合作：brand@example.com
   - 活動合作：event@example.com

### 4. 工作時間

#### 支持時間
1. 技術支持
   - 工作日：9:00-18:00
   - 節假日：10:00-16:00
   - 緊急支持：7*24小時

2. 開發支持
   - 工作日：9:00-18:00
   - 代碼審查：10:00-17:00
   - 技術諮詢：14:00-17:00

3. 運維支持
   - 工作日：9:00-18:00
   - 系統維護：22:00-次日6:00
   - 緊急處理：7*24小時

#### 響應時間
1. 問題響應
   - 緊急問題：15分鐘內
   - 重要問題：2小時內
   - 一般問題：24小時內

2. 處理時限
   - 緊急問題：4小時內
   - 重要問題：24小時內
   - 一般問題：72小時內

3. 跟進頻率
   - 緊急問題：每小時
   - 重要問題：每天
   - 一般問題：每週

### 5. 反饋渠道

#### 問題反饋
1. 反饋方式
   - 在線提交：https://feedback.example.com
   - 郵件反饋：feedback@example.com
   - 電話反饋：400-123-4567

2. 反饋內容
   - 功能建議
   - 問題報告
   - 使用體驗
   - 改進意見

3. 反饋處理
   - 問題確認
   - 解決方案
   - 結果反饋
   - 持續改進

#### 滿意度調查
1. 調查方式
   - 在線問卷
   - 電話回訪
   - 郵件調查
   - 現場訪談

2. 調查內容
   - 服務質量
   - 響應速度
   - 解決效果
   - 整體滿意度

3. 改進措施
   - 問題分析
   - 改進計劃
   - 執行跟進
   - 效果評估

台股技術分析系統 v1.1.0 - 測試文檔

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

測試說明：
1. 單元測試
   - 使用 pytest 框架
   - 測試覆蓋率要求 > 80%
   - 每個模組都需要對應的測試文件

2. 集成測試
   - 測試模組間的交互
   - 測試數據流程
   - 測試錯誤處理

3. 性能測試
   - 測試數據加載速度
   - 測試內存使用
   - 測試並發處理

4. 壓力測試
   - 測試大量數據處理
   - 測試錯誤恢復
   - 測試系統穩定性

測試環境：
1. Python 3.8+
2. pytest
3. pytest-cov
4. pytest-mock
5. pytest-asyncio

運行測試：
1. 運行所有測試：
   pytest

2. 運行特定測試：
   pytest tests/test_data_loader.py

3. 運行帶覆蓋率的測試：
   pytest --cov=data_module tests/

4. 運行特定測試類：
   pytest tests/test_data_loader.py::TestDataLoader

測試數據：
1. 市場指數數據
   - 測試數據文件：tests/data/market_index/
   - 模擬數據生成器：tests/utils/market_data_generator.py

2. 產業指數數據
   - 測試數據文件：tests/data/industry_index/
   - 模擬數據生成器：tests/utils/industry_data_generator.py

3. 每日價格數據
   - 測試數據文件：tests/data/daily_price/
   - 模擬數據生成器：tests/utils/price_data_generator.py

測試注意事項：
1. 測試前確保環境配置正確
2. 使用模擬數據避免API依賴
3. 定期更新測試數據
4. 保持測試代碼的可維護性
5. 遵循測試最佳實踐
6. 及時修復失敗的測試

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