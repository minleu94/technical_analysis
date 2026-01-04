# 執行指南 - 更新 20250828 數據

## 快速執行

### 方法 1: 使用 UI 應用程式（最推薦 ⭐⭐⭐）

```bash
python ui_app/main.py
```

在 UI 中選擇「數據更新」標籤頁，選擇更新類型，設定日期範圍，點擊「開始更新」。

### 方法 2: 使用批量更新腳本（推薦 ⭐⭐）

```bash
python scripts/batch_update_daily_data.py --start-date 2025-08-28
```

### 方法 3: 使用單日更新腳本

```bash
python scripts/update_daily_stock_data.py --date 2025-08-28
```

## 檢查結果

更新成功後，文件會保存在：
```
D:\Min\Python\Project\FA_Data\daily_price\20250828.csv
```

檢查文件是否存在：
```bash
python -c "from pathlib import Path; print(Path(r'D:\Min\Python\Project\FA_Data\daily_price\20250828.csv').exists())"
```

## 如果遇到問題

### 1. 依賴未安裝

```bash
pip install pandas requests
```

### 2. API 返回 307 錯誤

這是正常的，主模組已包含 Session 和延遲處理，通常可以解決。

### 3. 輸出被抑制

如果 PowerShell 輸出被抑制，可以：
- 使用 UI 應用程式查看日誌
- 檢查日誌文件

## 數據源優先順序

1. **傳統 API** - 最快，已包含 Session 和延遲處理
2. **主模組方法** - 統一處理，包含錯誤處理

腳本會自動處理，直到成功獲取數據。

## 驗證更新

更新成功後，可以檢查文件：

```python
import pandas as pd
from pathlib import Path

file_path = Path(r'D:\Min\Python\Project\FA_Data\daily_price\20250828.csv')
if file_path.exists():
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    print(f"數據筆數: {len(df)}")
    print(f"欄位: {list(df.columns)}")
    print(df.head())
else:
    print("文件不存在")
```

