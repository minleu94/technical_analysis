# Merge 和大盤數據實現總結

## 1. Merge 流程

### Merge 目標位置
- **目標文件**: `D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv`
- **源文件**: `D:\Min\Python\Project\FA_Data\daily_price\*.csv` (每日股票數據)
- **執行腳本**: `scripts/merge_daily_data.py`

### Merge 流程說明
1. 讀取 `daily_price` 目錄中的所有 CSV 文件
2. 檢查 `stock_data_whole.csv` 的最新日期
3. 只合併新文件（日期大於最新日期的文件）
4. 添加日期欄位到每筆數據
5. 合併所有數據並去重
6. 保存到 `stock_data_whole.csv`

### 執行方式
```bash
# 執行 merge
python scripts/merge_daily_data.py
```

### 主模組中的 Merge 方法
- **位置**: `data_module/data_loader.py`
- **方法**: `merge_daily_data()`
- **功能**: 合併每日價格數據到整合文件

---

## 2. 大盤數據實現

### 實現位置
- **主模組**: `data_module/data_loader.py`
- **方法**: `update_market_index(date: str)`
- **API**: 台灣證券交易所 FMTQIK API
- **API 端點**: `https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK`

### 數據存儲位置
- **文件路徑**: `D:\Min\Python\Project\FA_Data\meta_data\market_index.csv`
- **配置方法**: `config.market_index_file`

### 實現邏輯
1. **檢查現有數據**: 檢查是否已有該日期的數據
2. **API 請求**: 使用 FMTQIK API 獲取大盤數據
3. **數據處理**:
   - 轉換日期格式（民國年 → 西元年）
   - 處理數值欄位（移除逗號）
   - 重新組織數據格式
4. **合併數據**: 與現有數據合併，去重並排序
5. **保存數據**: 保存到 `market_index.csv`

### 使用方式

#### 使用 UI 應用程式（推薦）
```bash
python ui_app/main.py
```
在 UI 中選擇「數據更新」標籤頁，選擇「大盤指數數據」，設定日期範圍，點擊「開始更新」。

#### 使用主模組
```python
from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader

config = TWStockConfig()
loader = DataLoader(config)

# 更新指定日期的大盤數據
success = loader.update_market_index("2025-08-29")
```

#### 使用批量更新腳本
```bash
python scripts/batch_update_market_and_industry_index.py --type market --start-date 2025-08-28
```

### API 參數
- **date**: 日期格式 `YYYYMMDD`（如 `20250829`）
- **response**: `json`

### 數據欄位
- 日期
- 收盤價（發行量加權股價指數）
- 開盤價（與收盤價相同，因為 API 只提供收盤價）
- 最高價（與收盤價相同）
- 最低價（與收盤價相同）
- 成交量（成交股數）

### 相關方法
- `load_market_index()`: 加載市場指數數據
- `save_market_index(df)`: 保存市場指數數據

---

## 3. 其他相關數據

### 產業指數
- **方法**: `update_industry_index(date: str)`
- **API**: MI_INDEX API (type=IND)
- **文件**: `D:\Min\Python\Project\FA_Data\meta_data\industry_index.csv`

### 個股數據
- **方法**: `download_from_api(date: str)` 或 `update_daily_data(date: str)`
- **API**: MI_INDEX API (type=ALL)
- **文件**: `D:\Min\Python\Project\FA_Data\daily_price\YYYYMMDD.csv`

---

## 4. 數據流程

```
每日更新流程:
1. 更新個股數據 → daily_price/YYYYMMDD.csv
2. Merge 個股數據 → meta_data/stock_data_whole.csv
3. 更新大盤數據 → meta_data/market_index.csv
4. 更新產業指數 → meta_data/industry_index.csv
```

---

## 5. 注意事項

1. **Merge 是增量更新**: 只合併新文件，不會重複處理已存在的數據
2. **大盤數據 API 限制**: FMTQIK API 只提供收盤價，開盤/最高/最低價會使用收盤價
3. **日期格式**: 
   - API 使用: `YYYYMMDD`
   - 內部使用: `YYYY-MM-DD`
   - 文件命名: `YYYYMMDD.csv`
4. **備份機制**: 所有更新操作都會自動創建備份

