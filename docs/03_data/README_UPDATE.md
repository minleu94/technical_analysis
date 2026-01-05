# 數據更新指南

## 您應該使用的腳本

### ✅ 正式使用的腳本（在 `scripts/` 目錄下）

1. **`scripts/batch_update_daily_data.py`** - 批量更新個股數據（最推薦）
   ```bash
   python scripts/batch_update_daily_data.py --start-date 2025-08-28
   ```

2. **`scripts/update_daily_stock_data.py`** - 更新單日個股數據
   ```bash
   python scripts/update_daily_stock_data.py --date 2025-08-28 --merge
   ```

3. **`scripts/batch_update_market_and_industry_index.py`** - 更新大盤和產業指數
   ```bash
   python scripts/batch_update_market_and_industry_index.py --type both --start-date 2025-08-28
   ```

4. **`scripts/merge_daily_data.py`** - 手動合併每日數據
   ```bash
   python scripts/merge_daily_data.py
   ```

### ✅ UI 應用程式（最推薦 ⭐⭐⭐）

```bash
python ui_app/main.py
```

在 UI 中可以：
- 更新每日股票數據
- 更新大盤指數數據
- 更新產業指數數據
- 檢查數據狀態

### ❌ 開發參考用的文件（不要直接執行）

- `01_stock_data_collector_enhanced.py` - 開發過程中的參考版本
- `01_stock_data_collector.ipynb` - Jupyter notebook 開發版本
- `02_technical_calculator.ipynb` - 技術指標計算開發版本

這些文件是開發過程中的參考，功能已經整合到 `scripts/` 目錄下的正式腳本中。

## 更新流程

### 使用 UI 應用程式（最簡單）

```bash
python ui_app/main.py
```

在 UI 中選擇更新類型和日期範圍，點擊「開始更新」。

### 使用命令行

```bash
# 1. 更新指定日期的數據（會自動合併）
python scripts/update_daily_stock_data.py --date 2025-08-28 --merge

# 或者如果沒有自動合併，手動執行：
python scripts/merge_daily_data.py
```

### 批量更新多日數據

```bash
# 更新日期範圍的數據
python scripts/batch_update_daily_data.py --start-date 2025-08-28 --end-date 2025-08-30
```

## 數據存儲位置

- **每日數據**: `D:\Min\Python\Project\FA_Data\daily_price\YYYYMMDD.csv`
- **合併後數據**: `D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv`
- **大盤數據**: `D:\Min\Python\Project\FA_Data\meta_data\market_index.csv`
- **產業數據**: `D:\Min\Python\Project\FA_Data\meta_data\industry_index.csv`

## 注意事項

1. 日期格式使用 `YYYY-MM-DD`（例如：2025-08-28）
2. 系統會自動跳過週末
3. 如果 API 請求失敗，會自動重試
4. 更新前會自動創建備份

