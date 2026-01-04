# 數據重建指南

當 `daily_price` 數據完整，但其他數據（`stock_data_whole.csv`、`*_indicators.csv`、`all_stocks_data.csv`）需要重新生成時，請按照以下步驟執行。

## 數據流程

```
daily_price/*.csv
    ↓
[步驟1] merge_daily_data.py
    ↓
meta_data/stock_data_whole.csv
    ↓
[步驟2] calculate_technical_indicators.py
    ↓
technical_analysis/*_indicators.csv
    ↓
[步驟2自動完成]
    ↓
meta_data/all_stocks_data.csv
```

## 重建步驟

### 步驟 1: 重新合併每日數據

將 `daily_price` 目錄中的所有 CSV 文件合併成 `stock_data_whole.csv`。

```bash
# 強制重新合併所有數據（忽略現有數據）
python scripts/merge_daily_data.py --force-all
```

**說明：**
- `--force-all`: 強制重新合併所有數據，即使 `stock_data_whole.csv` 已存在
- 如果不加 `--force-all`，只會合併新數據（日期大於現有數據最新日期的文件）
- 執行前會自動備份現有的 `stock_data_whole.csv`

**輸出：**
- `meta_data/stock_data_whole.csv` - 合併後的完整股票數據

### 步驟 2: 重新計算技術指標

從 `stock_data_whole.csv` 讀取數據，計算所有股票的技術指標。

```bash
# 強制重新計算所有技術指標
python scripts/calculate_technical_indicators.py --force-all
```

**說明：**
- `--force-all`: 強制重新計算所有股票的技術指標，忽略日期檢查
- 如果不加 `--force-all`，只會計算新數據的指標（增量更新）
- 執行前會自動備份現有的指標文件

**輸出：**
- `technical_analysis/{股票代號}_indicators.csv` - 每個股票的技術指標文件
- `meta_data/all_stocks_data.csv` - 合併所有股票指標的整合文件（自動生成）

**其他參數：**
- `--stock STOCK_ID`: 只處理特定股票（例如：`--stock 2330`）
- `--verbose`: 顯示詳細處理信息
- `--check`: 僅檢查，不更新數據

## 完整重建命令

如果需要完全重建所有數據，按順序執行：

```bash
# 1. 重新合併每日數據
python scripts/merge_daily_data.py --force-all

# 2. 重新計算所有技術指標（這會自動生成 all_stocks_data.csv）
python scripts/calculate_technical_indicators.py --force-all
```

## 驗證重建結果

### 檢查 stock_data_whole.csv

```python
import pandas as pd
df = pd.read_csv("D:/Min/Python/Project/FA_Data/meta_data/stock_data_whole.csv")
print(f"總筆數: {len(df)}")
print(f"日期範圍: {df['日期'].min()} ~ {df['日期'].max()}")
print(f"股票數量: {df['證券代號'].nunique()}")
```

### 檢查技術指標文件

```python
from pathlib import Path
technical_dir = Path("D:/Min/Python/Project/FA_Data/technical_analysis")
indicator_files = list(technical_dir.glob("*_indicators.csv"))
print(f"指標文件數量: {len(indicator_files)}")
```

### 檢查 all_stocks_data.csv

```python
import pandas as pd
df = pd.read_csv("D:/Min/Python/Project/FA_Data/meta_data/all_stocks_data.csv")
print(f"總筆數: {len(df)}")
print(f"股票數量: {df['證券代號'].nunique()}")
print(f"日期範圍: {df['日期'].min()} ~ {df['日期'].max()}")
```

## 注意事項

1. **備份**：執行前會自動備份現有文件，備份位置在 `meta_data/backup/` 目錄
2. **時間**：重建所有數據可能需要較長時間，取決於數據量
3. **磁碟空間**：確保有足夠的磁碟空間存儲備份和臨時文件
4. **數據完整性**：確保 `daily_price` 目錄中的數據完整且格式正確

## 常見問題

### Q: 如果只想更新特定股票的指標？

```bash
python scripts/calculate_technical_indicators.py --stock 2330 --force-all
```

### Q: 如何檢查數據是否需要重建？

```bash
# 檢查技術指標文件
python scripts/calculate_technical_indicators.py --check

# 檢查合併數據
python scripts/merge_daily_data.py  # 不加 --force-all，會顯示是否有新數據
```

### Q: 重建後還是找不到強勢股？

檢查：
1. 技術指標文件的日期格式是否正確
2. `stock_screener.py` 的日期解析邏輯是否匹配
3. 數據的日期範圍是否在要求的範圍內

