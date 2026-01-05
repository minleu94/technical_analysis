# 產業指數 (industry_index.csv) 更新說明

## 更新位置

### 主模組實現（推薦使用）

**檔案**: `data_module/data_loader.py`  
**方法**: `update_industry_index(date: str) -> bool`

```python
from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader

config = TWStockConfig()
loader = DataLoader(config)

# 更新指定日期的產業指數
success = loader.update_industry_index("2025-08-29")
```

### API 資訊

- **API 端點**: `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX`
- **參數**:
  - `date`: 日期格式 `YYYYMMDD`（如 `20250829`）
  - `type`: `IND`（產業指數）
  - `response`: `json`

### 數據處理邏輯

1. 從 API 獲取數據
2. 尋找包含「類股指數」的表格
3. 解析每個產業指數的數據：
   - 指數名稱
   - 開盤指數
   - 最高指數
   - 最低指數
   - 收盤指數
   - 漲跌點數
   - 漲跌百分比
4. 與現有數據合併（移除當天舊數據，添加新數據）
5. 保存到 `industry_index.csv`

### 存儲位置

- **文件路徑**: `D:\Min\Python\Project\FA_Data\meta_data\industry_index.csv`
- **配置方法**: `config.industry_index_file`

---

## 使用方式

### 方式 1：使用 UI 應用程式（最推薦 ⭐⭐⭐）

```bash
python ui_app/main.py
```

在 UI 中選擇「數據更新」標籤頁，選擇「產業指數數據」，設定日期範圍，點擊「開始更新」。

### 方式 2：使用主模組（推薦 ⭐⭐）

```python
from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader

config = TWStockConfig()
loader = DataLoader(config)

# 更新單日
success = loader.update_industry_index("2025-08-29")
```

### 方式 3：使用批量更新腳本

```bash
# 更新所有數據（包括產業指數）
python scripts/batch_update_market_and_industry_index.py --type industry --start-date 2025-08-28
```

### 方式 4：使用修復腳本

```bash
# 修復並更新產業指數（從最後更新日期開始）
python scripts/fix_industry_index.py
```

---

## 相關檔案

1. **主模組**: `data_module/data_loader.py` - `update_industry_index()` 方法
2. **更新腳本**: `scripts/batch_update_market_and_industry_index.py` - 調用主模組方法
3. **修復腳本**: `scripts/fix_industry_index.py` - 修復和批量更新
4. **配置**: `data_module/config.py` - `industry_index_file` 屬性

---

## 數據欄位

- 日期
- 指數名稱
- 開盤指數
- 最高指數
- 最低指數
- 收盤指數
- 漲跌點數
- 漲跌百分比

---

## 注意事項

1. **API 限制**: 與個股數據相同，需要適當的延遲和 Session 處理
2. **數據格式**: 日期格式為 `YYYY-MM-DD`
3. **備份機制**: 更新前會自動創建備份
4. **增量更新**: 只更新指定日期的數據，不會重複處理已存在的日期
5. **數據完整性**: 更新邏輯已修正，避免數據丟失

